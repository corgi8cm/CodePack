"""Turn a scan plus a list of files into packed output text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from codepack.core.apply.formats import REPLY_FORMATS, REPLY_NONE, reply_instructions
from codepack.core.formatters import ExtraSection, PackDocument, PackedFile, get_formatter
from codepack.core.models import ScanResult
from codepack.core.reader import read_text
from codepack.core.scanners.secrets import SecretFinding, SecretMasker
from codepack.core.tokens import DEFAULT_ESTIMATOR, TokenEstimator
from codepack.core.tree_render import render_tree

TreeScope = Literal["selected", "all"]


@dataclass
class PackOptions:
    format: str = "markdown"
    include_tree: bool = True
    tree_scope: TreeScope = "selected"
    preamble: str = ""
    """Prompt text placed before the files."""
    mask_secrets: bool = True
    """Replace API keys, passwords, private keys and internal IPs with placeholders."""
    reply_format: str = REPLY_NONE
    """Append instructions asking the AI to answer in a format ``codepack apply`` can read."""
    git_diff: bool = False
    """Append ``git diff`` output as an extra section."""
    git_base: str = ""
    git_staged: bool = False
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
            "mask_secrets": self.mask_secrets,
            "reply_format": self.reply_format,
            "git_diff": self.git_diff,
            "git_base": self.git_base,
            "git_staged": self.git_staged,
            "transforms": list(self.transforms),
            "max_tokens_per_part": self.max_tokens_per_part,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PackOptions:
        scope = data.get("tree_scope", "selected")
        reply = data.get("reply_format", REPLY_NONE)
        max_tokens = data.get("max_tokens_per_part")
        return cls(
            format=str(data.get("format", "markdown")),
            include_tree=bool(data.get("include_tree", True)),
            tree_scope=scope if scope in ("selected", "all") else "selected",
            preamble=str(data.get("preamble", "")),
            mask_secrets=bool(data.get("mask_secrets", True)),
            reply_format=reply if reply in REPLY_FORMATS else REPLY_NONE,
            git_diff=bool(data.get("git_diff", False)),
            git_base=str(data.get("git_base", "")),
            git_staged=bool(data.get("git_staged", False)),
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
    findings: list[SecretFinding] = field(default_factory=list)
    """Secrets that were masked."""

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
    masker: SecretMasker | None = None,
) -> PackResult:
    options = options or PackOptions()
    estimator = estimator or DEFAULT_ESTIMATOR
    formatter = get_formatter(options.format)
    if options.mask_secrets and masker is None:
        masker = SecretMasker()

    packed: list[PackedFile] = []
    warnings: list[str] = []
    findings: list[SecretFinding] = []
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
        if options.mask_secrets and masker is not None:
            content, found = masker.mask(content, rel)
            findings.extend(found)
        packed.append(PackedFile(rel, entry.language, content, estimator.estimate(content)))

    sections: list[ExtraSection] = []
    if options.git_diff:
        from codepack.core.collectors.git import GitError, git_diff_text

        try:
            diff = git_diff_text(scan.root, options.git_base, options.git_staged)
        except GitError as exc:
            warnings.append(f"git diff: {exc}")
        else:
            if options.mask_secrets and masker is not None:
                diff, found = masker.mask(diff, "(git diff)")
                findings.extend(found)
            title = "Git Diff" + (f" (vs {options.git_base})" if options.git_base else "")
            sections.append(ExtraSection(title, diff or "(no changes)\n", "diff"))

    tree = ""
    if options.include_tree:
        tree_files = None if options.tree_scope == "all" else [p.rel_path for p in packed]
        tree = render_tree(scan, tree_files)

    doc = PackDocument(
        scan.project_name,
        tree,
        packed,
        options.preamble,
        sections=sections,
        postscript=reply_instructions(options.reply_format),
    )
    text = formatter.render(doc)
    return PackResult(
        parts=[text],
        total_tokens=estimator.estimate(text),
        per_file_tokens={p.rel_path: p.tokens for p in packed},
        files=[p.rel_path for p in packed],
        warnings=warnings,
        findings=findings,
    )
