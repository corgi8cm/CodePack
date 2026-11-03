"""Resolve Python imports to project files."""

from __future__ import annotations

import ast
import sys

from codepack.core.deps.base import Dependencies, normalize_rel
from codepack.core.models import ScanResult, parent_of

PY_SUFFIXES = (".py", ".pyi", ".pyw")
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(sys.builtin_module_names)


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


class PythonImportResolver:
    def __init__(self, scan: ScanResult):
        self.scan = scan
        self._base_roots = [r for r in ("", "src", "lib") if r == "" or r in scan.dirs]

    def handles(self, rel_path: str) -> bool:
        return rel_path.endswith(PY_SUFFIXES)

    # --- module lookup ----------------------------------------------------

    def _module_file(self, base: str, dotted: str) -> str | None:
        """``base`` + ``a.b`` -> ``base/a/b.py`` or ``base/a/b/__init__.py`` if present."""
        path = _join(base, dotted.replace(".", "/"))
        for candidate in (path + ".py", path + ".pyi", _join(path, "__init__.py")):
            norm = normalize_rel(candidate)
            if norm and norm in self.scan.files:
                return norm
        return None

    def _package_inits(self, base: str, rel_file: str) -> list[str]:
        """``__init__.py`` files of every package between ``base`` and the module."""
        inits = []
        d = parent_of(rel_file)
        while d and d != base and (not base or d.startswith(base + "/")):
            init = _join(d, "__init__.py")
            if init in self.scan.files and init != rel_file:
                inits.append(init)
            d = parent_of(d)
        return inits

    def _roots_for(self, rel_path: str) -> list[str]:
        roots = list(self._base_roots)
        # The directory above the importing file's top-level package is a root,
        # and a script's own directory is too (``import helper`` next to it).
        d = parent_of(rel_path)
        if d not in roots:
            roots.append(d)
        while d and _join(d, "__init__.py") in self.scan.files:
            d = parent_of(d)
        if d not in roots:
            roots.append(d)
        return roots

    def _resolve_absolute(self, roots: list[str], dotted: str, names: list[str]) -> tuple[list[str], list[str]]:
        """Return ``(modules, implicit)``: the modules the statement names, and the
        package ``__init__.py`` files Python runs along the way."""
        for base in roots:
            found = []
            for name in names:  # ``from pkg import submodule``
                sub = self._module_file(base, f"{dotted}.{name}") if dotted else self._module_file(base, name)
                if sub:
                    found.append(sub)
            all_submodules = bool(names) and len(found) == len(names)
            mod = self._module_file(base, dotted) if dotted else None
            implicit = []
            if mod:
                # ``from pkg import a, b`` where a and b are submodules only runs pkg/__init__.py.
                (implicit if all_submodules and mod.endswith("__init__.py") else found).append(mod)
            if found or implicit:
                implicit += [i for f in found + implicit for i in self._package_inits(base, f)]
                return found, [i for i in dict.fromkeys(implicit) if i not in found]
        return [], []

    # --- public -----------------------------------------------------------

    def dependencies(self, rel_path: str, text: str) -> Dependencies:
        try:
            tree = ast.parse(text, filename=rel_path)
        except (SyntaxError, ValueError):
            return Dependencies(unresolved=["(syntax error: imports not analyzed)"])

        roots = self._roots_for(rel_path)
        package_dir = parent_of(rel_path)
        resolved: list[str] = []
        unresolved: list[str] = []
        leaves: list[str] = []

        def add(result: tuple[list[str], list[str]], name: str) -> None:
            found, implicit = result
            if found or implicit:
                resolved.extend(f for f in found if f not in resolved)
                leaves.extend(f for f in implicit if f not in leaves)
            elif name.split(".")[0] not in _STDLIB and name not in unresolved:
                unresolved.append(name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add(self._resolve_absolute(roots, alias.name, []), alias.name)
            elif isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names if a.name != "*"]
                if node.level:
                    base = package_dir
                    for _ in range(node.level - 1):
                        base = parent_of(base)
                    result = self._resolve_absolute([base], node.module or "", names)
                    if not any(result) and not node.module:
                        init = _join(base, "__init__.py")
                        result = ([init] if init in self.scan.files else [], [])
                    add(result, "." * node.level + (node.module or ""))
                elif node.module:
                    add(self._resolve_absolute(roots, node.module, names), node.module)
        return Dependencies(resolved, unresolved, [f for f in leaves if f not in resolved])
