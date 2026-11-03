"""Turn a scan plus a list of files into packed output text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from codepack.core.formatters import PackDocument, PackedFile, get_formatter
from codepack.core.models import ScanResult
from codepack.core.reader import read_text
from codepack.core.tokens import DEFAULT_ESTIMATOR, TokenEstimator
from codepack.core.tree_render import render_tree

TreeScope = Literal["selected", "all"]


@dataclass
class PackOptions:
    format: str = "markdown"
    include_tree: bool = True
    tree_scope: TreeScope = "selected"
    preamble: str = ""
    """Phase 2: prompt text placed before the files."""
    transforms: list[str] = field(default_factory=list)
    """Phase 3: names of content transforms (e.g. comment stripping)."""
    max_tokens_per_part: int | None = None
    """Phase 3: split output into parts; not applied yet."""

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "include_tree": self.include_tree,
            "tree_scope": self.tree_scope,
            "preamble": self.preamble,
            "transforms": list(self.transforms),
            "max_tokens_per_part": self.max_tokens_per_part,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PackOptions:
        scope = data.get("tree_scope", "selected")
        max_tokens = data.get("max_tokens_per_part")
        return cls(
            format=str(data.get("format", "markdown")),
            include_tree=bool(data.get("include_tree", True)),
            tree_scope=scope if scope in ("selected", "all") else "selected",
            preamble=str(data.get("preamble", "")),
            transforms=[str(t) for t in data.get("transforms", [])],
            max_tokens_per_part=int(max_tokens) if max_tokens else None,
        )


@dataclass
class PackResult:
    parts: list[str]
    total_tokens: int
    per_file_tokens: dict[str, int]
    files: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.parts)


def build_pack(
    scan: ScanResult,
    files: Sequence[str],
    options: PackOptions | None = None,
    estimator: TokenEstimator | None = None,
) -> PackResult:
    options = options or PackOptions()
    estimator = estimator or DEFAULT_ESTIMATOR
    formatter = get_formatter(options.format)

    packed: list[PackedFile] = []
    warnings: list[str] = []
    for rel in files:
        entry = scan.files.get(rel)
        if entry is None:
            warnings.append(f"{rel}: not in scan, skipped")
            continue
        try:
            content = read_text(scan.root / rel)
        except OSError as exc:
            warnings.append(f"{rel}: cannot read ({exc.strerror or exc})")
            continue
        packed.append(PackedFile(rel, entry.language, content, estimator.estimate(content)))

    tree = ""
    if options.include_tree:
        tree_files = None if options.tree_scope == "all" else [p.rel_path for p in packed]
        tree = render_tree(scan, tree_files)

    doc = PackDocument(scan.project_name, tree, packed, options.preamble)
    text = formatter.render(doc)
    return PackResult(
        parts=[text],
        total_tokens=estimator.estimate(text),
        per_file_tokens={p.rel_path: p.tokens for p in packed},
        files=[p.rel_path for p in packed],
        warnings=warnings,
    )
