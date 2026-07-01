#!/usr/bin/env python3
import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a page region after JS has rendered it.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--selector", default="#playerShell")
    parser.add_argument("--wait-ms", type=int, default=12000)
    parser.add_argument("--quality", type=int, default=72)
    return parser.parse_args()


async def click_first_visible(frame, selectors):
    for selector in selectors:
        try:
            button = frame.locator(selector).first
            if await button.is_visible(timeout=500):
                await button.click(timeout=1000)
                return True
        except Exception:
            continue
    return False


async def keep_video_playing(page):
    skip_selectors = [
        "button.ytp-ad-skip-button-modern",
        ".ytp-ad-skip-button-modern",
        "button.ytp-ad-skip-button",
        ".ytp-ad-skip-button",
        ".ytp-skip-ad-button",
        "button:has-text('跳过')",
        "button:has-text('Skip')",
    ]
    for frame in page.frames:
        await click_first_visible(frame, skip_selectors)
        try:
            await frame.evaluate(
                """
                () => {
                  const video = document.querySelector("video");
                  if (!video) return false;
                  video.muted = true;
                  video.play().catch(() => {});
                  return true;
                }
                """
            )
        except Exception:
            continue


async def main():
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

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
        await page.wait_for_selector(args.selector, timeout=60_000)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + (args.wait_ms / 1000)
        while loop.time() < deadline:
            await keep_video_playing(page)
            await page.wait_for_timeout(2000)

        target = page.locator(args.selector).first
        await target.screenshot(path=str(args.out), type="jpeg", quality=args.quality)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
