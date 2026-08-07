"""Timestamp validation (Spec §16)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationIssue:
    code: str
    index: int
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _is_bad_number(x: float) -> bool:
    return math.isnan(x) or math.isinf(x)


def validate_items(
    items: list[dict[str, Any]],
    *,
    chunk_duration: float,
    max_gap: float = 2.0,
) -> ValidationReport:
    """Validate local-chunk aligned items against Spec invariants."""
    report = ValidationReport()
    prev_start: float | None = None
    prev_end: float | None = None

    for i, it in enumerate(items):
        try:
            start = float(it["start"])
            end = float(it["end"])
        except (KeyError, TypeError, ValueError):
            report.issues.append(
                ValidationIssue("INVALID_NUMBER", i, "missing/non-numeric timestamp")
            )
            continue

        if _is_bad_number(start) or _is_bad_number(end):
            report.issues.append(ValidationIssue("NAN_OR_INF", i, "NaN/Inf timestamp"))
            continue
        if start < 0 or end < 0:
            report.issues.append(ValidationIssue("NEGATIVE", i, "negative timestamp"))
        if end < start:
            report.issues.append(ValidationIssue("END_BEFORE_START", i, "end < start"))
        if end == start:
            report.issues.append(ValidationIssue("ZERO_DURATION", i, "start == end"))
        if end > chunk_duration + 0.05:
            report.issues.append(
                ValidationIssue("CHUNK_OVERFLOW", i, f"end {end} > chunk_duration {chunk_duration}")
            )
        if start > chunk_duration + 0.05:
            report.issues.append(
                ValidationIssue("CHUNK_OVERFLOW", i, f"start {start} > chunk_duration {chunk_duration}")
            )
        if prev_start is not None and start + 1e-6 < prev_start:
            report.issues.append(ValidationIssue("TIMESTAMP_REVERSAL", i, "start went backwards"))
        if prev_end is not None and start + 1e-3 < prev_end:
            report.issues.append(ValidationIssue("TOKEN_OVERLAP", i, "overlaps previous token"))
        if prev_end is not None and start - prev_end > max_gap:
            report.issues.append(
                ValidationIssue("ABNORMAL_GAP", i, f"gap {start - prev_end:.3f}s > {max_gap}s")
            )
        prev_start = start
        prev_end = end

    return report
