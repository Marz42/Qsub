"""Application paths and defaults (Spec §5)."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path

from qsub_core import __version__

APP_NAME = "QwenSubtitle"
APP_VERSION = __version__

TARGET_CHUNK_DURATION = 120.0
SOFT_MAX_DURATION = 180.0
HARD_MAX_DURATION = 240.0
CHUNK_OVERLAP = 0.75


def _looks_like_install_root(path: Path) -> bool:
    return (path / "manifests" / "runtime-lock.json").is_file() or (
        (path / "runtime").is_dir() and (path / "bin").is_dir()
    )


@lru_cache(maxsize=1)
def install_root() -> Path:
    """
    Resolve install / checkout root.

    Priority:
      1. QSUB_ROOT
      2. Walk parents of this file for a portable layout marker
      3. Source checkout root (…/src/qsub_core/config.py → repo)
    """
    env = os.environ.get("QSUB_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        if _looks_like_install_root(parent):
            return parent

    # Dev checkout: src/qsub_core/config.py → parents[2]
    return here.parents[2]


def repo_root() -> Path:
    """Alias for install_root (dev checkout or portable install)."""
    return install_root()


def user_data_dir() -> Path:
    override = os.environ.get("QSUB_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def ensure_user_dirs() -> dict[str, Path]:
    root = user_data_dir()
    paths = {
        "root": root,
        "logs": root / "logs",
        "cache": root / "cache",
        "jobs": root / "jobs",
        "crash": root / "crash",
        "config": root / "config.json",
    }
    for key in ("logs", "cache", "jobs", "crash"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def default_models_dir() -> Path:
    env = os.environ.get("QSUB_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return install_root() / "models"


def asr_model_path() -> Path:
    env = os.environ.get("QSUB_ASR_MODEL")
    if env:
        return Path(env).expanduser().resolve()
    return default_models_dir() / "Qwen3-ASR-0.6B"


def aligner_model_path() -> Path:
    env = os.environ.get("QSUB_ALIGNER_MODEL")
    if env:
        return Path(env).expanduser().resolve()
    return default_models_dir() / "Qwen3-ForcedAligner-0.6B"


def vad_model_path() -> Path:
    env = os.environ.get("QSUB_VAD_MODEL")
    if env:
        return Path(env).expanduser().resolve()
    return default_models_dir() / "silero-vad"


def bundled_bin_dir() -> Path:
    env = os.environ.get("QSUB_BIN_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return install_root() / "bin"


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
