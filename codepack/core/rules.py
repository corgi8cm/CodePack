"""Include / exclude rules and .gitignore handling.

All patterns use gitignore syntax (via ``pathspec.GitIgnoreSpec``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pathspec import GitIgnoreSpec

from codepack.core.models import ExcludeReason

DEFAULT_MAX_FILE_SIZE = 1_000_000


def parse_rule_lines(text: str | Iterable[str]) -> list[str]:
    """Split text into rule lines, dropping blanks and ``#`` comments."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    rules = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rules.append(stripped)
    return rules


def _spec(patterns: Iterable[str]) -> GitIgnoreSpec:
    return GitIgnoreSpec.from_lines(list(patterns))


def _match_path(rel_path: str, is_dir: bool) -> str:
    return rel_path + "/" if is_dir else rel_path


@dataclass
class RuleSet:
    include: list[str] = field(default_factory=list)
    """Empty means include everything."""
    exclude: list[str] = field(default_factory=list)
    """Exclude wins over include."""
    use_gitignore: bool = True
    max_file_size: int = DEFAULT_MAX_FILE_SIZE

    def compile(self) -> CompiledRules:
        return CompiledRules(self)

    def to_dict(self) -> dict:
        return {
            "include": list(self.include),
            "exclude": list(self.exclude),
            "use_gitignore": self.use_gitignore,
            "max_file_size": self.max_file_size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RuleSet:
        return cls(
            include=parse_rule_lines(data.get("include", [])),
            exclude=parse_rule_lines(data.get("exclude", [])),
            use_gitignore=bool(data.get("use_gitignore", True)),
            max_file_size=int(data.get("max_file_size", DEFAULT_MAX_FILE_SIZE)),
        )


class CompiledRules:
    """A RuleSet with its patterns compiled for fast matching."""

    def __init__(self, rules: RuleSet):
        self.rules = rules
        self._include = _spec(rules.include) if rules.include else None
        self._exclude = _spec(rules.exclude) if rules.exclude else None

    def classify_dir(self, rel_path: str) -> ExcludeReason | None:
        """Include patterns never prune directories; only exclude does."""
        if self._exclude is not None and self._exclude.match_file(_match_path(rel_path, True)):
            return ExcludeReason.EXCLUDE_RULE
        return None

    def classify_file(self, rel_path: str) -> ExcludeReason | None:
        if self._exclude is not None and self._exclude.match_file(rel_path):
            return ExcludeReason.EXCLUDE_RULE
        if self._include is not None and not self._include.match_file(rel_path):
            return ExcludeReason.NOT_INCLUDED
        return None


class GitignoreStack:
    """Collects .gitignore files per directory and applies git's precedence.

    Patterns in ``sub/.gitignore`` are relative to ``sub``; deeper files
    override shallower ones, and later lines override earlier lines.
    """

    def __init__(self) -> None:
        self._specs: dict[str, GitIgnoreSpec] = {}

    def add_patterns(self, dir_rel: str, lines: Iterable[str]) -> None:
        patterns = [ln.rstrip("\r\n") for ln in lines]
        patterns = [p for p in patterns if p.strip() and not p.lstrip().startswith("#")]
        if not patterns:
            return
        if dir_rel in self._specs:
            existing = [p.pattern for p in self._specs[dir_rel].patterns]
            patterns = existing + patterns
        self._specs[dir_rel] = _spec(patterns)

    def load_dir(self, root: Path, dir_rel: str) -> None:
        """Read ``<dir>/.gitignore`` (and ``.git/info/exclude`` at the root)."""
        base = root / dir_rel if dir_rel else root
        candidates = [base / ".gitignore"]
        if not dir_rel:
            candidates.insert(0, base / ".git" / "info" / "exclude")
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            self.add_patterns(dir_rel, text.splitlines())

    def is_ignored(self, rel_path: str, is_dir: bool) -> bool:
        ignored = False
        for dir_rel, spec in self._specs.items():
            if dir_rel:
                if not rel_path.startswith(dir_rel + "/"):
                    continue
                sub = rel_path[len(dir_rel) + 1:]
            else:
                sub = rel_path
            # Shallower directories come first because they were loaded first
            # during the walk; deeper results override.
            result = spec.check_file(_match_path(sub, is_dir))
            if result.include is not None:
                ignored = result.include
        return ignored
