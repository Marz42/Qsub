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
        )

    def save(self) -> None:
        path = user_config_path()
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
