"""Data models shared by every core module.

Paths are always POSIX-style strings relative to the project root
(``"src/main.cpp"``); the root directory itself is ``""``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ExcludeReason(str, Enum):
    GITIGNORE = "gitignore"
    EXCLUDE_RULE = "exclude_rule"
    NOT_INCLUDED = "not_included"
    BINARY = "binary"
    TOO_LARGE = "too_large"
    UNREADABLE = "unreadable"

    @property
    def forceable(self) -> bool:
        """Whether the user may still check a file excluded for this reason."""
        return self not in (ExcludeReason.BINARY, ExcludeReason.UNREADABLE)


def parent_of(rel_path: str) -> str:
    """``"a/b/c.py"`` -> ``"a/b"``, ``"c.py"`` -> ``""``."""
    idx = rel_path.rfind("/")
    return rel_path[:idx] if idx >= 0 else ""


def name_of(rel_path: str) -> str:
    return rel_path.rsplit("/", 1)[-1]


def join_rel(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def is_under(rel_path: str, dir_rel: str) -> bool:
    """True if ``rel_path`` is ``dir_rel`` itself or lies inside it."""
    if not dir_rel:
        return True
    return rel_path == dir_rel or rel_path.startswith(dir_rel + "/")


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    size: int
    tokens: int
    excluded: ExcludeReason | None = None
    language: str = ""

    @property
    def included(self) -> bool:
        return self.excluded is None

    @property
    def checkable(self) -> bool:
        return self.excluded is None or self.excluded.forceable

    @property
    def name(self) -> str:
        return name_of(self.rel_path)


@dataclass(frozen=True)
class DirEntry:
    rel_path: str
    pruned: ExcludeReason | None = None
    """Set when the directory was ignored; its contents were not scanned."""

    @property
    def name(self) -> str:
        return name_of(self.rel_path)


@dataclass
class ScanResult:
    root: Path
    files: dict[str, FileEntry] = field(default_factory=dict)
    dirs: dict[str, DirEntry] = field(default_factory=dict)
    _children: dict[str, list[str]] | None = field(default=None, init=False, repr=False, compare=False)
    _descendants: dict[str, list[str]] | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def project_name(self) -> str:
        return self.root.name or str(self.root)

    def _build_index(self) -> None:
        children: dict[str, list[str]] = {d: [] for d in self.dirs}
        children.setdefault("", [])
        descendants: dict[str, list[str]] = {d: [] for d in children}
        for rel in self.dirs:
            if rel:
                children.setdefault(parent_of(rel), []).append(rel)
        for rel in self.files:
            children.setdefault(parent_of(rel), []).append(rel)
            d = parent_of(rel)
            while True:
                descendants.setdefault(d, []).append(rel)
                if not d:
                    break
                d = parent_of(d)

        def sort_key(rel: str) -> tuple[int, str, str]:
            name = name_of(rel)
            return (0 if rel in self.dirs else 1, name.lower(), name)

        for lst in children.values():
            lst.sort(key=sort_key)
        for lst in descendants.values():
            lst.sort()
        self._children = children
        self._descendants = descendants

    def invalidate_index(self) -> None:
        self._children = None
        self._descendants = None

    def children(self, dir_rel: str = "") -> list[str]:
        """Direct children of a directory: subdirectories first, then files."""
        if self._children is None:
            self._build_index()
        assert self._children is not None
        return self._children.get(dir_rel, [])

    def files_under(self, dir_rel: str = "") -> list[str]:
        """All files below a directory (recursively), sorted."""
        if self._descendants is None:
            self._build_index()
        assert self._descendants is not None
        return self._descendants.get(dir_rel, [])

    def is_dir(self, rel_path: str) -> bool:
        return rel_path in self.dirs

    def included_files(self) -> list[str]:
        return sorted(rel for rel, f in self.files.items() if f.included)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files.values())
