"""Extract stage tests."""

from __future__ import annotations

from pathlib import Path

import soundfile as sf

from qsub_core.media.extract import extract_audio


def test_extract_to_16k_mono(tmp_path: Path):
    src = Path("tests/fixtures/tone_1s.wav").resolve()
    assert src.is_file()
    dst = tmp_path / "out.wav"
    extract_audio(src, dst, audio_stream_index=0)
    info = sf.info(str(dst))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.duration > 0.5
