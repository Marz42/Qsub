"""Simple time-based chunk planning (Phase 0). VAD-based planning arrives in Phase 2."""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Spec §12 defaults
TARGET_CHUNK_DURATION = 120.0
SOFT_MAX_DURATION = 180.0
HARD_MAX_DURATION = 240.0
OVERLAP = 0.75


@dataclass(frozen=True)
class ChunkPlan:
    id: int
    start: float
    end: float
    overlap_before: float

    def to_dict(self) -> dict:
        return asdict(self)


def plan_chunks(
    duration: float,
    *,
    hard_max: float = HARD_MAX_DURATION,
    target: float = TARGET_CHUNK_DURATION,
    soft_max: float = SOFT_MAX_DURATION,
    overlap: float = OVERLAP,
) -> list[ChunkPlan]:
    """Plan force-cut chunks so each window stays under ForcedAligner limits."""
    if duration <= 0:
        raise ValueError("audio duration must be > 0")

    chunks: list[ChunkPlan] = []
    cursor = 0.0
    chunk_id = 0
    while cursor < duration - 1e-6:
        remaining = duration - cursor
        if remaining <= hard_max:
            overlap_before = overlap if chunk_id > 0 else 0.0
            start = max(0.0, cursor - overlap_before) if chunk_id > 0 else cursor
            if chunk_id == 0:
                start = 0.0
                overlap_before = 0.0
            end = duration
            if end - start > hard_max:
                start = max(0.0, end - hard_max)
                overlap_before = overlap if chunk_id > 0 else 0.0
            chunks.append(ChunkPlan(chunk_id, start, end, overlap_before))
            break

        length = min(target, remaining)
        end = min(duration, cursor + length)
        if end < duration and (duration - end) < 30.0 and (end - cursor) <= soft_max:
            end = min(duration, cursor + min(soft_max, remaining))

        overlap_before = overlap if chunk_id > 0 else 0.0
        start = max(0.0, cursor - overlap_before) if chunk_id > 0 else cursor
        if chunk_id == 0:
            start = cursor
            overlap_before = 0.0
        if end - start > hard_max:
            end = start + hard_max

        chunks.append(ChunkPlan(chunk_id, start, end, overlap_before))
        cursor = end
        chunk_id += 1

    return chunks
