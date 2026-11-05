"""Main window: toolbar + three columns + status bar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QSplitter,
    QToolBar,
    QToolButton,
    QWidget,
)
from PySide6.QtGui import QGuiApplication

from codepack.core import (
    PackOptions,
    PackResult,
    Preset,
    RuleSet,
    ScanResult,
    Selection,
    all_presets,
    get_formatter,
    save_preset,
    user_preset_dir,
)
from codepack.core.collectors.git import GitError, changed_files
from codepack.core.deps import resolve_dependencies
from codepack.core.preset import preset_filename
from codepack.core.projects import ProjectList, load_projects, normalize_path, save_projects
from codepack.core.prompts import all_templates, find_template
from codepack.gui.apply_dialog import ApplyDialog
from codepack.gui.file_tree_model import FileTreeModel
from codepack.gui.file_tree_panel import FileTreePanel
from codepack.gui.labels import format_size
from codepack.gui.preview_panel import PreviewPanel
from codepack.gui.prompt_dialog import PromptTemplateDialog
from codepack.gui.rules_panel import RulesPanel
from codepack.gui.workers import PackJob, ScanJob

SETTINGS_ORG = "CodePack"
SETTINGS_APP = "CodePack"


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: QSettings | None = None,
        preset_dir: Path | None = None,
        projects_file: Path | None = None,
    ):
        super().__init__()
        self.setWindowTitle("CodePack")
        self.resize(1400, 850)
        self.settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.preset_dir = preset_dir or user_preset_dir()
        self.projects_file = projects_file
        self.projects: ProjectList = load_projects(projects_file)
        self._root: Path | None = None
        self._pending_overrides: tuple[str, list[str], list[str]] | None = None
        self.pool = QThreadPool.globalInstance()

        self._scan_job: ScanJob | None = None
        self._job_counter = 0
        self._active_scan_id = -1
        self._active_pack_id = -1
        self._pack_after_scan = False
        self._presets: list[Preset] = []

        self._build_toolbar()

        self.tree_model = FileTreeModel(self)
        self.tree_panel = FileTreePanel(self.tree_model)
        self.rules_panel = RulesPanel()
        self.preview_panel = PreviewPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree_panel)
        splitter.addWidget(self.rules_panel)
        splitter.addWidget(self.preview_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([420, 300, 680])
        self.setCentralWidget(splitter)
        self.splitter = splitter

        self.status_files = QLabel()
        self.status_size = QLabel()
        self.status_message = QLabel()
        self.statusBar().addWidget(self.status_message, 1)
        self.statusBar().addPermanentWidget(self.status_files)
        self.statusBar().addPermanentWidget(self.status_size)

        self.tree_model.selectionChanged.connect(self._on_selection_changed)
        self.rules_panel.rulesChanged.connect(self.rescan)
        self.rules_panel.optionsChanged.connect(self._mark_stale)
        self.preview_panel.saveRequested.connect(self.save_output)
        self.rules_panel.gitSelectRequested.connect(self.select_git_changes)
        self.rules_panel.depsSelectRequested.connect(self._deps_for_current)
        self.tree_panel.depsRequested.connect(self.select_dependencies)
        self.apply_dialog: ApplyDialog | None = None

        self._reload_presets(self.settings.value("preset", "default"))
        self._update_status()
        self._restore_state()

    # --- layout -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("main")
        bar.setMovable(False)
        self.addToolBar(bar)

        # Project list: switch between several project folders; each one
        # remembers its own preset, rules and checked files.
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(220)
        self.project_combo.setPlaceholderText("尚未加入專案")
        self.project_combo.activated.connect(self._project_selected)
        browse = QPushButton("加入專案…")
        browse.setToolTip("選一個資料夾加入專案清單並切換過去")
        browse.clicked.connect(self.browse)
        self.project_menu_button = QToolButton()
        self.project_menu_button.setText("⋯")
        self.project_menu_button.setToolTip("管理專案清單")
        self.project_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_menu = QMenu(self.project_menu_button)
        self.project_menu.aboutToShow.connect(self._rebuild_project_menu)
        self.project_menu_button.setMenu(self.project_menu)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(140)
        self.preset_combo.activated.connect(self._preset_selected)
        save_preset_button = QPushButton("儲存設定檔…")
        save_preset_button.clicked.connect(self.save_current_preset)

        self.rescan_button = QPushButton("重新掃描")
        self.rescan_button.clicked.connect(self.rescan)
        self.pack_button = QPushButton("打包")
        self.pack_button.setDefault(True)
        self.pack_button.setStyleSheet("font-weight: bold; padding: 4px 16px;")
        self.pack_button.clicked.connect(self.pack)
        self.apply_button = QPushButton("套用回答…")
        self.apply_button.setToolTip("把 AI 的回答(完整檔案或 diff)預覽後寫回專案，寫入前自動備份")
        self.apply_button.clicked.connect(self.open_apply_dialog)

        # Button copies the last used template; its arrow menu lists all of them.
        self.prompt_button = QToolButton()
        self.prompt_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.prompt_button.setText("複製提問模板")
        self.prompt_button.clicked.connect(lambda: self.copy_prompt(self.current_prompt_name()))
        self.prompt_menu = QMenu(self.prompt_button)
        self.prompt_menu.aboutToShow.connect(self._rebuild_prompt_menu)
        self.prompt_button.setMenu(self.prompt_menu)
        self.prompt_dialog: PromptTemplateDialog | None = None

        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 2, 4, 2)
        row.addWidget(QLabel("專案"))
        row.addWidget(self.project_combo, 1)
        row.addWidget(browse)
        row.addWidget(self.project_menu_button)
        row.addSpacing(12)
        row.addWidget(QLabel("設定檔"))
        row.addWidget(self.preset_combo)
        row.addWidget(save_preset_button)
        row.addSpacing(12)
        row.addWidget(self.rescan_button)
        row.addWidget(self.pack_button)
        row.addWidget(self.prompt_button)
        row.addWidget(self.apply_button)
        bar.addWidget(container)
        self._update_prompt_tooltip()

    def _restore_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        sizes = self.settings.value("splitter")
        if sizes is not None:
            self.splitter.restoreState(sizes)
        last = self.settings.value("last_project", "")
        if not self.projects.projects and last and Path(last).is_dir():
            self.projects.add(last)  # carry over the single project of older versions
            self.projects.current = normalize_path(last)
        self._refresh_project_combo()
        current = self.projects.current_entry()
        if current is not None and Path(current.path).is_dir():
            self.open_project(Path(current.path))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self._store_project_state()
        self._save_projects()
        if self._scan_job is not None:
            self._scan_job.cancel()
        super().closeEvent(event)

    # --- presets ----------------------------------------------------------

    def _reload_presets(self, select: str | None = None) -> None:
        self._presets = all_presets(self.preset_dir)
        self.preset_combo.clear()
        for p in self._presets:
            self.preset_combo.addItem(p.name if p.builtin else f"{p.name}(自訂)", p.name)
            self.preset_combo.setItemData(self.preset_combo.count() - 1, p.description, Qt.ItemDataRole.ToolTipRole)
        idx = max(0, self.preset_combo.findData(select)) if select else 0
        self.preset_combo.setCurrentIndex(idx)
        if self._presets:
            self._apply_preset(self._presets[idx])

    def _apply_preset(self, preset: Preset) -> None:
        self.rules_panel.load_preset(preset)
        self.settings.setValue("preset", preset.name)

    def _preset_selected(self, index: int) -> None:
        if 0 <= index < len(self._presets):
            self._apply_preset(self._presets[index])
            self.rescan()

    def current_preset(self, name: str) -> Preset:
        return Preset(name, self.rules_panel.rules(), self.rules_panel.options())

    def save_current_preset(self) -> None:
        current = self.preset_combo.currentData() or "my-preset"
        name, ok = QInputDialog.getText(self, "儲存設定檔", "設定檔名稱:", text=current)
        name = name.strip()
        if not ok or not name:
            return
        path = self.preset_dir / preset_filename(name)
        try:
            save_preset(self.current_preset(name), path)
        except OSError as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc))
            return
        self._reload_presets(name)
        self.status_message.setText(f"已儲存設定檔:{path}")

    # --- project & scanning -----------------------------------------------

    # --- project list -----------------------------------------------------

    def browse(self) -> None:
        start = str(self._root.parent) if self._root else self.settings.value("last_project", "")
        folder = QFileDialog.getExistingDirectory(self, "加入專案資料夾", start)
        if folder:
            self.open_project(Path(folder))

    def _save_projects(self) -> None:
        try:
            save_projects(self.projects, self.projects_file)
        except OSError as exc:
            self.status_message.setText(f"無法儲存專案清單:{exc}")

    def _refresh_project_combo(self) -> None:
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for p in self.projects.projects:
            self.project_combo.addItem(p.display_name, p.path)
            self.project_combo.setItemData(self.project_combo.count() - 1, p.path, Qt.ItemDataRole.ToolTipRole)
        current = self.projects.current_entry()
        self.project_combo.setCurrentIndex(self.projects.projects.index(current) if current else -1)
        self.project_combo.setToolTip(current.path if current else "")
        self.project_combo.blockSignals(False)

    def _project_selected(self, index: int) -> None:
        path = self.project_combo.itemData(index)
        if not path:
            return
        if self._root is not None and normalize_path(self._root) == normalize_path(path):
            return
        if not Path(path).is_dir():
            answer = QMessageBox.question(
                self, "找不到資料夾", f"資料夾已不存在:\n{path}\n\n要把它從專案清單移除嗎?"
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.projects.remove(path)
                self._save_projects()
            self._refresh_project_combo()
            return
        self.open_project(Path(path))

    def _rebuild_project_menu(self) -> None:
        menu = self.project_menu
        menu.clear()
        current = self.projects.current_entry()
        for label, slot in (
            ("重新命名…", self.rename_current_project),
            ("往上移", lambda: self._move_current_project(-1)),
            ("往下移", lambda: self._move_current_project(1)),
            ("從清單移除", self.remove_current_project),
        ):
            menu.addAction(label, slot).setEnabled(current is not None)

    def rename_current_project(self) -> None:
        entry = self.projects.current_entry()
        if entry is None:
            return
        name, ok = QInputDialog.getText(self, "重新命名專案", "顯示名稱(留空 = 資料夾名稱):", text=entry.name)
        if not ok:
            return
        entry.name = name.strip()
        self._save_projects()
        self._refresh_project_combo()
        self._update_title()

    def _move_current_project(self, offset: int) -> None:
        if self.projects.current:
            self.projects.move(self.projects.current, offset)
            self._save_projects()
            self._refresh_project_combo()

    def remove_current_project(self) -> None:
        """Remove the open project from the list (the folder itself is untouched)."""
        entry = self.projects.current_entry()
        if entry is None:
            return
        question = f"要把「{entry.display_name}」從專案清單移除嗎?\n(只會移出清單，不會刪除任何檔案)"
        if QMessageBox.question(self, "專案清單", question) != QMessageBox.StandardButton.Yes:
            return
        self.projects.remove(entry.path)
        self._save_projects()
        self._close_project()
        self._refresh_project_combo()

    def _store_project_state(self) -> None:
        """Remember the open project's preset, rules and check overrides."""
        if self._root is None:
            return
        entry = self.projects.find(self._root)
        if entry is None:
            return
        entry.preset = self.preset_combo.currentData() or ""
        entry.rules = self.rules_panel.rules().to_dict()
        entry.options = self.rules_panel.options().to_dict()
        selection = self.tree_model.selection
        if selection is not None and normalize_path(selection.scan.root) == normalize_path(self._root):
            entry.forced_on = sorted(selection.forced_on)
            entry.forced_off = sorted(selection.forced_off)

    def _restore_project_settings(self, preset_name: str, rules: dict | None, options: dict | None) -> None:
        preset = next((p for p in self._presets if p.name == preset_name), None)
        if preset is not None:
            self.preset_combo.setCurrentIndex(self._presets.index(preset))
        if rules is not None or options is not None:
            base = preset or self.current_preset(preset_name)
            self.rules_panel.load_preset(
                Preset(
                    base.name,
                    RuleSet.from_dict(rules) if rules is not None else base.rules,
                    PackOptions.from_dict(options) if options is not None else base.options,
                )
            )
        elif preset is not None:
            self._apply_preset(preset)
        # Otherwise (a newly added project) keep the settings currently shown.

    def _close_project(self) -> None:
        if self._scan_job is not None:
            self._scan_job.cancel()
            self._scan_job = None
        self._active_scan_id = -1
        self._active_pack_id = -1
        self._pack_after_scan = False
        self._root = None
        self.rescan_button.setEnabled(True)
        self.pack_button.setEnabled(True)
        self.tree_model.set_scan(None, None)
        self.preview_panel.set_result(None)
        self._update_status()
        self._update_title()

    def _update_title(self) -> None:
        entry = self.projects.find(self._root) if self._root else None
        self.setWindowTitle(f"{entry.display_name} - CodePack" if entry else "CodePack")

    def open_project(self, path: Path) -> None:
        """Switch to ``path``, adding it to the project list if needed."""
        path = path.resolve()
        if self._root is not None and normalize_path(self._root) == normalize_path(path):
            self.rescan()
            return
        self._store_project_state()
        entry = self.projects.add(path)
        self.projects.current = entry.path
        self._save_projects()
        self.settings.setValue("last_project", str(path))
        self._close_project()
        self._root = path
        self._restore_project_settings(entry.preset, entry.rules, entry.options)
        self._pending_overrides = (entry.path, list(entry.forced_on), list(entry.forced_off))
        self._refresh_project_combo()
        self._update_title()
        self.rescan()

    def project_root(self) -> Path | None:
        return self._root

    def rescan(self) -> None:
        root = self.project_root()
        if root is None or not root.is_dir():
            return
        if self._scan_job is not None:
            self._scan_job.cancel()
        self._job_counter += 1
        job = ScanJob(self._job_counter, root, self.rules_panel.rules())
        job.signals.progress.connect(lambda n, rel: self.status_message.setText(f"掃描中… {n} 個檔案  {rel}"))
        job.signals.finished.connect(self._scan_finished)
        job.signals.failed.connect(self._scan_failed)
        self._active_scan_id = job.job_id
        self._scan_job = job
        self.status_message.setText("掃描中…")
        self.rescan_button.setEnabled(False)
        self.pool.start(job)

    def _scan_finished(self, job_id: int, scan: ScanResult) -> None:
        if job_id != self._active_scan_id:
            return
        self._scan_job = None
        self.rescan_button.setEnabled(True)
        old = self.tree_model.selection
        pending, self._pending_overrides = self._pending_overrides, None
        if old is not None and old.scan.root == scan.root:
            selection = old.carry_over(scan)
        elif pending is not None and normalize_path(scan.root) == normalize_path(pending[0]):
            selection = Selection(scan, pending[1], pending[2])  # restore this project's checks
        else:
            selection = Selection(scan)
        self.tree_model.set_scan(scan, selection)
        self.status_message.setText("掃描完成")
        self._on_selection_changed()
        if self._pack_after_scan:
            self._pack_after_scan = False
            self.pack()

    def _scan_failed(self, job_id: int, message: str) -> None:
        if job_id != self._active_scan_id:
            return
        self._scan_job = None
        self._pack_after_scan = False
        self.rescan_button.setEnabled(True)
        self.status_message.setText("掃描失敗")
        QMessageBox.warning(self, "掃描失敗", message)

    # --- selection & packing ----------------------------------------------

    def _on_selection_changed(self) -> None:
        selection = self.tree_model.selection
        self.preview_panel.set_estimate(selection.checked_tokens() if selection else 0)
        self._mark_stale()
        self._update_status()

    def _mark_stale(self) -> None:
        self.preview_panel.set_stale(True)

    def _update_status(self) -> None:
        scan = self.tree_model.scan
        selection = self.tree_model.selection
        if scan is None or selection is None:
            self.status_files.setText("尚未開啟專案")
            self.status_size.setText("")
            return
        checked = selection.checked_files()
        checked_size = sum(scan.files[f].size for f in checked)
        self.status_files.setText(f"已選 {len(checked):,} / 共 {len(scan.files):,} 個檔案")
        self.status_size.setText(f"已選 {format_size(checked_size)} / 總大小 {format_size(scan.total_size)}")

    def pack(self) -> None:
        if self.rules_panel.flush():
            # Rules were edited but not yet applied: rescan first, then pack.
            self._pack_after_scan = True
            return
        if self._scan_job is not None:
            self._pack_after_scan = True
            return
        scan = self.tree_model.scan
        selection = self.tree_model.selection
        if scan is None or selection is None:
            QMessageBox.information(self, "CodePack", "請先選擇專案資料夾。")
            return
        files = selection.checked_files()
        if not files:
            QMessageBox.information(self, "CodePack", "沒有勾選任何檔案。")
            return
        self._job_counter += 1
        job = PackJob(self._job_counter, scan, files, self.rules_panel.options())
        job.signals.finished.connect(self._pack_finished)
        job.signals.failed.connect(self._pack_failed)
        self._active_pack_id = job.job_id
        self.pack_button.setEnabled(False)
        self.status_message.setText("打包中…")
        self.pool.start(job)

    def _pack_finished(self, job_id: int, result: PackResult) -> None:
        if job_id != self._active_pack_id:
            return
        self.pack_button.setEnabled(True)
        self.preview_panel.set_result(result)
        msg = f"打包完成:{len(result.files)} 個檔案,約 {result.total_tokens:,} tokens"
        if result.warnings:
            msg += f"({len(result.warnings)} 個警告)"
            QMessageBox.warning(self, "打包警告", "\n".join(result.warnings[:30]))
        self.status_message.setText(msg)

    def _pack_failed(self, job_id: int, message: str) -> None:
        if job_id != self._active_pack_id:
            return
        self.pack_button.setEnabled(True)
        self.status_message.setText("打包失敗")
        QMessageBox.warning(self, "打包失敗", message)

    # --- selection tools --------------------------------------------------

    def select_git_changes(self) -> None:
        scan = self.tree_model.scan
        if scan is None:
            QMessageBox.information(self, "CodePack", "請先選擇專案資料夾。")
            return
        opts = self.rules_panel.options()
        try:
            files = changed_files(scan.root, opts.git_base, opts.git_staged)
        except GitError as exc:
            QMessageBox.warning(self, "Git", str(exc))
            return
        in_scan = [f for f in files if f in scan.files]
        rejected = self.tree_model.select_files(in_scan, replace=True)
        msg = f"Git:已選取 {len(in_scan) - len(rejected)} 個變更的檔案"
        if len(files) > len(in_scan):
            msg += f"({len(files) - len(in_scan)} 個在被忽略的資料夾內)"
        self.status_message.setText(msg)
        if not in_scan:
            QMessageBox.information(self, "Git", "沒有找到變更的檔案。")

    def _deps_for_current(self, replace: bool) -> None:
        rel = self.tree_panel.current_path()
        if rel is None:
            QMessageBox.information(self, "依賴追蹤", "請先在左側檔案樹點選一個檔案。")
            return
        self.select_dependencies(rel, replace)

    def select_dependencies(self, rel: str, replace: bool) -> None:
        scan = self.tree_model.scan
        if scan is None:
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            result = resolve_dependencies(scan, [rel], self.rules_panel.dep_options())
        finally:
            self.unsetCursor()
        rejected = self.tree_model.select_files(result.files, replace=replace)
        msg = f"依賴:{rel} → {len(result.files) - len(rejected)} 個檔案"
        if result.skipped:
            msg += f",{len(result.skipped)} 個被規則排除未加入"
        self.status_message.setText(msg)
        if result.skipped:
            self.status_message.setToolTip("被排除的依賴:\n" + "\n".join(sorted(result.skipped)))

    # --- question templates ---------------------------------------------

    def current_prompt_name(self) -> str:
        names = [t.name for t in all_templates()]
        saved = self.settings.value("prompt_template", "")
        return saved if saved in names else (names[0] if names else "")

    def _update_prompt_tooltip(self) -> None:
        self.prompt_button.setToolTip(
            f"複製「{self.current_prompt_name()}」到剪貼簿，貼到 Gemini 後修改問題\n按右邊的 ▾ 可以選其他模板或編輯"
        )

    def _rebuild_prompt_menu(self) -> None:
        self.prompt_menu.clear()
        current = self.current_prompt_name()
        for t in all_templates():
            action = self.prompt_menu.addAction(t.name, lambda name=t.name: self.copy_prompt(name))
            action.setCheckable(True)
            action.setChecked(t.name == current)
            action.setToolTip(t.text)
        self.prompt_menu.setToolTipsVisible(True)
        self.prompt_menu.addSeparator()
        self.prompt_menu.addAction("管理模板…", self.open_prompt_dialog)

    def copy_prompt(self, name: str) -> None:
        try:
            template = find_template(name)
        except KeyError:
            return
        QGuiApplication.clipboard().setText(template.text)
        self.settings.setValue("prompt_template", template.name)
        self._update_prompt_tooltip()
        self.status_message.setText(f"已複製提問模板「{template.name}」,貼到 Gemini 後把問題改成你的內容")

    def open_prompt_dialog(self) -> None:
        if self.prompt_dialog is None:
            self.prompt_dialog = PromptTemplateDialog(select=self.current_prompt_name(), parent=self)
            self.prompt_dialog.copied.connect(self._prompt_copied_in_dialog)
            self.prompt_dialog.templatesChanged.connect(self._update_prompt_tooltip)
        else:
            self.prompt_dialog.reload(self.current_prompt_name())
        self.prompt_dialog.show()
        self.prompt_dialog.raise_()
        self.prompt_dialog.activateWindow()

    def _prompt_copied_in_dialog(self, name: str) -> None:
        self.settings.setValue("prompt_template", name)
        self._update_prompt_tooltip()
        self.status_message.setText(f"已複製提問模板「{name}」")

    # --- apply back ------------------------------------------------------

    def open_apply_dialog(self) -> None:
        root = self.project_root()
        if root is None or not root.is_dir():
            QMessageBox.information(self, "CodePack", "請先選擇專案資料夾。")
            return
        if self.apply_dialog is None or self.apply_dialog.root != root:
            self.apply_dialog = ApplyDialog(root, self)
            self.apply_dialog.applied.connect(self.rescan)
        self.apply_dialog.show()
        self.apply_dialog.raise_()
        self.apply_dialog.activateWindow()

    def save_output(self) -> None:
        result = self.preview_panel.result
        scan = self.tree_model.scan
        if result is None or scan is None:
            return
        formatter = get_formatter(self.rules_panel.options().format)
        default_dir = self.settings.value("last_save_dir", str(scan.root.parent))
        default = str(Path(default_dir) / f"{scan.project_name}_codepack{formatter.extension}")
        filters = "Markdown (*.md);;XML (*.xml);;純文字 (*.txt);;所有檔案 (*)"
        path, _ = QFileDialog.getSaveFileName(self, "另存檔案", default, filters)
        if not path:
            return
        try:
            Path(path).write_text(result.text, encoding="utf-8", newline="\n")
        except OSError as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc))
            return
        self.settings.setValue("last_save_dir", str(Path(path).parent))
        self.status_message.setText(f"已儲存:{path}")
