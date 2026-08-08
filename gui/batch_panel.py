"""Batch queue UI (v0.2) — driven by one `qsub batch` subprocess."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MEDIA_SUFFIXES = {
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

MEDIA_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.m4a *.aac *.flac *.ogg);;"
    "所有文件 (*.*)"
)

STATUS_LABELS = {
    "pending": "等待",
    "running": "处理中",
    "ok": "完成",
    "failed": "失败",
    "canceled": "已取消",
    "skipped": "跳过",
}


def collect_media_paths(raw: list[Path]) -> list[Path]:
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
                if child.is_file() and child.suffix.lower() in MEDIA_SUFFIXES:
                    found.append(child.resolve())
        for c in found:
            if c.is_file() and c not in seen:
                seen.add(c)
                out.append(c)
    return out


class BatchPanel(QWidget):
    queue_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[Path] = []
        self._item_work: dict[int, Path] = {}
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        tools = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件…")
        self.btn_add_files.setObjectName("BtnAmber")
        self.btn_add_folder = QPushButton("添加文件夹…")
        self.btn_add_folder.setObjectName("BtnAmber")
        self.btn_clear = QPushButton("清空队列")
        self.btn_clear.setObjectName("BtnCarbon")
        self.btn_remove = QPushButton("移除所选")
        self.btn_remove.setObjectName("BtnCarbon")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_clear.clicked.connect(self.clear_queue)
        self.btn_remove.clicked.connect(self._remove_selected)
        tools.addWidget(self.btn_add_files)
        tools.addWidget(self.btn_add_folder)
        tools.addWidget(self.btn_remove)
        tools.addWidget(self.btn_clear)
        tools.addStretch(1)
        root.addLayout(tools)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号", "文件名", "状态", "输出", "备注"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(180)
        root.addWidget(self.table, 1)

        opts = QGroupBox("批量参数")
        form = QFormLayout(opts)
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

        out_row = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setPlaceholderText("留空 = 各文件旁输出 .srt")
        self.btn_out_dir = QPushButton("浏览…")
        self.btn_out_dir.setObjectName("BtnAmber")
        self.btn_out_dir.clicked.connect(self._pick_out_dir)
        out_row.addWidget(self.out_dir_edit, 1)
        out_row.addWidget(self.btn_out_dir)

        self.chk_overwrite = QCheckBox("覆盖已存在的字幕")
        self.chk_stop = QCheckBox("遇错停止（默认继续下一项）")
        tip = QLabel("音轨固定为自动。设备 / 分句 / 编码见右侧「状态」与设置。")
        tip.setObjectName("HintText")
        tip.setWordWrap(True)

        form.addRow("语言", self.lang_combo)
        form.addRow("输出目录", out_row)
        form.addRow("", self.chk_overwrite)
        form.addRow("", self.chk_stop)
        form.addRow(tip)
        root.addWidget(opts)

        self.lbl_count = QLabel("队列：0 个文件")
        self.lbl_count.setObjectName("HintText")
        root.addWidget(self.lbl_count)

    def set_language(self, language: str) -> None:
        idx = self.lang_combo.findData(language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

    def language(self) -> str:
        return str(self.lang_combo.currentData() or "auto")

    def output_dir(self) -> Path | None:
        text = self.out_dir_edit.text().strip()
        return Path(text) if text else None

    def overwrite(self) -> bool:
        return self.chk_overwrite.isChecked()

    def stop_on_error(self) -> bool:
        return self.chk_stop.isChecked()

    def paths(self) -> list[Path]:
        return list(self._paths)

    def count(self) -> int:
        return len(self._paths)

    def item_work_dir(self, index: int) -> Path | None:
        return self._item_work.get(index)

    def set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self.btn_add_files,
            self.btn_add_folder,
            self.btn_clear,
            self.btn_remove,
            self.lang_combo,
            self.out_dir_edit,
            self.btn_out_dir,
            self.chk_overwrite,
            self.chk_stop,
        ):
            w.setEnabled(enabled)

    def add_paths(self, paths: list[Path]) -> int:
        added = 0
        existing = {p.resolve() for p in self._paths}
        for p in collect_media_paths(paths):
            if p in existing:
                continue
            existing.add(p)
            self._paths.append(p)
            added += 1
        if added:
            self._rebuild_table()
            self.queue_changed.emit()
        return added

    def clear_queue(self) -> None:
        self._paths.clear()
        self._item_work.clear()
        self._rebuild_table()
        self.queue_changed.emit()

    def reset_statuses(self) -> None:
        self._item_work.clear()
        for row in range(self.table.rowCount()):
            self._set_cell(row, 2, STATUS_LABELS["pending"])
            self._set_cell(row, 3, "")
            self._set_cell(row, 4, "")

    def set_item_started(self, index: int, *, output: str | None = None, work_dir: str | None = None) -> None:
        if not (0 <= index < self.table.rowCount()):
            return
        self._set_cell(index, 2, STATUS_LABELS["running"])
        if output:
            self._set_cell(index, 3, output)
        if work_dir:
            self._item_work[index] = Path(work_dir)
        self._set_cell(index, 4, "")
        self.table.selectRow(index)

    def set_item_finished(
        self,
        index: int,
        *,
        status: str,
        srt: str | None = None,
        note: str | None = None,
    ) -> None:
        if not (0 <= index < self.table.rowCount()):
            return
        self._set_cell(index, 2, STATUS_LABELS.get(status, status))
        if srt:
            self._set_cell(index, 3, srt)
        if note:
            self._set_cell(index, 4, note)

    def open_work_for_row(self, row: int) -> Path | None:
        return self._item_work.get(row)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "添加媒体文件", "", MEDIA_FILTER)
        if paths:
            self.add_paths([Path(p) for p in paths])

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加文件夹（递归收集媒体）")
        if folder:
            self.add_paths([Path(folder)])

    def _pick_out_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择统一输出目录")
        if folder:
            self.out_dir_edit.setText(folder)

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._paths):
                del self._paths[row]
        self._rebuild_table()
        self.queue_changed.emit()

    def _rebuild_table(self) -> None:
        self.table.setRowCount(len(self._paths))
        for i, path in enumerate(self._paths):
            self._set_cell(i, 0, str(i + 1), align=Qt.AlignmentFlag.AlignCenter)
            self._set_cell(i, 1, path.name)
            self._set_cell(i, 2, STATUS_LABELS["pending"])
            self._set_cell(i, 3, "")
            self._set_cell(i, 4, "")
            self.table.item(i, 1).setToolTip(str(path))
        self.lbl_count.setText(f"队列：{len(self._paths)} 个文件")

    def _set_cell(
        self,
        row: int,
        col: int,
        text: str,
        *,
        align: Qt.AlignmentFlag | None = None,
    ) -> None:
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            if align is not None:
                item.setTextAlignment(int(align))
            self.table.setItem(row, col, item)
        else:
            item.setText(text)

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
            self.add_paths(paths)
