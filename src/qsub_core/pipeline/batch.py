"""Sequential batch transcription runner (v0.2 — Spec §50 out-of-scope for MVP)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from qsub_core import errors
from qsub_core.config import ensure_user_dirs
from qsub_core.events import EventEmitter
from qsub_core.io_util import atomic_write_json
from qsub_core.pipeline.engine import PipelineEngine, TranscribeOptions
from qsub_core.pipeline.resume import cancel_flag_path, is_cancel_requested

MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
}


@dataclass
class BatchSharedOptions:
    language: str = "auto"
    device: str = "auto"
    audio_stream: str = "auto"
    mode: str = "safe"
    resume: bool = True
    keep_work: bool = False
    overwrite: bool = False
    encoding: str = "utf-8-bom"
    events: str = "text"
    log_level: str = "info"
    pause_gap: float = 0.45
    target_min: float = 1.5
    target_max: float = 6.0
    min_cue_duration: float = 0.8
    hard_max_duration: float = 8.0
    clause_break_ratio: float = 0.6
    stop_on_error: bool = False
    output_dir: Path | None = None


@dataclass
class BatchItemResult:
    index: int
    path: str
    status: str  # pending|running|ok|failed|canceled|skipped
    code: int = 0
    srt: str | None = None
    error_code: str | None = None
    message: str | None = None
    elapsed_seconds: float | None = None
    work_dir: str | None = None


@dataclass
class BatchPlan:
    batch_id: str
    root: Path
    inputs: list[Path]
    shared: BatchSharedOptions
    items: list[BatchItemResult] = field(default_factory=list)


class Emitter(Protocol):
    def emit(self, type: str, **payload: Any) -> None: ...


class ItemEventEmitter:
    """Wrap EventEmitter and stamp item_index on every event."""

    def __init__(self, inner: Emitter, item_index: int):
        self._inner = inner
        self._item_index = item_index
        self.mode = getattr(inner, "mode", "ndjson")

    def emit(self, type: str, **payload: Any) -> None:
        self._inner.emit(type, item_index=self._item_index, **payload)


def collect_input_paths(raw: list[Path]) -> list[Path]:
    """Expand dirs, filter media extensions, dedupe (resolved paths)."""
    out: list[Path] = []
    seen: set[Path] = set()
    for entry in raw:
        try:
            p = entry.expanduser().resolve()
        except OSError:
            continue
        found: list[Path] = []
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in MEDIA_EXTENSIONS:
                    found.append(child.resolve())
        for c in found:
            if not c.is_file():
                continue
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def load_manifest(path: Path) -> list[Path]:
    """Load paths from JSON list / {\"inputs\":[...]} / newline TXT."""
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        data = json.loads(stripped)
        if isinstance(data, list):
            return [Path(str(x)) for x in data]
        if isinstance(data, dict):
            items = data.get("inputs") or data.get("files") or []
            return [Path(str(x)) for x in items]
        raise ValueError("manifest JSON must be a list or object with inputs")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(Path(line))
    return lines


def resolve_output_path(
    source: Path,
    *,
    output_dir: Path | None,
    used: set[Path],
) -> Path:
    if output_dir is None:
        dest = source.with_suffix(".srt").resolve()
        used.add(dest)
        return dest

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = (output_dir / f"{source.stem}.srt").resolve()
    n = 2
    while dest in used:
        dest = (output_dir / f"{source.stem}__{n}.srt").resolve()
        n += 1
        if n > 10000:
            break
    used.add(dest)
    return dest


def create_batch_root(work_root: Path | None = None) -> tuple[str, Path]:
    batch_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if work_root is not None:
        root = Path(work_root).expanduser().resolve()
    else:
        dirs = ensure_user_dirs()
        batches = dirs["root"] / "batches"
        batches.mkdir(parents=True, exist_ok=True)
        root = batches / batch_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "items").mkdir(exist_ok=True)
    return batch_id, root


RunItemFn = Callable[[TranscribeOptions, Emitter], int]


def _default_run_item(opts: TranscribeOptions, events: Emitter) -> int:
    return PipelineEngine(opts, events).run()  # type: ignore[arg-type]


