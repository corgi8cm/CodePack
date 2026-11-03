import shutil
import subprocess
from pathlib import Path

import pytest

from codepack.core.collectors.git import GitError, changed_files, git_diff_text, is_git_repo
from codepack.core.packer import PackOptions, build_pack
from codepack.core.scanner import scan_project
from codepack.core.scanners.secrets import SecretMasker

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True,
    )


@pytest.fixture
def repo(make_project):
    root = make_project({"src/a.cpp": "int a;\n", "src/b.cpp": "int b;\n", "README.md": "hi\n", "gone.txt": "x\n"})
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def test_is_git_repo(repo, tmp_path):
    assert is_git_repo(repo)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not is_git_repo(plain)


def test_clean_repo_has_no_changes(repo):
    assert changed_files(repo) == []
    assert git_diff_text(repo) == ""


def test_working_tree_changes(repo):
    (repo / "src" / "a.cpp").write_text("int a = 1;\n")
    (repo / "new.py").write_text("x = 1\n")
    (repo / "gone.txt").unlink()
    (repo / "中文.txt").write_text("內容\n", encoding="utf-8")
    assert changed_files(repo) == ["new.py", "src/a.cpp", "中文.txt"]
    assert changed_files(repo, include_untracked=False) == ["src/a.cpp"]
    diff = git_diff_text(repo)
    assert "+int a = 1;" in diff and "gone.txt" in diff


def test_staged_only(repo):
    (repo / "src" / "a.cpp").write_text("int a = 1;\n")
    (repo / "src" / "b.cpp").write_text("int b = 2;\n")
    git(repo, "add", "src/b.cpp")
    assert changed_files(repo, staged=True) == ["src/b.cpp"]
    assert "int b = 2" in git_diff_text(repo, staged=True)
    assert "int a = 1" not in git_diff_text(repo, staged=True)


def test_branch_vs_base(repo):
    git(repo, "switch", "-q", "-c", "feature")
    (repo / "src" / "b.cpp").write_text("int b = 3;\n")
    git(repo, "commit", "-q", "-am", "change b")
    (repo / "README.md").write_text("changed\n")  # uncommitted on top
    assert changed_files(repo, base="main") == ["README.md", "src/b.cpp"]
    with pytest.raises(GitError):
        changed_files(repo, base="no-such-branch")


def test_subdirectory_paths_are_relative(repo):
    (repo / "src" / "a.cpp").write_text("int a = 9;\n")
    (repo / "README.md").write_text("changed\n")
    assert changed_files(repo / "src") == ["a.cpp"]
    assert "README" not in git_diff_text(repo / "src")


def test_repo_without_commits(make_project):
    root = make_project({"a.py": "1\n"}, name="fresh")
    git(root, "init", "-q")
    assert changed_files(root) == ["a.py"]
    git(root, "add", "a.py")
    assert changed_files(root, staged=True) == ["a.py"]


def test_not_a_repo_raises(tmp_path):
    with pytest.raises(GitError):
        changed_files(tmp_path)


def test_pack_with_git_diff_section(repo):
    (repo / "src" / "a.cpp").write_text('const char* kPassword = "hunter22";\n')
    scan = scan_project(repo)
    result = build_pack(scan, ["src/a.cpp"], PackOptions(git_diff=True), masker=SecretMasker(key=b"k" * 32))
    assert "## Git Diff" in result.text
    assert "hunter22" not in result.text  # masked in both the file and the diff
    assert {f.rel_path for f in result.findings} == {"src/a.cpp", "(git diff)"}


def test_pack_git_diff_outside_repo_warns(make_project):
    root = make_project({"a.py": "1\n"}, name="norepo")
    result = build_pack(scan_project(root), ["a.py"], PackOptions(git_diff=True))
    assert any("git diff" in w for w in result.warnings)
    assert "Git Diff" not in result.text
