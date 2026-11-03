"""Walk a project directory and classify every file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from codepack.core.binary import SAMPLE_SIZE, has_binary_extension, is_binary_bytes
from codepack.core.languages import detect_language
from codepack.core.models import DirEntry, ExcludeReason, FileEntry, ScanResult, join_rel
from codepack.core.reader import decode_bytes
from codepack.core.rules import CompiledRules, GitignoreStack, RuleSet
from codepack.core.tokens import DEFAULT_ESTIMATOR, CharTokenEstimator, TokenEstimator

ALWAYS_SKIP_DIRS = frozenset({".git", ".hg", ".svn"})

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class ScanCancelled(Exception):
    pass


def _sort_key(entry: os.DirEntry) -> tuple[str, str]:
    return (entry.name.lower(), entry.name)


def _estimate_from_size(estimator: TokenEstimator, size: int) -> int:
    if isinstance(estimator, CharTokenEstimator):
        return estimator.estimate_from_size(size)
    return size // 4


def _classify_file(
    path: Path,
    rel: str,
    size: int,
    rules: CompiledRules,
    gitignore: GitignoreStack | None,
    estimator: TokenEstimator,
) -> FileEntry:
    language = detect_language(path.name)

    def entry(tokens: int, reason: ExcludeReason | None) -> FileEntry:
        return FileEntry(rel, size, tokens, reason, language)

    if has_binary_extension(path.name):
        return entry(0, ExcludeReason.BINARY)

    too_large = size > rules.rules.max_file_size
    try:
        with open(path, "rb") as fh:
            data = fh.read(SAMPLE_SIZE if too_large else None)
    except OSError:
        return entry(0, ExcludeReason.UNREADABLE)

    if is_binary_bytes(data[:SAMPLE_SIZE]):
        return entry(0, ExcludeReason.BINARY)

    if too_large:
        tokens = _estimate_from_size(estimator, size)
    else:
        tokens = estimator.estimate(decode_bytes(data)[0])

    reason: ExcludeReason | None = None
    if gitignore is not None and gitignore.is_ignored(rel, is_dir=False):
        reason = ExcludeReason.GITIGNORE
    else:
        reason = rules.classify_file(rel)
    if reason is None and too_large:
        reason = ExcludeReason.TOO_LARGE
    return entry(tokens, reason)


def scan_project(
    root: Path | str,
    rules: RuleSet | None = None,
    estimator: TokenEstimator | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> ScanResult:
    """Scan ``root`` and return every file with its exclusion reason.

    Ignored directories are recorded as pruned ``DirEntry`` objects and not
    descended into. Symlinked directories are not followed.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    rules = rules or RuleSet()
    compiled = rules.compile()
    estimator = estimator or DEFAULT_ESTIMATOR
    gitignore = GitignoreStack() if rules.use_gitignore else None

    result = ScanResult(root=root)
    result.dirs[""] = DirEntry("")
    count = 0
    stack = [""]
    while stack:
        dir_rel = stack.pop()
        dir_path = root / dir_rel if dir_rel else root
        if gitignore is not None:
            gitignore.load_dir(root, dir_rel)
        try:
            with os.scandir(dir_path) as it:
                entries = sorted(it, key=_sort_key)
        except OSError:
            continue

        subdirs: list[str] = []
        for entry in entries:
            if cancel is not None and cancel():
                raise ScanCancelled()
            rel = join_rel(dir_rel, entry.name)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file()
            except OSError:
                continue

            if is_dir:
                if entry.name in ALWAYS_SKIP_DIRS:
                    continue
                reason = None
                if gitignore is not None and gitignore.is_ignored(rel, is_dir=True):
                    reason = ExcludeReason.GITIGNORE
                else:
                    reason = compiled.classify_dir(rel)
                result.dirs[rel] = DirEntry(rel, reason)
                if reason is None:
                    subdirs.append(rel)
            elif is_file:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                result.files[rel] = _classify_file(
                    Path(entry.path), rel, size, compiled, gitignore, estimator
                )
                count += 1
                if progress is not None:
                    progress(count, rel)

        # Push in reverse so directories are visited in sorted order (DFS).
        stack.extend(reversed(subdirs))
    return result
