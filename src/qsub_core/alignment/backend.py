"""Alignment backend interface (Spec §43)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class AlignedItem:
    text: str
    start: float
    end: float


@dataclass
class AlignmentResult:
    items: list[AlignedItem]
    model: str
    language: str | None = None


class AlignmentBackend(Protocol):
    def align(
        self,
        audio: np.ndarray,
        sample_rate: int,
        text: str,
        language: str,
    ) -> AlignmentResult: ...

    def close(self) -> None: ...
