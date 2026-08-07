"""Fingerprint helper tests."""

from __future__ import annotations

from pathlib import Path

from qsub_core.pipeline.fingerprint import source_fingerprint


def test_fingerprint_stable_for_same_bytes(tmp_path: Path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello-qsub" * 1000)
    a = source_fingerprint(p, edge_bytes=64)
    b = source_fingerprint(p, edge_bytes=64)
    assert a["fingerprint"] == b["fingerprint"]
    assert a["size"] == p.stat().st_size


def test_fingerprint_changes_when_content_changes(tmp_path: Path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"a" * 100)
    first = source_fingerprint(p, edge_bytes=32)["fingerprint"]
    p.write_bytes(b"b" * 100)
    second = source_fingerprint(p, edge_bytes=32)["fingerprint"]
    assert first != second
