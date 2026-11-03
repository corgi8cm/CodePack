import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from codepack import cli


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_pack_to_stdout(capsys, sample_project):
    code, out, err = run(capsys, "pack", str(sample_project))
    assert code == 0
    assert "### `src/main.cpp`" in out
    assert "packed" in err and "tokens" in err


def test_pack_to_file_xml(capsys, sample_project, tmp_path):
    dest = tmp_path / "out" / "pack.xml"
    code, out, err = run(capsys, "pack", str(sample_project), "-f", "xml", "-o", str(dest))
    assert code == 0
    assert out == ""
    root = ET.fromstring(dest.read_text(encoding="utf-8"))
    assert "src/util.h" in [f.get("path") for f in root.iter("file")]


def test_pack_include_exclude_and_force(capsys, sample_project):
    code, out, _ = run(
        capsys, "pack", str(sample_project), "-f", "plain", "--no-tree",
        "-i", "*.cpp", "-e", "src/util.cpp", "--force", "debug.log",
    )
    assert code == 0
    assert "File: src/main.cpp" in out
    assert "File: src/util.cpp" not in out
    assert "File: src/util.h" not in out
    assert "File: debug.log" in out
    assert "Directory Structure" not in out


def test_pack_force_binary_warns(capsys, sample_project):
    code, _, err = run(capsys, "pack", str(sample_project), "--force", "assets/logo.png")
    assert code == 0
    assert "cannot force" in err


def test_pack_preset_and_preamble(capsys, sample_project):
    code, out, _ = run(capsys, "pack", str(sample_project), "--preset", "python", "--preamble", "Review it")
    assert code == 0
    assert "Review it" in out
    assert "scripts/run.py" in out
    assert "main.cpp" not in out


def test_pack_copy(capsys, sample_project, monkeypatch):
    copied = []
    monkeypatch.setattr("codepack.clipboard.copy_text", copied.append)
    code, out, err = run(capsys, "pack", str(sample_project), "--copy")
    assert code == 0
    assert out == ""
    assert copied and "src/main.cpp" in copied[0]
    assert "clipboard" in err


def test_tree(capsys, sample_project):
    code, out, _ = run(capsys, "tree", str(sample_project))
    assert code == 0
    assert "build/  [gitignore]" in out
    code, out, _ = run(capsys, "tree", str(sample_project), "--selected")
    assert "build/" not in out and "[" not in out


def test_stats(capsys, sample_project):
    code, out, _ = run(capsys, "stats", str(sample_project), "--top", "2")
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0].startswith("file")
    assert len(lines) == 4  # header + 2 rows + summary
    assert "excluded" in lines[-1]


def test_presets(capsys):
    code, out, _ = run(capsys, "presets")
    assert code == 0
    assert "default" in out and "cpp" in out


def test_errors(capsys, tmp_path):
    code, _, err = run(capsys, "pack", str(tmp_path / "missing"))
    assert code == 2 and "error" in err
    code, _, err = run(capsys, "pack", str(tmp_path), "--preset", "nope")
    assert code == 2 and "not found" in err


def test_module_entry_point_utf8(sample_project):
    (sample_project / "src" / "zh.cpp").write_text("// 中文註解\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "codepack", "pack", str(sample_project)],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    text = proc.stdout.decode("utf-8")
    assert "中文註解" in text
    assert "└──" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 clipboard")
def test_windows_clipboard_roundtrip():
    import ctypes

    from codepack.clipboard import copy_text

    copy_text("codepack 測試\nline2")
    user32 = ctypes.WinDLL("user32")
    kernel32 = ctypes.WinDLL("kernel32")
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    assert user32.OpenClipboard(None)
    try:
        handle = user32.GetClipboardData(13)
        ptr = kernel32.GlobalLock(handle)
        value = ctypes.wstring_at(ptr)
        kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    assert value == "codepack 測試\r\nline2"
