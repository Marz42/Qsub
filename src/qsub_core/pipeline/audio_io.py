"""Audio helpers for chunked inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def load_mono_wav(path: Path | str) -> tuple[np.ndarray, int, float]:
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    duration = float(len(wav) / sr) if sr else 0.0
    return wav, int(sr), duration


def slice_wav(wav: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    i0 = int(round(start * sr))
    i1 = int(round(end * sr))
    i0 = max(0, min(i0, len(wav)))
    i1 = max(i0, min(i1, len(wav)))
    return wav[i0:i1].copy()
