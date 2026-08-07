"""Resume helper unit tests (no model load)."""

from __future__ import annotations

import json
from pathlib import Path

from qsub_core.io_util import atomic_write_json
from qsub_core.pipeline.resume import (
    is_valid_asr_artifact,
    list_completed_asr_chunks,
)


def test_valid_asr_artifact_checks_bounds():
    rec = {"chunk_id": 1, "start": 10.0, "end": 20.0, "text": "hi"}
    assert is_valid_asr_artifact(rec, chunk_id=1, start=10.0, end=20.0)
    assert not is_valid_asr_artifact(rec, chunk_id=2, start=10.0, end=20.0)
    assert not is_valid_asr_artifact(rec, chunk_id=1, start=11.0, end=20.0)
    assert not is_valid_asr_artifact({"chunk_id": 1, "start": 10, "end": 20}, chunk_id=1, start=10, end=20)


def test_list_completed_asr_chunks(tmp_path: Path):
    asr_dir = tmp_path / "asr"
    asr_dir.mkdir()
    chunks = [
        {"id": 0, "start": 0.0, "end": 10.0},
        {"id": 1, "start": 10.0, "end": 20.0},
    ]
    atomic_write_json(
        asr_dir / "000000.json",
        {"chunk_id": 0, "start": 0.0, "end": 10.0, "text": "a"},
    )
    # corrupt / incomplete second chunk
    (asr_dir / "000001.json").write_text("{not-json", encoding="utf-8")
    done = list_completed_asr_chunks(asr_dir, chunks)
    assert done == {0}
