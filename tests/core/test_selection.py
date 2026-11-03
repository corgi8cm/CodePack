from pathlib import Path

import pytest

from codepack.core.rules import RuleSet
from codepack.core.scanner import scan_project
from codepack.core.selection import CheckState, Selection


@pytest.fixture
def scan(sample_project: Path):
    return scan_project(sample_project)


def test_default_selection_is_included_files(scan):
    sel = Selection(scan)
    assert sel.checked_files() == scan.included_files()
    assert "debug.log" not in sel.checked_files()
    assert sel.state_of("src") is CheckState.CHECKED
    assert sel.state_of("") is CheckState.CHECKED
    assert sel.state_of("assets") is CheckState.UNCHECKED  # only a binary file


def test_uncheck_file_makes_parent_partial(scan):
    sel = Selection(scan)
    assert sel.set_file("src/util.h", False)
    assert not sel.is_checked("src/util.h")
    assert sel.state_of("src") is CheckState.PARTIAL
    assert sel.state_of("") is CheckState.PARTIAL
    sel.set_file("src/util.h", True)
    assert sel.state_of("src") is CheckState.CHECKED


def test_dir_toggle_cascades(scan):
    sel = Selection(scan)
    sel.set_dir("src", False)
    assert sel.state_of("src") is CheckState.UNCHECKED
    assert not any(f.startswith("src/") for f in sel.checked_files())
    sel.set_dir("src", True)
    assert sel.state_of("src") is CheckState.CHECKED


def test_check_dir_does_not_force_excluded(scan):
    sel = Selection(scan)
    sel.set_dir("", False)
    assert sel.checked_files() == []
    sel.set_dir("", True)
    assert "debug.log" not in sel.checked_files()
    assert "assets/logo.png" not in sel.checked_files()


def test_force_excluded_file(scan):
    sel = Selection(scan)
    assert sel.set_file("debug.log", True)
    assert "debug.log" in sel.checked_files()
    assert sel.state_of("") is CheckState.CHECKED
    # unchecking the parent also clears forced files
    sel.set_dir("", False)
    assert "debug.log" not in sel.checked_files()


def test_binary_cannot_be_checked(scan):
    sel = Selection(scan)
    assert not sel.set_file("assets/logo.png", True)
    assert not sel.is_checkable("assets/logo.png")
    assert not sel.is_checkable("build")  # pruned dir
    assert sel.is_checkable("src")
    assert not sel.set("missing.cpp", True)


def test_only_forced_files_gives_checked_state(scan):
    sel = Selection(scan)
    sel.set_dir("", False)
    sel.set_file("debug.log", True)
    assert sel.state_of("") is CheckState.PARTIAL


def test_checked_tokens(scan):
    sel = Selection(scan)
    expected = sum(scan.files[f].tokens for f in scan.included_files())
    assert sel.checked_tokens() == expected


def test_carry_over_keeps_overrides(sample_project: Path, scan):
    sel = Selection(scan)
    sel.set_file("src/util.h", False)
    sel.set_file("debug.log", True)
    new_scan = scan_project(sample_project, RuleSet(exclude=["scripts/"]))
    sel2 = sel.carry_over(new_scan)
    assert not sel2.is_checked("src/util.h")
    assert sel2.is_checked("debug.log")
    assert "scripts/run.py" not in sel2.checked_files()


def test_carry_over_drops_invalid_overrides(sample_project: Path, scan):
    sel = Selection(scan)
    sel.set_file("debug.log", True)
    # With gitignore off, debug.log becomes included: forced_on is no longer needed.
    sel2 = sel.carry_over(scan_project(sample_project, RuleSet(use_gitignore=False)))
    assert sel2.forced_on == set()
    assert sel2.is_checked("debug.log")


def test_reset(scan):
    sel = Selection(scan)
    sel.set_file("src/util.h", False)
    sel.reset()
    assert sel.checked_files() == scan.included_files()
