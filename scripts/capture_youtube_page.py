#!/usr/bin/env python3
import argparse
import asyncio
import shutil
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


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a real YouTube live player frame.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
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


async def screenshot_player(page, path):
    player = page.locator("#movie_player").first
    if await player.count() > 0:
        await page.mouse.move(5, 5)
        await player.screenshot(path=str(path), type="jpeg", quality=90)
        return
    video = page.locator("video").first
    await video.screenshot(path=str(path), type="jpeg", quality=90)


async def wait_for_qr_live_frame(page, out_path, timeout_seconds, qr_threshold):
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
            if state.get("ready") and not state.get("ad"):
                candidate = temporary_dir / f"candidate-{attempt}.jpg"
                await screenshot_player(page, candidate)
                score = qr_like_score(candidate)
                print(f"QR-like score: {score:.3f}")
                if score >= qr_threshold:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, out_path)
                    return True

            await page.wait_for_timeout(4000)
        return False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


async def main():
    args = parse_args()
    video_id = video_id_from_url(args.url)
    if not video_id:
        raise SystemExit("Could not parse YouTube video id.")

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
        page = await browser.new_page(
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        await page.goto(watch_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#movie_player, video", timeout=60_000)
        ready = await wait_for_qr_live_frame(
            page,
            args.out,
            args.timeout,
            args.qr_threshold,
        )
        if not ready:
            await browser.close()
            raise SystemExit("No QR live room frame was ready before timeout.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
