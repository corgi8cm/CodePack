from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

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
    w = MainWindow(settings=settings, preset_dir=tmp_path / "presets", projects_file=tmp_path / "projects.json")
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


# --- dependency tracking, git, masking, apply dialog ------------------------

import shutil
import subprocess

from codepack.core import PackOptions, Preset, RuleSet
from codepack.gui.apply_dialog import ApplyDialog
from codepack.gui.rules_panel import RulesPanel


def test_rules_panel_roundtrip(qtbot):
    panel = RulesPanel()
    qtbot.addWidget(panel)
    opts = PackOptions(format="xml", mask_secrets=False, reply_format="diff", git_diff=True,
                       git_base="main", git_staged=True, preamble="Review")
    panel.load_preset(Preset("p", RuleSet(include=["*.py"]), opts))
    assert panel.options() == opts
    assert panel.rules().include == ["*.py"]
    panel.depth_spin.setValue(0)
    panel.include_dirs_edit.setText("third_party; vendor/include")
    dep = panel.dep_options()
    assert dep.max_depth is None and dep.include_dirs == ["third_party", "vendor/include"]


def test_select_dependencies(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    window.select_dependencies("src/main.cpp", replace=True)
    assert window.tree_model.selection.checked_files() == ["src/main.cpp", "src/util.h"]
    assert "依賴" in window.status_message.text()
    window.tree_model.set_checked("scripts/run.py", True)
    window.rules_panel.pair_check.setChecked(True)
    window.select_dependencies("src/main.cpp", replace=False)
    assert "src/util.cpp" in window.tree_model.selection.checked_files()
    assert "scripts/run.py" in window.tree_model.selection.checked_files()  # add mode keeps others


def test_deps_button_uses_current_tree_item(window, qtbot, sample_project, monkeypatch):
    _open(window, qtbot, sample_project)
    shown = []
    monkeypatch.setattr("codepack.gui.main_window.QMessageBox.information", lambda *a: shown.append(a))
    window._deps_for_current(True)
    assert shown  # nothing highlighted yet
    src = window.tree_panel.proxy.mapFromSource(window.tree_model.index_of("src/main.cpp"))
    window.tree_panel.view.setCurrentIndex(src)
    window._deps_for_current(True)
    assert window.tree_model.selection.checked_files() == ["src/main.cpp", "src/util.h"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_select_git_changes(window, qtbot, sample_project):
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "-c", "commit.gpgsign=false", *a],
                       cwd=sample_project, check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    (sample_project / "src" / "util.h").write_text("#pragma once\n// changed\n")
    _open(window, qtbot, sample_project)
    window.select_git_changes()
    assert window.tree_model.selection.checked_files() == ["src/util.h"]


def test_select_git_changes_not_repo(window, qtbot, sample_project, monkeypatch):
    _open(window, qtbot, sample_project)
    warned = []
    monkeypatch.setattr("codepack.gui.main_window.QMessageBox.warning", lambda *a: warned.append(a))
    window.select_git_changes()
    assert warned


def test_masked_secrets_indicator(window, qtbot, sample_project):
    (sample_project / "src" / "cfg.h").write_text('const char* kPassword = "hunter22";\n')
    _open(window, qtbot, sample_project)
    window.pack()
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    assert "hunter22" not in window.preview_panel.preview.toPlainText()
    assert not window.preview_panel.secrets_button.isHidden()
    assert "1 處" in window.preview_panel.secrets_button.text()
    assert "src/cfg.h:1" in window.preview_panel.findings_text()


def test_reply_format_appended(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    combo = window.rules_panel.reply_combo
    combo.setCurrentIndex(combo.findData("files"))
    window.pack()
    qtbot.waitUntil(lambda: window.preview_panel.result is not None, timeout=10_000)
    assert "=== END FILE ===" in window.preview_panel.preview.toPlainText()


def test_apply_dialog_parse_apply_restore(qtbot, sample_project, monkeypatch):
    monkeypatch.setattr(
        "codepack.gui.apply_dialog.QMessageBox.question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    dialog = ApplyDialog(sample_project)
    qtbot.addWidget(dialog)
    assert not dialog.restore_button.isEnabled()
    reply = (
        "=== FILE: src/util.h ===\n#pragma once\nint add(int, int);\n=== END FILE ===\n"
        "--- a/missing.cpp\n+++ b/missing.cpp\n@@ -1 +1 @@\n-a\n+b\n"
    )
    dialog.reply_edit.setPlainText(reply)
    dialog.parse()
    assert dialog.change_list.topLevelItemCount() == 2
    assert dialog.checked_paths() == ["src/util.h"]
    assert "+int add(int, int);" in dialog.diff_view.toPlainText()
    assert dialog.apply_button.isEnabled()

    with qtbot.waitSignal(dialog.applied):
        dialog.apply()
    assert (sample_project / "src" / "util.h").read_text() == "#pragma once\nint add(int, int);\n"
    assert dialog.restore_button.isEnabled()
    assert dialog.checked_paths() == []  # now unchanged

    with qtbot.waitSignal(dialog.applied):
        dialog.restore()
    assert (sample_project / "src" / "util.h").read_text() == "#pragma once\nint add(int a, int b);\n"


def test_apply_dialog_from_main_window(window, qtbot, sample_project):
    _open(window, qtbot, sample_project)
    window.open_apply_dialog()
    assert window.apply_dialog is not None and window.apply_dialog.isVisible()
    assert window.apply_dialog.root == sample_project.resolve()
    window.apply_dialog.close()


# --- question templates ----------------------------------------------------------

from codepack.core.prompts import builtin_templates, find_template, set_template
from codepack.gui.prompt_dialog import PromptTemplateDialog


def test_prompt_button_copies_default_then_last_used(window):
    first = builtin_templates()[0]
    assert window.current_prompt_name() == first.name
    window.prompt_button.click()
    assert QGuiApplication.clipboard().text() == first.text
    assert "已複製" in window.status_message.text()

    window._rebuild_prompt_menu()
    actions = [a for a in window.prompt_menu.actions() if a.text()]
    assert actions[-1].text() == "管理模板…"
    review = next(a for a in actions if a.text() == "Code review")
    review.trigger()
    assert "審查" in QGuiApplication.clipboard().text()
    assert window.current_prompt_name() == "Code review"
    QGuiApplication.clipboard().clear()
    window.prompt_button.click()  # now copies the last used one
    assert "審查" in QGuiApplication.clipboard().text()
    assert "Code review" in window.prompt_button.toolTip()


def test_prompt_dialog_edit_add_delete(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "prompts.json"
    dialog = PromptTemplateDialog(path=path, select="Code review")
    qtbot.addWidget(dialog)
    assert dialog.current().name == "Code review"
    assert not dialog.delete_button.isEnabled() and not dialog.save_button.isEnabled()

    # edit a built-in -> stored as override -> restore default
    dialog.text_edit.setPlainText("我的 review 模板\n")
    assert dialog.save_button.isEnabled()
    with qtbot.waitSignal(dialog.templatesChanged):
        dialog.save()
    assert find_template("Code review", path).text == "我的 review 模板\n"
    assert dialog.list.currentItem().text() == "Code review(已修改)"
    assert dialog.delete_button.text() == "還原預設"
    monkeypatch.setattr("codepack.gui.prompt_dialog.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.delete()
    assert find_template("Code review", path).source == "builtin"

    # add, copy, delete a user template
    monkeypatch.setattr("codepack.gui.prompt_dialog.QInputDialog.getText", lambda *a, **k: ("效能", True))
    dialog.new_template()
    assert dialog.current().name == "效能" and dialog.current().source == "user"
    dialog.text_edit.setPlainText("請找效能瓶頸\n")
    dialog.save()
    with qtbot.waitSignal(dialog.copied):
        dialog.copy()
    assert QGuiApplication.clipboard().text() == "請找效能瓶頸\n"
    dialog.delete()
    with pytest.raises(KeyError):
        find_template("效能", path)


def test_prompt_dialog_from_main_window(window):
    set_template("自訂模板", "hi\n")
    window.open_prompt_dialog()
    dialog = window.prompt_dialog
    assert dialog.isVisible()
    assert "自訂模板" in [dialog.list.item(i).data(Qt.ItemDataRole.UserRole + 1) for i in range(dialog.list.count())]
    dialog.close()


# --- project list -----------------------------------------------------------

def test_switch_projects_keeps_each_projects_state(window, qtbot, sample_project, make_project):
    other = make_project({"app.py": "print(1)\n", "lib/util.py": "x = 1\n"}, name="other")
    _open(window, qtbot, sample_project)
    window.tree_model.set_checked("src/util.h", False)
    window.tree_model.set_checked("debug.log", True)  # force an excluded file
    window.rules_panel.format_combo.setCurrentIndex(window.rules_panel.format_combo.findData("xml"))

    _open(window, qtbot, other)
    qtbot.waitUntil(lambda: window.tree_model.scan is not None and window.tree_model.scan.root.name == "other", timeout=10_000)
    assert [window.project_combo.itemText(i) for i in range(window.project_combo.count())] == ["proj", "other"]
    assert window.project_combo.currentIndex() == 1
    assert window.windowTitle() == "other - CodePack"
    assert window.tree_model.selection.checked_files() == ["app.py", "lib/util.py"]
    window.rules_panel.format_combo.setCurrentIndex(window.rules_panel.format_combo.findData("plain"))

    window._project_selected(0)  # back to the first project via the combo
    qtbot.waitUntil(lambda: window.tree_model.scan is not None and window.tree_model.scan.root.name == "proj", timeout=10_000)
    checked = window.tree_model.selection.checked_files()
    assert "src/util.h" not in checked and "debug.log" in checked
    assert window.rules_panel.options().format == "xml"
    assert window.project_root() == sample_project.resolve()


def test_project_list_survives_restart(qtbot, tmp_path, sample_project, make_project):
    other = make_project({"a.py": "x = 1\n"}, name="other")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    kwargs = dict(settings=settings, preset_dir=tmp_path / "presets", projects_file=tmp_path / "projects.json")
    w1 = MainWindow(**kwargs)
    qtbot.addWidget(w1)
    _open(w1, qtbot, sample_project)
    w1.tree_model.set_checked("src/util.h", False)
    _open(w1, qtbot, other)
    qtbot.waitUntil(lambda: w1.tree_model.scan is not None and w1.tree_model.scan.root.name == "other", timeout=10_000)
    w1._project_selected(0)
    qtbot.waitUntil(lambda: w1.tree_model.scan is not None and w1.tree_model.scan.root.name == "proj", timeout=10_000)
    w1.close()

    w2 = MainWindow(**kwargs)
    qtbot.addWidget(w2)
    assert w2.project_combo.count() == 2
    qtbot.waitUntil(lambda: w2.tree_model.scan is not None, timeout=10_000)
    assert w2.project_root() == sample_project.resolve()
    assert "src/util.h" not in w2.tree_model.selection.checked_files()


def test_old_last_project_setting_is_migrated(qtbot, tmp_path, sample_project):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("last_project", str(sample_project))
    w = MainWindow(settings=settings, preset_dir=tmp_path / "presets", projects_file=tmp_path / "projects.json")
    qtbot.addWidget(w)
    assert w.project_combo.count() == 1
    qtbot.waitUntil(lambda: w.tree_model.scan is not None, timeout=10_000)


def test_rename_and_remove_project(window, qtbot, sample_project, monkeypatch):
    _open(window, qtbot, sample_project)
    monkeypatch.setattr("codepack.gui.main_window.QInputDialog.getText", lambda *a, **k: ("引擎", True))
    window.rename_current_project()
    assert window.project_combo.itemText(0) == "引擎"
    assert window.windowTitle() == "引擎 - CodePack"
    monkeypatch.setattr(
        "codepack.gui.main_window.QMessageBox.question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    window.remove_current_project()
    assert window.project_combo.count() == 0
    assert window.project_root() is None and window.tree_model.scan is None
    assert sample_project.is_dir()  # only removed from the list
