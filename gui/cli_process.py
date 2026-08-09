"""Launch qsub CLI as subprocess and stream NDJSON events (Spec §24)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class CliProcess(QObject):
    event_received = Signal(dict)
    finished = Signal(int)
    log_line = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._proc: subprocess.Popen[str] | None = None
        self._work_dir: Path | None = None
        self._item_work_dir: Path | None = None
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def work_dir(self) -> Path | None:
        return self._work_dir

    def set_work_dir(self, path: Path | None) -> None:
        """Update cancel target (e.g. after batch_started reveals the real root)."""
        self._work_dir = path

    @property
    def item_work_dir(self) -> Path | None:
        return self._item_work_dir

    def set_item_work_dir(self, path: Path | None) -> None:
        """Current batch item workspace (also receives cancel.flag)."""
        self._item_work_dir = path

    def start(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        work_dir: Path | None = None,
    ) -> None:
        if self.running:
            raise RuntimeError("process already running")
        self._work_dir = work_dir
        self._item_work_dir = None
        merged = os.environ.copy()
        if env:
            merged.update(env)
        # Windows: create new process group for safer terminate
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        self._proc = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=merged,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._wait, daemon=True).start()

    def request_cancel(self) -> None:
        """Write cancel.flag on job/batch root and current item work dir."""
        for root in (self._work_dir, self._item_work_dir):
            if root is None:
                continue
            try:
                (root / "cancel.flag").write_text("1", encoding="utf-8")
            except OSError:
                pass

    def _read_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                self.log_line.emit(line)
                continue
            if isinstance(obj, dict):
                self.event_received.emit(obj)

    def _read_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            text = line.rstrip()
            if text:
                self.log_line.emit(text)

    def _wait(self) -> None:
        assert self._proc is not None
        code = self._proc.wait()
        self.finished.emit(int(code))


STAGE_LABELS = {
    "probe": "探测媒体",
    "extract": "提取音频",
    "vad": "语音活动检测",
    "chunk": "分段规划",
    "asr": "语音识别",
    "alignment": "强制对齐",
    "subtitle": "字幕分句",
    "export": "导出字幕",
}

ERROR_MESSAGES = {
    "CUDA_OOM": (
        "显存不足",
        "模型处理过程中显存不足。\n已完成的处理进度已经保存。\n\n错误代码：CUDA_OOM",
    ),
    "MODEL_MISSING": (
        "模型缺失",
        "未找到完整且验证通过的本地模型。安装包默认不附带 ASR/对齐模型。\n\n"
        "请联网运行一次：\n"
        "  download-models.cmd\n"
        "模型会保存到 %LOCALAPPDATA%\\QwenSubtitle\\models。\n"
        "下载完成后可断网使用；转录不会自动联网下载。\n\n"
        "错误代码：MODEL_MISSING",
    ),
    "FFMPEG_FAILURE": (
        "音频提取失败",
        "FFmpeg 处理失败。请检查输入文件与 bin/ffmpeg.exe。\n\n错误代码：FFMPEG_FAILURE",
    ),
    "FFPROBE_FAILURE": (
        "媒体探测失败",
        "FFprobe 无法读取该文件。\n\n错误代码：FFPROBE_FAILURE",
    ),
    "CANCELED": (
        "已取消",
        "任务已取消。已完成的进度已保留，可使用相同工作目录继续。\n\n错误代码：CANCELED",
    ),
}


def humanize_error(code: str, message: str) -> tuple[str, str]:
    if code in ERROR_MESSAGES:
        return ERROR_MESSAGES[code]
    return ("处理失败", f"{message}\n\n错误代码：{code}")
