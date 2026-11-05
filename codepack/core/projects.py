"""The user's project list: several project folders to switch between.

Each project remembers what was last used for it (preset name, the rules and
output options as edited, and the manual check overrides), so switching back
restores the same state. Stored as JSON in ``user_config_dir()/projects.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from codepack.core.paths import user_config_dir

SCHEMA_VERSION = 1
PROJECTS_FILENAME = "projects.json"


def normalize_path(path: Path | str) -> str:
    """Absolute path string used as the project's identity."""
    return str(Path(path).expanduser().resolve())


def _same(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


@dataclass
class ProjectEntry:
    path: str
    name: str = ""
    preset: str = ""
    rules: dict | None = None
    """``RuleSet.to_dict()`` as last edited; ``None`` = use the preset's."""
    options: dict | None = None
    """``PackOptions.to_dict()`` as last edited; ``None`` = use the preset's."""
    forced_on: list[str] = field(default_factory=list)
    forced_off: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name or Path(self.path).name or self.path

    def to_dict(self) -> dict:
        data: dict = {"path": self.path, "name": self.name, "preset": self.preset}
        if self.rules is not None:
            data["rules"] = self.rules
        if self.options is not None:
            data["options"] = self.options
        data["forced_on"] = sorted(self.forced_on)
        data["forced_off"] = sorted(self.forced_off)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> ProjectEntry:
        def str_list(key: str) -> list[str]:
            value = data.get(key, [])
            return [str(v) for v in value] if isinstance(value, list) else []

        rules = data.get("rules")
        options = data.get("options")
        return cls(
            path=str(data["path"]),
            name=str(data.get("name", "")),
            preset=str(data.get("preset", "")),
            rules=rules if isinstance(rules, dict) else None,
            options=options if isinstance(options, dict) else None,
            forced_on=str_list("forced_on"),
            forced_off=str_list("forced_off"),
        )


@dataclass
class ProjectList:
    projects: list[ProjectEntry] = field(default_factory=list)
    current: str = ""
    """Path of the project that was open last."""

    def find(self, path: Path | str) -> ProjectEntry | None:
        target = normalize_path(path)
        for p in self.projects:
            if _same(p.path, target):
                return p
        return None

    def find_by_name(self, name: str) -> ProjectEntry | None:
        """Look up by display name (case-insensitive); ``None`` if absent or ambiguous."""
        matches = [p for p in self.projects if p.display_name.casefold() == name.casefold()]
        return matches[0] if len(matches) == 1 else None

    def add(self, path: Path | str, name: str = "") -> ProjectEntry:
        """Add a project (or return the existing entry for the same folder)."""
        existing = self.find(path)
        if existing is not None:
            if name:
                existing.name = name
            return existing
        entry = ProjectEntry(normalize_path(path), name=name)
        self.projects.append(entry)
        return entry

    def remove(self, path: Path | str) -> bool:
        entry = self.find(path)
        if entry is None:
            return False
        self.projects.remove(entry)
        if _same(self.current, entry.path):
            self.current = ""
        return True

    def move(self, path: Path | str, offset: int) -> None:
        entry = self.find(path)
        if entry is None:
            return
        i = self.projects.index(entry)
        j = max(0, min(len(self.projects) - 1, i + offset))
        self.projects.insert(j, self.projects.pop(i))

    def current_entry(self) -> ProjectEntry | None:
        return self.find(self.current) if self.current else None

    def resolve(self, arg: str) -> Path | None:
        """Turn a CLI argument into a folder: an existing directory, or a project name."""
        if Path(arg).is_dir():
            return Path(arg)
        entry = self.find_by_name(arg)
        return Path(entry.path) if entry is not None else None

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "current": self.current,
            "projects": [p.to_dict() for p in self.projects],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectList:
        if int(data.get("schema_version", SCHEMA_VERSION)) > SCHEMA_VERSION:
            raise ValueError("projects file is from a newer CodePack")
        projects = []
        for item in data.get("projects", []):
            if isinstance(item, dict) and item.get("path"):
                projects.append(ProjectEntry.from_dict(item))
        return cls(projects, str(data.get("current", "")))


def projects_path() -> Path:
    return user_config_dir() / PROJECTS_FILENAME


def load_projects(path: Path | None = None) -> ProjectList:
    """Load the list; a missing or unreadable file gives an empty list."""
    path = path or projects_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectList.from_dict(data) if isinstance(data, dict) else ProjectList()
    except (OSError, ValueError, TypeError, KeyError):
        return ProjectList()


def save_projects(projects: ProjectList, path: Path | None = None) -> None:
    path = path or projects_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(projects.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
