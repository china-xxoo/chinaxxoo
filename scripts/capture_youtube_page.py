#!/usr/bin/env python3
import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


SKIP_SELECTORS = [
    "button.ytp-ad-skip-button-modern",
    ".ytp-ad-skip-button-modern",
    "button.ytp-ad-skip-button",
    ".ytp-ad-skip-button",
    ".ytp-ad-skip-button-container button",
    ".ytp-skip-ad-button",
    "button:has-text('跳过')",
    "button:has-text('Skip')",
]

CONSENT_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('I agree')",
    "button:has-text('同意')",
    "button:has-text('接受全部')",
]

COOKIE_DOMAIN_ALLOWLIST = (
    "youtube.com",
    "google.com",
    "google.co",
)


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a real YouTube live player frame.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--debug-out", type=Path)
    parser.add_argument("--cookies", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--qr-threshold", type=float, default=0.12)
    return parser.parse_args()


def video_id_from_url(url):
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


def with_query(url, **params):
    separator = "&" if "?" in url else "?"
    return url + separator + "&".join(f"{key}={value}" for key, value in params.items())


async def click_first_visible(page, selectors, timeout=700):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=timeout):
                await locator.click(timeout=1200)
                return selector
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None


async def keep_video_playing(page):
    await page.evaluate(
        """
        () => {
          const video = document.querySelector("video");
          if (!video) return;
          video.muted = true;
          video.play().catch(() => {});
        }
        """
    )


async def current_video_state(page):
    return await page.evaluate(
        """
        () => {
          const video = document.querySelector("video");
          const player = document.querySelector("#movie_player");
          if (!video) return { ready: false, ad: Boolean(player?.classList.contains("ad-showing")) };
          return {
            ready: video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0,
            paused: video.paused,
            currentTime: video.currentTime || 0,
            ad: Boolean(player?.classList.contains("ad-showing"))
          };
        }
        """
    )


def qr_like_score(path):
    image = Image.open(path).convert("L")
    width, height = image.size
    best = 0.0

    for size_fraction in (0.28, 0.34, 0.40, 0.46, 0.52, 0.58):
        size = int(height * size_fraction)
        if size < 80:
            continue
        step = max(18, size // 5)
        x_start = int(width * 0.03)
        x_end = max(x_start, int(width * 0.62) - size)
        y_start = int(height * 0.05)
        y_end = max(y_start, int(height * 0.85) - size)

        for y in range(y_start, y_end + 1, step):
            for x in range(x_start, x_end + 1, step):
                crop = image.crop((x, y, x + size, y + size)).resize((96, 96))
                pixels = list(crop.getdata())
                ordered = sorted(pixels)
                p5 = ordered[int(len(ordered) * 0.05)]
                p95 = ordered[int(len(ordered) * 0.95)]
                contrast = p95 - p5
                mean = sum(pixels) / len(pixels)
                binary = [1 if value > mean else 0 for value in pixels]
                black_ratio = 1 - (sum(binary) / len(binary))
                dark_ratio = sum(1 for value in pixels if value < 70) / len(pixels)
                light_ratio = sum(1 for value in pixels if value > 185) / len(pixels)

                horizontal = 0
                vertical = 0
                for row_index in range(96):
                    row = binary[row_index * 96 : (row_index + 1) * 96]
                    horizontal += sum(1 for index in range(95) if row[index] != row[index + 1])
                for column_index in range(96):
                    column = [binary[row_index * 96 + column_index] for row_index in range(96)]
                    vertical += sum(
                        1 for index in range(95) if column[index] != column[index + 1]
                    )

                transitions = (horizontal + vertical) / (96 * 95 * 2)
                balance = 1 - abs(black_ratio - 0.5) * 2
                extremes = min(dark_ratio, light_ratio) * 2
                score = (
                    transitions
                    * max(balance, 0)
                    * min(contrast / 180, 1)
                    * min(extremes / 0.25, 1)
                )
                best = max(best, score)
    return best


def run_command(command, timeout):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            exc.stdout or "",
            exc.stderr or f"Command timed out after {timeout}s",
        )


