"""Resume / checkpoint helpers (Spec §28, §14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def asr_chunk_path(asr_dir: Path, chunk_id: int) -> Path:
    return asr_dir / f"{chunk_id:06d}.json"


def alignment_chunk_path(alignment_dir: Path, chunk_id: int) -> Path:
    return alignment_dir / f"{chunk_id:06d}.json"


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
    try:
        if abs(float(record.get("start", -1)) - float(start)) > 0.05:
            return False
        if abs(float(record.get("end", -1)) - float(end)) > 0.05:
            return False
    except (TypeError, ValueError):
        return False
    return True


def is_valid_alignment_artifact(
    record: Any,
    *,
    chunk_id: int,
    start: float,
    end: float,
) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("chunk_id") != chunk_id:
        return False
    if "items" not in record or not isinstance(record["items"], list):
        return False
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


def list_completed_alignment_chunks(
    alignment_dir: Path,
    chunks: list[dict[str, Any]],
) -> set[int]:
    done: set[int] = set()
    for ch in chunks:
        cid = int(ch["id"])
        path = alignment_chunk_path(alignment_dir, cid)
        record = load_json(path)
        if is_valid_alignment_artifact(
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


def clear_cancel_requested(work_dir: Path) -> None:
    try:
        cancel_flag_path(work_dir).unlink()
    except FileNotFoundError:
        pass


def classify_resume_change(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    same_source_path: bool,
    previous_pipeline_version: int,
) -> str:
    """Return none|recognition|media for stage-safe cache invalidation."""
    if (
        not same_source_path
        or previous_pipeline_version != int(current.get("pipeline_version", 0))
        or previous.get("source_fingerprint") != current.get("source_fingerprint")
        or previous.get("audio_stream") != current.get("audio_stream")
    ):
        return "media"
    if any(
        previous.get(key) != current.get(key)
        for key in ("language", "asr_revision", "aligner_revision")
    ):
        return "recognition"
    return "none"
