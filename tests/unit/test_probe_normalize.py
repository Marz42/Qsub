"""Probe normalize / select unit tests (no ffprobe required)."""

from __future__ import annotations

import pytest

from qsub_core import errors
from qsub_core.media.probe import ProbeError, normalize_probe, select_audio_stream


def test_normalize_probe_audio_streams():
    raw = {
        "format": {"format_name": "wav", "duration": "1.5", "size": "100"},
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "channels": 1,
                "sample_rate": "16000",
                "disposition": {"default": 1},
                "tags": {"language": "eng"},
            }
        ],
    }
    probe = normalize_probe(raw, source_path="x.wav")
    assert probe["duration"] == 1.5
    assert len(probe["audio_streams"]) == 1
    assert probe["audio_streams"][0]["default"] is True
    sel = select_audio_stream(probe, "auto")
    assert sel["index"] == 0


def test_select_missing_stream_raises():
    probe = {"audio_streams": [{"index": 1, "default": True}]}
    with pytest.raises(ProbeError) as ei:
        select_audio_stream(probe, 9)
    assert ei.value.code == errors.UNSUPPORTED_AUDIO_STREAM
