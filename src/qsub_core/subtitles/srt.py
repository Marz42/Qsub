"""SRT renderer / parser (Spec §20)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from qsub_core.io_util import atomic_write_bytes

EncodingName = Literal["utf-8", "utf-8-bom"]

_TS_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)
_ARROW_RE = re.compile(
    r"^(?P<a>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<b>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000.0))
    hours, rem = divmod(ms_total, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def parse_srt_timestamp(value: str) -> float:
    m = _TS_RE.fullmatch(value.strip())
    if not m:
        raise ValueError(f"invalid SRT timestamp: {value!r}")
    return (
        int(m.group("h")) * 3600
        + int(m.group("m")) * 60
        + int(m.group("s"))
        + int(m.group("ms")) / 1000.0
    )


def parse_srt(text: str) -> list[dict[str, Any]]:
    """Parse SRT text into cue dicts with id/start/end/text."""
    body = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        return []
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", body):
        lines = block.split("\n")
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()
        if len(lines) < 2:
            continue
        idx = 0
        cue_id: int | None = None
        if lines[0].strip().isdigit():
            cue_id = int(lines[0].strip())
            idx = 1
        if idx >= len(lines):
            continue
        am = _ARROW_RE.match(lines[idx].strip())
        if not am:
            continue
        start = parse_srt_timestamp(am.group("a"))
        end = parse_srt_timestamp(am.group("b"))
        text_lines = lines[idx + 1 :]
        cues.append(
            {
                "id": cue_id if cue_id is not None else len(cues) + 1,
                "start": start,
                "end": end,
                "text": "\n".join(text_lines),
            }
        )
    return cues


def load_srt(path: Path | str) -> list[dict[str, Any]]:
    raw = Path(path).expanduser().resolve().read_text(encoding="utf-8-sig")
    return parse_srt(raw)


def render_srt(subtitles: list[dict[str, Any]]) -> str:
    """Render subtitle events to SRT text (no BOM)."""
    blocks: list[str] = []
    prev_start = -1.0
    for i, cue in enumerate(subtitles, start=1):
        start = float(cue["start"])
        end = float(cue["end"])
        if end <= start:
            end = start + 0.02
        if start < prev_start:
            start = prev_start
            if end <= start:
                end = start + 0.02
        text = str(cue.get("text") or "").replace("\r\n", "\n").strip("\n")
        cue_id = int(cue.get("id") or i)
        blocks.append(
            f"{cue_id}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{text}"
        )
        prev_start = start
    body = "\n\n".join(blocks)
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def write_srt(
    path: Path | str,
    subtitles: list[dict[str, Any]],
    *,
    encoding: EncodingName = "utf-8-bom",
) -> Path:
    dest = Path(path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = render_srt(subtitles)
    if encoding == "utf-8-bom":
        data = text.encode("utf-8-sig")
    else:
        data = text.encode("utf-8")
    atomic_write_bytes(dest, data)
    return dest


def validate_srt_invariants(subtitles: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    prev_start = None
    for i, cue in enumerate(subtitles):
        expected_id = i + 1
        if int(cue.get("id", -1)) != expected_id:
            errors.append(f"id not continuous at {i}: {cue.get('id')}")
        start = float(cue["start"])
        end = float(cue["end"])
        if start < 0 or end < 0:
            errors.append(f"negative timestamp at {i}")
        if end <= start:
            errors.append(f"non-positive duration at {i}")
        if prev_start is not None and start + 1e-9 < prev_start:
            errors.append(f"start went backwards at {i}")
        prev_start = start
    return errors
