"""Canonical project.json model / IO (Spec §18)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qsub_core import __version__
from qsub_core.io_util import atomic_write_json
from qsub_core.pipeline.resume import load_json


def build_project(
    *,
    source_path: str,
    duration: float | None,
    audio_stream: int | None,
    language: str | None,
    tokens: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    asr_model: str = "Qwen3-ASR-0.6B",
    aligner_model: str = "Qwen3-ForcedAligner-0.6B",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app_version": __version__,
        "source": {
            "path": source_path,
            "duration": duration,
            "audio_stream": audio_stream,
        },
        "recognition": {
            "model": asr_model,
            "language": language,
        },
        "alignment": {
            "model": aligner_model,
        },
        "tokens": [
            {
                "text": t.get("text", ""),
                "start": float(t["start"]),
                "end": float(t["end"]),
            }
            for t in tokens
        ],
        "subtitles": [
            {
                "id": int(s["id"]),
                "start": float(s["start"]),
                "end": float(s["end"]),
                "text": s.get("text", ""),
            }
            for s in subtitles
        ],
    }


def write_project(path: Path | str, project: dict[str, Any]) -> Path:
    dest = Path(path)
    atomic_write_json(dest, project)
    return dest


def load_project(path: Path | str) -> dict[str, Any]:
    data = load_json(Path(path))
    if not isinstance(data, dict):
        raise ValueError(f"invalid project.json: {path}")
    if "subtitles" not in data and "tokens" not in data:
        raise ValueError(f"project missing subtitles/tokens: {path}")
    return data
