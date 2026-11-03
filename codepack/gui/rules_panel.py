"""Middle column: include/exclude rules and output options."""

from __future__ import annotations

from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from codepack.core import PackOptions, Preset, RuleSet, available_formats, parse_rule_lines
from codepack.gui.labels import FORMAT_LABELS

RULES_DEBOUNCE_MS = 700


class RulesPanel(QWidget):
    rulesChanged = Signal()
    """Emitted (debounced) when anything affecting the scan changes."""
    optionsChanged = Signal()
    """Emitted when output options change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.include_edit = QPlainTextEdit()
        self.include_edit.setPlaceholderText("例如:\n*.cpp\n*.h\nsrc/**\n(留空 = 全部)")
        self.exclude_edit = QPlainTextEdit()
        self.exclude_edit.setPlaceholderText("例如:\nbuild/\nthird_party/\n*.generated.h")
        for edit in (self.include_edit, self.exclude_edit):
            edit.setFont(mono)
            edit.textChanged.connect(self._rules_edited)

        self.gitignore_check = QCheckBox("套用 .gitignore")
        self.gitignore_check.setChecked(True)
        self.gitignore_check.toggled.connect(self._rules_edited)

        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(1, 1024 * 1024)
        self.max_size_spin.setSuffix(" KB")
        self.max_size_spin.setValue(1000)
        self.max_size_spin.valueChanged.connect(self._rules_edited)

        rules_box = QGroupBox("過濾規則(gitignore 語法,每行一條)")
        rules_layout = QVBoxLayout(rules_box)
        rules_layout.addWidget(QLabel("包含"))
        rules_layout.addWidget(self.include_edit)
        rules_layout.addWidget(QLabel("排除(優先於包含)"))
        rules_layout.addWidget(self.exclude_edit)
        rules_layout.addWidget(self.gitignore_check)
        size_form = QFormLayout()
        size_form.addRow("單檔大小上限", self.max_size_spin)
        rules_layout.addLayout(size_form)

        self.format_combo = QComboBox()
        for name in available_formats():
            self.format_combo.addItem(FORMAT_LABELS.get(name, name), name)
        self.tree_check = QCheckBox("開頭附目錄樹")
        self.tree_check.setChecked(True)
        self.tree_scope_combo = QComboBox()
        self.tree_scope_combo.addItem("只含選取的檔案", "selected")
        self.tree_scope_combo.addItem("整個專案", "all")
        self.format_combo.currentIndexChanged.connect(self._options_edited)
        self.tree_check.toggled.connect(self._options_edited)
        self.tree_check.toggled.connect(self.tree_scope_combo.setEnabled)
        self.tree_scope_combo.currentIndexChanged.connect(self._options_edited)

        output_box = QGroupBox("輸出選項")
        output_form = QFormLayout(output_box)
        output_form.addRow("格式", self.format_combo)
        output_form.addRow(self.tree_check)
        output_form.addRow("目錄樹範圍", self.tree_scope_combo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rules_box, 1)
        layout.addWidget(output_box)

        self._rules_timer = QTimer(self, singleShot=True, interval=RULES_DEBOUNCE_MS)
        self._rules_timer.timeout.connect(self.rulesChanged)

    # --- signals ----------------------------------------------------------

    def _rules_edited(self, *_):
        if not self._loading:
            self._rules_timer.start()

    def _options_edited(self, *_):
        if not self._loading:
            self.optionsChanged.emit()

    def flush(self) -> bool:
        """Fire a pending debounced rulesChanged now. Returns True if one was pending."""
        if self._rules_timer.isActive():
            self._rules_timer.stop()
            self.rulesChanged.emit()
            return True
        return False

    # --- values -----------------------------------------------------------

    def rules(self) -> RuleSet:
        return RuleSet(
            include=parse_rule_lines(self.include_edit.toPlainText()),
            exclude=parse_rule_lines(self.exclude_edit.toPlainText()),
            use_gitignore=self.gitignore_check.isChecked(),
            max_file_size=self.max_size_spin.value() * 1000,
        )

    def options(self, base: PackOptions | None = None) -> PackOptions:
        base = base or PackOptions()
        return PackOptions(
            format=self.format_combo.currentData(),
            include_tree=self.tree_check.isChecked(),
            tree_scope=self.tree_scope_combo.currentData(),
            preamble=base.preamble,
            transforms=list(base.transforms),
            max_tokens_per_part=base.max_tokens_per_part,
        )

    def load_preset(self, preset: Preset) -> None:
        """Fill the widgets from a preset without emitting change signals."""
        self._loading = True
        try:
            self.include_edit.setPlainText("\n".join(preset.rules.include))
            self.exclude_edit.setPlainText("\n".join(preset.rules.exclude))
            self.gitignore_check.setChecked(preset.rules.use_gitignore)
            self.max_size_spin.setValue(max(1, preset.rules.max_file_size // 1000))
            idx = self.format_combo.findData(preset.options.format)
            self.format_combo.setCurrentIndex(max(0, idx))
            self.tree_check.setChecked(preset.options.include_tree)
            idx = self.tree_scope_combo.findData(preset.options.tree_scope)
            self.tree_scope_combo.setCurrentIndex(max(0, idx))
        finally:
            self._loading = False
        self._rules_timer.stop()
