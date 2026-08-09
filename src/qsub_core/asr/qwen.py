"""Qwen3-ASR backend (local weights only)."""

from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np
import torch

from qsub_core import errors
from qsub_core.asr.backend import ASRResult
from qsub_core.config import asr_model_path
from qsub_core.model_store import model_entry, validate_model_dir

log = logging.getLogger(__name__)


class ASRError(Exception):
    def __init__(self, message: str, code: int = errors.ASR_FAILURE):
        super().__init__(message)
        self.code = code


class QwenASRBackend:
    def __init__(
        self,
        model_path: Path | str | None = None,
        *,
        device: str = "cuda:0",
        max_new_tokens: int = 512,
    ):
        path = Path(model_path) if model_path else asr_model_path()
        status = validate_model_dir(path, model_entry("Qwen3-ASR-0.6B"), verify_hashes=False)
        if not status["ok"]:
            raise ASRError(
                f"ASR model missing or invalid: {path}: {'; '.join(status['issues'])}",
                errors.MODEL_MISSING,
            )

        from qwen_asr import Qwen3ASRModel

        dtype = torch.bfloat16 if str(device).startswith("cuda") else torch.float32
        log.info("loading Qwen3-ASR from %s on %s", path, device)
        try:
            self._model = Qwen3ASRModel.from_pretrained(
                str(path),
                dtype=dtype,
                device_map=device,
                max_inference_batch_size=1,
                max_new_tokens=max_new_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            raise ASRError(f"failed to load ASR model: {exc}", errors.RUNTIME_UNAVAILABLE) from exc
        self._model_name = "Qwen3-ASR-0.6B"
        self._device = device

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
        language: str | None,
    ) -> ASRResult:
        wav = np.asarray(audio, dtype=np.float32)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        try:
            outs = self._model.transcribe(
                audio=(wav, int(sample_rate)),
                language=language,
                return_time_stamps=False,
            )
        except torch.cuda.OutOfMemoryError as exc:
            raise ASRError("CUDA out of memory during ASR", errors.CUDA_OOM) from exc
        except Exception as exc:  # noqa: BLE001
            raise ASRError(f"ASR failed: {exc}", errors.ASR_FAILURE) from exc

        out = outs[0]
        return ASRResult(
            text=getattr(out, "text", "") or "",
            language=getattr(out, "language", None),
            model=self._model_name,
        )

    def close(self) -> None:
        if getattr(self, "_model", None) is not None:
            del self._model
            self._model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
