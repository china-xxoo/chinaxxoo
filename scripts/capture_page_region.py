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
    return parser.parse_args()


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
        await page.wait_for_timeout(args.wait_ms)

        target = page.locator(args.selector).first
        await target.screenshot(path=str(args.out), type="jpeg", quality=90)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
