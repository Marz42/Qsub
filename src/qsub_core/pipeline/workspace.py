"""Job workspace under %LOCALAPPDATA%\\QwenSubtitle\\jobs\\<id> (Spec §27)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qsub_core.config import APP_VERSION, ensure_user_dirs, new_job_id
from qsub_core.io_util import atomic_write_json


@dataclass
class JobWorkspace:
    job_id: str
    root: Path
    created_at: float = field(default_factory=time.time)

    @property
    def job_json(self) -> Path:
        return self.root / "job.json"

    @property
    def probe_json(self) -> Path:
        return self.root / "probe.json"

    @property
    def chunks_json(self) -> Path:
        return self.root / "chunks.json"

    @property
    def audio_wav(self) -> Path:
        return self.root / "audio.wav"

    @property
    def vad_json(self) -> Path:
        return self.root / "vad.json"

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    @property
    def run_log(self) -> Path:
        return self.root / "run.log"

    @property
    def asr_dir(self) -> Path:
        return self.root / "asr"

    @property
    def alignment_dir(self) -> Path:
        return self.root / "alignment"

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.asr_dir.mkdir(exist_ok=True)
        self.alignment_dir.mkdir(exist_ok=True)

    def write_job(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.job_json, payload)


def create_job_workspace(
    *,
    job_id: str | None = None,
    work_dir: Path | str | None = None,
) -> JobWorkspace:
    jid = job_id or new_job_id()
    if work_dir is not None:
        root = Path(work_dir).expanduser().resolve()
    else:
        root = ensure_user_dirs()["jobs"] / jid
    ws = JobWorkspace(job_id=jid, root=root)
    ws.ensure_layout()
    return ws


def initial_job_record(
    *,
    job_id: str,
    source: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "job_id": job_id,
        "app_version": APP_VERSION,
        "pipeline_version": 1,
        "status": "created",
        "source": {"path": source},
        "args": args,
        "stages_completed": [],
        "phase": "phase2_media",
    }
