"""Resolve qsub executable / python -m entry for the GUI."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _looks_like_install_root(path: Path) -> bool:
    return (
        (path / "qsub.cmd").is_file()
        or (path / "manifests" / "runtime-lock.json").is_file()
        or (path / "runtime" / "Scripts" / "python.exe").is_file()
    )


def discover_install_root() -> Path | None:
    """Walk from this file / cwd for a portable or repo install root."""
    env = os.environ.get("QSUB_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if _looks_like_install_root(p) or p.is_dir():
            return p

    here = Path(__file__).resolve().parent
    for cand in (here, *here.parents):
        if _looks_like_install_root(cand):
            return cand
        # editable: gui/ next to pyproject.toml
        if (cand / "pyproject.toml").is_file() and (cand / "src" / "qsub_core").is_dir():
            return cand
    return None


def install_root_candidates() -> list[Path]:
    roots: list[Path] = []
    discovered = discover_install_root()
    if discovered is not None:
        roots.append(discovered)

    env = os.environ.get("QSUB_ROOT")
    if env:
        roots.append(Path(env).expanduser().resolve())

    here = Path(__file__).resolve().parent
    roots.append(here.parent)
    portable = here.parent / "dist" / "portable" / "QwenSubtitle"
    if portable.is_dir():
        roots.append(portable)

    out: list[Path] = []
    seen: set[Path] = set()
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def find_qsub_command() -> list[str]:
    """
    Return argv prefix to run qsub CLI.

    Prefer the same interpreter that runs the GUI (editable/dev), then portable
    qsub.cmd / runtime python, then PATH.
    """
    try:
        import qsub_core.cli  # noqa: F401

        return [sys.executable, "-m", "qsub_core.cli"]
    except ImportError:
        pass

    for root in install_root_candidates():
        cmd = root / "qsub.cmd"
        if cmd.is_file():
            return ["cmd", "/c", str(cmd)]
        runtime_py = root / "runtime" / "Scripts" / "python.exe"
        if runtime_py.is_file():
            return [str(runtime_py), "-m", "qsub_core.cli"]

    which = shutil.which("qsub") or shutil.which("qsub.exe")
    if which:
        return [which]

    return [sys.executable, "-m", "qsub_core.cli"]


def user_config_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) / "QwenSubtitle" if local else Path.home() / ".qwensubtitle"
    base.mkdir(parents=True, exist_ok=True)
    return base / "gui-config.json"
