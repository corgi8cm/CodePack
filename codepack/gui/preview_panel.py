"""Right column: output preview, token budget bar, copy and save."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from codepack.core import PackResult
from codepack.gui.labels import SECRET_LABELS

TOKEN_LIMITS = [
    ("32K", 32_000),
    ("128K", 128_000),
    ("200K", 200_000),
    ("1M(Gemini)", 1_000_000),
    ("2M", 2_000_000),
]
DEFAULT_LIMIT_INDEX = 3

# Render very large outputs only partially; copy/save always use the full text.
PREVIEW_CHAR_LIMIT = 2_000_000


class PreviewPanel(QWidget):
    saveRequested = Signal()
    limitChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: PackResult | None = None

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.preview.setPlaceholderText("按「打包」產生輸出")

        self.stale_label = QLabel("")
        self.stale_label.setStyleSheet("color: #b8860b;")
        self.secrets_button = QPushButton()
        self.secrets_button.setFlat(True)
        self.secrets_button.setStyleSheet("color: #2e7d32; text-align: left;")
        self.secrets_button.clicked.connect(self._show_findings)
        self.secrets_button.hide()

        self.limit_combo = QComboBox()
        for label, value in TOKEN_LIMITS:
            self.limit_combo.addItem(label, value)
        self.limit_combo.setCurrentIndex(DEFAULT_LIMIT_INDEX)
        self.limit_combo.currentIndexChanged.connect(lambda _: self._refresh_bar())
        self.limit_combo.currentIndexChanged.connect(lambda _: self.limitChanged.emit(self.limit()))

        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.token_label = QLabel()

        self.copy_button = QPushButton("複製到剪貼簿")
        self.save_button = QPushButton("另存檔案…")
        self.copy_button.clicked.connect(self.copy)
        self.save_button.clicked.connect(self.saveRequested)

        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("上限"))
        limit_row.addWidget(self.limit_combo)
        limit_row.addWidget(self.bar, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.token_label, 1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.stale_label)
        layout.addWidget(self.secrets_button)
        layout.addLayout(limit_row)
        layout.addLayout(buttons)

        self._estimate = 0
        self.set_result(None)

    def limit(self) -> int:
        return int(self.limit_combo.currentData())

    @property
    def result(self) -> PackResult | None:
        return self._result

    def set_result(self, result: PackResult | None) -> None:
        self._result = result
        has = result is not None
        self.copy_button.setEnabled(has)
        self.save_button.setEnabled(has)
        self.set_stale(False)
        findings = result.findings if result is not None else []
        self.secrets_button.setText(f"🔒 已遮罩 {len(findings)} 處機密(點此查看)")
        self.secrets_button.setVisible(bool(findings))
        if result is None:
            self.preview.clear()
        else:
            text = result.text
            if len(text) > PREVIEW_CHAR_LIMIT:
                text = text[:PREVIEW_CHAR_LIMIT] + "\n\n…(預覽已截斷,複製/另存仍是完整內容)"
            self.preview.setPlainText(text)
        self._refresh_bar()

    def set_estimate(self, tokens: int) -> None:
        """Live estimate from the current selection (before packing)."""
        self._estimate = tokens
        self._refresh_bar()

    def set_stale(self, stale: bool) -> None:
        self.stale_label.setText("選取或選項已變更,預覽不是最新的,請重新打包" if stale and self._result else "")
        self._refresh_bar()

    def _refresh_bar(self) -> None:
        limit = self.limit()
        if self._result is not None and not self.stale_label.text():
            tokens = self._result.total_tokens
            label = f"輸出約 {tokens:,} tokens / {self._result.char_count:,} 字元 / {len(self._result.files)} 個檔案"
        else:
            tokens = self._estimate
            label = f"選取內容約 {tokens:,} tokens(不含格式)"
        self.token_label.setText(label)
        self.bar.setRange(0, 1000)
        self.bar.setValue(min(1000, int(tokens * 1000 / limit)) if limit else 0)
        self.bar.setFormat(f"{tokens / limit:.1%}" if limit else "")
        over = tokens > limit
        self.bar.setStyleSheet("QProgressBar::chunk { background-color: #d9534f; }" if over else "")
        if over:
            self.bar.setFormat(self.bar.format() + "  超過上限")

    def findings_text(self) -> str:
        if self._result is None:
            return ""
        lines = [f"{f.rel_path}:{f.line}  {SECRET_LABELS.get(f.kind, f.kind)}  {f.preview}" for f in self._result.findings]
        return "\n".join(lines)

    def _show_findings(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("已遮罩的機密")
        box.setText(
            "以下內容在輸出中已換成 <REDACTED:...> 佔位符。\n"
            "用「套用回答」寫回專案時，佔位符會自動還原成原本的值。"
        )
        box.setDetailedText(self.findings_text())
        box.exec()

    def copy(self) -> None:
        if self._result is not None:
            QGuiApplication.clipboard().setText(self._result.text)
