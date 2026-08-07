"""Resolve bundled or system FFmpeg / FFprobe binaries."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from qsub_core.config import bundled_bin_dir


def find_executable(name: str) -> Path | None:
    """Find name.exe preferring QSUB_* env, then repo bin/, then PATH."""
    env_key = {
        "ffmpeg": "QSUB_FFMPEG",
        "ffprobe": "QSUB_FFPROBE",
    }.get(name.lower())
    if env_key:
        override = os.environ.get(env_key)
        if override:
            p = Path(override).expanduser()
            if p.is_file():
                return p.resolve()

    bundled = bundled_bin_dir() / f"{name}.exe"
    if bundled.is_file():
        return bundled.resolve()

    # Also accept extension-less on PATH (Windows resolves .exe)
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return Path(found).resolve()
    return None


def require_ffprobe() -> Path:
    path = find_executable("ffprobe")
    if path is None:
        raise FileNotFoundError(
            "ffprobe not found. Place bin/ffprobe.exe or install FFmpeg on PATH."
        )
    return path


def require_ffmpeg() -> Path:
    path = find_executable("ffmpeg")
    if path is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place bin/ffmpeg.exe or install FFmpeg on PATH."
        )
    return path
