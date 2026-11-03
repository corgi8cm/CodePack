"""Presets: a named RuleSet + PackOptions stored as JSON."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from codepack.core.packer import PackOptions
from codepack.core.rules import RuleSet

SCHEMA_VERSION = 1
PRESET_SUFFIX = ".json"


@dataclass
class Preset:
    name: str
    rules: RuleSet = field(default_factory=RuleSet)
    options: PackOptions = field(default_factory=PackOptions)
    description: str = ""
    builtin: bool = field(default=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "description": self.description,
            "rules": self.rules.to_dict(),
            "options": self.options.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, builtin: bool = False) -> Preset:
        version = int(data.get("schema_version", SCHEMA_VERSION))
        if version > SCHEMA_VERSION:
            raise ValueError(f"preset schema_version {version} is newer than supported ({SCHEMA_VERSION})")
        return cls(
            name=str(data.get("name", "unnamed")),
            description=str(data.get("description", "")),
            rules=RuleSet.from_dict(data.get("rules", {})),
            options=PackOptions.from_dict(data.get("options", {})),
            builtin=builtin,
        )


def load_preset(path: Path | str) -> Preset:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: preset must be a JSON object")
    return Preset.from_dict(data)


def save_preset(preset: Preset, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def builtin_presets() -> list[Preset]:
    presets = []
    folder = resources.files("codepack.core").joinpath("presets")
    for item in sorted(folder.iterdir(), key=lambda p: p.name):
        if item.name.endswith(PRESET_SUFFIX):
            presets.append(Preset.from_dict(json.loads(item.read_text(encoding="utf-8")), builtin=True))
    presets.sort(key=lambda p: (p.name != "default", p.name))
    return presets


def default_preset() -> Preset:
    for p in builtin_presets():
        if p.name == "default":
            return p
    return Preset("default", builtin=True)


def user_preset_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "CodePack" / "presets"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "codepack" / "presets"


def user_presets(directory: Path | None = None) -> list[Preset]:
    directory = directory or user_preset_dir()
    if not directory.is_dir():
        return []
    presets = []
    for path in sorted(directory.glob(f"*{PRESET_SUFFIX}")):
        try:
            presets.append(load_preset(path))
        except (OSError, ValueError):
            continue
    return presets


def all_presets(directory: Path | None = None) -> list[Preset]:
    """Built-in presets first; a user preset with the same name replaces the built-in."""
    by_name = {p.name: p for p in builtin_presets()}
    for p in user_presets(directory):
        by_name[p.name] = p
    return list(by_name.values())


def find_preset(name_or_path: str, directory: Path | None = None) -> Preset:
    """Look up a preset by name, or load it from a file path."""
    candidate = Path(name_or_path)
    if candidate.suffix == PRESET_SUFFIX and candidate.is_file():
        return load_preset(candidate)
    for p in all_presets(directory):
        if p.name == name_or_path:
            return p
    raise KeyError(f"preset {name_or_path!r} not found")


def preset_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "preset"
    return safe + PRESET_SUFFIX
