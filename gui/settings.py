"""GUI settings persistence (Chinese UI defaults)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from gui.paths import user_config_path


@dataclass
class GuiSettings:
    device: str = "auto"  # auto | cuda | cpu
    language: str = "auto"
    encoding: str = "utf-8-bom"  # utf-8-bom | utf-8
    keep_work: bool = False
    # Segmentation — same defaults as qsub_core.subtitles.segment
    pause_gap: float = 0.45
    target_min: float = 1.5
    target_max: float = 6.0
    min_cue_duration: float = 0.8
    hard_max_duration: float = 8.0
    clause_break_ratio: float = 0.6

    @classmethod
    def load(cls) -> GuiSettings:
        path = user_config_path()
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            device=str(data.get("device", "auto")),
            language=str(data.get("language", "auto")),
            encoding=str(data.get("encoding", "utf-8-bom")),
            keep_work=bool(data.get("keep_work", False)),
            pause_gap=float(data.get("pause_gap", 0.45)),
            target_min=float(data.get("target_min", 1.5)),
            target_max=float(data.get("target_max", 6.0)),
            min_cue_duration=float(data.get("min_cue_duration", 0.8)),
            hard_max_duration=float(data.get("hard_max_duration", 8.0)),
            clause_break_ratio=float(data.get("clause_break_ratio", 0.6)),
        )

    def save(self) -> None:
        path = user_config_path()
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def segment_cli_args(self) -> list[str]:
        return [
            "--pause-gap",
            str(self.pause_gap),
            "--target-min",
            str(self.target_min),
            "--target-max",
            str(self.target_max),
            "--min-cue-duration",
            str(self.min_cue_duration),
            "--hard-max-duration",
            str(self.hard_max_duration),
            "--clause-break-ratio",
            str(self.clause_break_ratio),
        ]