def is_browser_live_source_url(url, video_id):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if "googlevideo.com" not in host or "/videoplayback" not in parsed.path:
        return False

    query = parse_qs(parsed.query)
    source = query.get("source", [""])[0]
    media_id = query.get("id", [""])[0]
    is_live = query.get("live", [""])[0] == "1" or query.get("hang", [""])[0] == "1"

    return (
        source == "yt_live_broadcast"
        or is_live
        or bool(video_id and media_id.startswith(video_id))
    )


def rank_browser_live_source(url, video_id):
    query = parse_qs(urlparse(url).query)
    source = query.get("source", [""])[0]
    media_id = query.get("id", [""])[0]
    live = query.get("live", [""])[0]
    mime = query.get("mime", [""])[0]
    score = 0
    if source == "yt_live_broadcast":
        score += 100
    if live == "1":
        score += 40
    if video_id and media_id.startswith(video_id):
        score += 25
    if "video" in mime:
        score += 15
    if "audio" in mime:
        score -= 15
    return score


def ordered_live_sources(urls, video_id):
    unique = list(dict.fromkeys(urls))
    return sorted(
        unique,
        key=lambda url: rank_browser_live_source(url, video_id),
        reverse=True,
    )


def extract_stream_url(page_url, cookies_path=None):
    format_selector = "best[protocol^=m3u8][height<=1080]/best[height<=1080]/best"
    client_sets = ("android,ios,web", "android", "ios", "web")

    for clients in client_sets:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-warnings",
            "--no-playlist",
            "--force-ipv4",
            "--extractor-args",
            f"youtube:player_client={clients}",
            "-f",
            format_selector,
            "-g",
        ]
        if cookies_path and cookies_path.exists():
            command += ["--cookies", str(cookies_path)]
        command.append(page_url)
        result = run_command(command, timeout=75)
        if result.returncode != 0:
            print(f"yt-dlp failed for clients={clients}: {result.stderr.strip()}", flush=True)
            continue

        urls = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")]
        if urls:
            stream_url = next((url for url in urls if ".m3u8" in url), urls[0])
            print(f"yt-dlp extracted stream with clients={clients}", flush=True)
            return stream_url

    return None


def capture_stream_candidate(stream_url, path, wait_seconds):
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-user_agent",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "-headers",
        "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n",
        "-rw_timeout",
        "15000000",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        stream_url,
    ]
    if wait_seconds:
        command += ["-ss", str(wait_seconds)]
    command += ["-frames:v", "1", "-q:v", "2", str(path)]
    return run_command(command, timeout=max(75, wait_seconds + 75))


def capture_from_browser_sources(source_urls, video_id, out_path, debug_out, qr_threshold):
    candidates = ordered_live_sources(source_urls, video_id)[:6]
    if not candidates:
        print("No parsed browser live source candidates yet.", flush=True)
        return False

    print(f"Parsed browser live source candidates: {len(candidates)}", flush=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix="youtube-browser-source-"))
    try:
        for index, source_url in enumerate(candidates, start=1):
            candidate = temporary_dir / f"browser-source-{index}.jpg"
            result = capture_stream_candidate(source_url, candidate, 0)
            if result.returncode != 0 or not candidate.exists():
                print(
                    f"ffmpeg could not capture parsed browser source #{index}: "
                    f"{result.stderr.strip()}",
                    flush=True,
                )
                continue

            if debug_out:
                debug_out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, debug_out)

            score = qr_like_score(candidate)
            print(
                f"Parsed browser source #{index} QR-like score: {score:.3f}",
                flush=True,
            )
            if score >= qr_threshold:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, out_path)
                print("Captured by parsed browser live source.", flush=True)
                return True
        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def capture_from_stream(page_url, cookies_path, out_path, debug_out, qr_threshold):
    stream_url = extract_stream_url(page_url, cookies_path)
    if not stream_url:
        print("yt-dlp did not return a playable stream URL.", flush=True)
        return False

    temporary_dir = Path(tempfile.mkdtemp(prefix="youtube-live-stream-"))
    try:
        for wait_seconds in (0, 20, 60, 95):
            candidate = temporary_dir / f"stream-{wait_seconds}.jpg"
            result = capture_stream_candidate(stream_url, candidate, wait_seconds)
            if result.returncode != 0 or not candidate.exists():
                print(
                    f"ffmpeg failed after wait={wait_seconds}: {result.stderr.strip()}",
                    flush=True,
                )
                continue

            if debug_out:
                debug_out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, debug_out)

            score = qr_like_score(candidate)
            print(f"Stream QR-like score after wait={wait_seconds}: {score:.3f}", flush=True)
            if score >= qr_threshold:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, out_path)
                print(f"Captured by direct stream after wait={wait_seconds}", flush=True)
                return True

        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def load_netscape_cookies(path):
    if not path or not path.exists():
        return []

    cookies = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, cookie_path, secure, expires, name, value = parts
        if not any(allowed in domain for allowed in COOKIE_DOMAIN_ALLOWLIST):
            continue
        if not name:
            continue
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path or "/",
            "secure": secure.upper() == "TRUE",
        }
        try:
            expires_value = int(float(expires))
            if expires_value > 10_000_000_000_000:
                expires_value = int(expires_value / 1_000_000 - 11_644_473_600)
            if expires_value > 0:
                cookie["expires"] = expires_value
        except ValueError:
            pass
        cookies.append(cookie)
    return cookies


