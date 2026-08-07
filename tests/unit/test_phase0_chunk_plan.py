"""Unit tests for VAD-aware chunk planning."""

from __future__ import annotations

from qsub_core.pipeline.chunk_plan import plan_chunks, plan_chunks_from_vad


def test_plan_chunks_under_hard_max():
    chunks = plan_chunks(90.0, hard_max=240.0)
    assert len(chunks) == 1
    assert chunks[0].start == 0.0
    assert chunks[0].end == 90.0
    assert chunks[0].overlap_before == 0.0


def test_plan_chunks_splits_long_audio():
    chunks = plan_chunks(600.0, hard_max=240.0)
    assert len(chunks) >= 3
    for c in chunks:
        assert c.end - c.start <= 240.0 + 1e-6
        assert c.start < c.end
    assert chunks[0].start == 0.0
    assert abs(chunks[-1].end - 600.0) < 1e-6


def test_vad_prefers_silence_near_target():
    # Speech with a long gap around 120s
    speech = [
        {"start": 0.0, "end": 110.0},
        {"start": 125.0, "end": 240.0},
    ]
    chunks = plan_chunks_from_vad(240.0, speech, target=120.0, soft_max=180.0, hard_max=240.0)
    assert len(chunks) >= 2
    # First cut should land in the silence gap (~117.5 midpoint)
    assert 110.0 <= chunks[0].end <= 125.0
    assert chunks[0].cut_reason in {"natural", "soft"}
    assert chunks[0].overlap_before == 0.0


def test_force_cut_adds_overlap():
    # Continuous speech — no usable silence → force cuts with overlap
    speech = [{"start": 0.0, "end": 500.0}]
    chunks = plan_chunks_from_vad(500.0, speech, hard_max=240.0, target=120.0)
    assert len(chunks) >= 2
    forced = [c for c in chunks if c.cut_reason == "force"]
    assert forced
    # Second chunk should carry overlap when previous was force
    assert any(c.overlap_before > 0 for c in chunks[1:])
