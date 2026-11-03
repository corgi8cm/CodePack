from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication

from codepack.core import ExcludeReason, Selection, load_preset, scan_project
from codepack.gui.file_tree_model import COL_TOKENS, FileTreeModel
from codepack.gui.main_window import MainWindow


# --- model ----------------------------------------------------------------

@pytest.fixture
def model(qtbot, sample_project):
    scan = scan_project(sample_project)
    m = FileTreeModel()
    m.set_scan(scan, Selection(scan))
    return m


def test_model_structure(model):
    top = [model.data(model.index(r, 0)) for r in range(model.rowCount())]
    assert top[:5] == ["assets", "build", "docs", "scripts", "src"]
    src = model.index_of("src")
    assert model.rowCount(src) == 3
    child = model.index(0, 0, src)
    assert model.parent(child) == src
    assert model.path_of(child) == "src/main.cpp"
    assert model.rowCount(model.index_of("build")) == 0
    assert model.rowCount(model.index_of("src/main.cpp")) == 0


def test_model_check_cascade(model, qtbot):
    src = model.index_of("src")
    assert model.data(src, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    with qtbot.waitSignal(model.selectionChanged):
        assert model.setData(src, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert model.data(model.index(0, 0, src), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    root_state = model.selection.state_of("")
    assert root_state.name == "PARTIAL"
    model.setData(model.index(0, 0, src), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(src, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.PartiallyChecked


def test_model_excluded_items(model):
    logo = model.index_of("assets/logo.png")
    assert model.data(logo, Qt.ItemDataRole.CheckStateRole) is None
    assert not model.flags(logo) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.data(logo, Qt.ItemDataRole.ForegroundRole) is not None
    log = model.index_of("debug.log")
    assert model.flags(log) & Qt.ItemFlag.ItemIsUserCheckable
    assert "gitignore" in model.data(log, Qt.ItemDataRole.ToolTipRole)
    assert model.setData(log, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert "debug.log" in model.selection.checked_files()


def test_model_token_column(model):
    main = model.index_of("src/main.cpp", COL_TOKENS)
    assert model.data(main) == f"{model.scan.files['src/main.cpp'].tokens:,}"
    src_tokens = model.data(model.index_of("src", COL_TOKENS))
    model.set_checked("src/util.h", False)
    assert model.data(model.index_of("src", COL_TOKENS)) != src_tokens


# --- main window ----------------------------------------------------------

@pytest.fixture
def window(qtbot, tmp_path: Path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=settings, preset_dir=tmp_path / "presets")
    qtbot.addWidget(w)
    return w


def _open(window, qtbot, path: Path):
    window.open_project(path)
    qtbot.waitUntil(lambda: window.tree_model.scan is not None, timeout=10_000)


def test_open_and_pack(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    assert "已選" in window.status_files.text()
    window.pack()
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    text = window.preview_panel.preview.toPlainText()
    assert "### `src/main.cpp`" in text
    assert "debug.log" not in text
    assert window.preview_panel.copy_button.isEnabled()

    window.preview_panel.copy()
    assert "src/main.cpp" in QGuiApplication.clipboard().text()

    window.tree_model.set_checked("src", False)
    assert window.preview_panel.stale_label.text()


def test_rule_edit_triggers_rescan_and_pack(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    window.rules_panel.exclude_edit.setPlainText("src/")
    window.pack()  # flushes the pending rule change, rescans, then packs
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    scan = window.tree_model.scan
    assert scan.dirs["src"].pruned is ExcludeReason.EXCLUDE_RULE
    assert "main.cpp" not in window.preview_panel.preview.toPlainText()


def test_format_option(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    window.rules_panel.format_combo.setCurrentIndex(window.rules_panel.format_combo.findData("xml"))
    window.pack()
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    assert window.preview_panel.preview.toPlainText().startswith("<project")


def test_save_preset(window, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "codepack.gui.main_window.QInputDialog.getText", lambda *a, **k: ("my cpp", True)
    )
    window.rules_panel.include_edit.setPlainText("*.cpp\n*.h")
    window.save_current_preset()
    saved = load_preset(tmp_path / "presets" / "my cpp.json")
    assert saved.rules.include == ["*.cpp", "*.h"]
    assert window.preset_combo.currentData() == "my cpp"


def test_preset_switch_changes_rules(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    idx = window.preset_combo.findData("python")
    window.preset_combo.setCurrentIndex(idx)
    window._preset_selected(idx)
    qtbot.waitUntil(
        lambda: window.tree_model.scan is not None
        and window.tree_model.scan.files["src/main.cpp"].excluded is ExcludeReason.NOT_INCLUDED,
        timeout=10_000,
    )
    assert "*.py" in window.rules_panel.include_edit.toPlainText()


def test_save_output(window, qtbot, sample_project, monkeypatch, tmp_path):
    _open(window, qtbot, sample_project)
    window.pack()
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    dest = tmp_path / "out.md"
    monkeypatch.setattr(
        "codepack.gui.main_window.QFileDialog.getSaveFileName", lambda *a, **k: (str(dest), "")
    )
    window.save_output()
    assert dest.read_text(encoding="utf-8") == window.preview_panel.result.text
