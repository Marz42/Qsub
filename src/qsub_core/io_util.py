"""Atomic JSON / file writes for crash-safe checkpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(
    path: Path | str,
    obj: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    payload = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii) + "\n"
    atomic_write_text(path, payload)
