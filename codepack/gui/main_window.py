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
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QWidget,
)

from codepack.core import (
    PackOptions,
    PackResult,
    Preset,
    ScanResult,
    Selection,
    all_presets,
    get_formatter,
    save_preset,
    user_preset_dir,
)
from codepack.core.preset import preset_filename
from codepack.gui.file_tree_model import FileTreeModel
from codepack.gui.file_tree_panel import FileTreePanel
from codepack.gui.labels import format_size
from codepack.gui.preview_panel import PreviewPanel
from codepack.gui.rules_panel import RulesPanel
from codepack.gui.workers import PackJob, ScanJob

SETTINGS_ORG = "CodePack"
SETTINGS_APP = "CodePack"


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, preset_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle("CodePack")
        self.resize(1400, 850)
        self.settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.preset_dir = preset_dir or user_preset_dir()
        self.pool = QThreadPool.globalInstance()

        self._scan_job: ScanJob | None = None
        self._job_counter = 0
        self._active_scan_id = -1
        self._active_pack_id = -1
        self._pack_after_scan = False
        self._presets: list[Preset] = []
        self._base_options = PackOptions()

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

        self._reload_presets(self.settings.value("preset", "default"))
        self._update_status()
        self._restore_state()

    # --- layout -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("main")
        bar.setMovable(False)
        self.addToolBar(bar)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("專案資料夾路徑")
        self.path_edit.returnPressed.connect(self._path_entered)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self.browse)

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

        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 2, 4, 2)
        row.addWidget(QLabel("專案"))
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        row.addSpacing(12)
        row.addWidget(QLabel("設定檔"))
        row.addWidget(self.preset_combo)
        row.addWidget(save_preset_button)
        row.addSpacing(12)
        row.addWidget(self.rescan_button)
        row.addWidget(self.pack_button)
        bar.addWidget(container)

    def _restore_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        sizes = self.settings.value("splitter")
        if sizes is not None:
            self.splitter.restoreState(sizes)
        last = self.settings.value("last_project", "")
        if last and Path(last).is_dir():
            self.open_project(Path(last))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
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
        self._base_options = preset.options
        self.rules_panel.load_preset(preset)
        self.settings.setValue("preset", preset.name)

    def _preset_selected(self, index: int) -> None:
        if 0 <= index < len(self._presets):
            self._apply_preset(self._presets[index])
            self.rescan()

    def current_preset(self, name: str) -> Preset:
        return Preset(name, self.rules_panel.rules(), self.rules_panel.options(self._base_options))

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

    def browse(self) -> None:
        start = self.path_edit.text() or self.settings.value("last_project", "")
        folder = QFileDialog.getExistingDirectory(self, "選擇專案資料夾", start)
        if folder:
            self.open_project(Path(folder))

    def _path_entered(self) -> None:
        path = Path(self.path_edit.text().strip())
        if path.is_dir():
            self.open_project(path)
        else:
            QMessageBox.warning(self, "找不到資料夾", f"不是有效的資料夾:\n{path}")

    def open_project(self, path: Path) -> None:
        path = path.resolve()
        self.path_edit.setText(str(path))
        self.settings.setValue("last_project", str(path))
        self.tree_model.set_scan(None, None)
        self.preview_panel.set_result(None)
        self.rescan()

    def project_root(self) -> Path | None:
        text = self.path_edit.text().strip()
        return Path(text).resolve() if text else None

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
        if old is not None and old.scan.root == scan.root:
            selection = old.carry_over(scan)
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
        job = PackJob(self._job_counter, scan, files, self.rules_panel.options(self._base_options))
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
