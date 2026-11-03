"""Dependency resolution framework: follow imports/includes from target files."""

from __future__ import annotations

import posixpath
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

from codepack.core.models import ExcludeReason, ScanResult
from codepack.core.reader import read_text


@dataclass
class DepOptions:
    max_depth: int | None = None
    """None = follow the whole graph; 1 = direct dependencies only."""
    pair_sources: bool = False
    """For every C/C++ header reached, also add its implementation file (foo.h -> foo.cpp)."""
    follow_excluded: bool = False
    """Also add dependencies that the rules exclude (they will be force-selected)."""
    include_dirs: list[str] = field(default_factory=list)
    """Extra C/C++ include directories, relative to the project root."""
    use_compile_commands: bool = True


@dataclass
class Dependencies:
    resolved: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    leaves: list[str] = field(default_factory=list)
    """Included but not followed further (e.g. package ``__init__.py`` files that
    are only executed implicitly; following them would pull in whole packages)."""


class DependencyResolver(Protocol):
    def handles(self, rel_path: str) -> bool: ...

    def dependencies(self, rel_path: str, text: str) -> Dependencies: ...


@dataclass
class DependencyResult:
    targets: list[str]
    files: list[str]
    """Targets plus every dependency reached, sorted."""
    edges: dict[str, list[str]] = field(default_factory=dict)
    unresolved: dict[str, list[str]] = field(default_factory=dict)
    """Imports/includes not found in the project (standard library, system headers, ...)."""
    skipped: dict[str, ExcludeReason] = field(default_factory=dict)
    """Dependencies found but not followed because the rules exclude them."""


def normalize_rel(path: str) -> str | None:
    """Normalize a joined relative path; None if it escapes the project root."""
    norm = posixpath.normpath(path.replace("\\", "/"))
    if norm == "." or norm.startswith("../") or norm == ".." or posixpath.isabs(norm):
        return None
    return norm


def default_resolvers(scan: ScanResult, options: DepOptions) -> list[DependencyResolver]:
    from codepack.core.deps.cpp import CppIncludeResolver
    from codepack.core.deps.python import PythonImportResolver

    return [PythonImportResolver(scan), CppIncludeResolver(scan, options)]


def resolve_dependencies(
    scan: ScanResult,
    targets: Sequence[str],
    options: DepOptions | None = None,
    resolvers: Iterable[DependencyResolver] | None = None,
) -> DependencyResult:
    options = options or DepOptions()
    resolvers = list(resolvers) if resolvers is not None else default_resolvers(scan, options)
    targets = [t for t in targets if t in scan.files]
    result = DependencyResult(targets=list(targets), files=[])

    seen: set[str] = set(targets)
    queue: deque[tuple[str, int]] = deque((t, 0) for t in targets)
    while queue:
        rel, depth = queue.popleft()
        if options.max_depth is not None and depth >= options.max_depth:
            continue
        resolver = next((r for r in resolvers if r.handles(rel)), None)
        if resolver is None:
            continue
        try:
            text = read_text(scan.root / rel)
        except OSError:
            continue
        deps = resolver.dependencies(rel, text)
        if deps.unresolved:
            result.unresolved[rel] = deps.unresolved
        followed = []
        leaves = set(deps.leaves) - set(deps.resolved)
        for dep in [*deps.resolved, *[d for d in deps.leaves if d in leaves]]:
            entry = scan.files.get(dep)
            if entry is None or dep == rel:
                continue
            if not entry.included and not (options.follow_excluded and entry.checkable):
                assert entry.excluded is not None
                result.skipped[dep] = entry.excluded
                continue
            followed.append(dep)
            if dep not in seen:
                seen.add(dep)
                if dep not in leaves:
                    queue.append((dep, depth + 1))
        if followed:
            result.edges[rel] = followed

    result.files = sorted(seen)
    return result
