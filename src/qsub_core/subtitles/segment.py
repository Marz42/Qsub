"""Subtitle segmentation from aligned tokens (Spec §19)."""

from __future__ import annotations

from typing import Any

from qsub_core.subtitles.width import char_display_width, display_width, wrap_by_display_width

MIN_DURATION = 0.8
TARGET_MIN = 1.5
TARGET_MAX = 6.0
HARD_MAX_DURATION = 8.0
MAX_LINES = 2
MAX_LINE_WIDTH = 36  # ~18 CJK chars per line
MAX_CUE_WIDTH = MAX_LINE_WIDTH * MAX_LINES
CLAUSE_BREAK_RATIO = 0.6

SENTENCE_END = set("。？！!?…")
CLAUSE_BREAK = set("，,；;、")
PAUSE_GAP = 0.45


def segment_tokens(
    tokens: list[dict[str, Any]],
    *,
    min_duration: float = MIN_DURATION,
    target_min: float = TARGET_MIN,
    target_max: float = TARGET_MAX,
    hard_max: float = HARD_MAX_DURATION,
    max_lines: int = MAX_LINES,
    max_line_width: int = MAX_LINE_WIDTH,
    pause_gap: float = PAUSE_GAP,
    clause_break_ratio: float = CLAUSE_BREAK_RATIO,
) -> list[dict[str, Any]]:
    if not tokens:
        return []

    cues: list[dict[str, Any]] = []
    buf: list[dict[str, Any]] = []
    max_cue_width = max_line_width * max_lines
    clause_ratio = max(0.0, min(1.0, float(clause_break_ratio)))

    def flush(*, force: bool = False) -> None:
        nonlocal buf
        if not buf:
            return
        start = float(buf[0]["start"])
        end = float(buf[-1]["end"])
        text = "".join(t.get("text", "") for t in buf)
        if not force and (end - start) < min_duration and cues:
            prev = cues[-1]
            merged_text = prev["text"].replace("\n", "") + text
            prev["end"] = max(float(prev["end"]), end)
            prev["text"] = _format_cue_text(merged_text, max_lines, max_line_width)
            buf = []
            return
        if end <= start:
            end = start + 0.02
        if end - start < min_duration:
            end = start + min_duration
        cues.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": _format_cue_text(text, max_lines, max_line_width),
            }
        )
        buf = []

    for i, tok in enumerate(tokens):
        buf.append(tok)
        text = "".join(t.get("text", "") for t in buf)
        start = float(buf[0]["start"])
        end = float(buf[-1]["end"])
        dur = end - start
        piece = tok.get("text") or ""
        ch = piece[-1] if piece else ""

        next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
        gap = 0.0
        if next_tok is not None:
            gap = float(next_tok["start"]) - float(tok["end"])

        should_cut = False
        if ch in SENTENCE_END and dur >= min_duration:
            should_cut = True
        elif ch in CLAUSE_BREAK and dur >= target_max * clause_ratio:
            should_cut = True
        elif next_tok is not None and gap >= pause_gap and dur >= target_min:
            should_cut = True
        elif dur >= hard_max:
            should_cut = True
        elif dur >= target_max and display_width(text) >= max_line_width:
            should_cut = True
        elif display_width(text) >= max_cue_width and dur >= min_duration:
            should_cut = True

        if should_cut:
            flush(force=True)

    flush(force=True)

    fixed: list[dict[str, Any]] = []
    for i, cue in enumerate(cues, start=1):
        s = float(cue["start"])
        e = float(cue["end"])
        if fixed and s < float(fixed[-1]["end"]):
            s = float(fixed[-1]["end"])
        if e <= s:
            e = s + 0.02
        if e - s > hard_max:
            e = s + hard_max
        fixed.append(
            {
                "id": i,
                "start": round(s, 3),
                "end": round(e, 3),
                "text": cue["text"],
            }
        )
    return fixed


def _format_cue_text(text: str, max_lines: int, max_line_width: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if display_width(text) <= max_line_width:
        return text
    lines = wrap_by_display_width(text, max_line_width)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    head = lines[: max_lines - 1]
    rest = "".join(lines[max_lines - 1 :])
    last = _truncate_width(rest, max_line_width)
    return "\n".join(head + [last])


def _truncate_width(text: str, max_width: int) -> str:
    out: list[str] = []
    width = 0
    for ch in text:
        cw = char_display_width(ch)
        if width + cw > max_width:
            break
        out.append(ch)
        width += cw
    return "".join(out)
