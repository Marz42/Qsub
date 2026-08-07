"""Application paths and defaults (Spec §5)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from qsub_core import __version__

APP_NAME = "QwenSubtitle"
APP_VERSION = __version__

# Spec §12 chunk defaults (exposed for CLI later)
TARGET_CHUNK_DURATION = 120.0
SOFT_MAX_DURATION = 180.0
HARD_MAX_DURATION = 240.0
CHUNK_OVERLAP = 0.75


def repo_root() -> Path:
    """Repository root when running from a source checkout; else install root."""
    # src/qsub_core/config.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


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
    return repo_root() / "models"


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
    return repo_root() / "bin"


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
