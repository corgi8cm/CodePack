"""Left column: searchable, checkable file tree."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from codepack.gui.file_tree_model import COL_NAME, COL_TOKENS, PATH_ROLE, FileTreeModel


class FileTreePanel(QWidget):
    depsRequested = Signal(str, bool)
    """(file, replace): select the file's dependencies."""

    def __init__(self, model: FileTreeModel, parent=None):
        super().__init__(parent)
        self.model = model

        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterRole(PATH_ROLE)
        self.proxy.setFilterKeyColumn(COL_NAME)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋檔案…")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self, singleShot=True, interval=200)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _: self._search_timer.start())

        self.view = QTreeView()
        self.view.setModel(self.proxy)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        header = self.view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_TOKENS, QHeaderView.ResizeMode.ResizeToContents)

        check_all = QPushButton("全選")
        check_none = QPushButton("全不選")
        expand = QPushButton("展開")
        collapse = QPushButton("收合")
        check_all.clicked.connect(lambda: model.set_all(True))
        check_none.clicked.connect(lambda: model.set_all(False))
        expand.clicked.connect(self.view.expandAll)
        collapse.clicked.connect(self.view.collapseAll)

        buttons = QHBoxLayout()
        for b in (check_all, check_none, expand, collapse):
            buttons.addWidget(b)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search)
        layout.addWidget(self.view)
        layout.addLayout(buttons)

        model.modelReset.connect(self._after_reset)

        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)

    def current_path(self) -> str | None:
        """Path of the highlighted file, or None if nothing / a directory is highlighted."""
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        rel = self.proxy.data(index, PATH_ROLE)
        scan = self.model.scan
        return rel if scan is not None and rel in scan.files else None

    def _context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        rel = self.current_path()
        if rel is None:
            return
        menu = QMenu(self)
        menu.addAction("只選取此檔案及其依賴", lambda: self.depsRequested.emit(rel, True))
        menu.addAction("把此檔案的依賴加入選取", lambda: self.depsRequested.emit(rel, False))
        menu.addSeparator()
        menu.addAction("只選取此檔案", lambda: self.model.select_files([rel], replace=True))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _apply_filter(self) -> None:
        text = self.search.text().strip()
        self.proxy.setFilterFixedString(text)
        if text:
            self.view.expandAll()

    def _after_reset(self) -> None:
        # Expand the first level so the project's layout is visible right away.
        for row in range(self.proxy.rowCount()):
            self.view.expand(self.proxy.index(row, 0))
        if self.search.text().strip():
            self.view.expandAll()
