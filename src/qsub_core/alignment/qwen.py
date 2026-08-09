"""Qwen3-ForcedAligner backend (local weights only)."""

from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np
import torch

from qsub_core import errors
from qsub_core.alignment.backend import AlignedItem, AlignmentResult
from qsub_core.config import aligner_model_path
from qsub_core.model_store import model_entry, validate_model_dir

log = logging.getLogger(__name__)


class AlignmentError(Exception):
    def __init__(self, message: str, code: int = errors.ALIGNMENT_FAILURE):
        super().__init__(message)
        self.code = code


class QwenAlignmentBackend:
    def __init__(
        self,
        model_path: Path | str | None = None,
        *,
        device: str = "cuda:0",
    ):
        path = Path(model_path) if model_path else aligner_model_path()
        status = validate_model_dir(
            path,
            model_entry("Qwen3-ForcedAligner-0.6B"),
            verify_hashes=False,
        )
        if not status["ok"]:
            raise AlignmentError(
                f"Aligner model missing or invalid: {path}: {'; '.join(status['issues'])}",
                errors.MODEL_MISSING,
            )

        from qwen_asr import Qwen3ForcedAligner

        dtype = torch.bfloat16 if str(device).startswith("cuda") else torch.float32
        log.info("loading Qwen3-ForcedAligner from %s on %s", path, device)
        try:
            self._model = Qwen3ForcedAligner.from_pretrained(
                str(path),
                dtype=dtype,
                device_map=device,
            )
        except Exception as exc:  # noqa: BLE001
            raise AlignmentError(
                f"failed to load aligner: {exc}",
                errors.RUNTIME_UNAVAILABLE,
            ) from exc
        self._model_name = "Qwen3-ForcedAligner-0.6B"

    def align(
        self,
        audio: np.ndarray,
        sample_rate: int,
        text: str,
        language: str,
    ) -> AlignmentResult:
        wav = np.asarray(audio, dtype=np.float32)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        try:
            outs = self._model.align(
                audio=(wav, int(sample_rate)),
                text=text,
                language=language,
            )
        except torch.cuda.OutOfMemoryError as exc:
            raise AlignmentError("CUDA out of memory during alignment", errors.CUDA_OOM) from exc
        except Exception as exc:  # noqa: BLE001
            raise AlignmentError(f"alignment failed: {exc}", errors.ALIGNMENT_FAILURE) from exc

        items: list[AlignedItem] = []
        for it in outs[0]:
            items.append(
                AlignedItem(
                    text=getattr(it, "text", "") or "",
                    start=float(getattr(it, "start_time")),
                    end=float(getattr(it, "end_time")),
                )
            )
        return AlignmentResult(items=items, model=self._model_name, language=language)

    def close(self) -> None:
        if getattr(self, "_model", None) is not None:
            del self._model
            self._model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
