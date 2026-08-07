#!/usr/bin/env python3
"""Download pinned Windows FFmpeg essentials into bin/ and update manifests/ffmpeg-lock.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
LOCK = ROOT / "manifests" / "ffmpeg-lock.json"

# Pinned release (immutable URL) — Spec forbids floating "latest" in releases.
FFMPEG_VERSION = "8.1"
FFMPEG_URL = (
    "https://github.com/GyanD/codexffmpeg/releases/download/"
    f"{FFMPEG_VERSION}/ffmpeg-{FFMPEG_VERSION}-essentials_build.zip"
)
FFMPEG_LICENSE = "GPL-3.0-or-later"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "QwenSubtitle-build/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch pinned FFmpeg into bin/")
    p.add_argument("--url", default=FFMPEG_URL)
    p.add_argument("--version", default=FFMPEG_VERSION)
    p.add_argument("--dest-bin", type=Path, default=BIN)
    args = p.parse_args()

    dest_bin: Path = args.dest_bin
    dest_bin.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="qsub-ffmpeg-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "ffmpeg.zip"
        print(f"Downloading {args.url}")
        download(args.url, archive)
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)

        ffmpeg = next(extract_dir.rglob("ffmpeg.exe"), None)
        ffprobe = next(extract_dir.rglob("ffprobe.exe"), None)
        if ffmpeg is None or ffprobe is None:
            print("ffmpeg.exe / ffprobe.exe not found in archive")
            return 1

        out_ffmpeg = dest_bin / "ffmpeg.exe"
        out_ffprobe = dest_bin / "ffprobe.exe"
        shutil.copy2(ffmpeg, out_ffmpeg)
        shutil.copy2(ffprobe, out_ffprobe)
        print(f"Wrote {out_ffmpeg}")
        print(f"Wrote {out_ffprobe}")

        lock = {
            "schema_version": 1,
            "description": "Locked bundled FFmpeg / FFprobe binaries",
            "entries": [
                {
                    "name": "ffmpeg",
                    "version": args.version,
                    "source": args.url,
                    "local_path": "bin/ffmpeg.exe",
                    "sha256": sha256_file(out_ffmpeg),
                    "license": FFMPEG_LICENSE,
                },
                {
                    "name": "ffprobe",
                    "version": args.version,
                    "source": args.url,
                    "local_path": "bin/ffprobe.exe",
                    "sha256": sha256_file(out_ffprobe),
                    "license": FFMPEG_LICENSE,
                },
            ],
        }
        # Prefer writing lock next to dest when building portable tree
        lock_path = LOCK
        if dest_bin.parent.name != ROOT.name and (dest_bin.parent / "manifests").is_dir():
            lock_path = dest_bin.parent / "manifests" / "ffmpeg-lock.json"
        elif dest_bin.resolve() != BIN.resolve():
            # portable: <root>/bin → <root>/manifests
            maybe = dest_bin.parent / "manifests" / "ffmpeg-lock.json"
            maybe.parent.mkdir(parents=True, exist_ok=True)
            lock_path = maybe
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {lock_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
