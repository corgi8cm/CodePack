import shutil
import subprocess
from pathlib import Path

import pytest

from codepack.core.apply import (
    ApplyError,
    BackupError,
    apply_plan,
    list_backups,
    parse_reply,
    plan_changes,
    restore_backup,
)
from codepack.core.apply.parser import FileDelete, FilePatch, FileReplace
from codepack.core.apply.patch import apply_hunks
from codepack.core.packer import PackOptions, build_pack
from codepack.core.scanner import scan_project
from codepack.core.scanners.secrets import SecretMasker

KEY = b"k" * 32

# --- parser -----------------------------------------------------------------


def test_parse_file_blocks_with_fences_and_prose():
    reply = """Sure! Here are the changes.

=== FILE: src/a.py ===
```python
def f():
    return 1
```
=== END FILE ===

And a new one:

**=== FILE: `docs/new.md` ===**
# Title
=== END FILE ===

=== DELETE: old/legacy.py ===
"""
    parsed = parse_reply(reply)
    assert parsed.errors == []
    a, new, delete = parsed.edits
    assert a == FileReplace("src/a.py", "def f():\n    return 1\n")
    assert new == FileReplace("docs/new.md", "# Title\n")
    assert delete == FileDelete("old/legacy.py")


def test_parse_file_block_inside_outer_fence():
    reply = "```\n=== FILE: a.txt ===\nhello\n=== END FILE ===\n```\n"
    assert parse_reply(reply).edits == [FileReplace("a.txt", "hello\n")]
    reply = "=== FILE: a.txt ===\nhello\n```\n=== END FILE ==="
    assert parse_reply(reply).edits == [FileReplace("a.txt", "hello\n")]


def test_parse_file_block_keeps_markdown_fences():
    reply = "=== FILE: README.md ===\nText\n```bash\nls\n```\n=== END FILE ===\n"
    assert parse_reply(reply).edits[0].content == "Text\n```bash\nls\n```\n"


def test_parse_missing_end_marker():
    parsed = parse_reply("=== FILE: a.py ===\nx = 1\n=== FILE: b.py ===\ny = 2\n=== END FILE ===\n")
    assert [e.path for e in parsed.edits] == ["a.py", "b.py"]
    assert parsed.edits[0].content == "x = 1\n"
    assert len(parsed.errors) == 1


def test_parse_unified_diff():
    reply = """Here is the fix:

```diff
diff --git a/src/a.py b/src/a.py
index 123..456 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,3 @@
 def f():
-    return 1
+    return 2

--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
--- a/src/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-z = 3
```
Done."""
    parsed = parse_reply(reply)
    assert parsed.errors == []
    mod, new, gone = parsed.edits
    assert isinstance(mod, FilePatch) and mod.path == "src/a.py"
    assert mod.hunks[0].lines == [" def f():", "-    return 1", "+    return 2"]
    assert new.is_new and new.hunks[0].new_lines == ["x = 1", "y = 2"]
    assert gone.is_delete and gone.old_path == "src/gone.py"


def test_parse_blank_context_lines_and_loose_hunk_headers():
    reply = "--- a/x.py\n+++ b/x.py\n@@ fix @@\n a = 1\n\n-b = 2\n+b = 3\n\nprose after\n"
    patch = parse_reply(reply).edits[0]
    assert patch.hunks[0].lines == [" a = 1", " ", "-b = 2", "+b = 3"]
    assert patch.hunks[0].old_start == 0


def test_parse_nothing():
    parsed = parse_reply("I think the code looks fine.")
    assert parsed.edits == [] and parsed.errors


# --- patch engine -------------------------------------------------------------

def _hunks(diff: str):
    return parse_reply(diff).edits[0].hunks


def test_apply_hunks_with_wrong_line_numbers():
    text = "".join(f"line{i}\n" for i in range(1, 21))
    diff = "--- a/f\n+++ b/f\n@@ -2,3 +2,3 @@\n line14\n-line15\n+LINE15\n line16\n"
    result = apply_hunks(text, _hunks(diff))
    assert result.failed == []
    assert "LINE15\n" in result.text and "line15\n" not in result.text


