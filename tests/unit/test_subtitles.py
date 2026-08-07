"""Subtitle width / segmentation / SRT tests."""

from __future__ import annotations

from pathlib import Path

from qsub_core.subtitles.segment import segment_tokens
from qsub_core.subtitles.srt import format_srt_timestamp, render_srt, validate_srt_invariants, write_srt
from qsub_core.subtitles.width import display_width


def test_display_width_cjk_vs_latin():
    assert display_width("中文") == 4
    assert display_width("abcdefghij") == 10
    assert display_width("ab中文cd") == 8


def test_segment_on_sentence_end():
    tokens = []
    t = 0.0
    for ch in "今天很好。明天也好。":
        tokens.append({"text": ch, "start": t, "end": t + 0.2})
        t += 0.25
    cues = segment_tokens(tokens)
    assert len(cues) >= 2
    assert validate_srt_invariants(cues) == []
    assert all(c["end"] > c["start"] for c in cues)


def test_srt_renderer_and_bom(tmp_path: Path):
    subs = [
        {"id": 1, "start": 12.31, "end": 15.82, "text": "今天我们讨论一下这个问题。"},
        {"id": 2, "start": 16.0, "end": 18.0, "text": "第二句"},
    ]
    text = render_srt(subs)
    assert "00:00:12,310 --> 00:00:15,820" in text
    assert format_srt_timestamp(0) == "00:00:00,000"
    path = write_srt(tmp_path / "a.srt", subs, encoding="utf-8-bom")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    path2 = write_srt(tmp_path / "b.srt", subs, encoding="utf-8")
    assert not path2.read_bytes().startswith(b"\xef\xbb\xbf")
