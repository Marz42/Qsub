"""Chunk planning — VAD-aware with Spec §12 defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Spec §12 defaults
TARGET_CHUNK_DURATION = 120.0
SOFT_MAX_DURATION = 180.0
HARD_MAX_DURATION = 240.0
OVERLAP = 0.75

# Prefer longer natural pauses when choosing a cut.
LONG_SILENCE_S = 0.80
MIN_SILENCE_CUT_S = 0.30
MIN_CHUNK_S = 20.0


@dataclass(frozen=True)
class ChunkPlan:
    id: int
    start: float
    end: float
    overlap_before: float
    cut_reason: str = "natural"  # natural | soft | force

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _SilenceGap:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def cut_at(self) -> float:
        # Midpoint of silence — stable boundary for consecutive chunks.
        return (self.start + self.end) / 2.0


def silence_gaps(
    duration: float,
    speech_segments: list[dict[str, Any]],
) -> list[_SilenceGap]:
    """Compute silence intervals from VAD speech segments over [0, duration]."""
    segs = sorted(
        (
            {"start": float(s["start"]), "end": float(s["end"])}
            for s in speech_segments
            if float(s.get("end", 0)) > float(s.get("start", 0))
        ),
        key=lambda s: s["start"],
    )
    gaps: list[_SilenceGap] = []
    cursor = 0.0
    for seg in segs:
        start = max(0.0, min(duration, seg["start"]))
        end = max(0.0, min(duration, seg["end"]))
        if start > cursor + 1e-6:
            gaps.append(_SilenceGap(cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 1e-6:
        gaps.append(_SilenceGap(cursor, duration))
    return gaps


def plan_chunks(
    duration: float,
    *,
    hard_max: float = HARD_MAX_DURATION,
    target: float = TARGET_CHUNK_DURATION,
    soft_max: float = SOFT_MAX_DURATION,
    overlap: float = OVERLAP,
) -> list[ChunkPlan]:
    """Force-cut planner (no VAD). Kept for Phase 0 / fallback."""
    return plan_chunks_from_vad(
        duration,
        speech_segments=[],
        hard_max=hard_max,
        target=target,
        soft_max=soft_max,
        overlap=overlap,
    )


def plan_chunks_from_vad(
    duration: float,
    speech_segments: list[dict[str, Any]],
    *,
    hard_max: float = HARD_MAX_DURATION,
    target: float = TARGET_CHUNK_DURATION,
    soft_max: float = SOFT_MAX_DURATION,
    overlap: float = OVERLAP,
) -> list[ChunkPlan]:
    """
    Plan contiguous chunks covering [0, duration].

    Cut priority (Spec §12):
      长停顿 > 短停顿 > 强制时间切分
    Overlap is applied only on forced cuts.
    """
    if duration <= 0:
        raise ValueError("audio duration must be > 0")

    # No VAD speech → fall back to pure time cuts (do not treat whole file as silence).
    if not speech_segments:
        return _plan_force_time(
            duration,
            hard_max=hard_max,
            target=target,
            soft_max=soft_max,
            overlap=overlap,
        )

    gaps = [
        g
        for g in silence_gaps(duration, speech_segments)
        if g.duration >= MIN_SILENCE_CUT_S
    ]

    chunks: list[ChunkPlan] = []
    cursor = 0.0
    chunk_id = 0
    pending_overlap = 0.0

    while cursor < duration - 1e-6:
        remaining = duration - cursor
        window_lo = cursor + MIN_CHUNK_S
        window_hi = min(duration, cursor + soft_max)
        target_abs = cursor + target

        candidates = [
            g
            for g in gaps
            if window_lo <= g.cut_at <= window_hi and g.cut_at > cursor + 1e-6
        ]

        # If the remainder fits under hard_max and there is no useful cut near target,
        # emit a single tail chunk.
        if remaining <= hard_max + 1e-9 and not candidates:
            start = max(0.0, cursor - pending_overlap)
            chunks.append(
                ChunkPlan(
                    id=chunk_id,
                    start=start,
                    end=duration,
                    overlap_before=pending_overlap if chunk_id > 0 else 0.0,
                    cut_reason="tail",
                )
            )
            break

        chosen: _SilenceGap | None = None
        cut_reason = "force"
        end = min(duration, cursor + hard_max)
        next_overlap = overlap

        if candidates:
            def score(g: _SilenceGap) -> tuple:
                long_bonus = 1.0 if g.duration >= LONG_SILENCE_S else 0.0
                return (long_bonus, -abs(g.cut_at - target_abs), g.duration)

            chosen = max(candidates, key=score)
            end = min(duration, chosen.cut_at)
            if end - cursor > hard_max:
                end = cursor + hard_max
                cut_reason = "force"
                next_overlap = overlap
                chosen = None
            else:
                cut_reason = "natural" if chosen.duration >= LONG_SILENCE_S else "soft"
                next_overlap = 0.0

        if chosen is None and cut_reason == "force":
            if remaining <= hard_max + 1e-9:
                end = duration
                cut_reason = "tail"
                next_overlap = 0.0
            else:
                end = min(duration, cursor + hard_max)
                next_overlap = overlap

        if end <= cursor + 1e-6:
            end = min(duration, cursor + hard_max)
            next_overlap = overlap
            cut_reason = "force"

        start = max(0.0, cursor - pending_overlap)
        if end - start > hard_max:
            start = max(0.0, end - hard_max)
            pending_overlap = max(pending_overlap, cursor - start) if chunk_id > 0 else 0.0

        chunks.append(
            ChunkPlan(
                id=chunk_id,
                start=start,
                end=end,
                overlap_before=pending_overlap if chunk_id > 0 else 0.0,
                cut_reason=cut_reason,
            )
        )
        cursor = end
        pending_overlap = next_overlap if cut_reason == "force" else 0.0
        chunk_id += 1

    return chunks


def _plan_force_time(
    duration: float,
    *,
    hard_max: float,
    target: float,
    soft_max: float,
    overlap: float,
) -> list[ChunkPlan]:
    chunks: list[ChunkPlan] = []
    cursor = 0.0
    chunk_id = 0
    pending_overlap = 0.0
    while cursor < duration - 1e-6:
        remaining = duration - cursor
        if remaining <= hard_max + 1e-9:
            start = max(0.0, cursor - pending_overlap)
            if chunk_id == 0:
                start = 0.0
                pending_overlap = 0.0
            end = duration
            if end - start > hard_max:
                start = max(0.0, end - hard_max)
            chunks.append(
                ChunkPlan(
                    id=chunk_id,
                    start=start,
                    end=end,
                    overlap_before=pending_overlap if chunk_id > 0 else 0.0,
                    cut_reason="tail",
                )
            )
            break

        length = min(target, remaining)
        end = min(duration, cursor + length)
        if end < duration and (duration - end) < 30.0 and (end - cursor) <= soft_max:
            end = min(duration, cursor + min(soft_max, remaining))
        if end - cursor > hard_max:
            end = cursor + hard_max

        start = max(0.0, cursor - pending_overlap)
        if chunk_id == 0:
            start = cursor
            pending_overlap = 0.0
        if end - start > hard_max:
            end = start + hard_max

        chunks.append(
            ChunkPlan(
                id=chunk_id,
                start=start,
                end=end,
                overlap_before=pending_overlap if chunk_id > 0 else 0.0,
                cut_reason="force",
            )
        )
        cursor = end
        pending_overlap = overlap
        chunk_id += 1
    return chunks
