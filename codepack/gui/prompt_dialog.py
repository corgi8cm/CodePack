"""Dialog for viewing, editing and adding question templates."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from codepack.core.prompts import PromptTemplate, all_templates, delete_template, set_template

NAME_ROLE = Qt.ItemDataRole.UserRole + 1
_SOURCE_SUFFIX = {"builtin": "", "override": "(已修改)", "user": "(自訂)"}


class PromptTemplateDialog(QDialog):
    templatesChanged = Signal()
    copied = Signal(str)
    """Emitted with the template name after copying it."""

    def __init__(self, path: Path | None = None, select: str | None = None, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("提問模板")
        self.resize(900, 560)
        self._templates: dict[str, PromptTemplate] = {}

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)

        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-weight: bold;")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text_edit.textChanged.connect(self._update_buttons)

        self.new_button = QPushButton("新增…")
        self.save_button = QPushButton("儲存")
        self.delete_button = QPushButton("刪除")
        self.copy_button = QPushButton("複製到剪貼簿")
        close = QPushButton("關閉")
        self.new_button.clicked.connect(self.new_template)
        self.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self.delete)
        self.copy_button.clicked.connect(self.copy)
        close.clicked.connect(self.close)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.addRow("名稱", self.name_label)
        right_layout.addLayout(form)
        right_layout.addWidget(self.text_edit, 1)
        right_layout.addWidget(QLabel("複製後貼到 Gemini,接在打包內容後面，再把「我想問:」後面改成你的問題。"))

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list)
        split.addWidget(right)
        split.setSizes([260, 640])

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addLayout(buttons)

        self.reload(select)

    # --- state ------------------------------------------------------------

    def current(self) -> PromptTemplate | None:
        item = self.list.currentItem()
        return self._templates.get(item.data(NAME_ROLE)) if item else None

    def reload(self, select: str | None = None) -> None:
        templates = all_templates(self.path)
        self._templates = {t.name: t for t in templates}
        self.list.blockSignals(True)
        self.list.clear()
        for t in templates:
            item = QListWidgetItem(t.name + _SOURCE_SUFFIX[t.source])
            item.setData(NAME_ROLE, t.name)
            self.list.addItem(item)
        self.list.blockSignals(False)
        names = [t.name for t in templates]
        row = names.index(select) if select in names else 0
        self.list.setCurrentRow(row)
        self._show(self.list.currentItem())

    def _show(self, item: QListWidgetItem | None, _prev=None) -> None:
        t = self._templates.get(item.data(NAME_ROLE)) if item else None
        self.name_label.setText(t.name if t else "")
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(t.text if t else "")
        self.text_edit.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        t = self.current()
        self.save_button.setEnabled(t is not None and self.text_edit.toPlainText() != t.text)
        self.copy_button.setEnabled(t is not None)
        if t is None or t.source == "builtin":
            self.delete_button.setText("刪除")
            self.delete_button.setEnabled(False)
        elif t.source == "override":
            self.delete_button.setText("還原預設")
            self.delete_button.setEnabled(True)
        else:
            self.delete_button.setText("刪除")
            self.delete_button.setEnabled(True)

    # --- actions ----------------------------------------------------------

    def new_template(self) -> None:
        name, ok = QInputDialog.getText(self, "新增模板", "模板名稱:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self._templates:
            QMessageBox.information(self, "提問模板", f"已經有名為「{name}」的模板。")
            return
        set_template(name, "我想問:\n", self.path)
        self.reload(name)
        self.text_edit.setFocus()
        self.templatesChanged.emit()

    def save(self) -> None:
        t = self.current()
        if t is None:
            return
        set_template(t.name, self.text_edit.toPlainText(), self.path)
        self.reload(t.name)
        self.templatesChanged.emit()

    def delete(self) -> None:
        t = self.current()
        if t is None or t.source == "builtin":
            return
        question = f"要把「{t.name}」還原成預設內容嗎?" if t.source == "override" else f"要刪除模板「{t.name}」嗎?"
        if QMessageBox.question(self, "提問模板", question) != QMessageBox.StandardButton.Yes:
            return
        delete_template(t.name, self.path)
        self.reload(t.name)
        self.templatesChanged.emit()

    def copy(self) -> None:
        t = self.current()
        if t is None:
            return
        QGuiApplication.clipboard().setText(self.text_edit.toPlainText())
        self.copied.emit(t.name)
