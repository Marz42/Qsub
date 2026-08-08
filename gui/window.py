"""Main window — Nintendo 2001 chrome over qsub CLI (Chinese UI)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.batch_panel import BatchPanel
from gui.cli_process import STAGE_LABELS, CliProcess, humanize_error
from gui.paths import discover_install_root, find_qsub_command
from gui.settings import GuiSettings
from gui import theme

MEDIA_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.m4a *.aac *.flac *.ogg);;"
    "所有文件 (*.*)"
)


def _chamfer_path(w: float, h: float, cut: float = 10.0) -> QPainterPath:
    poly = QPolygonF(
        [
            QPointF(cut, 0),
            QPointF(w - cut, 0),
            QPointF(w, cut),
            QPointF(w, h - cut),
            QPointF(w - cut, h),
            QPointF(cut, h),
            QPointF(0, h - cut),
            QPointF(0, cut),
        ]
    )
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    return path


class DropZone(QWidget):
    def __init__(self, on_paths, parent=None):
        super().__init__(parent)
        self._on_paths = on_paths
        self.setAcceptDrops(True)
        self.setMinimumHeight(96)
        self.setMaximumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel("放入媒体")
        self.title.setObjectName("DropTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel("将视频 / 音频放入此处 · 或按下「选择文件」")
        self.hint.setObjectName("DropHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_pick = QPushButton("选择文件")
        self.btn_pick.setObjectName("BtnAmber")
        self.btn_pick.setFixedWidth(120)

        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addWidget(self.btn_pick, 0, Qt.AlignmentFlag.AlignHCenter)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        path = _chamfer_path(float(self.width()), float(self.height()), 10.0)
        p.fillPath(path, QColor(theme.LAVENDER))
        p.setPen(QPen(QColor(theme.CHROME_INDIGO), 1))
        p.drawPath(path)
        # top highlight
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.drawLine(12, 1, self.width() - 12, 1)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self._on_paths(paths)


def _spin(value: float, minimum: float, maximum: float, step: float, suffix: str = " 秒") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setSingleStep(step)
    w.setDecimals(2)
    w.setValue(value)
    w.setSuffix(suffix)
    return w


class SettingsDialog(QDialog):
    def __init__(self, settings: GuiSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(480, 420)
        self.resize(520, 560)
        self._settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        general = QGroupBox("常规")
        form = QFormLayout(general)
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

        form.addRow("设备", self.device)
        form.addRow("语言", self.language)
        form.addRow("输出编码", self.encoding)
        form.addRow("", self.keep_work)
        layout.addWidget(general)

        seg = QGroupBox("分句（只影响字幕切条，不改识别文字）")
        seg_form = QFormLayout(seg)
        tip = QLabel(
            "字幕太碎：先加大「停顿切句」和「停顿切句最短时长」。\n"
            "一条太长：先减小「推荐最长」。老在逗号切开：加大「逗号切句比例」。"
        )
        tip.setObjectName("HintText")
        tip.setWordWrap(True)
        seg_form.addRow(tip)

        self.pause_gap = _spin(settings.pause_gap, 0.10, 2.00, 0.05)
        self.pause_gap.setToolTip(
            "说话停顿达到此秒数就切开字幕。\n碎句太多 → 调大；该断不断 → 调小。"
        )
        self.target_min = _spin(settings.target_min, 0.20, 6.00, 0.10)
        self.target_min.setToolTip("靠停顿切句时，当前条至少已持续多久。碎句多 → 调大。")
        self.target_max = _spin(settings.target_max, 1.00, 20.00, 0.50)
        self.target_max.setToolTip("推荐单条最长。太长 → 调小；太碎 → 调大。")
        self.min_cue = _spin(settings.min_cue_duration, 0.20, 4.00, 0.10)
        self.min_cue.setToolTip("单条最短时长；过短会并入上一句。")
        self.hard_max = _spin(settings.hard_max_duration, 2.00, 30.00, 0.50)
        self.hard_max.setToolTip("硬上限：到点强制切开。")
        self.clause_ratio = _spin(settings.clause_break_ratio, 0.0, 1.0, 0.05, suffix="")
        self.clause_ratio.setToolTip("逗号切句比例：越大越不容易在逗号处切开。")

        seg_form.addRow("停顿切句", self.pause_gap)
        seg_form.addRow("停顿切句最短时长", self.target_min)
        seg_form.addRow("推荐最长", self.target_max)
        seg_form.addRow("最短条长", self.min_cue)
        seg_form.addRow("硬上限", self.hard_max)
        seg_form.addRow("逗号切句比例", self.clause_ratio)

        for name, desc in [
            ("停顿切句", "停顿多久才切一句"),
            ("停顿切句最短时长", "停顿切句前，当前条至少要播多久"),
            ("推荐最长", "希望单条字幕大概不超过多久"),
            ("最短条长", "太短的条合并到上一句"),
            ("硬上限", "再长也必须切开"),
            ("逗号切句比例", "越大越不容易在逗号处切开"),
        ]:
            lbl = QLabel(f"· {name}：{desc}")
            lbl.setObjectName("HintText")
            seg_form.addRow(lbl)

        layout.addWidget(seg)
        layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
            pause_gap=float(self.pause_gap.value()),
            target_min=float(self.target_min.value()),
            target_max=float(self.target_max.value()),
            min_cue_duration=float(self.min_cue.value()),
            hard_max_duration=float(self.hard_max.value()),
            clause_break_ratio=float(self.clause_ratio.value()),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QwenSubtitle")
        # Content is taller with Noto Sans SC + DPI scaling; allow shrink + scroll.
        self.setMinimumSize(640, 520)
        self.settings = GuiSettings.load()
        self.input_path: Path | None = None
        self.work_dir: Path | None = None
        self.last_srt: Path | None = None
        self.ui_mode = "single"  # single | batch
        self.job_kind: str | None = None  # single | batch while running
        self.batch_root: Path | None = None
        self._batch_item_stage = ""
        self._batch_summary: dict = {}
        self.cli = CliProcess(self)
        self.cli.event_received.connect(self.on_event)
        self.cli.finished.connect(self.on_finished)
        self.cli.log_line.connect(self.on_log)

        root = QWidget()
        root.setObjectName("CentralRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_nav())
        layout.addWidget(self._build_subnav())

        body = QWidget()
        body.setObjectName("CentralRoot")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(12, 12, 12, 12)
        body_lay.setSpacing(10)

        mid = QHBoxLayout()
        mid.setSpacing(12)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._build_single_page())
        self.batch_panel = BatchPanel()
        self.batch_panel.set_language(self.settings.language)
        self.batch_panel.queue_changed.connect(self._on_batch_queue_changed)
        self.mode_stack.addWidget(self.batch_panel)
        mid.addWidget(self.mode_stack, 2)

        status_box = QGroupBox("状态")
        status_box.setObjectName("StatusBox")
        status_form = QVBoxLayout(status_box)
        self.lbl_device = QLabel()
        self.lbl_encoding = QLabel()
        self.lbl_segment = QLabel()
        for w in (self.lbl_device, self.lbl_encoding, self.lbl_segment):
            w.setObjectName("HintText")
            w.setWordWrap(True)
            status_form.addWidget(w)
        self.btn_settings = QPushButton("设置…")
        self.btn_settings.setObjectName("BtnCarbon")
        self.btn_settings.clicked.connect(self.open_settings)
        status_form.addWidget(self.btn_settings)
        status_form.addStretch(1)
        mid.addWidget(status_box, 1)
        body_lay.addLayout(mid, 1)
        self._refresh_status_rail()

        progress_box = QGroupBox("进度")
        progress_box.setObjectName("ProgressPlate")
        prog = QVBoxLayout(progress_box)
        self.status = QLabel("准备就绪")
        self.status.setObjectName("StatusLine")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("生成字幕")
        self.btn_run.setObjectName("BtnSignal")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.start_job)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("BtnCarbon")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_batch_work = QPushButton("打开批量目录")
        self.btn_batch_work.setObjectName("BtnAmber")
        self.btn_batch_work.setVisible(False)
        self.btn_batch_work.clicked.connect(self.open_batch_root)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_batch_work)
        btn_row.addStretch(1)
        prog.addWidget(self.status)
        prog.addWidget(self.progress)
        prog.addLayout(btn_row)
        body_lay.addWidget(progress_box)

        self.result_box = QGroupBox("结果")
        result_layout = QVBoxLayout(self.result_box)
        self.result_label = QLabel("未生成 — 完成后显示预览")
        self.result_label.setObjectName("StatusLine")
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(120)
        self.preview.setPlaceholderText("字幕预览（只读）")
        open_row = QHBoxLayout()
        self.btn_open_srt = QPushButton("打开字幕")
        self.btn_open_folder = QPushButton("打开文件夹")
        self.btn_open_log = QPushButton("查看日志")
        self.btn_open_srt.setObjectName("BtnAmber")
        self.btn_open_folder.setObjectName("BtnAmber")
        self.btn_open_log.setObjectName("BtnCarbon")
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
        body_lay.addWidget(self.result_box)

        scroll = QScrollArea()
        scroll.setObjectName("BodyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._build_footer())
        self._apply_default_geometry()
        self.set_ui_mode("single")

    def _apply_default_geometry(self) -> None:
        """Fit default size to available screen; prefer ~860x760 logical, clamp to desktop."""
        screen = self.screen()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        target_w, target_h = 860, 760
        if avail is not None:
            # Leave margin for taskbar / DPI; never exceed available desktop.
            target_w = min(target_w, max(self.minimumWidth(), avail.width() - 48))
            target_h = min(target_h, max(self.minimumHeight(), avail.height() - 48))
            self.resize(target_w, target_h)
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())
        else:
            self.resize(target_w, target_h)

    def _build_nav(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("NavBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        pill = QLabel("Q")
        pill.setObjectName("BrandPill")
        name = QLabel("QwenSubtitle")
        name.setObjectName("BrandName")
        self.nav_meta = QLabel("本地离线字幕机 · READY")
        self.nav_meta.setObjectName("NavMeta")
        lay.addWidget(pill)
        lay.addWidget(name)
        lay.addStretch(1)
        lay.addWidget(self.nav_meta)
        return bar

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.drop = DropZone(self._accept_paths)
        self.drop.btn_pick.clicked.connect(self.pick_file)
        lay.addWidget(self.drop)

        form_box = QGroupBox("任务")
        form = QFormLayout(form_box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_file = QLabel("（未选择）")
        self.lbl_file.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_file.setWordWrap(True)
        self.lbl_duration = QLabel("—")
        self.audio_combo = QComboBox()
        self.audio_combo.addItem("自动（先选择文件）", "auto")
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
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.currentIndex()))

        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.btn_out = QPushButton("浏览…")
        self.btn_out.setObjectName("BtnAmber")
        self.btn_out.clicked.connect(self.pick_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.btn_out)

        form.addRow("文件", self.lbl_file)
        form.addRow("时长", self.lbl_duration)
        form.addRow("音轨", self.audio_combo)
        form.addRow("语言", self.lang_combo)
        form.addRow("输出", out_row)
        lay.addWidget(form_box)
        lay.addStretch(1)
        return page

    def _build_subnav(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("SubNav")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(4)
        self.btn_mode_single = QPushButton("单文件")
        self.btn_mode_batch = QPushButton("批量")
        for btn, mode in ((self.btn_mode_single, "single"), (self.btn_mode_batch, "batch")):
            btn.setObjectName("SubNavLink")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, m=mode: self.set_ui_mode(m))
            lay.addWidget(btn)
        sep = QLabel("·")
        sep.setObjectName("NavMeta")
        lay.addWidget(sep)
        for text, slot in (("设置", self.open_settings), ("日志目录", self.open_log)):
            btn = QPushButton(text)
            btn.setObjectName("SubNavLink")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
        lay.addStretch(1)
        return bar

    def set_ui_mode(self, mode: str) -> None:
        if self.cli.running and mode != self.ui_mode:
            QMessageBox.information(self, "处理中", "请先等待当前任务结束或取消后再切换。")
            self.btn_mode_single.setChecked(self.ui_mode == "single")
            self.btn_mode_batch.setChecked(self.ui_mode == "batch")
            return
        self.ui_mode = mode if mode in {"single", "batch"} else "single"
        self.mode_stack.setCurrentIndex(0 if self.ui_mode == "single" else 1)
        self.btn_mode_single.setChecked(self.ui_mode == "single")
        self.btn_mode_batch.setChecked(self.ui_mode == "batch")
        if self.ui_mode == "single":
            self.btn_run.setText("生成字幕")
            self.btn_run.setEnabled(self.input_path is not None and not self.cli.running)
            self.result_box.setVisible(bool(self.last_srt and self.last_srt.is_file()))
            self.btn_batch_work.setVisible(False)
        else:
            self.btn_run.setText("开始批量")
            self.btn_run.setEnabled(self.batch_panel.count() > 0 and not self.cli.running)
            self.result_box.setVisible(False)
            self.btn_batch_work.setVisible(self.batch_root is not None)
        self.nav_meta.setText(
            "本地离线字幕机 · 批量" if self.ui_mode == "batch" else "本地离线字幕机 · READY"
        )

    def _on_batch_queue_changed(self) -> None:
        if self.ui_mode == "batch" and not self.cli.running:
            self.btn_run.setEnabled(self.batch_panel.count() > 0)

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("FooterBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        self.footer_left = QLabel("work · —")
        self.footer_left.setObjectName("FooterText")
        self.footer_right = QLabel("QwenSubtitle 0.1.0 · CLI subprocess")
        self.footer_right.setObjectName("FooterText")
        lay.addWidget(self.footer_left)
        lay.addStretch(1)
        lay.addWidget(self.footer_right)
        return bar

    def _refresh_status_rail(self) -> None:
        device_map = {"auto": "自动", "cuda": "CUDA", "cpu": "CPU"}
        enc_map = {"utf-8-bom": "UTF-8 BOM", "utf-8": "UTF-8"}
        self.lbl_device.setText(f"设备\n{device_map.get(self.settings.device, self.settings.device)}")
        self.lbl_encoding.setText(f"输出编码\n{enc_map.get(self.settings.encoding, self.settings.encoding)}")
        self.lbl_segment.setText(
            f"分句\n停顿 {self.settings.pause_gap:g}s · 推荐最长 {self.settings.target_max:g}s"
        )

    def _accept_paths(self, paths: list[Path]) -> None:
        if paths:
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
            self.batch_panel.set_language(self.settings.language)
            self._refresh_status_rail()

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
        self.result_label.setText("未生成 — 完成后显示预览")
        self.preview.clear()
        self.last_srt = None
        self.nav_meta.setText("本地离线字幕机 · 已选文件")
        self._probe_async(path)

    def _probe_async(self, path: Path) -> None:
        self.lbl_duration.setText("探测中…")
        self.audio_combo.clear()
        self.audio_combo.addItem("探测中…", "auto")
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
                self.audio_combo.clear()
                self.audio_combo.addItem("自动", "auto")
                self.audio_combo.setEnabled(True)
                return
            data = json.loads(proc.stdout)
        except Exception as exc:  # noqa: BLE001
            self.lbl_duration.setText(f"探测失败：{exc}")
            self.audio_combo.clear()
            self.audio_combo.addItem("自动", "auto")
            self.audio_combo.setEnabled(True)
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
            codec = st.get("codec") or "?"
            ch = st.get("channels")
            ch_s = f"{ch}ch" if ch is not None else "?ch"
            label = f"#{st.get('index')} {codec} {ch_s} {lang}"
            if st.get("default"):
                label += "（默认）"
            self.audio_combo.addItem(label, str(st.get("index")))
        if len(streams) == 0:
            # Still usable: WAV/MP3 often reports one stream; if none, keep 自动
            self.audio_combo.setItemText(0, "自动（未列出音轨）")
        self.audio_combo.setEnabled(True)

    def start_job(self) -> None:
        if self.cli.running:
            return
        if self.ui_mode == "batch":
            self.start_batch()
            return
        if not self.input_path:
            return
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "缺少输出", "请指定输出 SRT 路径。")
            return
        out_path = Path(out)

        self.job_kind = "single"
        self.work_dir = Path(tempfile.mkdtemp(prefix="qsub-gui-"))
        self.footer_left.setText(f"work · {self.work_dir}")
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
            *self.settings.segment_cli_args(),
        ]
        if self.settings.keep_work:
            cmd.append("--keep-work")

        self.progress.setValue(0)
        self.status.setText("正在启动…")
        self.nav_meta.setText("本地离线字幕机 · 处理中")
        self.result_box.setVisible(False)
        self.result_label.setText("未生成 — 完成后显示预览")
        self.preview.clear()
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.drop.btn_pick.setEnabled(False)

        env = {}
        root = discover_install_root()
        if root is not None:
            env["QSUB_ROOT"] = str(root)
        try:
            self.cli.start(cmd, work_dir=self.work_dir, env=env)
        except Exception as exc:  # noqa: BLE001
            self.job_kind = None
            self.btn_run.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.drop.btn_pick.setEnabled(True)
            self.nav_meta.setText("本地离线字幕机 · 错误")
            QMessageBox.critical(self, "无法启动", str(exc))

    def start_batch(self) -> None:
        paths = self.batch_panel.paths()
        if not paths or self.cli.running:
            return

        self.batch_root = None
        self._batch_summary = {}
        self.job_kind = "batch"
        self._batch_item_stage = ""
        self.batch_panel.reset_statuses()
        self.batch_panel.set_controls_enabled(False)

        cmd = find_qsub_command() + [
            "batch",
            *[str(p) for p in paths],
            "--language",
            self.batch_panel.language(),
            "--device",
            self.settings.device,
            "--audio-stream",
            "auto",
            "--encoding",
            self.settings.encoding,
            "--events",
            "ndjson",
            *self.settings.segment_cli_args(),
        ]
        out_dir = self.batch_panel.output_dir()
        if out_dir is not None:
            cmd.extend(["--output-dir", str(out_dir)])
        if self.batch_panel.overwrite():
            cmd.append("--overwrite")
        if self.batch_panel.stop_on_error():
            cmd.append("--stop-on-error")
        if self.settings.keep_work:
            cmd.append("--keep-work")

        self.progress.setValue(0)
        self.status.setText(f"正在启动批量… 0 / {len(paths)}")
        self.nav_meta.setText("本地离线字幕机 · 批量处理中")
        self.result_box.setVisible(False)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_batch_work.setVisible(False)
        self.footer_left.setText("work · （等待批量目录）")

        env = {}
        root = discover_install_root()
        if root is not None:
            env["QSUB_ROOT"] = str(root)
        try:
            # work_dir set on batch_started (default %LOCALAPPDATA%\...\batches\<id>)
            self.cli.start(cmd, work_dir=None, env=env)
        except Exception as exc:  # noqa: BLE001
            self.job_kind = None
            self.batch_panel.set_controls_enabled(True)
            self.btn_run.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.nav_meta.setText("本地离线字幕机 · 错误")
            QMessageBox.critical(self, "无法启动", str(exc))

    def cancel_job(self) -> None:
        self.status.setText("正在取消…")
        if self.batch_root is not None:
            self.cli.set_work_dir(self.batch_root)
        self.cli.request_cancel()

    def on_event(self, event: dict) -> None:
        et = event.get("type")
        if self.job_kind == "batch":
            self._on_batch_event(event)
            return
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
            self.status.setText(f"警告：{event.get('code')}")
        elif et == "error":
            title, body = humanize_error(str(event.get("code") or "ERROR"), str(event.get("message") or ""))
            self.status.setText(title)
            self.nav_meta.setText("本地离线字幕机 · 错误")
            QMessageBox.critical(self, title, body)
        elif et == "completed":
            overall = event.get("overall")
            if isinstance(overall, (int, float)):
                self.progress.setValue(int(float(overall) * 1000))
            srt = event.get("srt")
            if srt:
                self.last_srt = Path(str(srt))

    def _on_batch_event(self, event: dict) -> None:
        et = event.get("type")
        if et == "batch_started":
            root = event.get("work_root")
            if root:
                self.batch_root = Path(str(root))
                self.work_dir = self.batch_root
                self.cli.set_work_dir(self.batch_root)
                self.footer_left.setText(f"work · {self.batch_root}")
                self.btn_batch_work.setVisible(True)
            total = event.get("total")
            self.status.setText(f"批量开始… 0 / {total}")
        elif et == "item_started":
            idx = int(event.get("index") or 0)
            total = event.get("total")
            work = event.get("work_dir")
            out = event.get("output")
            self.batch_panel.set_item_started(idx, output=str(out) if out else None, work_dir=str(work) if work else None)
            if work:
                self.cli.set_item_work_dir(Path(str(work)))
            name = Path(str(event.get("path") or "")).name
            self.status.setText(f"文件 {idx + 1} / {total} · {name}")
            self._batch_item_stage = ""
        elif et == "item_finished":
            idx = int(event.get("index") or 0)
            status = str(event.get("status") or ("ok" if event.get("ok") else "failed"))
            note = str(event.get("error_code") or event.get("message") or "")
            srt = event.get("srt")
            self.batch_panel.set_item_finished(idx, status=status, srt=str(srt) if srt else None, note=note or None)
        elif et == "batch_progress":
            overall = event.get("overall")
            if isinstance(overall, (int, float)):
                self.progress.setValue(int(max(0.0, min(1.0, float(overall))) * 1000))
            cur, total = event.get("current"), event.get("total")
            if cur is not None and total is not None and not self._batch_item_stage:
                self.status.setText(f"批量进度 {cur} / {total}")
        elif et == "progress":
            # Per-file progress: blend file-level overall with batch index when possible
            item_idx = event.get("item_index")
            stage = str(event.get("stage") or "")
            label = STAGE_LABELS.get(stage, stage)
            self._batch_item_stage = label
            file_overall = event.get("overall")
            cur, total = event.get("current"), event.get("total")
            prefix = f"文件 {(int(item_idx) + 1)} · " if item_idx is not None else ""
            if cur is not None and total is not None:
                self.status.setText(f"{prefix}{label}… {cur} / {total}")
            else:
                self.status.setText(f"{prefix}{label}…")
            if isinstance(file_overall, (int, float)) and item_idx is not None:
                # Soft update within current file slot
                n = max(self.batch_panel.count(), 1)
                blended = (int(item_idx) + max(0.0, min(1.0, float(file_overall)))) / n
                self.progress.setValue(int(blended * 1000))
        elif et == "stage_started":
            stage = str(event.get("stage") or "")
            label = STAGE_LABELS.get(stage, stage)
            self._batch_item_stage = label
            item_idx = event.get("item_index")
            prefix = f"文件 {(int(item_idx) + 1)} · " if item_idx is not None else ""
            self.status.setText(f"{prefix}{label}…")
        elif et == "error":
            # Row-level failures; avoid modal spam during batch
            code = str(event.get("code") or "")
            idx = event.get("item_index")
            if idx is not None:
                self.batch_panel.set_item_finished(int(idx), status="failed", note=code)
            else:
                self.status.setText(f"错误：{code}")
        elif et == "batch_completed":
            overall = event.get("overall")
            if isinstance(overall, (int, float)):
                self.progress.setValue(int(float(overall) * 1000))
            self._batch_summary = {
                "succeeded": int(event.get("succeeded") or 0),
                "failed": int(event.get("failed") or 0),
                "canceled": int(event.get("canceled") or 0),
                "skipped": int(event.get("skipped") or 0),
                "summary_path": event.get("summary_path"),
            }

    def on_log(self, line: str) -> None:
        _ = line

    def on_finished(self, code: int) -> None:
        kind = self.job_kind
        self.job_kind = None
        self.btn_cancel.setEnabled(False)
        self.cli.set_item_work_dir(None)
        self.drop.btn_pick.setEnabled(True)

        if kind == "batch":
            self.batch_panel.set_controls_enabled(True)
            self.btn_run.setEnabled(self.batch_panel.count() > 0)
            summary = getattr(self, "_batch_summary", None) or {}
            ok = int(summary.get("succeeded") or 0)
            failed = int(summary.get("failed") or 0)
            canceled = int(summary.get("canceled") or 0)
            skipped = int(summary.get("skipped") or 0)
            if code == 130 or canceled:
                self.status.setText(f"批量已取消 · 成功 {ok} / 失败 {failed}")
                self.nav_meta.setText("本地离线字幕机 · 已取消")
            elif failed:
                self.status.setText(f"批量结束 · 成功 {ok} · 失败 {failed}" + (f" · 跳过 {skipped}" if skipped else ""))
                self.nav_meta.setText("本地离线字幕机 · 部分失败")
            elif code == 0:
                self.progress.setValue(1000)
                self.status.setText(f"批量完成 · 成功 {ok}")
                self.nav_meta.setText("本地离线字幕机 · READY")
            else:
                self.status.setText(f"批量失败（退出码 {code}）")
                self.nav_meta.setText("本地离线字幕机 · 失败")
            QMessageBox.information(
                self,
                "批量摘要",
                f"成功：{ok}\n失败：{failed}\n取消：{canceled}\n跳过：{skipped}\n\n"
                f"工作目录：\n{self.batch_root or '—'}",
            )
            self.btn_batch_work.setVisible(self.batch_root is not None)
            return

        self.btn_run.setEnabled(self.input_path is not None)
        if code == 0 and self.last_srt and self.last_srt.is_file():
            self.progress.setValue(1000)
            self.status.setText("字幕已生成")
            self.nav_meta.setText("本地离线字幕机 · READY")
            self.result_label.setText(f"字幕已生成 · {self.last_srt.name}")
            self.result_box.setVisible(True)
            self._load_preview(self.last_srt)
        elif code == 130:
            self.status.setText("已取消")
            self.nav_meta.setText("本地离线字幕机 · 已取消")
        elif code != 0:
            self.status.setText(f"失败（退出码 {code}）")
            self.nav_meta.setText("本地离线字幕机 · 失败")

    def _load_preview(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            self.preview.setPlainText("")
            return
        self.preview.setPlainText("\n".join(text.splitlines()[:80]))

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

    def open_batch_root(self) -> None:
        if self.batch_root and self.batch_root.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.batch_root)))
        else:
            QMessageBox.information(self, "批量目录", "尚无批量作业目录。")
