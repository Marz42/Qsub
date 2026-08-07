"""Timestamp repair after ForcedAligner (Spec §16)."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from qsub_core.alignment.validate import ValidationIssue, validate_items


def _finite(x: float, fallback: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(v) or math.isinf(v):
        return fallback
    return v


def repair_items(
    items: list[dict[str, Any]],
    *,
    chunk_duration: float,
    min_dur: float = 0.02,
) -> tuple[list[dict[str, Any]], list[ValidationIssue], str]:
    """
    Repair local aligned items.

    Returns (repaired_items, residual_issues, quality) where quality is
    "ok" | "repaired" | "degraded".
    """
    if not items:
        return [], [], "ok"

    out = deepcopy(items)
    n = len(out)
    changed = False

    # 1) Sanitize numbers / clamp into [0, chunk_duration]
    for it in out:
        s = _finite(it.get("start"), 0.0)
        e = _finite(it.get("end"), s)
        s = max(0.0, min(s, chunk_duration))
        e = max(0.0, min(e, chunk_duration))
        if e < s:
            e = s
        if s != it.get("start") or e != it.get("end"):
            changed = True
        it["start"] = s
        it["end"] = e

    # 2) Fix zero-duration / end < start via neighbor interpolation
    for i in range(n):
        s = float(out[i]["start"])
        e = float(out[i]["end"])
        if e > s:
            continue
        changed = True
        left = float(out[i - 1]["end"]) if i > 0 else max(0.0, s)
        right = float(out[i + 1]["start"]) if i + 1 < n else min(chunk_duration, max(e, left + min_dur))
        if right <= left:
            # Collapse: nudge forward with min_dur if possible
            left = s
            right = min(chunk_duration, left + min_dur)
        # Place a small span around midpoint, or uniform in available gap
        span = max(min_dur, (right - left) / 3.0)
        mid = (left + right) / 2.0
        ns = max(left, mid - span / 2.0)
        ne = min(right, ns + span)
        if ne <= ns:
            ne = min(chunk_duration, ns + min_dur)
        out[i]["start"] = ns
        out[i]["end"] = ne

    # 3) Consecutive equal timestamps → uniform interpolate across a run
    i = 0
    while i < n:
        j = i + 1
        while j < n and abs(float(out[j]["start"]) - float(out[i]["start"])) < 1e-9 and abs(
            float(out[j]["end"]) - float(out[i]["end"])
        ) < 1e-9:
            j += 1
        if j - i >= 2:
            changed = True
            left = float(out[i - 1]["end"]) if i > 0 else float(out[i]["start"])
            right = float(out[j]["start"]) if j < n else chunk_duration
            if right <= left:
                right = min(chunk_duration, left + min_dur * (j - i))
            step = (right - left) / (j - i)
            for k, idx in enumerate(range(i, j)):
                out[idx]["start"] = left + k * step
                out[idx]["end"] = left + (k + 1) * step
        i = j

    # 4) Small overlaps → midpoint adjust
    for i in range(1, n):
        prev_e = float(out[i - 1]["end"])
        cur_s = float(out[i]["start"])
        if cur_s + 1e-6 < prev_e:
            changed = True
            mid = (prev_e + cur_s) / 2.0
            out[i - 1]["end"] = mid
            out[i]["start"] = mid
            if float(out[i - 1]["end"]) <= float(out[i - 1]["start"]):
                out[i - 1]["end"] = min(chunk_duration, float(out[i - 1]["start"]) + min_dur)
            if float(out[i]["end"]) <= float(out[i]["start"]):
                out[i]["end"] = min(chunk_duration, float(out[i]["start"]) + min_dur)

    # 5) Enforce monotonic non-decreasing starts
    for i in range(1, n):
        if float(out[i]["start"]) < float(out[i - 1]["start"]):
            changed = True
            out[i]["start"] = float(out[i - 1]["start"])
        if float(out[i]["start"]) < float(out[i - 1]["end"]):
            # after previous end if still overlapping badly
            out[i]["start"] = float(out[i - 1]["end"])
            changed = True
        if float(out[i]["end"]) <= float(out[i]["start"]):
            out[i]["end"] = min(chunk_duration, float(out[i]["start"]) + min_dur)
            changed = True

    # Round for stability
    for it in out:
        it["start"] = round(float(it["start"]), 3)
        it["end"] = round(float(it["end"]), 3)
        if it["end"] <= it["start"]:
            it["end"] = round(min(chunk_duration, it["start"] + min_dur), 3)

    residual = validate_items(out, chunk_duration=chunk_duration).issues
    # Filter residual: ABNORMAL_GAP is warning-only, not degraded by itself
    hard = [x for x in residual if x.code not in {"ABNORMAL_GAP"}]
    if hard:
        quality = "degraded"
        for it in out:
            it["alignment_quality"] = "degraded"
    elif changed:
        quality = "repaired"
    else:
        quality = "ok"
    return out, residual, quality
