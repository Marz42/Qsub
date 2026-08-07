"""Timestamp repair unit tests."""

from __future__ import annotations

from qsub_core.alignment.repair import repair_items
from qsub_core.alignment.validate import validate_items


def test_repair_zero_duration_span():
    items = [
        {"text": "A", "start": 10.10, "end": 10.30},
        {"text": "B", "start": 10.30, "end": 10.30},
        {"text": "C", "start": 10.30, "end": 10.65},
    ]
    repaired, _issues, quality = repair_items(items, chunk_duration=20.0)
    assert quality in {"repaired", "ok", "degraded"}
    assert repaired[1]["end"] > repaired[1]["start"]
    report = validate_items(repaired, chunk_duration=20.0)
    hard = [i for i in report.issues if i.code in {"ZERO_DURATION", "END_BEFORE_START", "NEGATIVE"}]
    assert not hard


def test_repair_small_overlap_midpoint():
    items = [
        {"text": "A", "start": 5.00, "end": 5.32},
        {"text": "B", "start": 5.28, "end": 5.60},
    ]
    repaired, _, quality = repair_items(items, chunk_duration=10.0)
    assert quality == "repaired"
    assert repaired[0]["end"] <= repaired[1]["start"] + 1e-9


def test_validate_detects_zero_duration():
    items = [{"text": "x", "start": 1.0, "end": 1.0}]
    report = validate_items(items, chunk_duration=5.0)
    assert any(i.code == "ZERO_DURATION" for i in report.issues)
