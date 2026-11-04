import shutil
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


# --- dependency tracking, git, secrets, apply ----------------------------------

def test_pack_deps(capsys, sample_project):
    code, out, err = run(capsys, "pack", str(sample_project), "--deps", "src/main.cpp", "--no-tree")
    assert code == 0
    assert "src/main.cpp" in out and "src/util.h" in out
    assert "src/util.cpp" not in out and "run.py" not in out
    assert "dependencies: 2 files" in err
    code, out, _ = run(capsys, "pack", str(sample_project), "--deps", "src/main.cpp", "--deps-pair", "--no-tree")
    assert "src/util.cpp" in out


def test_pack_deps_unknown_target(capsys, sample_project):
    code, _, err = run(capsys, "pack", str(sample_project), "--deps", "nope.cpp")
    assert code == 2 and "not found" in err


def test_deps_command(capsys, sample_project):
    code, out, err = run(capsys, "deps", str(sample_project), r"src\main.cpp")  # Windows-style separator
    assert code == 0
    assert "* src/main.cpp" in out and "  src/util.h" in out
    assert "2 files" in out


def test_pack_masks_secrets_and_reply_format(capsys, sample_project):
    (sample_project / "src" / "cfg.h").write_text('const char* kPassword = "hunter22";\n')
    code, out, err = run(capsys, "pack", str(sample_project), "--reply-format", "files")
    assert code == 0
    assert "hunter22" not in out and "<REDACTED:password:" in out
    assert "masked 1 secrets: password x1" in err
    assert "=== END FILE ===" in out  # reply instructions at the end
    code, out, _ = run(capsys, "pack", str(sample_project), "--no-mask")
    assert "hunter22" in out


def test_secrets_command(capsys, sample_project):
    (sample_project / "src" / "cfg.h").write_text('\nconst char* kPassword = "hunter22";\n')
    code, out, _ = run(capsys, "secrets", str(sample_project))
    assert code == 0
    assert "src/cfg.h:2  password" in out
    assert "hunter22" not in out
    assert "1 secrets found" in out


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_pack_git_changed(capsys, sample_project):
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "-c", "commit.gpgsign=false", *a],
                       cwd=sample_project, check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    (sample_project / "src" / "util.cpp").write_text("int add(int a, int b) { return a - b; }\n")
    code, out, err = run(capsys, "pack", str(sample_project), "--git-changed", "--git-diff", "--no-tree")
    assert code == 0
    assert "### `src/util.cpp`" in out and "src/main.cpp" not in out.split("## Git Diff")[0]
    assert "## Git Diff" in out and "-int add(int a, int b) { return a + b; }" in out
    assert "git: 1 changed files" in err


def test_pack_git_changed_not_repo(capsys, sample_project):
    code, _, err = run(capsys, "pack", str(sample_project), "--git-changed")
    assert code == 2 and "error" in err


REPLY = (
    "Here you go:\n"
    "=== FILE: src/util.cpp ===\n"
    '#include "util.h"\nint add(int a, int b) { return b + a; }\n'
    "=== END FILE ===\n"
    "=== FILE: src/new.h ===\n#pragma once\n=== END FILE ===\n"
)


def test_apply_dry_run_and_apply_and_restore(capsys, sample_project, tmp_path):
    reply_file = tmp_path / "reply.md"
    reply_file.write_text(REPLY, encoding="utf-8")
    original = (sample_project / "src" / "util.cpp").read_text()

    code, out, err = run(capsys, "apply", str(sample_project), str(reply_file), "--dry-run", "--diff")
    assert code == 0
    assert "M src/util.cpp  +1 -1" in out and "A src/new.h  +1 -0" in out
    assert "+int add(int a, int b) { return b + a; }" in out
    assert "dry run: 2 file(s)" in err
    assert (sample_project / "src" / "util.cpp").read_text() == original

    code, out, err = run(capsys, "apply", str(sample_project), str(reply_file), "--yes", "--no-git-stash")
    assert code == 0
    assert "applied: 2 written" in err and "backup:" in err
    assert "b + a" in (sample_project / "src" / "util.cpp").read_text()

    code, out, _ = run(capsys, "backups", str(sample_project))
    assert "2 files" in out

    code, out, _ = run(capsys, "restore", str(sample_project), "--yes")
    assert code == 0
    assert "restored src/util.cpp" in out and "removed  src/new.h" in out
    assert (sample_project / "src" / "util.cpp").read_text() == original
    assert not (sample_project / "src" / "new.h").exists()


def test_apply_from_stdin_requires_yes(capsys, sample_project, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(REPLY))
    code, _, err = run(capsys, "apply", str(sample_project))
    assert code == 2 and "--yes" in err


def test_apply_nothing_and_errors(capsys, sample_project, tmp_path):
    reply_file = tmp_path / "r.md"
    reply_file.write_text("looks good to me", encoding="utf-8")
    code, _, err = run(capsys, "apply", str(sample_project), str(reply_file), "-y")
    assert code == 1 and "nothing to apply" in err
    code, _, err = run(capsys, "restore", str(sample_project), "-y")
    assert code == 2 and "no backups" in err


# --- question templates ----------------------------------------------------------

def test_prompt_list_print_copy(capsys, monkeypatch):
    code, out, _ = run(capsys, "prompt")
    assert code == 0
    assert "修改程式(完整檔案格式)  [built-in]" in out

    code, out, _ = run(capsys, "prompt", "修改程式(完整檔案格式)")
    assert code == 0
    assert "=== FILE: 相對路徑 ===" in out and out.rstrip().endswith("我想問:")

    copied = []
    monkeypatch.setattr("codepack.clipboard.copy_text", copied.append)
    code, out, err = run(capsys, "prompt", "只問問題(不改程式)", "--copy")
    assert code == 0 and out == "" and "copied" in err
    assert copied and "不需要修改程式" in copied[0]

    code, _, err = run(capsys, "prompt", "沒有這個")
    assert code == 2 and "not found" in err


def test_prompt_lists_user_templates(capsys):
    from codepack.core.prompts import set_template

    set_template("我的模板", "hello\n")
    set_template("Code review", "edited\n")
    code, out, _ = run(capsys, "prompt")
    assert "我的模板  [user]" in out and "Code review  [built-in, edited]" in out
