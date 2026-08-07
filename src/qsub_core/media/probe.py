"""Media probe via ffprobe (Spec §9). Never shell-concatenate paths."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from qsub_core import errors
from qsub_core.system.binaries import require_ffprobe


class ProbeError(Exception):
    def __init__(self, message: str, code: int = errors.FFPROBE_FAILURE):
        super().__init__(message)
        self.code = code


def probe_media(path: Path | str, *, ffprobe: Path | None = None) -> dict[str, Any]:
    media = Path(path).expanduser().resolve()
    if not media.is_file():
        raise ProbeError(f"input not found: {media}", errors.INVALID_INPUT)

    exe = ffprobe or require_ffprobe()
    cmd = [
        str(exe),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(media),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ProbeError(f"ffprobe failed to start: {exc}", errors.FFPROBE_FAILURE) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ProbeError(f"ffprobe failed: {detail}", errors.FFPROBE_FAILURE)

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned invalid JSON", errors.FFPROBE_FAILURE) from exc

    return normalize_probe(raw, source_path=str(media))


def normalize_probe(raw: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    fmt = raw.get("format") or {}
    duration = None
    if fmt.get("duration") is not None:
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = None

    audio_streams: list[dict[str, Any]] = []
    for stream in raw.get("streams") or []:
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        sample_rate = stream.get("sample_rate")
        try:
            sample_rate_i = int(sample_rate) if sample_rate is not None else None
        except (TypeError, ValueError):
            sample_rate_i = None
        channels = stream.get("channels")
        try:
            channels_i = int(channels) if channels is not None else None
        except (TypeError, ValueError):
            channels_i = None

        audio_streams.append(
            {
                "index": int(stream.get("index", len(audio_streams))),
                "codec": stream.get("codec_name"),
                "channels": channels_i,
                "sample_rate": sample_rate_i,
                "language": tags.get("language"),
                "default": bool(disposition.get("default")),
                "title": tags.get("title"),
            }
        )

    return {
        "schema_version": 1,
        "path": source_path,
        "container": fmt.get("format_name"),
        "duration": duration,
        "size_bytes": _maybe_int(fmt.get("size")),
        "bit_rate": _maybe_int(fmt.get("bit_rate")),
        "audio_streams": audio_streams,
        "raw_stream_count": len(raw.get("streams") or []),
    }


def select_audio_stream(
    probe: dict[str, Any],
    selector: str | int = "auto",
) -> dict[str, Any]:
    streams = probe.get("audio_streams") or []
    if not streams:
        raise ProbeError("no audio stream found", errors.UNSUPPORTED_AUDIO_STREAM)

    if selector == "auto" or selector is None:
        for s in streams:
            if s.get("default"):
                return s
        return streams[0]

    try:
        index = int(selector)
    except (TypeError, ValueError) as exc:
        raise ProbeError(f"invalid audio stream selector: {selector!r}", errors.INVALID_ARGS) from exc

    for s in streams:
        if s.get("index") == index:
            return s
    raise ProbeError(f"audio stream index not found: {index}", errors.UNSUPPORTED_AUDIO_STREAM)


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
