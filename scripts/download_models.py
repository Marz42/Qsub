#!/usr/bin/env python3
"""Explicit model fetch helper for build machines (NOT used by the app at runtime).

Spec §38: the installed app must never implicitly download from Hugging Face.
This script is for developers / release packaging only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

TARGETS = {
    "asr": {
        "repo": "Qwen/Qwen3-ASR-0.6B",
        "dest": MODELS / "Qwen3-ASR-0.6B",
    },
    "aligner": {
        "repo": "Qwen/Qwen3-ForcedAligner-0.6B",
        "dest": MODELS / "Qwen3-ForcedAligner-0.6B",
    },
    "vad": {
        "repo": "snakers4/silero-vad",
        "dest": MODELS / "silero-vad",
        "note": "Prefer placing the official Silero VAD torch hub / onnx bundle manually; "
        "record revision + sha256 in manifests/model-lock.json.",
    },
}


def main() -> int:
    p = argparse.ArgumentParser(description="Show model download targets (explicit build step)")
    p.add_argument(
        "--confirm-download",
        action="store_true",
        help="Actually download via huggingface_hub (optional; requires network + package)",
    )
    p.add_argument(
        "--only",
        choices=["asr", "aligner", "vad", "all"],
        default="all",
    )
    args = p.parse_args()

    keys = ["asr", "aligner", "vad"] if args.only == "all" else [args.only]
    for key in keys:
        t = TARGETS[key]
        print(f"[{key}] repo={t['repo']}")
        print(f"      dest={t['dest']}")
        if t.get("note"):
            print(f"      note={t['note']}")

    if not args.confirm_download:
        print("\nDry run only. Re-run with --confirm-download to fetch ASR/Aligner via huggingface_hub.")
        print("After download, fill manifests/model-lock.json (revision + sha256).")
        return 0

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub not installed. Run: uv add --dev huggingface_hub")
        return 2

    for key in keys:
        if key == "vad":
            print("[vad] skip auto-download; place Silero VAD manually.")
            continue
        t = TARGETS[key]
        t["dest"].parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {t['repo']} -> {t['dest']} ...")
        snapshot_download(repo_id=t["repo"], local_dir=str(t["dest"]))
        print(f"Done: {t['dest']}")

    print("Update manifests/model-lock.json with revision/sha256 before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
