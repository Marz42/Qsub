"""Main window — thin Chinese GUI over qsub CLI (Spec §33–§35, §51)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
)

from gui.cli_process import STAGE_LABELS, CliProcess, humanize_error
from gui.paths import discover_install_root, find_qsub_command
from gui.settings import GuiSettings

MEDIA_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.m4a *.aac *.flac *.ogg);;"
    "所有文件 (*.*)"
)


class DropZone(QLabel):
    def __init__(self, on_paths, parent=None):
        super().__init__(parent)
        self._on_paths = on_paths
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
        self.setText("将视频或音频拖放到此处\n或点击下方「选择文件」")
        self.setStyleSheet(
            "QLabel {"
            " border: 2px dashed #7a8699;"
            " border-radius: 8px;"
            " color: #334155;"
            " background: #f1f5f9;"
            " font-size: 15px;"
            " padding: 16px;"
            "}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self._on_paths(paths)


class SettingsDialog(QDialog):
    def __init__(self, settings: GuiSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._settings = settings
        layout = QFormLayout(self)

        self.device = QComboBox()
        self.device.addItem("自动", "auto")
        self.device.addItem("CUDA（NVIDIA）", "cuda")
        self.device.addItem("CPU", "cpu")
        self._set_combo(self.device, settings.device)

        self.language = QComboBox()
        for label, value in [
            ("自动识别", "auto"),
            ("中文", "Chinese"),
            ("英文", "English"),
            ("日文", "Japanese"),
            ("韩文", "Korean"),
            ("粤语", "Cantonese"),
        ]:
            self.language.addItem(label, value)
        self._set_combo(self.language, settings.language)

        self.encoding = QComboBox()
        self.encoding.addItem("UTF-8 BOM（推荐）", "utf-8-bom")
        self.encoding.addItem("UTF-8", "utf-8")
        self._set_combo(self.encoding, settings.encoding)

        self.keep_work = QCheckBox("保留处理缓存（便于断点续跑）")
        self.keep_work.setChecked(settings.keep_work)

        layout.addRow("设备", self.device)
        layout.addRow("语言", self.language)
        layout.addRow("输出编码", self.encoding)
        layout.addRow("", self.keep_work)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def result_settings(self) -> GuiSettings:
        return GuiSettings(
            device=str(self.device.currentData()),
            language=str(self.language.currentData()),
            encoding=str(self.encoding.currentData()),
            keep_work=self.keep_work.isChecked(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QwenSubtitle")
        self.resize(720, 640)
        self.settings = GuiSettings.load()
        self.input_path: Path | None = None
        self.work_dir: Path | None = None
        self.last_srt: Path | None = None
        self.last_log_path: Path | None = None
        self.cli = CliProcess(self)
        self.cli.event_received.connect(self.on_event)
        self.cli.finished.connect(self.on_finished)
        self.cli.log_line.connect(self.on_log)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        brand = QLabel("QwenSubtitle")
        brand.setStyleSheet("font-size: 28px; font-weight: 700; color: #0f172a;")
        layout.addWidget(brand)

        subtitle = QLabel("本地离线字幕生成")
        subtitle.setStyleSheet("color: #64748b; font-size: 13px;")
        layout.addWidget(subtitle)

        self.drop = DropZone(self._accept_paths)
        layout.addWidget(self.drop)

        row = QHBoxLayout()
        self.btn_pick = QPushButton("选择文件…")
        self.btn_pick.clicked.connect(self.pick_file)
        self.btn_settings = QPushButton("设置…")
        self.btn_settings.clicked.connect(self.open_settings)
        row.addWidget(self.btn_pick)
        row.addWidget(self.btn_settings)
        row.addStretch(1)
        layout.addLayout(row)

        form_box = QGroupBox("任务")
        form = QFormLayout(form_box)
        self.lbl_file = QLabel("（未选择）")
        self.lbl_file.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_duration = QLabel("—")
        self.audio_combo = QComboBox()
        self.audio_combo.setEnabled(False)
        self.lang_combo = QComboBox()
        for label, value in [
            ("自动识别", "auto"),
            ("中文", "Chinese"),
            ("英文", "English"),
            ("日文", "Japanese"),
            ("韩文", "Korean"),
            ("粤语", "Cantonese"),
        ]:
            self.lang_combo.addItem(label, value)
        idx = self.lang_combo.findData(self.settings.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.btn_out = QPushButton("浏览…")
        self.btn_out.clicked.connect(self.pick_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.btn_out)

        form.addRow("文件", self.lbl_file)
        form.addRow("时长", self.lbl_duration)
        form.addRow("音轨", self.audio_combo)
        form.addRow("语言", self.lang_combo)
        form.addRow("输出", out_row)
        layout.addWidget(form_box)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("生成字幕")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.start_job)
        self.btn_run.setStyleSheet(
            "QPushButton { background:#0f766e; color:white; padding:10px 18px;"
            " border:none; border-radius:6px; font-weight:600; }"
            "QPushButton:disabled { background:#94a3b8; }"
        )
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_job)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("准备就绪")
        self.status.setStyleSheet("color:#334155;")
        layout.addWidget(self.status)

        self.result_box = QGroupBox("结果")
        result_layout = QVBoxLayout(self.result_box)
        self.result_label = QLabel("")
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(140)
        self.preview.setPlaceholderText("完成后将显示字幕预览（只读）")
        open_row = QHBoxLayout()
        self.btn_open_srt = QPushButton("打开字幕")
        self.btn_open_folder = QPushButton("打开文件夹")
        self.btn_open_log = QPushButton("查看日志")
        self.btn_open_srt.clicked.connect(self.open_srt)
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_open_log.clicked.connect(self.open_log)
        open_row.addWidget(self.btn_open_srt)
        open_row.addWidget(self.btn_open_folder)
        open_row.addWidget(self.btn_open_log)
        open_row.addStretch(1)
        result_layout.addWidget(self.result_label)
        result_layout.addWidget(self.preview)
        result_layout.addLayout(open_row)
        self.result_box.setVisible(False)
        layout.addWidget(self.result_box)
        layout.addStretch(1)

    def _accept_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        self.set_input(paths[0])

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择媒体文件", "", MEDIA_FILTER)
        if path:
            self.set_input(Path(path))

    def pick_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存字幕", self.out_edit.text() or "", "SRT (*.srt)")
        if path:
            self.out_edit.setText(path)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.result_settings()
            self.settings.save()
            idx = self.lang_combo.findData(self.settings.language)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)

    def set_input(self, path: Path) -> None:
        path = path.expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, "无效文件", f"找不到文件：\n{path}")
            return
        self.input_path = path
        self.lbl_file.setText(str(path))
        self.out_edit.setText(str(path.with_suffix(".srt")))
        self.btn_run.setEnabled(True)
        self.result_box.setVisible(False)
        self.last_srt = None
        self._probe_async(path)

    def _probe_async(self, path: Path) -> None:
        self.lbl_duration.setText("探测中…")
        self.audio_combo.clear()
        self.audio_combo.setEnabled(False)
        try:
            cmd = find_qsub_command() + ["probe", str(path), "--json"]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode != 0:
                self.lbl_duration.setText("探测失败")
                return
            data = json.loads(proc.stdout)
        except Exception as exc:  # noqa: BLE001
            self.lbl_duration.setText(f"探测失败：{exc}")
            return

        dur = data.get("duration")
        if isinstance(dur, (int, float)):
            m, s = divmod(float(dur), 60.0)
            self.lbl_duration.setText(f"{int(m):02d}:{s:06.3f}")
        else:
            self.lbl_duration.setText("—")

        streams = data.get("audio_streams") or []
        self.audio_combo.clear()
        self.audio_combo.addItem("自动", "auto")
        for st in streams:
            lang = st.get("language") or "?"
            label = f"#{st.get('index')} {st.get('codec')} {st.get('channels')}ch {lang}"
            if st.get("default"):
                label += "（默认）"
            self.audio_combo.addItem(label, str(st.get("index")))
        self.audio_combo.setEnabled(True)

    def start_job(self) -> None:
        if not self.input_path or self.cli.running:
            return
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "缺少输出", "请指定输出 SRT 路径。")
            return
        out_path = Path(out)

        self.work_dir = Path(tempfile.mkdtemp(prefix="qsub-gui-"))
        cmd = find_qsub_command() + [
            "transcribe",
            str(self.input_path),
            "--output",
            str(out_path),
            "--language",
            str(self.lang_combo.currentData()),
            "--device",
            self.settings.device,
            "--audio-stream",
            str(self.audio_combo.currentData() or "auto"),
            "--encoding",
            self.settings.encoding,
            "--events",
            "ndjson",
            "--work-dir",
            str(self.work_dir),
            "--overwrite",
        ]
        if self.settings.keep_work:
            cmd.append("--keep-work")

        self.progress.setValue(0)
        self.status.setText("正在启动…")
        self.result_box.setVisible(False)
        self.preview.clear()
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_pick.setEnabled(False)

        env = {}
        root = discover_install_root()
        if root is not None:
            env["QSUB_ROOT"] = str(root)
        try:
            self.cli.start(cmd, work_dir=self.work_dir, env=env)
        except Exception as exc:  # noqa: BLE001
            self.btn_run.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.btn_pick.setEnabled(True)
            QMessageBox.critical(self, "无法启动", str(exc))

    def cancel_job(self) -> None:
        self.status.setText("正在取消…")
        self.cli.request_cancel()

    def on_event(self, event: dict) -> None:
        et = event.get("type")
        if et == "progress":
            overall = event.get("overall")
            if isinstance(overall, (int, float)):
                self.progress.setValue(int(max(0.0, min(1.0, float(overall))) * 1000))
            stage = str(event.get("stage") or "")
            label = STAGE_LABELS.get(stage, stage)
            cur, total = event.get("current"), event.get("total")
            if cur is not None and total is not None:
                self.status.setText(f"{label}… {cur} / {total}")
            else:
                self.status.setText(f"{label}…")
        elif et == "stage_started":
            stage = str(event.get("stage") or "")
            self.status.setText(f"{STAGE_LABELS.get(stage, stage)}…")
        elif et == "artifact" and event.get("kind") == "srt":
            self.last_srt = Path(str(event.get("path")))
        elif et == "warning":
            code = event.get("code")
            self.status.setText(f"警告：{code}")
        elif et == "error":
            title, body = humanize_error(str(event.get("code") or "ERROR"), str(event.get("message") or ""))
            self.status.setText(title)
            QMessageBox.critical(self, title, body)
        elif et == "completed":
            overall = event.get("overall")
            if isinstance(overall, (int, float)):
                self.progress.setValue(int(float(overall) * 1000))
            srt = event.get("srt")
            if srt:
                self.last_srt = Path(str(srt))

    def on_log(self, line: str) -> None:
        # Keep UI quiet; optional debug could append.
        _ = line

    def on_finished(self, code: int) -> None:
        self.btn_cancel.setEnabled(False)
        self.btn_pick.setEnabled(True)
        self.btn_run.setEnabled(self.input_path is not None)
        if code == 0 and self.last_srt and self.last_srt.is_file():
            self.progress.setValue(1000)
            self.status.setText("字幕已生成")
            self.result_label.setText(f"✓ 字幕已生成\n{self.last_srt}")
            self.result_box.setVisible(True)
            self._load_preview(self.last_srt)
        elif code == 130:
            self.status.setText("已取消")
        elif code != 0:
            self.status.setText(f"失败（退出码 {code}）")
            if not self.result_box.isVisible():
                # Generic fallback if no NDJSON error arrived
                pass

    def _load_preview(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            self.preview.setPlainText("")
            return
        # Show first ~20 cue blocks worth of lines
        lines = text.splitlines()
        self.preview.setPlainText("\n".join(lines[:80]))

    def open_srt(self) -> None:
        if self.last_srt and self.last_srt.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_srt)))

    def open_folder(self) -> None:
        target = self.last_srt.parent if self.last_srt else None
        if target and target.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def open_log(self) -> None:
        local = os.environ.get("LOCALAPPDATA")
        log_dir = Path(local) / "QwenSubtitle" / "logs" if local else Path.home() / ".qwensubtitle" / "logs"
        if log_dir.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        else:
            QMessageBox.information(self, "日志", f"日志目录尚不存在：\n{log_dir}")
