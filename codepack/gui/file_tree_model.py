"""Qt item model over a core ScanResult + Selection."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyle

from codepack.core import CheckState, ScanResult, Selection
from codepack.core.models import parent_of
from codepack.gui.labels import REASON_LABELS

PATH_ROLE = Qt.ItemDataRole.UserRole + 1

COL_NAME = 0
COL_TOKENS = 1

_QT_STATE = {
    CheckState.CHECKED: Qt.CheckState.Checked,
    CheckState.PARTIAL: Qt.CheckState.PartiallyChecked,
    CheckState.UNCHECKED: Qt.CheckState.Unchecked,
}

Index = QModelIndex | QPersistentModelIndex


class FileTreeModel(QAbstractItemModel):
    selectionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scan: ScanResult | None = None
        self._selection: Selection | None = None
        self._ids: dict[str, int] = {}
        self._paths: list[str] = []
        self._dir_tokens: dict[str, int] = {}
        style = QApplication.style()
        self._dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._gray = QBrush(QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))

    # --- data source ------------------------------------------------------

    def set_scan(self, scan: ScanResult | None, selection: Selection | None) -> None:
        self.beginResetModel()
        self._scan = scan
        self._selection = selection
        self._ids = {}
        self._paths = []
        self._dir_tokens = {}
        if scan is not None:
            for rel in [*scan.dirs, *scan.files]:
                self._ids[rel] = len(self._paths)
                self._paths.append(rel)
        self.endResetModel()

    @property
    def scan(self) -> ScanResult | None:
        return self._scan

    @property
    def selection(self) -> Selection | None:
        return self._selection

    def path_of(self, index: Index) -> str:
        if not index.isValid():
            return ""
        return self._paths[index.internalId()]

    def index_of(self, rel: str, column: int = 0) -> QModelIndex:
        if self._scan is None or not rel or rel not in self._ids:
            return QModelIndex()
        siblings = self._scan.children(parent_of(rel))
        return self.createIndex(siblings.index(rel), column, self._ids[rel])

    # --- structure --------------------------------------------------------

    def index(self, row: int, column: int, parent: Index = QModelIndex()) -> QModelIndex:
        if self._scan is None:
            return QModelIndex()
        children = self._scan.children(self.path_of(parent))
        if not (0 <= row < len(children)) or not (0 <= column < 2):
            return QModelIndex()
        return self.createIndex(row, column, self._ids[children[row]])

    def parent(self, index: Index = QModelIndex()) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        return self.index_of(parent_of(self.path_of(index)))

    def rowCount(self, parent: Index = QModelIndex()) -> int:
        if self._scan is None or parent.column() > 0:
            return 0
        rel = self.path_of(parent)
        if parent.isValid() and rel not in self._scan.dirs:
            return 0
        return len(self._scan.children(rel))

    def columnCount(self, parent: Index = QModelIndex()) -> int:
        return 2

    def hasChildren(self, parent: Index = QModelIndex()) -> bool:
        return self.rowCount(parent) > 0

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("名稱", "Tokens")[section]
        return None

    # --- data -------------------------------------------------------------

    def _checked_tokens_under(self, dir_rel: str) -> int:
        cached = self._dir_tokens.get(dir_rel)
        if cached is None:
            assert self._scan is not None and self._selection is not None
            cached = sum(
                self._scan.files[f].tokens for f in self._scan.files_under(dir_rel) if self._selection.is_checked(f)
            )
            self._dir_tokens[dir_rel] = cached
        return cached

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self._scan is None or self._selection is None:
            return None
        rel = self.path_of(index)
        is_dir = rel in self._scan.dirs
        file = None if is_dir else self._scan.files[rel]
        reason = self._scan.dirs[rel].pruned if is_dir else file.excluded  # type: ignore[union-attr]
        col = index.column()

        if role == PATH_ROLE:
            return rel
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return self._scan.dirs[rel].name if is_dir else file.name  # type: ignore[union-attr]
            if is_dir:
                if reason is not None:
                    return ""
                tokens = self._checked_tokens_under(rel)
                return f"{tokens:,}" if tokens else ""
            return f"{file.tokens:,}" if file.tokens else ""  # type: ignore[union-attr]
        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_TOKENS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
            return self._dir_icon if is_dir else self._file_icon
        if role == Qt.ItemDataRole.ForegroundRole and reason is not None:
            return self._gray
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = rel
            if reason is not None:
                tip += f"\n{REASON_LABELS[reason]}"
                if file is not None and reason.forceable:
                    tip += "(可手動勾選強制納入)"
            return tip
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_NAME and self._selection.is_checkable(rel):
            return _QT_STATE[self._selection.state_of(rel)]
        return None

    def flags(self, index: Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_NAME and self._selection is not None and self._selection.is_checkable(
            self.path_of(index)
        ):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: Index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.CheckStateRole or self._selection is None or not index.isValid():
            return False
        state = value if isinstance(value, Qt.CheckState) else Qt.CheckState(value)
        return self.set_checked(self.path_of(index), state == Qt.CheckState.Checked)

    def set_checked(self, rel: str, checked: bool) -> bool:
        if self._selection is None or not self._selection.set(rel, checked):
            return False
        self._dir_tokens.clear()
        self._emit_changed(rel)
        self.selectionChanged.emit()
        return True

    def set_all(self, checked: bool) -> None:
        if self._selection is None:
            return
        self._selection.set_dir("", checked)
        self._dir_tokens.clear()
        self._emit_changed("")
        self.selectionChanged.emit()

    def _emit_changed(self, rel: str) -> None:
        """Refresh ``rel``, its subtree and its ancestors."""
        assert self._scan is not None
        roles = [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.DisplayRole]

        def emit_children(dir_rel: str) -> None:
            children = self._scan.children(dir_rel)
            if not children:
                return
            parent = self.index_of(dir_rel)
            self.dataChanged.emit(self.index(0, 0, parent), self.index(len(children) - 1, 1, parent), roles)
            for child in children:
                if child in self._scan.dirs:
                    emit_children(child)

        if rel in self._scan.dirs:
            emit_children(rel)
        node = rel
        while node:
            idx = self.index_of(node)
            self.dataChanged.emit(idx, idx.siblingAtColumn(1), roles)
            node = parent_of(node)