async def screenshot_player(page, path):
    player = page.locator("#movie_player").first
    if await player.count() > 0:
        await page.mouse.move(5, 5)
        await player.screenshot(path=str(path), type="jpeg", quality=90)
        return
    video = page.locator("video").first
    await video.screenshot(path=str(path), type="jpeg", quality=90)


async def screenshot_debug(page, path):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await screenshot_player(page, path)
    except Exception:
        await page.screenshot(path=str(path), type="jpeg", quality=82)


async def wait_for_qr_live_frame(
    page,
    video_id,
    source_urls,
    out_path,
    debug_out,
    timeout_seconds,
    qr_threshold,
):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    temporary_dir = Path(tempfile.mkdtemp(prefix="youtube-live-frame-"))
    try:
        attempt = 0
        while asyncio.get_running_loop().time() < deadline:
            attempt += 1
            await click_first_visible(page, CONSENT_SELECTORS)
            skipped = await click_first_visible(page, SKIP_SELECTORS)
            if skipped:
                print(f"Clicked ad skip control: {skipped}")
                await page.wait_for_timeout(2500)

            await keep_video_playing(page)
            state = await current_video_state(page)
            print(
                "video state:",
                f"ready={state.get('ready')}",
                f"paused={state.get('paused')}",
                f"ad={state.get('ad')}",
                f"time={state.get('currentTime')}",
                flush=True,
            )
            if state.get("ready") and not state.get("ad"):
                if capture_from_browser_sources(
                    source_urls,
                    video_id,
                    out_path,
                    debug_out,
                    qr_threshold,
                ):
                    return True

                candidate = temporary_dir / f"candidate-{attempt}.jpg"
                await screenshot_player(page, candidate)
                score = qr_like_score(candidate)
                print(f"QR-like score: {score:.3f}", flush=True)
                if score >= qr_threshold:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, out_path)
                    return True
            await screenshot_debug(page, debug_out)

            await page.wait_for_timeout(4000)
        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


async def main():
    args = parse_args()
    video_id = video_id_from_url(args.url)
    if not video_id:
        raise SystemExit("Could not parse YouTube video id.")

    if capture_from_stream(args.url, args.cookies, args.out, args.debug_out, args.qr_threshold):
        return

    print("Direct stream capture did not produce a QR frame. Falling back to browser.", flush=True)
    watch_url = with_query(args.url, autoplay=1, mute=1)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--lang=zh-CN",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        cookies = load_netscape_cookies(args.cookies)
        if cookies:
            await context.add_cookies(cookies)
            print(f"Loaded {len(cookies)} browser cookies.", flush=True)

        page = await context.new_page()
        source_urls = []

        def remember_live_source(request):
            url = request.url
            if is_browser_live_source_url(url, video_id) and url not in source_urls:
                source_urls.append(url)
                print(
                    f"Parsed browser live source #{len(source_urls)} "
                    f"rank={rank_browser_live_source(url, video_id)}",
                    flush=True,
                )

        page.on("request", remember_live_source)
        await page.goto(watch_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#movie_player, video", timeout=60_000)
        ready = await wait_for_qr_live_frame(
            page,
            video_id,
            source_urls,
            args.out,
            args.debug_out,
            args.timeout,
            args.qr_threshold,
        )
        if not ready:
            await context.close()
            raise SystemExit("No QR live room frame was ready before timeout.")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
