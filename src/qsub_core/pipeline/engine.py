"""Pipeline engine — Phase 2: probe → extract → VAD → chunk plan."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qsub_core import errors
from qsub_core.events import EventEmitter
from qsub_core.io_util import atomic_write_json
from qsub_core.media.extract import ExtractError, extract_audio
from qsub_core.media.probe import ProbeError, probe_media, select_audio_stream
from qsub_core.pipeline.chunk_plan import plan_chunks_from_vad
from qsub_core.pipeline.fingerprint import source_fingerprint
from qsub_core.pipeline.workspace import (
    JobWorkspace,
    create_job_workspace,
    initial_job_record,
)
from qsub_core.vad.silero import VadError, run_vad

log = logging.getLogger(__name__)

WEIGHTS = {
    "probe": 0.02,
    "extract": 0.05,
    "vad": 0.03,
    "chunk": 0.0,  # folded into vad progress for Phase 2 reporting
    "asr": 0.45,
    "alignment": 0.35,
    "subtitle": 0.05,
    "export": 0.05,
}


@dataclass
class TranscribeOptions:
    input_path: Path
    output: Path | None = None
    language: str = "auto"
    device: str = "auto"
    audio_stream: str = "auto"
    mode: str = "safe"
    resume: bool = True
    work_dir: Path | None = None
    keep_work: bool = False
    overwrite: bool = False
    events: str = "text"
    log_level: str = "info"


class PipelineEngine:
    """Phase 2 media pipeline. ASR/align/SRT arrive in Phase 3–5."""

    def __init__(self, opts: TranscribeOptions, events: EventEmitter):
        self.opts = opts
        self.events = events
        self.ws: JobWorkspace | None = None

    def run(self) -> int:
        t0 = time.perf_counter()
        src = self.opts.input_path.expanduser().resolve()
        if not src.is_file():
            self.events.emit("error", code="INVALID_INPUT", message=f"input not found: {src}")
            return errors.INVALID_INPUT

        self.ws = create_job_workspace(work_dir=self.opts.work_dir)
        job = initial_job_record(
            job_id=self.ws.job_id,
            source=str(src),
            args={
                "language": self.opts.language,
                "device": self.opts.device,
                "audio_stream": self.opts.audio_stream,
                "mode": self.opts.mode,
                "resume": self.opts.resume,
                "output": str(self.opts.output) if self.opts.output else None,
            },
        )
        if self.opts.resume and self.ws.job_json.is_file():
            try:
                import json

                existing = json.loads(self.ws.job_json.read_text(encoding="utf-8"))
                # Keep completed stages when reusing --work-dir
                if existing.get("source", {}).get("path") == str(src):
                    job["stages_completed"] = list(existing.get("stages_completed") or [])
                    job["job_id"] = existing.get("job_id", job["job_id"])
                    self.ws.job_id = job["job_id"]
            except (OSError, json.JSONDecodeError):
                pass
        job["phase"] = "phase2_media"
        self.ws.write_job(job)
        self.events.emit("job_started", job_id=self.ws.job_id, work_dir=str(self.ws.root))
        log.info("job %s work_dir=%s source=%s", self.ws.job_id, self.ws.root, src)

        try:
            fp = source_fingerprint(src)
            job["source"]["fingerprint"] = fp
            self.ws.write_job(job)
        except OSError as exc:
            self.events.emit("error", code="INVALID_INPUT", message=str(exc))
            return errors.INVALID_INPUT

        # --- probe ---
        code, probe, stream = self._stage_probe(job)
        if code != errors.SUCCESS:
            return code
        assert probe is not None and stream is not None
        overall = WEIGHTS["probe"]

        # --- extract ---
        code = self._stage_extract(job, src, stream)
        if code != errors.SUCCESS:
            return code
        overall += WEIGHTS["extract"]

        # --- vad ---
        code, vad = self._stage_vad(job)
        if code != errors.SUCCESS:
            return code
        assert vad is not None
        overall += WEIGHTS["vad"]

        # --- chunk plan ---
        duration = float(probe.get("duration") or 0.0)
        if duration <= 0:
            # Fallback: derive from wav length via soundfile
            import soundfile as sf

            info = sf.info(str(self.ws.audio_wav))
            duration = float(info.duration)

        chunks = plan_chunks_from_vad(duration, vad.get("segments") or [])
        chunks_payload = {"version": 1, "chunks": [c.to_dict() for c in chunks]}
        atomic_write_json(self.ws.chunks_json, chunks_payload)
        job.setdefault("stages_completed", [])
        if "chunk" not in job["stages_completed"]:
            job["stages_completed"].append("chunk")
        job["chunks"] = {"count": len(chunks), "duration": duration}
        job["status"] = "phase2_media_complete"
        job["notes"] = [
            "Phase 2 media pipeline: probe + extract + VAD + chunk plan.",
            "ASR / alignment / SRT arrive in Phase 3–5.",
        ]
        self.ws.write_job(job)
        self.events.emit("artifact", kind="chunks", path=str(self.ws.chunks_json))
        self.events.emit(
            "progress",
            stage="chunk",
            current=len(chunks),
            total=len(chunks),
            overall=overall,
        )

        elapsed = round(time.perf_counter() - t0, 3)
        self.events.emit("artifact", kind="job", path=str(self.ws.job_json))
        self.events.emit(
            "completed",
            elapsed_seconds=elapsed,
            phase="phase2_media",
            chunks=len(chunks),
            next="asr (Phase 3)",
        )
        log.info(
            "job %s phase2 complete chunks=%s duration=%.2fs in %ss",
            self.ws.job_id,
            len(chunks),
            duration,
            elapsed,
        )
        return errors.SUCCESS

    def _fail(self, job: dict[str, Any], code: int, message: str) -> int:
        job["status"] = "failed"
        job["error"] = {"code": code, "message": message}
        assert self.ws is not None
        self.ws.write_job(job)
        self.events.emit("error", code=_code_name(code), message=message)
        return code

    def _stage_probe(
        self, job: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
        assert self.ws is not None
        self.events.emit("stage_started", stage="probe")
        self.events.emit("progress", stage="probe", current=0, total=1, overall=0.0)
        try:
            if (
                self.opts.resume
                and self.ws.probe_json.is_file()
                and "probe" in (job.get("stages_completed") or [])
            ):
                import json

                probe = json.loads(self.ws.probe_json.read_text(encoding="utf-8"))
                stream = probe.get("selected_audio_stream") or select_audio_stream(
                    probe, self.opts.audio_stream
                )
            else:
                src = Path(job["source"]["path"])
                probe = probe_media(src)
                stream = select_audio_stream(probe, self.opts.audio_stream)
                probe["selected_audio_stream"] = stream
                atomic_write_json(self.ws.probe_json, probe)
        except ProbeError as exc:
            return self._fail(job, exc.code, str(exc)), None, None
        except FileNotFoundError as exc:
            return self._fail(job, errors.FFPROBE_FAILURE, str(exc)), None, None

        stages = list(job.get("stages_completed") or [])
        if "probe" not in stages:
            stages.append("probe")
        job["stages_completed"] = stages
        job["probe"] = {
            "duration": probe.get("duration"),
            "audio_stream": stream.get("index"),
            "codec": stream.get("codec"),
        }
        self.ws.write_job(job)
        self.events.emit(
            "progress", stage="probe", current=1, total=1, overall=WEIGHTS["probe"]
        )
        self.events.emit("stage_finished", stage="probe")
        self.events.emit("artifact", kind="probe", path=str(self.ws.probe_json))
        return errors.SUCCESS, probe, stream

    def _stage_extract(
        self,
        job: dict[str, Any],
        src: Path,
        stream: dict[str, Any],
    ) -> int:
        assert self.ws is not None
        self.events.emit("stage_started", stage="extract")
        self.events.emit(
            "progress",
            stage="extract",
            current=0,
            total=1,
            overall=WEIGHTS["probe"],
        )
        try:
            if self.opts.resume and self.ws.audio_wav.is_file() and self.ws.audio_wav.stat().st_size > 0:
                log.info("resume: reusing %s", self.ws.audio_wav)
            else:
                extract_audio(
                    src,
                    self.ws.audio_wav,
                    audio_stream_index=int(stream["index"]),
                )
        except ExtractError as exc:
            return self._fail(job, exc.code, str(exc))
        except FileNotFoundError as exc:
            return self._fail(job, errors.FFMPEG_FAILURE, str(exc))

        stages = list(job.get("stages_completed") or [])
        if "extract" not in stages:
            stages.append("extract")
        job["stages_completed"] = stages
        self.ws.write_job(job)
        self.events.emit(
            "progress",
            stage="extract",
            current=1,
            total=1,
            overall=WEIGHTS["probe"] + WEIGHTS["extract"],
        )
        self.events.emit("stage_finished", stage="extract")
        self.events.emit("artifact", kind="audio", path=str(self.ws.audio_wav))
        return errors.SUCCESS

    def _stage_vad(self, job: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        assert self.ws is not None
        self.events.emit("stage_started", stage="vad")
        base = WEIGHTS["probe"] + WEIGHTS["extract"]
        self.events.emit("progress", stage="vad", current=0, total=1, overall=base)
        try:
            if self.opts.resume and self.ws.vad_json.is_file():
                import json

                vad = json.loads(self.ws.vad_json.read_text(encoding="utf-8"))
                log.info("resume: reusing %s", self.ws.vad_json)
            else:
                vad = run_vad(self.ws.audio_wav)
                # Spec example is a bare array; we store object + keep segments key.
                # Also write Spec-compatible array companion? Prefer object with segments.
                atomic_write_json(self.ws.vad_json, vad.get("segments") or [])
                atomic_write_json(self.ws.root / "vad_meta.json", vad)
        except VadError as exc:
            return self._fail(job, exc.code, str(exc)), None

        # Normalize in-memory shape
        if isinstance(vad, list):
            vad = {"schema_version": 1, "segments": vad}
        stages = list(job.get("stages_completed") or [])
        if "vad" not in stages:
            stages.append("vad")
        job["stages_completed"] = stages
        job["vad"] = {"segments": len(vad.get("segments") or [])}
        self.ws.write_job(job)
        self.events.emit(
            "progress",
            stage="vad",
            current=1,
            total=1,
            overall=base + WEIGHTS["vad"],
        )
        self.events.emit("stage_finished", stage="vad")
        self.events.emit("artifact", kind="vad", path=str(self.ws.vad_json))
        return errors.SUCCESS, vad


def _code_name(code: int) -> str:
    mapping = {
        errors.INVALID_ARGS: "INVALID_ARGS",
        errors.INVALID_INPUT: "INVALID_INPUT",
        errors.UNSUPPORTED_AUDIO_STREAM: "UNSUPPORTED_AUDIO_STREAM",
        errors.FFPROBE_FAILURE: "FFPROBE_FAILURE",
        errors.FFMPEG_FAILURE: "FFMPEG_FAILURE",
        errors.RUNTIME_UNAVAILABLE: "RUNTIME_UNAVAILABLE",
        errors.MODEL_MISSING: "MODEL_MISSING",
    }
    return mapping.get(code, f"CODE_{code}")
