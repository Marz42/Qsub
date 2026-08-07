"""Extract audio to 16 kHz mono PCM WAV via FFmpeg (Spec §10)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from qsub_core import errors
from qsub_core.system.binaries import require_ffmpeg


class ExtractError(Exception):
    def __init__(self, message: str, code: int = errors.FFMPEG_FAILURE):
        super().__init__(message)
        self.code = code


def extract_audio(
    input_path: Path | str,
    output_wav: Path | str,
    *,
    audio_stream_index: int | None = None,
    sample_rate: int = 16000,
    ffmpeg: Path | None = None,
) -> Path:
    """Extract / convert to PCM s16le mono WAV. Uses argv list (no shell)."""
    src = Path(input_path).expanduser().resolve()
    dst = Path(output_wav).expanduser().resolve()
    if not src.is_file():
        raise ExtractError(f"input not found: {src}", errors.INVALID_INPUT)

    dst.parent.mkdir(parents=True, exist_ok=True)
    # FFmpeg needs a recognizable extension to pick the muxer.
    tmp = dst.with_name(f"{dst.stem}.partial{dst.suffix or '.wav'}")

    exe = ffmpeg or require_ffmpeg()
    cmd: list[str] = [
        str(exe),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
    ]
    if audio_stream_index is not None:
        # Map specific audio stream by absolute stream index from ffprobe.
        cmd.extend(["-map", f"0:{audio_stream_index}"])
    else:
        cmd.extend(["-map", "0:a:0"])

    cmd.extend(
        [
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(tmp),
        ]
    )

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
        raise ExtractError(f"ffmpeg failed to start: {exc}", errors.FFMPEG_FAILURE) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise ExtractError(f"ffmpeg failed: {detail}", errors.FFMPEG_FAILURE)

    tmp.replace(dst)
    return dst
