"""Checks for the PyInstaller packaging that do not require running a build."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_build_module():
    spec = importlib.util.spec_from_file_location("codepack_build", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaging_files_present():
    for rel in ("codepack.spec", "packaging/build.py", "packaging/gui_entry.py", "packaging/cli_entry.py",
                "codepack/gui/codepack.ico"):
        assert (ROOT / rel).is_file(), rel
    assert (ROOT / "codepack/gui/codepack.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"  # ICO header


def test_spec_excludes_networking():
    spec = (ROOT / "codepack.spec").read_text(encoding="utf-8")
    assert '"PySide6.QtNetwork"' in spec
    assert "qtuiotouchplugin" in spec and "UNWANTED_BINARIES" in spec
    assert "upx=False" in spec


def test_bundled_binaries_parsing_and_forbidden_dll(tmp_path):
    build = _load_build_module()
    work = tmp_path / "work" / "codepack"
    work.mkdir(parents=True)
    (work / "EXE-00.toc").write_text(
        "[('Qt6Core.dll', 'C:\\\\venv\\\\PySide6\\\\Qt6Core.dll', 'BINARY'),\n"
        " ('Qt6Network.dll', 'C:\\\\venv\\\\PySide6\\\\Qt6Network.dll', 'BINARY')]\n",
        encoding="utf-8",
    )
    paths = build.bundled_binaries(tmp_path / "work")
    assert [p.name for p in paths] == ["Qt6Core.dll", "Qt6Network.dll"]
    problems = build.verify_offline(tmp_path / "work")
    assert "bundled networking DLL: qt6network.dll" in problems


@pytest.mark.parametrize("entry", ["gui_entry.py", "cli_entry.py"])
def test_entry_scripts_compile(entry):
    compile((ROOT / "packaging" / entry).read_text(encoding="utf-8"), entry, "exec")


def test_cli_prog_name_when_frozen(monkeypatch):
    import importlib

    import codepack.cli as cli

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        reloaded = importlib.reload(cli)
        assert reloaded.PROG == "codepack-cli"
        assert reloaded.build_parser().prog == "codepack-cli"
    finally:
        monkeypatch.delattr(sys, "frozen")
        importlib.reload(cli)


def test_version_has_single_source(capsys):
    import re

    from codepack import __version__, cli

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "codepack.__version__"}' in pyproject
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip().endswith(__version__)
