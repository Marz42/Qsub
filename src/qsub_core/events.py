"""NDJSON event protocol for GUI ↔ CLI (Spec §24–§25)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO, Literal

EventMode = Literal["text", "ndjson"]


@dataclass
class EventEmitter:
    mode: EventMode = "text"
    stream: TextIO = field(default_factory=lambda: sys.stdout)
    text_stream: TextIO = field(default_factory=lambda: sys.stderr)

    def emit(self, type: str, **payload: Any) -> None:
        event = {"v": 1, "type": type, **payload}
        if self.mode == "ndjson":
            self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.stream.flush()
        else:
            # Human-readable summary on stderr; keep stdout clean for pipes.
            msg = _format_text(event)
            self.text_stream.write(msg + "\n")
            self.text_stream.flush()


def _format_text(event: dict[str, Any]) -> str:
    t = event.get("type", "?")
    if t == "progress":
        stage = event.get("stage", "")
        cur = event.get("current")
        total = event.get("total")
        overall = event.get("overall")
        pct = f" {overall * 100:.0f}%" if isinstance(overall, (int, float)) else ""
        frac = f" {cur}/{total}" if cur is not None and total is not None else ""
        return f"[progress]{pct}{frac} {stage}".rstrip()
    if t == "stage_started":
        return f"[stage] start {event.get('stage')}"
    if t == "stage_finished":
        return f"[stage] done  {event.get('stage')}"
    if t == "warning":
        return f"[warning] {event.get('code')} {event.get('message', '')}".rstrip()
    if t == "error":
        return f"[error] {event.get('code')} {event.get('message', '')}".rstrip()
    if t == "artifact":
        return f"[artifact] {event.get('kind')} → {event.get('path')}"
    if t == "job_started":
        return f"[job] started {event.get('job_id')}"
    if t == "completed":
        return f"[job] completed in {event.get('elapsed_seconds')}s"
    if t == "batch_started":
        return f"[batch] started id={event.get('batch_id')} total={event.get('total')}"
    if t == "item_started":
        return f"[batch] item {event.get('index')}/{event.get('total')} start {event.get('path')}"
    if t == "item_finished":
        st = event.get("status") or ("ok" if event.get("ok") else "failed")
        return f"[batch] item {event.get('index')}/{event.get('total')} {st}"
    if t == "batch_progress":
        return f"[batch] progress {event.get('current')}/{event.get('total')}"
    if t == "batch_completed":
        return (
            f"[batch] done ok={event.get('succeeded')} "
            f"fail={event.get('failed')} cancel={event.get('canceled')}"
        )
    return f"[{t}] " + " ".join(f"{k}={v}" for k, v in event.items() if k not in {"v", "type"})