def test_apply_hunks_whitespace_fuzz_keeps_original_context():
    text = "def f():\n    a = 1\n    return a\n"
    diff = "--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n def f():  \n   a = 1\n-  return a\n+    return a + 1\n"
    result = apply_hunks(text, _hunks(diff))
    assert result.failed == [] and len(result.fuzzy) == 1
    assert result.text == "def f():\n    a = 1\n    return a + 1\n"


def test_apply_multiple_hunks_in_order():
    text = "a\nb\nc\nd\ne\nf\ng\n"
    diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,3 @@\n a\n+a2\n b\n@@ -6,2 +7,2 @@\n f\n-g\n+G\n"
    assert apply_hunks(text, _hunks(diff)).text == "a\na2\nb\nc\nd\ne\nf\nG\n"


def test_apply_hunk_failure_reported():
    result = apply_hunks("a\nb\n", _hunks("--- a/f\n+++ b/f\n@@ -1 +1 @@\n-zzz\n+y\n"))
    assert result.failed == ["@@ -1 +1 @@"]


def test_no_trailing_newline_preserved():
    result = apply_hunks("a\nb", _hunks("--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+A\n"))
    assert result.text == "A\nb"


# --- planner & apply ------------------------------------------------------------

@pytest.fixture
def project(make_project):
    return make_project({
        "src/a.py": "def f():\n    return 1\n",
        "src/crlf.py": b"x = 1\r\ny = 2\r\n",
        "src/big5.cpp": "// 中文註解\nint x;\n".encode("cp950"),
        "keep.txt": "keep\n",
    })


def test_plan_and_apply_full_files(project):
    reply = (
        "=== FILE: src/a.py ===\ndef f():\n    return 2\n=== END FILE ===\n"
        "=== FILE: src/new/mod.py ===\nX = 1\n=== END FILE ===\n"
        "=== DELETE: keep.txt ===\n"
    )
    plan = plan_changes(project, reply)
    assert plan.errors == []
    kinds = {c.path: c.kind for c in plan.changes}
    assert kinds == {"src/a.py": "modify", "src/new/mod.py": "create", "keep.txt": "delete"}
    a = next(c for c in plan.changes if c.path == "src/a.py")
    assert "-    return 1\n+    return 2\n" in a.diff()
    assert a.stats() == (1, 1)

    result = apply_plan(plan, git_stash=False)
    assert sorted(result.written) == ["src/a.py", "src/new/mod.py"]
    assert result.deleted == ["keep.txt"]
    assert (project / "src/a.py").read_text() == "def f():\n    return 2\n"
    assert not (project / "keep.txt").exists()

    restored = restore_backup(project)
    assert restored.id == result.backup.id
    assert (project / "src/a.py").read_text() == "def f():\n    return 1\n"
    assert (project / "keep.txt").read_text() == "keep\n"
    assert not (project / "src/new/mod.py").exists()


def test_apply_preserves_crlf_and_encoding(project):
    reply = (
        "--- a/src/crlf.py\n+++ b/src/crlf.py\n@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 3\n"
        "=== FILE: src/big5.cpp ===\n// 中文註解 修改\nint x;\n=== END FILE ===\n"
    )
    plan = plan_changes(project, reply)
    assert [c.error for c in plan.changes] == [None, None]
    apply_plan(plan, git_stash=False)
    assert (project / "src/crlf.py").read_bytes() == b"x = 1\r\ny = 3\r\n"
    assert (project / "src/big5.cpp").read_bytes() == "// 中文註解 修改\nint x;\n".encode("cp950")


