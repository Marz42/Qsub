"""Global token merge + overlap dedupe (Spec §17)."""

from __future__ import annotations

from typing import Any


def _norm_text(s: str) -> str:
    return "".join(ch for ch in (s or "") if not ch.isspace())


def tokens_from_alignment_chunk(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Map local repaired items to global timeline."""
    base = float(record["start"])
    chunk_id = int(record["chunk_id"])
    out: list[dict[str, Any]] = []
    for it in record.get("items") or []:
        out.append(
            {
                "text": it.get("text", ""),
                "start": round(base + float(it["start"]), 3),
                "end": round(base + float(it["end"]), 3),
                "chunk_id": chunk_id,
                "alignment_quality": it.get("alignment_quality", record.get("alignment_quality", "ok")),
            }
        )
    return out


def _suffix_prefix_overlap(prev_texts: list[str], next_texts: list[str], max_k: int = 24) -> int:
    """Return length of best text-token overlap (prev suffix == next prefix)."""
    if not prev_texts or not next_texts:
        return 0
    max_k = min(max_k, len(prev_texts), len(next_texts))
    best = 0
    for k in range(1, max_k + 1):
        a = [_norm_text(t) for t in prev_texts[-k:]]
        b = [_norm_text(t) for t in next_texts[:k]]
        if a == b and any(a):
            best = k
    return best


def merge_global_tokens(
    alignment_records: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge chunk alignments onto a global monotonic timeline.

    For force-cut overlaps: drop a prefix of the newer chunk when timestamps
    overlap and text suffix/prefix matches (Spec §17). Never blind string wipe.
    """
    by_id = {int(r["chunk_id"]): r for r in alignment_records}
    chunk_by_id = {int(c["id"]): c for c in chunks}

    merged: list[dict[str, Any]] = []
    ordered_ids = sorted(by_id.keys())

    for cid in ordered_ids:
        rec = by_id[cid]
        toks = tokens_from_alignment_chunk(rec)
        ch = chunk_by_id.get(cid) or {}
        overlap_before = float(ch.get("overlap_before") or rec.get("overlap_before") or 0.0)

        if not merged or overlap_before <= 0 or not toks:
            merged.extend(toks)
            continue

        # Overlap window in global time: [this.start, prev_chunk.end]
        this_start = float(rec["start"])
        # previous chunk end from plan
        prev_ids = [i for i in ordered_ids if i < cid]
        if not prev_ids:
            merged.extend(toks)
            continue
        prev_rec = by_id[prev_ids[-1]]
        prev_end = float(prev_rec["end"])
        window_end = prev_end

        prev_in_window = [t for t in merged if t["end"] > this_start - 1e-3 and t["start"] < window_end + 1e-3]
        next_in_window = [t for t in toks if t["start"] < window_end + 1e-3]

        drop = 0
        if prev_in_window and next_in_window:
            drop = _suffix_prefix_overlap(
                [t["text"] for t in prev_in_window],
                [t["text"] for t in next_in_window],
            )
            # If text overlap weak but timestamps heavily overlap, drop next tokens
            # that start before previous last token end (keep earlier chunk).
            if drop == 0:
                last_prev_end = float(prev_in_window[-1]["end"])
                for t in next_in_window:
                    if float(t["start"]) + 0.05 < last_prev_end and float(t["end"]) <= last_prev_end + 0.15:
                        drop += 1
                    else:
                        break

        kept = toks[drop:] if drop else toks

        # Enforce monotonicity vs last kept token
        if merged and kept:
            last_start = float(merged[-1]["start"])
            last_end = float(merged[-1]["end"])
            fixed: list[dict[str, Any]] = []
            for t in kept:
                s = float(t["start"])
                e = float(t["end"])
                if s + 1e-6 < last_start:
                    # still overlapping awkwardly — skip duplicate-ish early token
                    continue
                if s < last_end:
                    s = last_end
                if e <= s:
                    e = round(s + 0.02, 3)
                nt = dict(t)
                nt["start"] = round(s, 3)
                nt["end"] = round(e, 3)
                fixed.append(nt)
                last_start = nt["start"]
                last_end = nt["end"]
            kept = fixed

        merged.extend(kept)

    # Final monotonic pass
    final: list[dict[str, Any]] = []
    last_s = -1.0
    last_e = -1.0
    for t in merged:
        s = float(t["start"])
        e = float(t["end"])
        if s < last_s:
            s = last_s
        if s < last_e:
            s = last_e
        if e <= s:
            e = round(s + 0.02, 3)
        nt = dict(t)
        nt["start"] = round(s, 3)
        nt["end"] = round(e, 3)
        final.append(nt)
        last_s = nt["start"]
        last_e = nt["end"]
    return final
