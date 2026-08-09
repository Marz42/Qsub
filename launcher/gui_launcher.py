"""
Thin GUI launcher for portable / installed layouts (Spec §4–§5).

Sets QSUB_ROOT then starts gui.main with the embedded runtime (pythonw when available).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def find_root() -> Path:
    env = os.environ.get("QSUB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    if (here / "runtime").is_dir() or (here / "manifests").is_dir():
        return here
    if (here.parent / "runtime").is_dir() or (here.parent / "pyproject.toml").is_file():
        return here.parent
    return here.parent


def find_pythonw(root: Path) -> Path:
    candidates = [
        root / "runtime" / "pythonw.exe",
        root / "runtime" / "python.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return Path(sys.executable)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = find_root()
    os.environ["QSUB_ROOT"] = str(root)
    python = find_pythonw(root)
    if Path(sys.executable).resolve() == python.resolve() or python.name.lower() == "pythonw.exe":
        # When already the right interpreter, import in-process (python.exe path).
        if python.name.lower() != "pythonw.exe" or Path(sys.executable).resolve() == python.resolve():
            try:
                from gui.main import main as gui_main

                return int(gui_main() or 0)
            except ImportError:
                pass
    cmd = [str(python), "-m", "gui.main", *argv]
    return subprocess.call(cmd, cwd=str(root))


if __name__ == "__main__":
    raise SystemExit(main())
