"""Silero VAD wrapper — local weights preferred (Spec §11)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch

from qsub_core import errors
from qsub_core.config import vad_model_path

log = logging.getLogger(__name__)


class VadError(Exception):
    def __init__(self, message: str, code: int = errors.RUNTIME_UNAVAILABLE):
        super().__init__(message)
        self.code = code


def _find_local_model_file(model_dir: Path) -> Path | None:
    if not model_dir.is_dir():
        return None
    for name in (
        "silero_vad.jit",
        "silero_vad.onnx",
        "silero_vad_16k_op15.onnx",
    ):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    for pattern in ("**/silero_vad.jit", "**/silero_vad.onnx", "**/silero_vad_16k_op15.onnx"):
        matches = sorted(model_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def load_vad_model(model_dir: Path | str | None = None):
    """Load Silero VAD from local dir, else bundled silero-vad package (offline)."""
    directory = Path(model_dir) if model_dir else vad_model_path()
    local = _find_local_model_file(directory)

    if local is not None and local.suffix == ".jit":
        log.info("loading Silero VAD JIT from %s", local)
        model = torch.jit.load(str(local), map_location="cpu")
        model.eval()
        return model, {"source": str(local), "format": "jit"}

    if local is not None and local.suffix == ".onnx":
        try:
            from silero_vad.utils_vad import OnnxWrapper
        except ImportError as exc:
            raise VadError(
                "local ONNX VAD found but silero-vad package is missing",
                errors.RUNTIME_UNAVAILABLE,
            ) from exc
        log.info("loading Silero VAD ONNX from %s", local)
        model = OnnxWrapper(str(local), force_onnx_cpu=True)
        return model, {"source": str(local), "format": "onnx"}

    try:
        from silero_vad import load_silero_vad
    except ImportError as exc:
        raise VadError(
            f"Silero VAD not found under {directory} and silero-vad package is not installed. "
            "Place silero_vad.jit in models/silero-vad/ or add dependency silero-vad.",
            errors.MODEL_MISSING,
        ) from exc

    log.info("loading Silero VAD from silero-vad package (bundled weights)")
    model = load_silero_vad()
    return model, {"source": "silero-vad-package", "format": "package"}


def read_wav_mono(path: Path | str, *, target_sr: int = 16000) -> tuple[torch.Tensor, int]:
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if len(wav) == 0:
        return torch.zeros(0), target_sr
    if int(sr) == target_sr:
        return torch.from_numpy(wav), target_sr

    # Linear resample to target_sr (extract already targets 16 kHz; this is a safety net).
    n = max(1, int(round(len(wav) * float(target_sr) / float(sr))))
    x_old = np.linspace(0.0, 1.0, num=len(wav), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    resampled = np.interp(x_new, x_old, wav).astype(np.float32)
    return torch.from_numpy(resampled), target_sr


def run_vad(
    wav_path: Path | str,
    *,
    model_dir: Path | str | None = None,
    sampling_rate: int = 16000,
    min_silence_ms: int = 300,
    min_speech_ms: int = 250,
) -> dict[str, Any]:
    """Return Spec-shaped VAD result: speech segments in seconds."""
    model, meta = load_vad_model(model_dir)
    try:
        from silero_vad import get_speech_timestamps
    except ImportError as exc:
        raise VadError(
            "silero-vad package required for get_speech_timestamps",
            errors.RUNTIME_UNAVAILABLE,
        ) from exc

    audio, sr = read_wav_mono(wav_path, target_sr=sampling_rate)
    if audio.numel() == 0:
        return {"schema_version": 1, "model": meta, "segments": []}

    timestamps = get_speech_timestamps(
        audio,
        model,
        sampling_rate=sr,
        min_silence_duration_ms=min_silence_ms,
        min_speech_duration_ms=min_speech_ms,
        return_seconds=True,
    )

    segments = [
        {"start": float(t["start"]), "end": float(t["end"])}
        for t in timestamps
        if float(t["end"]) > float(t["start"])
    ]
    return {
        "schema_version": 1,
        "model": meta,
        "sample_rate": sr,
        "segments": segments,
    }
