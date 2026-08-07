"""Logging setup (Spec §36)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from qsub_core.config import APP_NAME, APP_VERSION, ensure_user_dirs


def setup_logging(level: str = "info", *, log_dir: Path | None = None) -> Path:
    ensure_user_dirs()
    directory = log_dir or ensure_user_dirs()["logs"]
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"qsub-{date.today().isoformat()}.log"

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(_parse_level(level))

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(_parse_level(level))
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    # Console: warnings+ by default unless debug
    sh.setLevel(logging.DEBUG if level.lower() == "debug" else logging.WARNING)
    root.addHandler(sh)

    logging.getLogger(APP_NAME).info(
        "logging started version=%s file=%s level=%s",
        APP_VERSION,
        log_path,
        level,
    )
    return log_path


def _parse_level(level: str) -> int:
    mapping = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    return mapping.get(level.lower(), logging.INFO)
