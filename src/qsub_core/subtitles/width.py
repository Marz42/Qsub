"""Display width helpers (Spec §19). CJK wide = 2, Latin = 1."""

from __future__ import annotations

import unicodedata


def char_display_width(ch: str) -> int:
    if not ch:
        return 0
    # Treat fullwidth / wide East Asian as 2.
    ea = unicodedata.east_asian_width(ch)
    if ea in {"F", "W"}:
        return 2
    # Ambiguous: treat CJK-ish / fullwidth-leaning as 2 for subtitle layout.
    if ea == "A":
        # Common punctuation in CJK contexts
        if ord(ch) >= 0x1100:
            return 2
        return 1
    return 1


def display_width(text: str) -> int:
    return sum(char_display_width(ch) for ch in text)


def wrap_by_display_width(text: str, max_width: int) -> list[str]:
    """Greedy wrap by display width; prefers breaks at spaces when Latin."""
    if max_width <= 0:
        return [text]
    if display_width(text) <= max_width:
        return [text]

    lines: list[str] = []
    buf: list[str] = []
    width = 0
    for ch in text:
        w = char_display_width(ch)
        if width + w > max_width and buf:
            lines.append("".join(buf).rstrip())
            buf = []
            width = 0
            if ch.isspace():
                continue
        buf.append(ch)
        width += w
    if buf:
        lines.append("".join(buf).rstrip())
    return [ln for ln in lines if ln]