def test_unchanged_and_failed_changes_not_applied(project):
    reply = (
        "=== FILE: src/a.py ===\ndef f():\n    return 1\n=== END FILE ===\n"
        "--- a/keep.txt\n+++ b/keep.txt\n@@ -1 +1 @@\n-nope\n+x\n"
        "--- a/missing.py\n+++ b/missing.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    plan = plan_changes(project, reply)
    by_path = {c.path: c for c in plan.changes}
    assert by_path["src/a.py"].unchanged
    assert "hunk" in by_path["keep.txt"].error
    assert by_path["missing.py"].error
    assert plan.applicable == []
    assert apply_plan(plan).backup is None


@pytest.mark.parametrize("bad", ["../evil.py", "/etc/passwd", "C:/Windows/x.dll", ".git/config", "a/../../x", ".codepack/x"])
def test_unsafe_paths_rejected(project, bad):
    plan = plan_changes(project, f"=== FILE: {bad} ===\nx\n=== END FILE ===\n")
    assert plan.changes == [] and plan.errors


def test_apply_subset_and_stale_check(project):
    reply = (
        "=== FILE: src/a.py ===\nchanged\n=== END FILE ===\n"
        "=== FILE: keep.txt ===\nchanged\n=== END FILE ===\n"
    )
    plan = plan_changes(project, reply)
    apply_plan(plan, paths=["keep.txt"], git_stash=False)
    assert (project / "keep.txt").read_text() == "changed\n"
    assert (project / "src/a.py").read_text() == "def f():\n    return 1\n"

    (project / "src/a.py").write_text("edited meanwhile\n")
    with pytest.raises(ApplyError):
        apply_plan(plan, paths=["src/a.py"], git_stash=False)


def test_sequential_patches_on_same_file(project):
    reply = (
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-def f():\n+def g():\n"
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -2 +2 @@\n-    return 1\n+    return 5\n"
    )
    plan = plan_changes(project, reply)
    assert len(plan.changes) == 1
    assert plan.changes[0].new_text == "def g():\n    return 5\n"


def test_placeholders_restored_from_project(make_project):
    root = make_project({
        "cfg.py": 'DB_PASSWORD = "hunter22"\nHOST = "10.0.0.7"\n',
        "other.py": 'TOKEN = "s3cr3t-token"\n',
    })
    masker = SecretMasker(key=KEY)
    packed = build_pack(scan_project(root), ["cfg.py", "other.py"], PackOptions(format="plain"), masker=masker)
    masked_cfg = packed.text.split("File: cfg.py\n" + "=" * 64 + "\n")[1].split("=" * 64)[0].rstrip("\n") + "\n"
    token_ph = masker.placeholder("password", "s3cr3t-token")
    reply = f"=== FILE: cfg.py ===\n{masked_cfg}DEBUG = True\n=== END FILE ===\n" \
            f"=== FILE: new.py ===\nT = \"{token_ph}\"\nU = \"<REDACTED:password:00000000>\"\n=== END FILE ===\n"
    plan = plan_changes(root, reply, masker=masker)
    cfg, new = plan.changes
    assert cfg.new_text == 'DB_PASSWORD = "hunter22"\nHOST = "10.0.0.7"\nDEBUG = True\n'
    assert cfg.warnings == []
    assert 'T = "s3cr3t-token"' in new.new_text  # found in another project file
    assert any("placeholder" in w for w in new.warnings)


def test_backups_listing_and_errors(project):
    with pytest.raises(BackupError):
        restore_backup(project)
    for content in ("one", "two"):
        apply_plan(plan_changes(project, f"=== FILE: keep.txt ===\n{content}\n=== END FILE ===\n"), git_stash=False)
    backups = list_backups(project)
    assert len(backups) == 2
    assert backups[0].entries[0].path == "keep.txt"
    restore_backup(project, backups[1].id)
    assert (project / "keep.txt").read_text() == "keep\n"
    with pytest.raises(BackupError):
        restore_backup(project, "nope")
    assert (project / ".codepack" / ".gitignore").exists()
    assert ".codepack" not in scan_project(project).dirs


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_stash_snapshot_does_not_touch_worktree(project):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "-c", "commit.gpgsign=false", *args],
            cwd=project, check=True, capture_output=True, text=True,
        ).stdout

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    (project / "keep.txt").write_text("uncommitted work\n")
    plan = plan_changes(project, "=== FILE: src/a.py ===\nnew\n=== END FILE ===\n")
    result = apply_plan(plan)
    assert result.backup.git_stash
    assert "codepack backup" in git("stash", "list")
    assert (project / "keep.txt").read_text() == "uncommitted work\n"  # untouched
    assert (project / "src/a.py").read_text() == "new\n"
    assert ".codepack" not in git("status", "--porcelain")
