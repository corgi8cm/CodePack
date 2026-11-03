"""Render a directory tree as text."""

from __future__ import annotations

from typing import Iterable

from codepack.core.models import ScanResult, parent_of


def render_tree(
    scan: ScanResult,
    files: Iterable[str] | None = None,
    annotate_excluded: bool = False,
) -> str:
    """Render the project tree.

    ``files`` limits the tree to those files (and their parent directories);
    ``None`` renders everything in the scan, including pruned directories.
    """
    if files is None:
        wanted_files = set(scan.files)
        wanted_dirs = set(scan.dirs)
    else:
        wanted_files = {f for f in files if f in scan.files}
        wanted_dirs = {""}
        for f in wanted_files:
            d = parent_of(f)
            while d not in wanted_dirs:
                wanted_dirs.add(d)
                d = parent_of(d)

    lines = [f"{scan.project_name}/"]

    def label(rel: str) -> str:
        if rel in scan.dirs:
            name = scan.dirs[rel].name + "/"
            reason = scan.dirs[rel].pruned
        else:
            name = scan.files[rel].name
            reason = scan.files[rel].excluded
        if annotate_excluded and reason is not None:
            name += f"  [{reason.value}]"
        return name

    def walk(dir_rel: str, prefix: str) -> None:
        children = [c for c in scan.children(dir_rel) if c in wanted_dirs or c in wanted_files]
        for i, child in enumerate(children):
            last = i == len(children) - 1
            lines.append(prefix + ("└── " if last else "├── ") + label(child))
            if child in scan.dirs:
                walk(child, prefix + ("    " if last else "│   "))

    walk("", "")
    return "\n".join(lines)
