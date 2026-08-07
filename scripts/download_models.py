#!/usr/bin/env python3
"""Explicit model fetch helper for build machines (NOT used by the app at runtime)."""

from __future__ import annotations

import argparse
import shutil
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
        "note": "Copies bundled silero_vad.jit from the installed silero-vad package.",
    },
}


def _export_silero_vad(dest: Path) -> None:
    """Copy weight files from site-packages without importing silero_vad (avoids torchaudio)."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        from importlib.metadata import distribution
    except ImportError as exc:
        raise SystemExit("importlib.metadata unavailable") from exc

    try:
        dist = distribution("silero-vad")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "silero-vad not installed. Run: uv add silero-vad && re-run this script."
        ) from exc

    copied = 0
    for file in dist.files or []:
        name = Path(file.name).name
        if name in {"silero_vad.jit", "silero_vad.onnx", "silero_vad_16k_op15.onnx"} or (
            name.startswith("silero_vad") and name.endswith((".jit", ".onnx"))
        ):
            src = Path(dist.locate_file(file))
            if src.is_file():
                shutil.copy2(src, dest / name)
                print(f"Copied {name} -> {dest / name}")
                copied += 1
    if copied == 0:
        raise SystemExit("could not locate bundled silero_vad weights in package files")


def main() -> int:
    p = argparse.ArgumentParser(description="Show / fetch model artifacts (explicit build step)")
    p.add_argument("--confirm-download", action="store_true", help="Actually download / export models")
    p.add_argument("--only", choices=["asr", "aligner", "vad", "all"], default="all")
    args = p.parse_args()

    keys = ["asr", "aligner", "vad"] if args.only == "all" else [args.only]
    for key in keys:
        t = TARGETS[key]
        print(f"[{key}] repo={t['repo']}")
        print(f"      dest={t['dest']}")
        if t.get("note"):
            print(f"      note={t['note']}")

    if not args.confirm_download:
        print("\nDry run only. Re-run with --confirm-download to fetch.")
        return 0

    for key in keys:
        t = TARGETS[key]
        if key == "vad":
            _export_silero_vad(t["dest"])
            continue
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            print("huggingface_hub not installed. Run: uv add --dev huggingface_hub")
            return 2
        t["dest"].parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {t['repo']} -> {t['dest']} ...")
        snapshot_download(repo_id=t["repo"], local_dir=str(t["dest"]))
        print(f"Done: {t['dest']}")

    print("Update manifests/model-lock.json with revision/sha256 before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
