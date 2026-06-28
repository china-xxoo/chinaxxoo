#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
: "${YOUTUBE_COOKIES_B64:?YOUTUBE_COOKIES_B64 is required}"

YOUTUBE_URL="${YOUTUBE_URL:-https://www.youtube.com/watch?v=FS7IPxmfEms}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-china-xxoo/chinaxxoo}"
MAX_SNAPSHOTS="${MAX_SNAPSHOTS:-5}"
SITE_TIMEZONE="${SITE_TIMEZONE:-Asia/Shanghai}"
CAPTURE_INTERVAL="${CAPTURE_INTERVAL:-300}"
RETRY_INTERVAL="${RETRY_INTERVAL:-300}"

mkdir -p tmp
printf '%s' "$YOUTUBE_COOKIES_B64" | base64 -d > tmp/youtube-cookies.txt

python3 -m pip install --user --upgrade playwright pillow yt-dlp
python3 -m playwright install --with-deps chromium

python3 scripts/live_room_daemon.py \
  --url "$YOUTUBE_URL" \
  --repo "$GITHUB_REPOSITORY" \
  --cookies tmp/youtube-cookies.txt \
  --interval "$CAPTURE_INTERVAL" \
  --retry-interval "$RETRY_INTERVAL" \
  --max-snapshots "$MAX_SNAPSHOTS" \
  --timezone "$SITE_TIMEZONE"
