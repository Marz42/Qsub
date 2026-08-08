#!/usr/bin/env python3
"""
Compile the Inno Setup installer (Phase 8).

Wraps dist/portable/QwenSubtitle into:
  dist/installer/QwenSubtitle-Setup.exe
  dist/installer/QwenSubtitle-Setup-*.bin   (disk spanning)

Requires Inno Setup 6+ (prefer 7) with ISCC.exe on PATH or in Program Files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "dist" / "portable" / "QwenSubtitle"
DEFAULT_ISS = ROOT / "packaging" / "inno" / "QwenSubtitle.iss"
DEFAULT_OUT = ROOT / "dist" / "installer"


def find_iscc() -> Path | None:
    env = os.environ.get("ISCC") or os.environ.get("INNO_SETUP_ISCC")
    if env:
        p = Path(env)
        if p.is_file():
            return p

    which = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if which:
        return Path(which)

    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def check_source(source: Path, *, require_models: bool) -> list[str]:
    errors: list[str] = []
    if not source.is_dir():
        errors.append(f"portable tree missing: {source} (run scripts/build_runtime.py first)")
        return errors
    if not (source / "qsub.cmd").is_file():
        errors.append(f"missing qsub.cmd under {source}")
    if not (source / "QwenSubtitle.vbs").is_file() and not (source / "QwenSubtitle.cmd").is_file():
        errors.append(f"missing GUI launcher under {source}")
    if not (source / "runtime" / "Scripts" / "python.exe").is_file():
        errors.append(f"missing embedded runtime under {source / 'runtime'}")
    if require_models:
        for name in ("Qwen3-ASR-0.6B", "Qwen3-ForcedAligner-0.6B", "silero-vad"):
            d = source / "models" / name
            if not d.is_dir() or not any(d.iterdir()):
                errors.append(f"models/{name} missing or empty (rebuild with --with-models)")
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description="Build QwenSubtitle Inno Setup installer")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Portable tree to package")
    p.add_argument("--iss", type=Path, default=DEFAULT_ISS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--version", default="0.1.0")
    p.add_argument("--require-models", action="store_true", help="Fail if models/ not bundled")
    p.add_argument("--iscc", type=Path, default=None, help="Path to ISCC.exe")
    args = p.parse_args()

    source = args.source.resolve()
    iss = args.iss.resolve()
    out = args.out.resolve()

    if not iss.is_file():
        print(f"missing ISS: {iss}", file=sys.stderr)
        return 2

    errors = check_source(source, require_models=args.require_models)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2

    iscc = args.iscc or find_iscc()
    if iscc is None:
        print(
            "ISCC.exe not found. Install Inno Setup 7:\n"
            "  winget install JRSoftware.InnoSetup.7\n"
            "Or set ISCC=C:\\Path\\to\\ISCC.exe",
            file=sys.stderr,
        )
        return 3

    out.mkdir(parents=True, exist_ok=True)
    # Paths relative to ISS location for defines that Inno resolves from script dir
    # Pass absolute paths to avoid cwd confusion.
    cmd = [
        str(iscc),
        f"/DMyAppVersion={args.version}",
        f"/DSourceDir={source}",
        f"/DOutputDir={out}",
        str(iss),
    ]
    print("+", " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        print(f"ISCC failed: {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1

    setup = out / "QwenSubtitle-Setup.exe"
    print(f"Installer output directory: {out}")
    if setup.is_file():
        print(f"  {setup} ({setup.stat().st_size} bytes)")
    for bin_path in sorted(out.glob("QwenSubtitle-Setup-*.bin")):
        print(f"  {bin_path.name} ({bin_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
