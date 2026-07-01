#!/usr/bin/env python3
import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


SKIP_SELECTORS = [
    "button.ytp-ad-skip-button-modern",
    ".ytp-ad-skip-button-modern",
    "button.ytp-ad-skip-button",
    ".ytp-ad-skip-button",
    ".ytp-skip-ad-button",
    "button:has-text('Skip')",
    "button:has-text('跳过')",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a YouTube embed player image.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--debug-out", type=Path)
    parser.add_argument("--wait-ms", type=int, default=8000)
    return parser.parse_args()


async def click_first(page, selectors):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=250):
                await locator.click(timeout=1000)
                print(f"Clicked control: {selector}", flush=True)
                return True
        except Exception:
            continue
    return False


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


async def video_state(page):
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
            ad: Boolean(player?.classList.contains("ad-showing")),
          };
        }
        """
    )


async def screenshot_player(page, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    player = page.locator("#movie_player, .html5-video-player, video").first
    if await player.count() > 0:
        await player.screenshot(path=str(path), type="jpeg", quality=90)
        return
    await page.screenshot(path=str(path), type="jpeg", quality=90, full_page=False)


async def main():
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.debug_out:
        args.debug_out.parent.mkdir(parents=True, exist_ok=True)

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
        await page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#movie_player, .html5-video-player, video", timeout=60_000)

        deadline = asyncio.get_running_loop().time() + (args.wait_ms / 1000)
        last_state = {}
        while asyncio.get_running_loop().time() < deadline:
            await click_first(page, SKIP_SELECTORS)
            await keep_video_playing(page)
            last_state = await video_state(page)
            print(
                "embed state:",
                f"ready={last_state.get('ready')}",
                f"paused={last_state.get('paused')}",
                f"ad={last_state.get('ad')}",
                f"time={last_state.get('currentTime')}",
                flush=True,
            )
            await page.wait_for_timeout(1000)

        await screenshot_player(page, args.out)
        if args.debug_out:
            await screenshot_player(page, args.debug_out)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
