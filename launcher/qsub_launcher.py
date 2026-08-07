"""
Thin CLI launcher for portable installs (Spec §4).

Layout:
  <root>/qsub.cmd  →  <root>/runtime/Scripts/python.exe -m qsub_core.cli
  or this module invoked as: python qsub_launcher.py ...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def find_root() -> Path:
    env = os.environ.get("QSUB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # launcher/qsub_launcher.py → parent = install/repo root when copied to root,
    # or repo root when living under launcher/
    here = Path(__file__).resolve().parent
    if (here / "runtime").is_dir() or (here / "manifests").is_dir():
        return here
    if (here.parent / "runtime").is_dir() or (here.parent / "pyproject.toml").is_file():
        return here.parent
    return here.parent


def find_python(root: Path) -> Path:
    candidates = [
        root / "runtime" / "Scripts" / "python.exe",
        root / "runtime" / "python.exe",
        root / "runtime" / "bin" / "python",
    ]
    for c in candidates:
        if c.is_file():
            return c
    # Dev fallback
    return Path(sys.executable)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = find_root()
    os.environ.setdefault("QSUB_ROOT", str(root))
    python = find_python(root)
    # Prefer in-process when already running inside the portable runtime.
    if Path(sys.executable).resolve() == python.resolve():
        from qsub_core.cli import main as cli_main

        return cli_main(argv)

    import subprocess

    cmd = [str(python), "-m", "qsub_core.cli", *argv]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
