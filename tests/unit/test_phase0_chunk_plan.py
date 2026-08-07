"""Unit tests for Phase 0 chunk planning."""

from __future__ import annotations

from qsub_core.pipeline.chunk_plan import plan_chunks


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
