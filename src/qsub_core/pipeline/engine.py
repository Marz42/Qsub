"""Pipeline engine — Phase 3: media pipeline + chunk ASR with resume."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qsub_core import errors
from qsub_core.asr.qwen import ASRError, QwenASRBackend
from qsub_core.events import EventEmitter
from qsub_core.io_util import atomic_write_json
from qsub_core.media.extract import ExtractError, extract_audio
from qsub_core.media.probe import ProbeError, probe_media, select_audio_stream
from qsub_core.pipeline.audio_io import load_mono_wav, slice_wav
from qsub_core.pipeline.chunk_plan import ChunkPlan, plan_chunks_from_vad
from qsub_core.pipeline.fingerprint import source_fingerprint
from qsub_core.pipeline.resume import (
    asr_chunk_path,
    is_cancel_requested,
    is_valid_asr_artifact,
    list_completed_asr_chunks,
    load_json,
)
from qsub_core.pipeline.workspace import (
    JobWorkspace,
    create_job_workspace,
    initial_job_record,
)
from qsub_core.system.gpu import resolve_device
from qsub_core.vad.silero import VadError, run_vad

log = logging.getLogger(__name__)

WEIGHTS = {
    "probe": 0.02,
    "extract": 0.05,
    "vad": 0.03,
    "chunk": 0.0,
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
    """Phase 3: probe → extract → VAD → chunks → ASR (Safe Mode, resumable)."""

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
            existing = load_json(self.ws.job_json)
            if isinstance(existing, dict) and existing.get("source", {}).get("path") == str(src):
                prev_lang = (existing.get("args") or {}).get("language", "auto")
                job["stages_completed"] = list(existing.get("stages_completed") or [])
                job["job_id"] = existing.get("job_id", job["job_id"])
                self.ws.job_id = job["job_id"]
                # Language change invalidates ASR and descendants (Spec §28).
                if prev_lang != self.opts.language:
                    log.info(
                        "language changed %r → %r; invalidating ASR artifacts",
                        prev_lang,
                        self.opts.language,
                    )
                    self._invalidate_asr()
                    job["stages_completed"] = [
                        s for s in job["stages_completed"] if s not in {"asr", "alignment", "subtitle", "export"}
                    ]
        job["phase"] = "phase3_asr"
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

        code, probe, stream = self._stage_probe(job)
        if code != errors.SUCCESS:
            return code
        assert probe is not None and stream is not None

        code = self._stage_extract(job, src, stream)
        if code != errors.SUCCESS:
            return code

        code, vad = self._stage_vad(job)
        if code != errors.SUCCESS:
            return code
        assert vad is not None

        code, chunks = self._stage_chunk(job, probe, vad)
        if code != errors.SUCCESS:
            return code
        assert chunks is not None

        code = self._stage_asr(job, chunks)
        if code != errors.SUCCESS:
            return code

        overall = WEIGHTS["probe"] + WEIGHTS["extract"] + WEIGHTS["vad"] + WEIGHTS["asr"]
        job["status"] = "phase3_asr_complete"
        job["notes"] = [
            "Phase 3: media pipeline + chunk ASR complete (Safe Mode).",
            "Alignment / timestamp repair / SRT arrive in Phase 4–5.",
        ]
        self.ws.write_job(job)

        elapsed = round(time.perf_counter() - t0, 3)
        self.events.emit("artifact", kind="job", path=str(self.ws.job_json))
        self.events.emit(
            "completed",
            elapsed_seconds=elapsed,
            phase="phase3_asr",
            chunks=len(chunks),
            overall=overall,
            next="alignment (Phase 4)",
        )
        log.info(
            "job %s phase3 complete chunks=%s in %ss",
            self.ws.job_id,
            len(chunks),
            elapsed,
        )
        return errors.SUCCESS

    def _invalidate_asr(self) -> None:
        assert self.ws is not None
        for path in self.ws.asr_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass

    def _fail(self, job: dict[str, Any], code: int, message: str) -> int:
        job["status"] = "failed" if code != errors.CANCELED else "canceled"
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
            if self.opts.resume and self.ws.probe_json.is_file():
                probe = load_json(self.ws.probe_json)
                if not isinstance(probe, dict):
                    raise ProbeError("corrupt probe.json", errors.FFPROBE_FAILURE)
                stream = probe.get("selected_audio_stream") or select_audio_stream(
                    probe, self.opts.audio_stream
                )
                log.info("resume: reusing %s", self.ws.probe_json)
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
                vad = load_json(self.ws.vad_json)
                log.info("resume: reusing %s", self.ws.vad_json)
            else:
                vad = run_vad(self.ws.audio_wav)
                atomic_write_json(self.ws.vad_json, vad.get("segments") or [])
                atomic_write_json(self.ws.root / "vad_meta.json", vad)
        except VadError as exc:
            return self._fail(job, exc.code, str(exc)), None

        if isinstance(vad, list):
            vad = {"schema_version": 1, "segments": vad}
        elif not isinstance(vad, dict):
            return self._fail(job, errors.RUNTIME_UNAVAILABLE, "corrupt vad.json"), None

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

    def _stage_chunk(
        self,
        job: dict[str, Any],
        probe: dict[str, Any],
        vad: dict[str, Any],
    ) -> tuple[int, list[ChunkPlan] | None]:
        assert self.ws is not None
        base = WEIGHTS["probe"] + WEIGHTS["extract"] + WEIGHTS["vad"]

        duration = float(probe.get("duration") or 0.0)
        if duration <= 0:
            import soundfile as sf

            duration = float(sf.info(str(self.ws.audio_wav)).duration)

        if self.opts.resume and self.ws.chunks_json.is_file():
            payload = load_json(self.ws.chunks_json)
            if isinstance(payload, dict) and payload.get("chunks"):
                chunks = [
                    ChunkPlan(
                        id=int(c["id"]),
                        start=float(c["start"]),
                        end=float(c["end"]),
                        overlap_before=float(c.get("overlap_before") or 0.0),
                        cut_reason=str(c.get("cut_reason") or "natural"),
                    )
                    for c in payload["chunks"]
                ]
                log.info("resume: reusing %s (%s chunks)", self.ws.chunks_json, len(chunks))
            else:
                chunks = plan_chunks_from_vad(duration, vad.get("segments") or [])
                atomic_write_json(
                    self.ws.chunks_json,
                    {"version": 1, "chunks": [c.to_dict() for c in chunks]},
                )
        else:
            chunks = plan_chunks_from_vad(duration, vad.get("segments") or [])
            atomic_write_json(
                self.ws.chunks_json,
                {"version": 1, "chunks": [c.to_dict() for c in chunks]},
            )

        stages = list(job.get("stages_completed") or [])
        if "chunk" not in stages:
            stages.append("chunk")
        job["stages_completed"] = stages
        job["chunks"] = {"count": len(chunks), "duration": duration}
        self.ws.write_job(job)
        self.events.emit("artifact", kind="chunks", path=str(self.ws.chunks_json))
        self.events.emit(
            "progress",
            stage="chunk",
            current=len(chunks),
            total=len(chunks),
            overall=base,
        )
        return errors.SUCCESS, chunks

    def _stage_asr(self, job: dict[str, Any], chunks: list[ChunkPlan]) -> int:
        assert self.ws is not None
        self.events.emit("stage_started", stage="asr")
        base = WEIGHTS["probe"] + WEIGHTS["extract"] + WEIGHTS["vad"]
        total = len(chunks)
        chunk_dicts = [c.to_dict() for c in chunks]

        done = set()
        if self.opts.resume:
            done = list_completed_asr_chunks(self.ws.asr_dir, chunk_dicts)
            if done:
                log.info("resume: skipping %s/%s completed ASR chunks", len(done), total)
                self.events.emit(
                    "progress",
                    stage="asr",
                    current=len(done),
                    total=total,
                    overall=base + WEIGHTS["asr"] * (len(done) / max(total, 1)),
                )

        if len(done) == total and total > 0:
            stages = list(job.get("stages_completed") or [])
            if "asr" not in stages:
                stages.append("asr")
            job["stages_completed"] = stages
            job["asr"] = {"completed": total, "total": total, "skipped": total}
            self.ws.write_job(job)
            self.events.emit("stage_finished", stage="asr")
            self.events.emit("artifact", kind="asr_dir", path=str(self.ws.asr_dir))
            return errors.SUCCESS

        language = None if self.opts.language.lower() == "auto" else self.opts.language
        try:
            device = resolve_device(self.opts.device)
        except RuntimeError as exc:
            return self._fail(job, errors.CUDA_UNAVAILABLE, str(exc))

        wav, sr, _ = load_mono_wav(self.ws.audio_wav)
        backend: QwenASRBackend | None = None
        skipped = len(done)
        processed = 0
        try:
            backend = QwenASRBackend(device=device)
            for ch in chunks:
                if is_cancel_requested(self.ws.root):
                    return self._fail(job, errors.CANCELED, "canceled by user")

                if ch.id in done:
                    continue

                audio = slice_wav(wav, sr, ch.start, ch.end)
                t1 = time.perf_counter()
                try:
                    result = backend.transcribe(audio, sr, language)
                except ASRError as exc:
                    return self._fail(job, exc.code, str(exc))

                record = {
                    "chunk_id": ch.id,
                    "start": ch.start,
                    "end": ch.end,
                    "overlap_before": ch.overlap_before,
                    "language": result.language,
                    "text": result.text,
                    "model": result.model,
                    "elapsed_seconds": round(time.perf_counter() - t1, 3),
                }
                path = asr_chunk_path(self.ws.asr_dir, ch.id)
                atomic_write_json(path, record)
                done.add(ch.id)
                processed += 1
                self.events.emit(
                    "progress",
                    stage="asr",
                    current=len(done),
                    total=total,
                    overall=base + WEIGHTS["asr"] * (len(done) / max(total, 1)),
                )
                log.info(
                    "ASR chunk %06d chars=%s lang=%r in %ss",
                    ch.id,
                    len(result.text),
                    result.language,
                    record["elapsed_seconds"],
                )
        finally:
            if backend is not None:
                backend.close()

        # Verify all artifacts present
        missing = [c.id for c in chunks if c.id not in done]
        if missing:
            return self._fail(
                job,
                errors.ASR_FAILURE,
                f"ASR incomplete; missing chunks: {missing[:8]}",
            )

        stages = list(job.get("stages_completed") or [])
        if "asr" not in stages:
            stages.append("asr")
        job["stages_completed"] = stages
        job["asr"] = {
            "completed": len(done),
            "total": total,
            "skipped": skipped,
            "processed": processed,
        }
        self.ws.write_job(job)
        self.events.emit("stage_finished", stage="asr")
        self.events.emit("artifact", kind="asr_dir", path=str(self.ws.asr_dir))
        return errors.SUCCESS


def _code_name(code: int) -> str:
    mapping = {
        errors.INVALID_ARGS: "INVALID_ARGS",
        errors.INVALID_INPUT: "INVALID_INPUT",
        errors.UNSUPPORTED_AUDIO_STREAM: "UNSUPPORTED_AUDIO_STREAM",
        errors.FFPROBE_FAILURE: "FFPROBE_FAILURE",
        errors.FFMPEG_FAILURE: "FFMPEG_FAILURE",
        errors.RUNTIME_UNAVAILABLE: "RUNTIME_UNAVAILABLE",
        errors.CUDA_UNAVAILABLE: "CUDA_UNAVAILABLE",
        errors.CUDA_OOM: "CUDA_OOM",
        errors.MODEL_MISSING: "MODEL_MISSING",
        errors.ASR_FAILURE: "ASR_FAILURE",
        errors.CANCELED: "CANCELED",
    }
    return mapping.get(code, f"CODE_{code}")
