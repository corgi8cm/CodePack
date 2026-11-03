"""Middle column: filter rules, output options and selection tools (git / dependencies)."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from codepack.core import PackOptions, Preset, RuleSet, available_formats, parse_rule_lines
from codepack.core.apply import REPLY_DIFF, REPLY_FILES, REPLY_NONE
from codepack.core.deps import DepOptions
from codepack.gui.labels import FORMAT_LABELS

RULES_DEBOUNCE_MS = 700


class RulesPanel(QWidget):
    rulesChanged = Signal()
    """Emitted (debounced) when anything affecting the scan changes."""
    optionsChanged = Signal()
    """Emitted when output options change."""
    gitSelectRequested = Signal()
    depsSelectRequested = Signal(bool)
    """True = select only the current file and its dependencies; False = add them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._base_options = PackOptions()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_rules_tab(mono), "過濾規則")
        self.tabs.addTab(self._build_output_tab(), "輸出")
        self.tabs.addTab(self._build_tools_tab(), "選取工具")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        self._rules_timer = QTimer(self, singleShot=True, interval=RULES_DEBOUNCE_MS)
        self._rules_timer.timeout.connect(self.rulesChanged)

    # --- tabs -------------------------------------------------------------

    def _build_rules_tab(self, mono) -> QWidget:
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

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("包含(gitignore 語法,每行一條)"))
        layout.addWidget(self.include_edit)
        layout.addWidget(QLabel("排除(優先於包含)"))
        layout.addWidget(self.exclude_edit)
        layout.addWidget(self.gitignore_check)
        form = QFormLayout()
        form.addRow("單檔大小上限", self.max_size_spin)
        layout.addLayout(form)
        return tab

    def _build_output_tab(self) -> QWidget:
        self.format_combo = QComboBox()
        for name in available_formats():
            self.format_combo.addItem(FORMAT_LABELS.get(name, name), name)
        self.tree_check = QCheckBox("開頭附目錄樹")
        self.tree_check.setChecked(True)
        self.tree_scope_combo = QComboBox()
        self.tree_scope_combo.addItem("只含選取的檔案", "selected")
        self.tree_scope_combo.addItem("整個專案", "all")
        self.mask_check = QCheckBox("遮罩機密(API key、密碼、私鑰、內部 IP)")
        self.mask_check.setChecked(True)
        self.reply_combo = QComboBox()
        self.reply_combo.addItem("不指定", REPLY_NONE)
        self.reply_combo.addItem("完整檔案(=== FILE ===)", REPLY_FILES)
        self.reply_combo.addItem("Unified diff", REPLY_DIFF)
        self.reply_combo.setToolTip("在輸出結尾要求 AI 用這個格式回答，之後可用「套用回答」寫回專案")
        self.git_diff_check = QCheckBox("附上 git diff(比較對象見「選取工具」)")
        self.preamble_edit = QPlainTextEdit()
        self.preamble_edit.setPlaceholderText("前置提示詞，例如:請幫我找出記憶體洩漏")
        self.preamble_edit.setMaximumHeight(120)

        self.format_combo.currentIndexChanged.connect(self._options_edited)
        self.tree_check.toggled.connect(self._options_edited)
        self.tree_check.toggled.connect(self.tree_scope_combo.setEnabled)
        self.tree_scope_combo.currentIndexChanged.connect(self._options_edited)
        self.mask_check.toggled.connect(self._options_edited)
        self.reply_combo.currentIndexChanged.connect(self._options_edited)
        self.git_diff_check.toggled.connect(self._options_edited)
        self.preamble_edit.textChanged.connect(self._options_edited)

        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow("格式", self.format_combo)
        form.addRow(self.tree_check)
        form.addRow("目錄樹範圍", self.tree_scope_combo)
        form.addRow(self.mask_check)
        form.addRow("要求回答格式", self.reply_combo)
        form.addRow(self.git_diff_check)
        form.addRow(QLabel("前置提示詞"))
        form.addRow(self.preamble_edit)
        return tab

    def _build_tools_tab(self) -> QWidget:
        self.git_base_edit = QLineEdit()
        self.git_base_edit.setPlaceholderText("留空 = 與 HEAD 比較;例如 main")
        self.git_staged_check = QCheckBox("只看已暫存(staged)的變更")
        self.git_select_button = QPushButton("只選取 git 變更的檔案")
        self.git_select_button.clicked.connect(self.gitSelectRequested)
        self.git_base_edit.textChanged.connect(self._options_edited)
        self.git_staged_check.toggled.connect(self._options_edited)

        git_box = QGroupBox("Git")
        git_form = QFormLayout(git_box)
        git_form.addRow("比較對象", self.git_base_edit)
        git_form.addRow(self.git_staged_check)
        git_form.addRow(self.git_select_button)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(0, 50)
        self.depth_spin.setSpecialValueText("不限")
        self.pair_check = QCheckBox("標頭檔連帶加入對應的 .cpp")
        self.follow_excluded_check = QCheckBox("也加入被規則排除的依賴")
        self.include_dirs_edit = QLineEdit()
        self.include_dirs_edit.setPlaceholderText("額外 include 目錄，以 ; 分隔(會自動讀 compile_commands.json)")
        deps_only = QPushButton("只選取目前檔案及其依賴")
        deps_add = QPushButton("把目前檔案的依賴加入選取")
        deps_only.clicked.connect(lambda: self.depsSelectRequested.emit(True))
        deps_add.clicked.connect(lambda: self.depsSelectRequested.emit(False))

        deps_box = QGroupBox("依賴追蹤(Python import / C++ #include)")
        deps_form = QFormLayout(deps_box)
        deps_form.addRow("追蹤層數", self.depth_spin)
        deps_form.addRow(self.pair_check)
        deps_form.addRow(self.follow_excluded_check)
        deps_form.addRow("Include 目錄", self.include_dirs_edit)
        deps_form.addRow(QLabel("先在左側檔案樹點選目標檔(也可按右鍵)"))
        deps_form.addRow(deps_only)
        deps_form.addRow(deps_add)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(git_box)
        layout.addWidget(deps_box)
        layout.addStretch()
        return tab

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

    def options(self) -> PackOptions:
        base = self._base_options
        return PackOptions(
            format=self.format_combo.currentData(),
            include_tree=self.tree_check.isChecked(),
            tree_scope=self.tree_scope_combo.currentData(),
            preamble=self.preamble_edit.toPlainText(),
            mask_secrets=self.mask_check.isChecked(),
            reply_format=self.reply_combo.currentData(),
            git_diff=self.git_diff_check.isChecked(),
            git_base=self.git_base_edit.text().strip(),
            git_staged=self.git_staged_check.isChecked(),
            transforms=list(base.transforms),
            max_tokens_per_part=base.max_tokens_per_part,
        )

    def dep_options(self) -> DepOptions:
        dirs = [d.strip() for d in self.include_dirs_edit.text().replace(",", ";").split(";") if d.strip()]
        return DepOptions(
            max_depth=self.depth_spin.value() or None,
            pair_sources=self.pair_check.isChecked(),
            follow_excluded=self.follow_excluded_check.isChecked(),
            include_dirs=dirs,
        )

    def load_preset(self, preset: Preset) -> None:
        """Fill the widgets from a preset without emitting change signals."""
        self._loading = True
        self._base_options = preset.options
        opts = preset.options
        try:
            self.include_edit.setPlainText("\n".join(preset.rules.include))
            self.exclude_edit.setPlainText("\n".join(preset.rules.exclude))
            self.gitignore_check.setChecked(preset.rules.use_gitignore)
            self.max_size_spin.setValue(max(1, preset.rules.max_file_size // 1000))
            self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(opts.format)))
            self.tree_check.setChecked(opts.include_tree)
            self.tree_scope_combo.setCurrentIndex(max(0, self.tree_scope_combo.findData(opts.tree_scope)))
            self.mask_check.setChecked(opts.mask_secrets)
            self.reply_combo.setCurrentIndex(max(0, self.reply_combo.findData(opts.reply_format)))
            self.git_diff_check.setChecked(opts.git_diff)
            self.git_base_edit.setText(opts.git_base)
            self.git_staged_check.setChecked(opts.git_staged)
            self.preamble_edit.setPlainText(opts.preamble)
        finally:
            self._loading = False
        self._rules_timer.stop()
