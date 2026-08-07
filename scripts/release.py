#!/usr/bin/env python3
"""Orchestrate a release-oriented portable build (Phase 6 entrypoint)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="QwenSubtitle release helper")
    p.add_argument("--with-ffmpeg", action="store_true", default=True)
    p.add_argument("--no-ffmpeg", action="store_true")
    p.add_argument("--with-models", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    run([sys.executable, str(ROOT / "scripts" / "verify_models.py")])

    cmd = [sys.executable, str(ROOT / "scripts" / "build_runtime.py"), "--clean"]
    if args.out:
        cmd += ["--out", str(args.out)]
    if args.with_models:
        cmd.append("--with-models")
    if not args.no_ffmpeg:
        cmd.append("--with-ffmpeg")
    run(cmd)
    print("Release portable tree build finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
