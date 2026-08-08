"""Pipeline engine — Phase 5: full offline CLI through SRT export."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qsub_core import errors
from qsub_core.alignment.merge import merge_global_tokens
from qsub_core.alignment.qwen import AlignmentError, QwenAlignmentBackend
from qsub_core.alignment.repair import repair_items
from qsub_core.alignment.validate import validate_items
from qsub_core.asr.qwen import ASRError, QwenASRBackend
from qsub_core.events import EventEmitter
from qsub_core.io_util import atomic_write_json
from qsub_core.media.extract import ExtractError, extract_audio
from qsub_core.media.probe import ProbeError, probe_media, select_audio_stream
from qsub_core.pipeline.audio_io import load_mono_wav, slice_wav
from qsub_core.pipeline.chunk_plan import ChunkPlan, plan_chunks_from_vad
from qsub_core.pipeline.fingerprint import source_fingerprint
from qsub_core.pipeline.resume import (
    alignment_chunk_path,
    asr_chunk_path,
    is_cancel_requested,
    list_completed_alignment_chunks,
    list_completed_asr_chunks,
    load_json,
)
from qsub_core.pipeline.workspace import (
    JobWorkspace,
    create_job_workspace,
    initial_job_record,
)
from qsub_core.project.model import build_project, write_project
from qsub_core.subtitles.segment import segment_tokens
from qsub_core.subtitles.srt import validate_srt_invariants, write_srt
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
    encoding: str = "utf-8-bom"
    # Subtitle segmentation (Spec §19) — see qsub_core.subtitles.segment defaults
    pause_gap: float = 0.45
    target_min: float = 1.5
    target_max: float = 6.0
    min_cue_duration: float = 0.8
    hard_max_duration: float = 8.0
    clause_break_ratio: float = 0.6


class PipelineEngine:
    """Phase 5: full CLI pipeline through project.json + SRT export."""

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
                "encoding": self.opts.encoding,
                "pause_gap": self.opts.pause_gap,
                "target_min": self.opts.target_min,
                "target_max": self.opts.target_max,
                "min_cue_duration": self.opts.min_cue_duration,
                "hard_max_duration": self.opts.hard_max_duration,
                "clause_break_ratio": self.opts.clause_break_ratio,
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
                        "language changed %r → %r; invalidating ASR/alignment artifacts",
                        prev_lang,
                        self.opts.language,
                    )
                    self._invalidate_asr()
                    self._invalidate_alignment()
                    job["stages_completed"] = [
                        s
                        for s in job["stages_completed"]
                        if s not in {"asr", "alignment", "subtitle", "export"}
                    ]
        job["phase"] = "phase5_subtitle"
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

        code = self._stage_alignment(job, chunks)
        if code != errors.SUCCESS:
            return code

        code, srt_path = self._stage_subtitle_export(job, probe, chunks)
        if code != errors.SUCCESS:
            return code

        overall = sum(WEIGHTS[k] for k in ("probe", "extract", "vad", "asr", "alignment", "subtitle", "export"))
        job["status"] = "completed"
        job["notes"] = [
            "Phase 5 complete: canonical project.json + SRT exported.",
        ]
        if srt_path is not None:
            job["output_srt"] = str(srt_path)
        self.ws.write_job(job)

        elapsed = round(time.perf_counter() - t0, 3)
        self.events.emit("artifact", kind="job", path=str(self.ws.job_json))
        self.events.emit(
            "completed",
            elapsed_seconds=elapsed,
            phase="phase5_subtitle",
            chunks=len(chunks),
            overall=overall,
            srt=str(srt_path) if srt_path else None,
        )
        log.info(
            "job %s complete chunks=%s srt=%s in %ss",
            self.ws.job_id,
            len(chunks),
            srt_path,
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

    def _invalidate_alignment(self) -> None:
        assert self.ws is not None
        for directory in (self.ws.alignment_dir, self.ws.alignment_repaired_dir):
            for path in directory.glob("*.json"):
                try:
                    path.unlink()
                except OSError:
                    pass
        if self.ws.tokens_json.exists():
            try:
                self.ws.tokens_json.unlink()
            except OSError:
                pass
        if self.ws.project_json.exists():
            try:
                self.ws.project_json.unlink()
            except OSError:
                pass
        for name in ("output.srt",):
            p = self.ws.root / name
            if p.exists():
                try:
                    p.unlink()
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

    def _stage_alignment(self, job: dict[str, Any], chunks: list[ChunkPlan]) -> int:
        assert self.ws is not None
        self.events.emit("stage_started", stage="alignment")
        base = WEIGHTS["probe"] + WEIGHTS["extract"] + WEIGHTS["vad"] + WEIGHTS["asr"]
        total = len(chunks)
        chunk_dicts = [c.to_dict() for c in chunks]

        done = set()
        if self.opts.resume:
            done = list_completed_alignment_chunks(self.ws.alignment_dir, chunk_dicts)
            if done:
                log.info(
                    "resume: skipping %s/%s completed alignment chunks",
                    len(done),
                    total,
                )
                self.events.emit(
                    "progress",
                    stage="alignment",
                    current=len(done),
                    total=total,
                    overall=base + WEIGHTS["alignment"] * (len(done) / max(total, 1)),
                )

        # Load ASR texts for all chunks
        asr_by_id: dict[int, dict[str, Any]] = {}
        for ch in chunks:
            rec = load_json(asr_chunk_path(self.ws.asr_dir, ch.id))
            if not isinstance(rec, dict):
                return self._fail(
                    job,
                    errors.ASR_FAILURE,
                    f"missing ASR artifact for chunk {ch.id}",
                )
            asr_by_id[ch.id] = rec

        need_infer = [c for c in chunks if c.id not in done]
        skipped = len(done)
        processed = 0
        warning_count = 0

        if need_infer:
            try:
                device = resolve_device(self.opts.device)
            except RuntimeError as exc:
                return self._fail(job, errors.CUDA_UNAVAILABLE, str(exc))

            wav, sr, _ = load_mono_wav(self.ws.audio_wav)
            backend: QwenAlignmentBackend | None = None
            try:
                backend = QwenAlignmentBackend(device=device)
                for ch in need_infer:
                    if is_cancel_requested(self.ws.root):
                        return self._fail(job, errors.CANCELED, "canceled by user")

                    asr = asr_by_id[ch.id]
                    text = (asr.get("text") or "").strip()
                    language = asr.get("language") or (
                        None if self.opts.language.lower() == "auto" else self.opts.language
                    ) or "Chinese"

                    if not text:
                        record = {
                            "chunk_id": ch.id,
                            "start": ch.start,
                            "end": ch.end,
                            "overlap_before": ch.overlap_before,
                            "language": language,
                            "items": [],
                            "warning": "empty_asr_text",
                            "model": "Qwen3-ForcedAligner-0.6B",
                        }
                        atomic_write_json(alignment_chunk_path(self.ws.alignment_dir, ch.id), record)
                        done.add(ch.id)
                        processed += 1
                        continue

                    audio = slice_wav(wav, sr, ch.start, ch.end)
                    t1 = time.perf_counter()
                    try:
                        result = backend.align(audio, sr, text, str(language))
                    except AlignmentError as exc:
                        return self._fail(job, exc.code, str(exc))

                    items = [
                        {"text": it.text, "start": it.start, "end": it.end}
                        for it in result.items
                    ]
                    record = {
                        "chunk_id": ch.id,
                        "start": ch.start,
                        "end": ch.end,
                        "overlap_before": ch.overlap_before,
                        "language": language,
                        "items": items,
                        "model": result.model,
                        "elapsed_seconds": round(time.perf_counter() - t1, 3),
                    }
                    # Raw aligner output — do not overwrite with repairs (Spec §15).
                    atomic_write_json(alignment_chunk_path(self.ws.alignment_dir, ch.id), record)
                    done.add(ch.id)
                    processed += 1
                    self.events.emit(
                        "progress",
                        stage="alignment",
                        current=len(done),
                        total=total,
                        overall=base + WEIGHTS["alignment"] * (len(done) / max(total, 1)),
                    )
                    log.info(
                        "align chunk %06d tokens=%s in %ss",
                        ch.id,
                        len(items),
                        record["elapsed_seconds"],
                    )
            finally:
                if backend is not None:
                    backend.close()

        missing = [c.id for c in chunks if c.id not in done]
        if missing:
            return self._fail(
                job,
                errors.ALIGNMENT_FAILURE,
                f"alignment incomplete; missing chunks: {missing[:8]}",
            )

        # Repair each chunk + merge globally
        repaired_records: list[dict[str, Any]] = []
        for ch in chunks:
            raw = load_json(alignment_chunk_path(self.ws.alignment_dir, ch.id))
            if not isinstance(raw, dict):
                return self._fail(
                    job,
                    errors.ALIGNMENT_FAILURE,
                    f"corrupt alignment artifact chunk {ch.id}",
                )
            chunk_dur = max(0.001, float(ch.end) - float(ch.start))
            issues_before = validate_items(raw.get("items") or [], chunk_duration=chunk_dur)
            for issue in issues_before.issues:
                if issue.code == "ZERO_DURATION":
                    self.events.emit(
                        "warning",
                        code="ALIGN_ZERO_DURATION",
                        chunk=ch.id,
                        index=issue.index,
                    )
                    warning_count += 1
            repaired_items, residual, quality = repair_items(
                list(raw.get("items") or []),
                chunk_duration=chunk_dur,
            )
            repaired = dict(raw)
            repaired["items"] = repaired_items
            repaired["alignment_quality"] = quality
            repaired["validation_issues"] = [
                {"code": i.code, "index": i.index, "message": i.message}
                for i in residual
            ]
            atomic_write_json(
                self.ws.alignment_repaired_dir / f"{ch.id:06d}.json",
                repaired,
            )
            repaired_records.append(repaired)

        tokens = merge_global_tokens(repaired_records, chunk_dicts)
        atomic_write_json(
            self.ws.tokens_json,
            {
                "schema_version": 1,
                "count": len(tokens),
                "tokens": tokens,
            },
        )

        # Basic global invariant check
        mono_viol = 0
        for i in range(1, len(tokens)):
            if tokens[i]["start"] + 1e-9 < tokens[i - 1]["start"]:
                mono_viol += 1
        if mono_viol:
            self.events.emit(
                "warning",
                code="TOKEN_MONOTONICITY",
                count=mono_viol,
                message="global token starts not fully monotonic after merge",
            )
            warning_count += 1

        stages = list(job.get("stages_completed") or [])
        if "alignment" not in stages:
            stages.append("alignment")
        job["stages_completed"] = stages
        job["alignment"] = {
            "completed": total,
            "total": total,
            "skipped": skipped,
            "processed": processed,
            "tokens": len(tokens),
            "warnings": warning_count,
        }
        self.ws.write_job(job)
        self.events.emit(
            "progress",
            stage="alignment",
            current=total,
            total=total,
            overall=base + WEIGHTS["alignment"],
        )
        self.events.emit("stage_finished", stage="alignment")
        self.events.emit("artifact", kind="alignment_dir", path=str(self.ws.alignment_dir))
        self.events.emit("artifact", kind="tokens", path=str(self.ws.tokens_json))
        return errors.SUCCESS

    def _stage_subtitle_export(
        self,
        job: dict[str, Any],
        probe: dict[str, Any],
        chunks: list[ChunkPlan],
    ) -> tuple[int, Path | None]:
        assert self.ws is not None
        self.events.emit("stage_started", stage="subtitle")
        base = (
            WEIGHTS["probe"]
            + WEIGHTS["extract"]
            + WEIGHTS["vad"]
            + WEIGHTS["asr"]
            + WEIGHTS["alignment"]
        )
        self.events.emit("progress", stage="subtitle", current=0, total=1, overall=base)

        tok_payload = load_json(self.ws.tokens_json)
        if not isinstance(tok_payload, dict) or "tokens" not in tok_payload:
            return self._fail(job, errors.PROJECT_FAILURE, "missing tokens.json"), None

        tokens = list(tok_payload.get("tokens") or [])
        subtitles = segment_tokens(
            tokens,
            min_duration=float(self.opts.min_cue_duration),
            target_min=float(self.opts.target_min),
            target_max=float(self.opts.target_max),
            hard_max=float(self.opts.hard_max_duration),
            pause_gap=float(self.opts.pause_gap),
            clause_break_ratio=float(self.opts.clause_break_ratio),
        )
        inv = validate_srt_invariants(subtitles)
        if inv:
            return (
                self._fail(
                    job,
                    errors.TIMESTAMP_VALIDATION_FAILURE,
                    f"subtitle invariants failed: {inv[0]}",
                ),
                None,
            )

        # Language from first ASR chunk if available
        language = None
        if chunks:
            asr0 = load_json(asr_chunk_path(self.ws.asr_dir, chunks[0].id))
            if isinstance(asr0, dict):
                language = asr0.get("language")
        if language is None and self.opts.language.lower() != "auto":
            language = self.opts.language

        stream = (probe.get("selected_audio_stream") or {}) if probe else {}
        project = build_project(
            source_path=str(job["source"]["path"]),
            duration=probe.get("duration"),
            audio_stream=stream.get("index"),
            language=language,
            tokens=tokens,
            subtitles=subtitles,
        )
        try:
            write_project(self.ws.project_json, project)
        except OSError as exc:
            return self._fail(job, errors.PROJECT_FAILURE, str(exc)), None

        stages = list(job.get("stages_completed") or [])
        if "subtitle" not in stages:
            stages.append("subtitle")
        job["stages_completed"] = stages
        job["subtitles"] = {"count": len(subtitles)}
        self.ws.write_job(job)
        self.events.emit(
            "progress",
            stage="subtitle",
            current=1,
            total=1,
            overall=base + WEIGHTS["subtitle"],
        )
        self.events.emit("stage_finished", stage="subtitle")
        self.events.emit("artifact", kind="project", path=str(self.ws.project_json))

        # Export SRT
        self.events.emit("stage_started", stage="export")
        out = self.opts.output
        if out is None:
            src = Path(job["source"]["path"])
            out = src.with_suffix(".srt")
        out = out.expanduser().resolve()
        if out.exists() and not self.opts.overwrite:
            # Allow overwrite when output is the same completed path on resume
            same_job_out = job.get("output_srt") and Path(str(job["output_srt"])) == out
            if not (self.opts.resume and same_job_out):
                return (
                    self._fail(
                        job,
                        errors.INVALID_ARGS,
                        f"output exists (use --overwrite): {out}",
                    ),
                    None,
                )

        encoding = self.opts.encoding if self.opts.encoding in {"utf-8", "utf-8-bom"} else "utf-8-bom"
        try:
            write_srt(out, subtitles, encoding=encoding)  # type: ignore[arg-type]
            # Also keep a copy inside the job workspace
            write_srt(self.ws.root / "output.srt", subtitles, encoding=encoding)  # type: ignore[arg-type]
        except OSError as exc:
            return self._fail(job, errors.EXPORT_FAILURE, str(exc)), None

        if "export" not in stages:
            stages.append("export")
        job["stages_completed"] = stages
        job["output_srt"] = str(out)
        self.ws.write_job(job)
        self.events.emit(
            "progress",
            stage="export",
            current=1,
            total=1,
            overall=base + WEIGHTS["subtitle"] + WEIGHTS["export"],
        )
        self.events.emit("stage_finished", stage="export")
        self.events.emit("artifact", kind="srt", path=str(out))
        return errors.SUCCESS, out


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
        errors.ALIGNMENT_FAILURE: "ALIGNMENT_FAILURE",
        errors.TIMESTAMP_VALIDATION_FAILURE: "TIMESTAMP_VALIDATION_FAILURE",
        errors.PROJECT_FAILURE: "PROJECT_FAILURE",
        errors.EXPORT_FAILURE: "EXPORT_FAILURE",
        errors.CANCELED: "CANCELED",
    }
    return mapping.get(code, f"CODE_{code}")
