"""ASR backend interface (Spec §43)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class ASRResult:
    text: str
    language: str | None
    model: str


class ASRBackend(Protocol):
    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
        language: str | None,
    ) -> ASRResult: ...

    def close(self) -> None: ...
