"""Dialog for the return trip: paste the AI's reply, review diffs, apply with backup, restore."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codepack.core.apply import (
    ApplyError,
    BackupError,
    ChangePlan,
    apply_plan,
    list_backups,
    plan_changes,
    restore_backup,
)
from codepack.gui.labels import CHANGE_LABELS

PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class DiffHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._formats = {}
        for prefix, color in (("+", "#2e7d32"), ("-", "#c62828"), ("@", "#1565c0")):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[prefix] = fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        if text.startswith(("+++", "---")):
            return
        fmt = self._formats.get(text[:1])
        if fmt is not None:
            self.setFormat(0, len(text), fmt)


class ApplyDialog(QDialog):
    applied = Signal()
    """Emitted after files were written or restored."""

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.plan: ChangePlan | None = None
        self.setWindowTitle(f"套用 AI 回答 — {root.name}")
        self.resize(1100, 750)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.reply_edit = QPlainTextEdit()
        self.reply_edit.setPlaceholderText(
            "把 AI 的回答整段貼在這裡。\n"
            "支援兩種格式(可混用):\n"
            "  === FILE: path === … === END FILE ===  (完整檔案)\n"
            "  --- a/path / +++ b/path / @@ … @@     (unified diff)\n"
            "打包時在「輸出 → 要求回答格式」選一種，AI 就會照格式回答。"
        )
        self.reply_edit.setFont(mono)
        paste = QPushButton("從剪貼簿貼上")
        paste.clicked.connect(self._paste)
        self.parse_button = QPushButton("解析")
        self.parse_button.clicked.connect(self.parse)

        reply_box = QWidget()
        reply_layout = QVBoxLayout(reply_box)
        reply_layout.setContentsMargins(0, 0, 0, 0)
        reply_layout.addWidget(self.reply_edit)
        row = QHBoxLayout()
        row.addWidget(paste)
        row.addStretch()
        row.addWidget(self.parse_button)
        reply_layout.addLayout(row)

        self.change_list = QTreeWidget()
        self.change_list.setHeaderLabels(["檔案", "動作", "+/-", "狀態"])
        self.change_list.setRootIsDecorated(False)
        self.change_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        header = self.change_list.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.change_list.currentItemChanged.connect(self._show_diff)
        self.change_list.itemChanged.connect(lambda *_: self._update_buttons())

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff_view.setFont(mono)
        self._highlighter = DiffHighlighter(self.diff_view.document())

        changes_split = QSplitter(Qt.Orientation.Horizontal)
        changes_split.addWidget(self.change_list)
        changes_split.addWidget(self.diff_view)
        changes_split.setSizes([460, 620])

        main_split = QSplitter(Qt.Orientation.Vertical)
        main_split.addWidget(reply_box)
        main_split.addWidget(changes_split)
        main_split.setSizes([250, 450])

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.backup_check = QCheckBox("寫入前備份(可一鍵還原)")
        self.backup_check.setChecked(True)
        self.apply_button = QPushButton("套用勾選的變更")
        self.apply_button.setStyleSheet("font-weight: bold; padding: 4px 16px;")
        self.apply_button.clicked.connect(self.apply)

        self.backup_combo = QComboBox()
        self.backup_combo.setMinimumWidth(260)
        self.restore_button = QPushButton("還原此備份")
        self.restore_button.clicked.connect(self.restore)
        close = QPushButton("關閉")
        close.clicked.connect(self.close)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("備份"))
        bottom.addWidget(self.backup_combo)
        bottom.addWidget(self.restore_button)
        bottom.addStretch()
        bottom.addWidget(self.backup_check)
        bottom.addWidget(self.apply_button)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(main_split, 1)
        layout.addWidget(self.message_label)
        layout.addLayout(bottom)

        self._reload_backups()
        self._update_buttons()

    # --- helpers ----------------------------------------------------------

    def _paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self.reply_edit.setPlainText(text)
            self.parse()

    def _reload_backups(self) -> None:
        self.backup_combo.clear()
        for b in list_backups(self.root):
            self.backup_combo.addItem(f"{b.id}  ({len(b.entries)} 個檔案)", b.id)
        self.restore_button.setEnabled(self.backup_combo.count() > 0)
        if self.backup_combo.count() == 0:
            self.backup_combo.addItem("(尚無備份)")

    def checked_paths(self) -> list[str]:
        paths = []
        for i in range(self.change_list.topLevelItemCount()):
            item = self.change_list.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                paths.append(item.data(0, PATH_ROLE))
        return paths

    def _update_buttons(self) -> None:
        self.apply_button.setEnabled(bool(self.checked_paths()))

    def _show_diff(self, item: QTreeWidgetItem | None, _prev=None) -> None:
        if item is None or self.plan is None:
            self.diff_view.clear()
            return
        path = item.data(0, PATH_ROLE)
        change = next(c for c in self.plan.changes if c.path == path)
        parts = []
        if change.error:
            parts.append(f"# 無法套用:{change.error}\n")
        parts.extend(f"# 注意:{w}\n" for w in change.warnings)
        parts.append(change.diff() if not change.unchanged else "(內容沒有變更)\n")
        self.diff_view.setPlainText("".join(parts))

    # --- actions ----------------------------------------------------------

    def parse(self) -> None:
        self.plan = plan_changes(self.root, self.reply_edit.toPlainText())
        self.change_list.blockSignals(True)
        self.change_list.clear()
        for c in self.plan.changes:
            added, removed = c.stats() if c.ok else (0, 0)
            if c.error:
                status = "錯誤"
            elif c.unchanged:
                status = "無變更"
            elif c.warnings:
                status = "請檢查"
            else:
                status = "可套用"
            item = QTreeWidgetItem([c.path, CHANGE_LABELS[c.kind], f"+{added} -{removed}", status])
            item.setData(0, PATH_ROLE, c.path)
            if c.applicable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setForeground(0, QColor("gray"))
            if c.error:
                item.setForeground(3, QColor("#c62828"))
            elif c.warnings:
                item.setForeground(3, QColor("#b8860b"))
            self.change_list.addTopLevelItem(item)
        self.change_list.blockSignals(False)

        n = len(self.plan.applicable)
        msg = f"找到 {len(self.plan.changes)} 個檔案,{n} 個可套用。"
        if self.plan.errors:
            msg += "  解析問題:" + ";".join(self.plan.errors)
        self.message_label.setText(msg)
        if self.change_list.topLevelItemCount():
            self.change_list.setCurrentItem(self.change_list.topLevelItem(0))
        self._update_buttons()

    def apply(self) -> None:
        if self.plan is None:
            return
        paths = self.checked_paths()
        if not paths:
            return
        backup = self.backup_check.isChecked()
        question = f"要把 {len(paths)} 個檔案的變更寫入專案嗎?"
        if not backup:
            question += "\n\n未勾選備份，寫入後將無法用 CodePack 還原。"
        if QMessageBox.question(self, "確認套用", question) != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_plan(self.plan, paths, backup=backup, description=f"套用 AI 回答({len(paths)} 個檔案)")
        except (ApplyError, OSError) as exc:
            QMessageBox.warning(self, "套用失敗", str(exc))
            return
        msg = f"已寫入 {len(result.written)} 個、刪除 {len(result.deleted)} 個檔案。"
        if result.backup:
            msg += f"  備份:{result.backup.id}"
        if result.warnings:
            msg += "  " + ";".join(result.warnings)
        self.message_label.setText(msg)
        self._reload_backups()
        self.parse()  # refresh: applied changes now show as unchanged
        self.applied.emit()

    def restore(self) -> None:
        backup_id = self.backup_combo.currentData()
        if not backup_id:
            return
        if QMessageBox.question(self, "確認還原", f"要把備份 {backup_id} 裡的檔案還原嗎?\n套用時新增的檔案會被刪除。") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            info = restore_backup(self.root, backup_id)
        except (BackupError, OSError) as exc:
            QMessageBox.warning(self, "還原失敗", str(exc))
            return
        self.message_label.setText(f"已從備份 {info.id} 還原 {len(info.entries)} 個檔案。")
        if self.plan is not None:
            self.parse()
        self.applied.emit()
