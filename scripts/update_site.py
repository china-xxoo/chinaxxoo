#!/usr/bin/env python3
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Update the static live snapshot site.")
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--max-snapshots", required=True, type=int)
    return parser.parse_args()


def load_manifest(path):
    if not path.exists():
        return {"sourceUrl": "", "latest": None, "snapshots": []}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def snapshot_name(captured_at):
    captured = datetime.fromisoformat(captured_at)
    return captured.strftime("%Y-%m-%d_%H-%M-%S.jpg")


def main():
    args = parse_args()
    site_dir = args.site
    snapshots_dir = site_dir / "snapshots"
    manifest_path = site_dir / "manifest.json"

    site_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(args.public / "index.html", site_dir / "index.html")
    public_assets = args.public / "assets"
    if public_assets.exists():
        shutil.copytree(public_assets, site_dir / "assets", dirs_exist_ok=True)
    (site_dir / ".nojekyll").touch()

    filename = snapshot_name(args.captured_at)
    history_path = snapshots_dir / filename
    shutil.copy2(args.snapshot, history_path)
    shutil.copy2(args.snapshot, site_dir / "latest.jpg")

    manifest = load_manifest(manifest_path)
    previous = [
        item
        for item in manifest.get("snapshots", [])
        if item.get("file") != f"snapshots/{filename}"
    ]

    snapshots = [
        {
            "file": f"snapshots/{filename}",
            "capturedAt": args.captured_at,
        },
        *previous,
    ][: args.max_snapshots]

    keep_files = {Path(item["file"]).name for item in snapshots}
    for old_file in snapshots_dir.glob("*.jpg"):
        if old_file.name not in keep_files:
            old_file.unlink()

    next_manifest = {
        "sourceUrl": args.source_url,
        "latest": {
            "file": "latest.jpg",
            "capturedAt": args.captured_at,
        },
        "snapshots": snapshots,
    }

    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(next_manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
