"""Changed files and diffs from a local git repository.

Runs the local ``git`` executable only; never contacts a remote.
Paths are relative to the project root even when it is a subdirectory
of the repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# git's well-known empty tree: diff against it when the repo has no commits yet.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW for the GUI exe


class GitError(RuntimeError):
    pass


def run_git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=root,
            capture_output=True,
            timeout=60,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        raise GitError("找不到 git 執行檔(git not found on PATH)") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out") from None
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return proc.stdout.decode("utf-8", "replace")


def is_git_repo(root: Path) -> bool:
    try:
        return run_git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except GitError:
        return False


def _has_head(root: Path) -> bool:
    try:
        run_git(root, "rev-parse", "--verify", "--quiet", "HEAD")
        return True
    except GitError:
        return False


def _diff_refs(root: Path, base: str, staged: bool) -> list[str]:
    """Arguments selecting what to compare.

    * ``staged``: index vs ``base`` (default HEAD)
    * ``base``: working tree vs the merge-base of ``base`` and HEAD (branch review)
    * neither: working tree (staged + unstaged) vs HEAD
    """
    head = "HEAD" if _has_head(root) else EMPTY_TREE
    if staged:
        return ["--cached", base or head]
    if base:
        return [run_git(root, "merge-base", base, "HEAD").strip()]
    return [head]


def changed_files(root: Path | str, base: str = "", staged: bool = False, include_untracked: bool = True) -> list[str]:
    """Existing files that differ from the comparison point (deleted files are omitted)."""
    root = Path(root)
    refs = _diff_refs(root, base, staged)
    out = run_git(root, "diff", "--name-only", "-z", "--relative", "--diff-filter=d", *refs)
    files = {f for f in out.split("\0") if f}
    if include_untracked and not staged:
        out = run_git(root, "ls-files", "--others", "--exclude-standard", "-z")
        files.update(f for f in out.split("\0") if f)
    return sorted(files)


def git_diff_text(root: Path | str, base: str = "", staged: bool = False) -> str:
    root = Path(root)
    refs = _diff_refs(root, base, staged)
    return run_git(root, "diff", "--relative", "--no-color", "--no-ext-diff", *refs)
