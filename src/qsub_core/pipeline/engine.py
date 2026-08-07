"""Pipeline engine skeleton (Phase 1: probe + job lifecycle only)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qsub_core import errors
from qsub_core.events import EventEmitter
from qsub_core.io_util import atomic_write_json
from qsub_core.media.probe import ProbeError, probe_media, select_audio_stream
from qsub_core.pipeline.fingerprint import source_fingerprint
from qsub_core.pipeline.workspace import (
    JobWorkspace,
    create_job_workspace,
    initial_job_record,
)

log = logging.getLogger(__name__)

# Spec §26 progress weights
WEIGHTS = {
    "probe": 0.02,
    "extract": 0.05,
    "vad": 0.03,
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
    """Phase 1: create job workspace, fingerprint, probe. Later stages in Phase 2+."""

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
        self.ws.write_job(job)
        self.events.emit("job_started", job_id=self.ws.job_id, work_dir=str(self.ws.root))
        log.info("job %s work_dir=%s source=%s", self.ws.job_id, self.ws.root, src)

        # Fingerprint
        try:
            fp = source_fingerprint(src)
            job["source"]["fingerprint"] = fp
            self.ws.write_job(job)
        except OSError as exc:
            self.events.emit("error", code="INVALID_INPUT", message=str(exc))
            return errors.INVALID_INPUT

        # Stage: probe
        self.events.emit("stage_started", stage="probe")
        self.events.emit("progress", stage="probe", current=0, total=1, overall=0.0)
        try:
            probe = probe_media(src)
            stream = select_audio_stream(probe, self.opts.audio_stream)
            probe["selected_audio_stream"] = stream
            atomic_write_json(self.ws.probe_json, probe)
        except ProbeError as exc:
            job["status"] = "failed"
            job["error"] = {"code": exc.code, "message": str(exc)}
            self.ws.write_job(job)
            self.events.emit("error", code=_code_name(exc.code), message=str(exc))
            return exc.code
        except FileNotFoundError as exc:
            job["status"] = "failed"
            job["error"] = {"code": errors.FFPROBE_FAILURE, "message": str(exc)}
            self.ws.write_job(job)
            self.events.emit("error", code="FFPROBE_FAILURE", message=str(exc))
            return errors.FFPROBE_FAILURE

        job["stages_completed"] = ["probe"]
        job["status"] = "phase1_probe_complete"
        job["probe"] = {
            "duration": probe.get("duration"),
            "audio_stream": stream.get("index"),
            "codec": stream.get("codec"),
        }
        job["notes"] = [
            "Phase 1 CLI skeleton: probe + job workspace only.",
            "Extract / VAD / ASR / alignment / SRT arrive in Phase 2–5.",
        ]
        self.ws.write_job(job)

        self.events.emit("progress", stage="probe", current=1, total=1, overall=WEIGHTS["probe"])
        self.events.emit("stage_finished", stage="probe")
        self.events.emit("artifact", kind="probe", path=str(self.ws.probe_json))
        self.events.emit(
            "artifact",
            kind="job",
            path=str(self.ws.job_json),
        )
        elapsed = round(time.perf_counter() - t0, 3)
        self.events.emit(
            "completed",
            elapsed_seconds=elapsed,
            phase="phase1_skeleton",
            next="extract/vad (Phase 2), asr (Phase 3)",
        )
        log.info("job %s phase1 complete in %ss", self.ws.job_id, elapsed)
        return errors.SUCCESS


def _code_name(code: int) -> str:
    mapping = {
        errors.INVALID_ARGS: "INVALID_ARGS",
        errors.INVALID_INPUT: "INVALID_INPUT",
        errors.UNSUPPORTED_AUDIO_STREAM: "UNSUPPORTED_AUDIO_STREAM",
        errors.FFPROBE_FAILURE: "FFPROBE_FAILURE",
        errors.FFMPEG_FAILURE: "FFMPEG_FAILURE",
    }
    return mapping.get(code, f"CODE_{code}")
