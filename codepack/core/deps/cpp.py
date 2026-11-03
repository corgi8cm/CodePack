"""Resolve C/C++ ``#include`` directives to project files.

A lightweight parser (no preprocessor): every ``#include`` line counts,
regardless of ``#if`` blocks. Later resolvers can call ``g++ -MM`` or MSVC
``/showIncludes`` behind the same ``DependencyResolver`` interface.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

from codepack.core.deps.base import Dependencies, DepOptions, normalize_rel
from codepack.core.models import ScanResult, name_of, parent_of

HEADER_EXTS = (".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp", ".tpp", ".cuh")
SOURCE_EXTS = (".c", ".cc", ".cpp", ".cxx", ".c++", ".cu", ".m", ".mm")
CPP_EXTS = HEADER_EXTS + SOURCE_EXTS

_INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*([<"])([^>"\n]+)[>"]', re.MULTILINE)
_AUTO_INCLUDE_DIRS = ("", "include", "inc", "src")
_COMPILE_DB_LOCATIONS = ("compile_commands.json", "build/compile_commands.json", "out/compile_commands.json")


def _stem_ext(name: str) -> tuple[str, str]:
    dot = name.rfind(".")
    return (name[:dot], name[dot:].lower()) if dot > 0 else (name, "")


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def include_dirs_from_compile_commands(root: Path) -> list[str]:
    """Include directories (relative to ``root``) found in compile_commands.json."""
    db_paths = [root / p for p in _COMPILE_DB_LOCATIONS]
    db_paths += sorted(root.glob("cmake-build-*/compile_commands.json"))
    root_resolved = root.resolve()
    found: list[str] = []
    for db in db_paths:
        try:
            entries = json.loads(db.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            args = entry.get("arguments") or _split_command(str(entry.get("command", "")))
            directory = Path(entry.get("directory") or root)
            it = iter(args)
            for arg in it:
                arg = arg.strip('"')
                value = None
                for flag in ("-I", "/I", "-isystem", "-iquote", "/external:I"):
                    if arg == flag:
                        value = next(it, None)
                        break
                    if arg.startswith(flag) and len(arg) > len(flag):
                        value = arg[len(flag):]
                        break
                if not value:
                    continue
                path = Path(value.strip('"'))
                if not path.is_absolute():
                    path = directory / path
                try:
                    rel = path.resolve().relative_to(root_resolved).as_posix()
                except (OSError, ValueError):
                    continue  # outside the project (system/SDK headers)
                rel = "" if rel == "." else rel
                if rel not in found:
                    found.append(rel)
        break  # first database found wins
    return found


class CppIncludeResolver:
    def __init__(self, scan: ScanResult, options: DepOptions | None = None):
        self.scan = scan
        self.options = options or DepOptions()
        dirs = [d for d in _AUTO_INCLUDE_DIRS if d in scan.dirs]
        dirs += [d.strip("/") for d in self.options.include_dirs]
        if self.options.use_compile_commands:
            dirs += include_dirs_from_compile_commands(scan.root)
        self.include_dirs = list(dict.fromkeys(dirs))
        self._by_name: dict[str, list[str]] = {}
        for rel in scan.files:
            self._by_name.setdefault(name_of(rel).lower(), []).append(rel)

    def handles(self, rel_path: str) -> bool:
        return _stem_ext(name_of(rel_path))[1] in CPP_EXTS

    def _lookup(self, base: str, include: str) -> str | None:
        norm = normalize_rel(f"{base}/{include}" if base else include)
        return norm if norm and norm in self.scan.files else None

    def _by_suffix(self, include: str, near: str) -> str | None:
        """Unique (or closest) project file whose path ends with ``include``."""
        include = include.replace("\\", "/").lstrip("./")
        candidates = [
            f for f in self._by_name.get(name_of(include).lower(), [])
            if f == include or f.lower().endswith("/" + include.lower())
        ]
        if len(candidates) <= 1:
            return candidates[0] if candidates else None

        def shared_prefix(f: str) -> int:
            return len(os.path.commonprefix([f.split("/"), near.split("/")]))

        candidates.sort(key=lambda f: (-shared_prefix(f), f))
        return candidates[0]

    def resolve_include(self, rel_path: str, include: str, quoted: bool) -> str | None:
        if quoted:
            found = self._lookup(parent_of(rel_path), include)
            if found:
                return found
        for d in self.include_dirs:
            found = self._lookup(d, include)
            if found:
                return found
        return self._by_suffix(include, rel_path)

    def source_for_header(self, header: str) -> str | None:
        stem, ext = _stem_ext(name_of(header))
        if ext not in HEADER_EXTS:
            return None
        folder = parent_of(header)
        for src_ext in SOURCE_EXTS:
            candidate = f"{folder}/{stem}{src_ext}" if folder else f"{stem}{src_ext}"
            if candidate in self.scan.files:
                return candidate
        for src_ext in SOURCE_EXTS:  # e.g. include/lib/foo.h <-> src/foo.cpp
            matches = self._by_name.get(f"{stem}{src_ext}".lower(), [])
            if len(matches) == 1:
                return matches[0]
        return None

    def dependencies(self, rel_path: str, text: str) -> Dependencies:
        resolved: list[str] = []
        unresolved: list[str] = []
        for m in _INCLUDE_RE.finditer(text):
            quoted, include = m.group(1) == '"', m.group(2).strip()
            found = self.resolve_include(rel_path, include, quoted)
            if found is None:
                if include not in unresolved:
                    unresolved.append(include)
                continue
            if found not in resolved:
                resolved.append(found)
            if self.options.pair_sources:
                src = self.source_for_header(found)
                if src and src != rel_path and src not in resolved:
                    resolved.append(src)
        if self.options.pair_sources:
            src = self.source_for_header(rel_path)
            if src and src not in resolved:
                resolved.append(src)
        return Dependencies(resolved, unresolved)
