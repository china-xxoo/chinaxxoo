#!/usr/bin/env python3
import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from capture_youtube_page import (
    CONSENT_SELECTORS,
    SKIP_SELECTORS,
    click_first_visible,
    current_video_state,
    is_browser_live_source_url,
    keep_video_playing,
    load_netscape_cookies,
    qr_like_score,
    rank_browser_live_source,
    screenshot_debug,
    screenshot_player,
    video_id_from_url,
    with_query,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Keep one cloud browser in a YouTube live room and publish snapshots."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "china-xxoo/chinaxxoo"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--source-dir", type=Path, default=Path("."))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--cookies", type=Path)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--retry-interval", type=int, default=300)
    parser.add_argument("--max-snapshots", type=int, default=5)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--qr-threshold", type=float, default=0.12)
    parser.add_argument("--debug-out", type=Path, default=Path("tmp/debug-player.jpg"))
    return parser.parse_args()


def run(command, cwd=None, timeout=120, env=None):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{command[0]} failed: {message}")
    return result


def github_repo_url(repo):
    return f"https://github.com/{repo}.git"


def git_auth_env(token):
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for publishing.")

    askpass_dir = Path(tempfile.gettempdir()) / "youtube-live-git-auth"
    askpass_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    askpass = askpass_dir / "askpass.sh"
    askpass.write_text(
        """#!/bin/sh
case "$1" in
  *Username*) printf '%s\\n' 'x-access-token' ;;
  *) printf '%s\\n' "$GITHUB_TOKEN" ;;
esac
""",
        encoding="utf-8",
    )
    askpass.chmod(0o700)

    env = os.environ.copy()
    env["GITHUB_TOKEN"] = token
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def ensure_site_checkout(args):
    repo_url = github_repo_url(args.repo)
    git_env = git_auth_env(args.token)

    args.site.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "config", "--global", "user.name", "cloud-live-snapshot"])
    run(["git", "config", "--global", "user.email", "cloud-live-snapshot@users.noreply.github.com"])

    if (args.site / ".git").exists():
        run(["git", "remote", "set-url", "origin", repo_url], cwd=args.site)
        run(["git", "fetch", "origin", "gh-pages"], cwd=args.site, timeout=180, env=git_env)
        run(["git", "checkout", "gh-pages"], cwd=args.site)
        run(["git", "reset", "--hard", "origin/gh-pages"], cwd=args.site)
        return

    if args.site.exists() and any(args.site.iterdir()):
        raise RuntimeError(f"{args.site} exists and is not an empty git checkout.")

    refs = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", repo_url, "gh-pages"],
        env=git_env,
        capture_output=True,
        text=True,
        check=False,
    )
    if refs.returncode == 0:
        run(
            ["git", "clone", "--depth=1", "--branch", "gh-pages", repo_url, str(args.site)],
            timeout=240,
            env=git_env,
        )
    else:
        args.site.mkdir(parents=True, exist_ok=True)
        run(["git", "init"], cwd=args.site)
        run(["git", "checkout", "--orphan", "gh-pages"], cwd=args.site)
        run(["git", "remote", "add", "origin", repo_url], cwd=args.site)


def publish_snapshot(args, snapshot_path):
    from update_site import main as update_site_main

    captured_at = datetime.now(ZoneInfo(args.timezone)).isoformat(timespec="seconds")
    old_argv = sys.argv
    try:
        sys.argv = [
            "update_site.py",
            "--site",
            str(args.site),
            "--public",
            str(args.source_dir / "public"),
            "--snapshot",
            str(snapshot_path),
            "--captured-at",
            captured_at,
            "--source-url",
            args.url,
            "--max-snapshots",
            str(args.max_snapshots),
        ]
        update_site_main()
    finally:
        sys.argv = old_argv

    run(["git", "add", "."], cwd=args.site)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=args.site, check=False)
    if diff.returncode == 0:
        print("No site changes to publish.", flush=True)
        return
    run(["git", "commit", "-m", "Update live snapshot"], cwd=args.site)
    run(["git", "push", "origin", "gh-pages"], cwd=args.site, timeout=240, env=git_auth_env(args.token))
    print(f"Published snapshot at {captured_at}.", flush=True)


async def prepare_page(context, args, video_id, live_sources):
    page = await context.new_page()

    def remember_live_source(request):
        url = request.url
        if is_browser_live_source_url(url, video_id) and url not in live_sources:
            live_sources.append(url)
            print(
                f"Parsed cloud live source #{len(live_sources)} "
                f"rank={rank_browser_live_source(url, video_id)}",
                flush=True,
            )

    page.on("request", remember_live_source)
    await page.goto(with_query(args.url, autoplay=1, mute=1), wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_selector("#movie_player, video", timeout=60_000)
    return page


async def make_player_ready(page, timeout_seconds):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        await click_first_visible(page, CONSENT_SELECTORS)
        skipped = await click_first_visible(page, SKIP_SELECTORS)
        if skipped:
            print(f"Clicked ad skip control: {skipped}", flush=True)
            await page.wait_for_timeout(2500)

        await keep_video_playing(page)
        state = await current_video_state(page)
        print(
            "cloud video state:",
            f"ready={state.get('ready')}",
            f"paused={state.get('paused')}",
            f"ad={state.get('ad')}",
            f"time={state.get('currentTime')}",
            flush=True,
        )
        if state.get("ready") and not state.get("ad"):
            return True
        await page.wait_for_timeout(5000)
    return False


async def capture_once(page, args, temporary_dir):
    await keep_video_playing(page)
    state = await current_video_state(page)
    if not state.get("ready") or state.get("ad"):
        return None

    candidate = temporary_dir / "snapshot.jpg"
    await screenshot_player(page, candidate)
    score = qr_like_score(candidate)
    print(f"cloud QR-like score: {score:.3f}", flush=True)
    if score < args.qr_threshold:
        await screenshot_debug(page, args.debug_out)
        return None
    return candidate


async def run_forever(args):
    video_id = video_id_from_url(args.url)
    if not video_id:
        raise RuntimeError("Could not parse YouTube video id.")

    ensure_site_checkout(args)

    async with async_playwright() as playwright:
        while True:
            live_sources = []
            temporary_dir = Path(tempfile.mkdtemp(prefix="cloud-live-room-"))
            context = None
            page = None
            try:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-blink-features=AutomationControlled",
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
                    print(f"Loaded {len(cookies)} cloud browser cookies.", flush=True)

                page = await prepare_page(context, args, video_id, live_sources)
                ready = await make_player_ready(page, timeout_seconds=180)
                if not ready:
                    print("Cloud live room not ready; reconnecting later.", flush=True)
                    await context.close()
                    await asyncio.sleep(args.retry_interval)
                    continue

                print("Cloud browser is now staying inside the live room.", flush=True)
                while True:
                    snapshot = await capture_once(page, args, temporary_dir)
                    if snapshot:
                        publish_snapshot(args, snapshot)
                    else:
                        print("No valid QR live frame on this interval.", flush=True)
                    await asyncio.sleep(args.interval)
            except Exception as exc:
                print(f"Cloud live worker error: {exc}", flush=True)
                if context:
                    await context.close()
                await asyncio.sleep(args.retry_interval)
            finally:
                shutil.rmtree(temporary_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_forever(parse_args()))
