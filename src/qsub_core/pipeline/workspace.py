"""Job workspace under %LOCALAPPDATA%\\QwenSubtitle\\jobs\\<id> (Spec §27)."""

from __future__ import annotations

import shutil
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
    def tokens_json(self) -> Path:
        return self.root / "tokens.json"

    @property
    def asr_dir(self) -> Path:
        return self.root / "asr"

    @property
    def alignment_dir(self) -> Path:
        return self.root / "alignment"

    @property
    def alignment_repaired_dir(self) -> Path:
        return self.root / "alignment_repaired"

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.asr_dir.mkdir(exist_ok=True)
        self.alignment_dir.mkdir(exist_ok=True)
        self.alignment_repaired_dir.mkdir(exist_ok=True)

    def write_job(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.job_json, payload)

    def prune_intermediates(self) -> list[str]:
        """Remove bulky reproducible cache after success; keep job/project/output."""
        warnings: list[str] = []
        for path in (self.audio_wav, self.probe_json, self.vad_json, self.chunks_json, self.tokens_json):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                warnings.append(f"{path}: {exc}")
        for directory in (self.asr_dir, self.alignment_dir, self.alignment_repaired_dir):
            if directory.is_dir():
                try:
                    shutil.rmtree(directory)
                except OSError as exc:
                    warnings.append(f"{directory}: {exc}")
        return warnings


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
        "pipeline_version": 2,
        "status": "created",
        "source": {"path": source},
        "args": args,
        "stages_completed": [],
        "phase": "phase5_subtitle",
    }
