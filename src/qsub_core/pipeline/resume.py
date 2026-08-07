"""Resume / checkpoint helpers (Spec §28, §14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def asr_chunk_path(asr_dir: Path, chunk_id: int) -> Path:
    return asr_dir / f"{chunk_id:06d}.json"


def load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_valid_asr_artifact(record: Any, *, chunk_id: int, start: float, end: float) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("chunk_id") != chunk_id:
        return False
    if "text" not in record:
        return False
    # Allow small float noise
    try:
        if abs(float(record.get("start", -1)) - float(start)) > 0.05:
            return False
        if abs(float(record.get("end", -1)) - float(end)) > 0.05:
            return False
    except (TypeError, ValueError):
        return False
    return True


def list_completed_asr_chunks(asr_dir: Path, chunks: list[dict[str, Any]]) -> set[int]:
    done: set[int] = set()
    for ch in chunks:
        cid = int(ch["id"])
        path = asr_chunk_path(asr_dir, cid)
        record = load_json(path)
        if is_valid_asr_artifact(
            record,
            chunk_id=cid,
            start=float(ch["start"]),
            end=float(ch["end"]),
        ):
            done.add(cid)
    return done


def cancel_flag_path(work_dir: Path) -> Path:
    return work_dir / "cancel.flag"


def is_cancel_requested(work_dir: Path) -> bool:
    return cancel_flag_path(work_dir).is_file()
