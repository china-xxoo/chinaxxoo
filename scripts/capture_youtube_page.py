#!/usr/bin/env python3
import argparse
import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright


def parse_args():
    parser = argparse.ArgumentParser(description="Capture a real YouTube live player frame.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=90)
    return parser.parse_args()


def video_id_from_url(url):
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


async def wait_for_video_frame(page, timeout_ms):
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        state = await page.evaluate(
            """
            () => {
              const video = document.querySelector("video");
              if (!video) return { ready: false };
              video.muted = true;
              video.play().catch(() => {});
              return {
                ready: video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0,
                paused: video.paused,
                currentTime: video.currentTime || 0
              };
            }
            """
        )
        if state.get("ready"):
            first_time = state.get("currentTime", 0)
            await page.wait_for_timeout(2500)
            second_state = await page.evaluate(
                """
                () => {
                  const video = document.querySelector("video");
                  if (!video) return { ready: false };
                  return {
                    ready: video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0,
                    paused: video.paused,
                    currentTime: video.currentTime || 0
                  };
                }
                """
            )
            if (
                second_state.get("ready")
                and not second_state.get("paused")
                and second_state.get("currentTime", 0) > first_time + 0.6
            ):
                return True
        await page.mouse.click(640, 360)
        await page.wait_for_timeout(2000)
    return False


async def main():
    args = parse_args()
    video_id = video_id_from_url(args.url)
    if not video_id:
        raise SystemExit("Could not parse YouTube video id.")

    embed_url = (
        f"https://www.youtube.com/embed/{video_id}"
        "?autoplay=1&mute=1&playsinline=1&controls=0&modestbranding=1"
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        page = await browser.new_page(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        await page.goto(embed_url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
        ready = await wait_for_video_frame(page, args.timeout * 1000)
        if not ready:
            await browser.close()
            raise SystemExit("No live video frame was ready before timeout.")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(args.out), type="jpeg", quality=90)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
