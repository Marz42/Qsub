#!/usr/bin/env python3
"""Orchestrate portable runtime + optional Inno installer (Phase 6/8)."""

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
    p = argparse.ArgumentParser(
        description="QwenSubtitle release helper (default: runtime without ASR/Aligner weights)"
    )
    p.add_argument("--with-ffmpeg", action="store_true", default=True)
    p.add_argument("--no-ffmpeg", action="store_true")
    p.add_argument(
        "--with-models",
        action="store_true",
        help="Bundle ASR/Aligner from repo models/ (optional air-gap; not default)",
    )
    p.add_argument("--installer", action="store_true", help="Also compile Inno Setup package")
    p.add_argument(
        "--require-models",
        action="store_true",
        help="Fail installer build if ASR/Aligner missing (only with --with-models)",
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--version", default="0.1.0")
    args = p.parse_args()

    if args.with_models:
        run([sys.executable, str(ROOT / "scripts" / "verify_models.py")])
    elif args.require_models:
        print("error: --require-models needs --with-models", file=sys.stderr)
        return 2

    cmd = [sys.executable, str(ROOT / "scripts" / "build_runtime.py"), "--clean"]
    if args.out:
        cmd += ["--out", str(args.out)]
    if args.with_models:
        cmd.append("--with-models")
    if not args.no_ffmpeg:
        cmd.append("--with-ffmpeg")
    run(cmd)

    if args.installer:
        inst = [
            sys.executable,
            str(ROOT / "scripts" / "build_installer.py"),
            "--version",
            args.version,
        ]
        if args.out:
            inst += ["--source", str(args.out)]
        if args.require_models:
            inst.append("--require-models")
        run(inst)

    print("Release build finished.")
    if not args.with_models:
        print("Models: not bundled. End users run download-models.cmd once (network).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