class BatchRunner:
    def __init__(
        self,
        events: EventEmitter,
        shared: BatchSharedOptions,
        *,
        run_item: RunItemFn | None = None,
    ):
        self.events = events
        self.shared = shared
        self._run_item = run_item or _default_run_item

    def run(
        self,
        inputs: list[Path],
        *,
        work_root: Path | None = None,
    ) -> int:
        paths = collect_input_paths(inputs)
        if not paths:
            self.events.emit("error", code="INVALID_ARGS", message="no media inputs for batch")
            return errors.INVALID_ARGS

        batch_id, root = create_batch_root(work_root)
        used_outputs: set[Path] = set()
        items: list[BatchItemResult] = []
        for i, src in enumerate(paths):
            out = resolve_output_path(src, output_dir=self.shared.output_dir, used=used_outputs)
            items.append(
                BatchItemResult(
                    index=i,
                    path=str(src),
                    status="pending",
                    srt=str(out),
                )
            )

        plan = BatchPlan(
            batch_id=batch_id,
            root=root,
            inputs=paths,
            shared=self.shared,
            items=items,
        )
        self._write_batch_json(plan, status="running")
        total = len(items)
        self.events.emit("batch_started", batch_id=batch_id, total=total, work_root=str(root))

        succeeded = 0
        failed = 0
        canceled = 0
        stop_remaining = False

        for item in items:
            if stop_remaining:
                item.status = "skipped"
                item.message = "skipped after earlier failure (--stop-on-error)"
                self.events.emit(
                    "item_finished",
                    index=item.index,
                    total=total,
                    path=item.path,
                    ok=False,
                    code=errors.INVALID_ARGS,
                    srt=None,
                    error_code="SKIPPED",
                    status="skipped",
                )
                continue

            if is_cancel_requested(root):
                self._cancel_from(items, item.index, total)
                canceled = sum(1 for it in items if it.status == "canceled")
                break

            item_work = root / "items" / f"{item.index:04d}"
            item_work.mkdir(parents=True, exist_ok=True)
            item.work_dir = str(item_work)
            item.status = "running"
            self._write_batch_json(plan, status="running")

            self.events.emit(
                "item_started",
                index=item.index,
                total=total,
                path=item.path,
                output=item.srt,
                work_dir=item.work_dir,
            )
            self.events.emit(
                "batch_progress",
                current=item.index,
                total=total,
                overall=item.index / total if total else 0.0,
            )

            out_path = Path(item.srt) if item.srt else None
            if out_path is not None and out_path.exists() and not self.shared.overwrite:
                item.status = "failed"
                item.code = errors.INVALID_ARGS
                item.error_code = "OUTPUT_EXISTS"
                item.message = f"output exists (use --overwrite): {out_path}"
                failed += 1
                self.events.emit(
                    "error",
                    item_index=item.index,
                    code="OUTPUT_EXISTS",
                    message=item.message,
                )
                self.events.emit(
                    "item_finished",
                    index=item.index,
                    total=total,
                    path=item.path,
                    ok=False,
                    code=item.code,
                    srt=None,
                    error_code=item.error_code,
                    status="failed",
                    message=item.message,
                )
                if self.shared.stop_on_error:
                    stop_remaining = True
                continue

            if is_cancel_requested(root):
                try:
                    cancel_flag_path(item_work).write_text("1", encoding="utf-8")
                except OSError:
                    pass
                self._cancel_from(items, item.index, total)
                canceled = sum(1 for it in items if it.status == "canceled")
                break

            opts = TranscribeOptions(
                input_path=Path(item.path),
                output=out_path,
                language=self.shared.language,
                device=self.shared.device,
                audio_stream=self.shared.audio_stream,
                mode=self.shared.mode,
                resume=self.shared.resume,
                work_dir=item_work,
                keep_work=self.shared.keep_work,
                overwrite=self.shared.overwrite,
                events=self.shared.events,
                log_level=self.shared.log_level,
                encoding=self.shared.encoding,
                pause_gap=self.shared.pause_gap,
                target_min=self.shared.target_min,
                target_max=self.shared.target_max,
                min_cue_duration=self.shared.min_cue_duration,
                hard_max_duration=self.shared.hard_max_duration,
                clause_break_ratio=self.shared.clause_break_ratio,
            )
            item_events = ItemEventEmitter(self.events, item.index)
            t0 = time.perf_counter()
            code = self._run_item(opts, item_events)
            elapsed = round(time.perf_counter() - t0, 3)
            item.elapsed_seconds = elapsed
            item.code = code

            if code == errors.SUCCESS:
                item.status = "ok"
                succeeded += 1
                if out_path is not None and out_path.is_file():
                    item.srt = str(out_path)
                self.events.emit(
                    "item_finished",
                    index=item.index,
                    total=total,
                    path=item.path,
                    ok=True,
                    code=0,
                    srt=item.srt,
                    error_code=None,
                    status="ok",
                    elapsed_seconds=elapsed,
                )
            elif code == errors.CANCELED or is_cancel_requested(root):
                item.status = "canceled"
                item.error_code = "CANCELED"
                item.code = errors.CANCELED
                self._cancel_from(items, item.index, total)
                canceled = sum(1 for it in items if it.status == "canceled")
                break
            else:
                item.status = "failed"
                item.error_code = f"EXIT_{code}"
                failed += 1
                self.events.emit(
                    "item_finished",
                    index=item.index,
                    total=total,
                    path=item.path,
                    ok=False,
                    code=code,
                    srt=None,
                    error_code=item.error_code,
                    status="failed",
                    elapsed_seconds=elapsed,
                )
                if self.shared.stop_on_error:
                    stop_remaining = True

            self.events.emit(
                "batch_progress",
                current=item.index + 1,
                total=total,
                overall=(item.index + 1) / total if total else 1.0,
            )
            self._write_batch_json(plan, status="running")

        skipped = sum(1 for it in items if it.status == "skipped")
        canceled = sum(1 for it in items if it.status == "canceled")
        failed = sum(1 for it in items if it.status == "failed")
        succeeded = sum(1 for it in items if it.status == "ok")

        summary_path = root / "batch_summary.json"
        summary = {
            "schema_version": 1,
            "batch_id": batch_id,
            "work_root": str(root),
            "succeeded": succeeded,
            "failed": failed,
            "canceled": canceled,
            "skipped": skipped,
            "total": total,
            "items": [asdict(it) for it in items],
        }
        atomic_write_json(summary_path, summary)
        plan.items = items

        if canceled and succeeded == 0 and failed == 0:
            final_status = "canceled"
        elif failed or canceled:
            final_status = "completed_with_errors"
        else:
            final_status = "completed"
        self._write_batch_json(plan, status=final_status, summary_path=str(summary_path))

        self.events.emit(
            "batch_completed",
            batch_id=batch_id,
            succeeded=succeeded,
            failed=failed,
            canceled=canceled,
            skipped=skipped,
            total=total,
            summary_path=str(summary_path),
            overall=1.0,
        )

        if canceled:
            return errors.CANCELED
        if failed:
            return 1
        return errors.SUCCESS

    def _cancel_from(self, items: list[BatchItemResult], start_index: int, total: int) -> None:
        for item in items[start_index:]:
            if item.status in {"ok", "failed", "skipped"}:
                continue
            item.status = "canceled"
            item.code = errors.CANCELED
            item.error_code = "CANCELED"
            self.events.emit(
                "item_finished",
                index=item.index,
                total=total,
                path=item.path,
                ok=False,
                code=errors.CANCELED,
                srt=None,
                error_code="CANCELED",
                status="canceled",
            )

    def _write_batch_json(
        self,
        plan: BatchPlan,
        *,
        status: str,
        summary_path: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "batch_id": plan.batch_id,
            "status": status,
            "work_root": str(plan.root),
            "shared": {
                "language": plan.shared.language,
                "device": plan.shared.device,
                "audio_stream": plan.shared.audio_stream,
                "encoding": plan.shared.encoding,
                "overwrite": plan.shared.overwrite,
                "stop_on_error": plan.shared.stop_on_error,
                "output_dir": str(plan.shared.output_dir) if plan.shared.output_dir else None,
            },
            "items": [asdict(it) for it in plan.items],
        }
        if summary_path:
            payload["summary_path"] = summary_path
        atomic_write_json(plan.root / "batch.json", payload)
