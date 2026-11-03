import json
from pathlib import Path

import pytest

from codepack.core.packer import PackOptions
from codepack.core.preset import (
    Preset,
    all_presets,
    builtin_presets,
    default_preset,
    find_preset,
    load_preset,
    preset_filename,
    save_preset,
    user_preset_dir,
)
from codepack.core.rules import RuleSet


def test_builtin_presets_load():
    names = [p.name for p in builtin_presets()]
    assert names[0] == "default"
    assert {"default", "cpp", "python"} <= set(names)
    assert all(p.builtin for p in builtin_presets())
    assert "*.cpp" in find_preset("cpp").rules.include
    assert "__pycache__/" in default_preset().rules.exclude


def test_save_and_load_roundtrip(tmp_path: Path):
    preset = Preset(
        "mine",
        RuleSet(include=["*.py"], exclude=["tests/"], use_gitignore=False),
        PackOptions(format="xml", preamble="中文提示"),
        description="d",
    )
    path = tmp_path / "sub" / "mine.json"
    save_preset(preset, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "中文提示" in path.read_text(encoding="utf-8")
    assert load_preset(path) == preset


def test_missing_fields_get_defaults(tmp_path: Path):
    path = tmp_path / "old.json"
    path.write_text('{"name": "old"}', encoding="utf-8")
    p = load_preset(path)
    assert p.rules == RuleSet()
    assert p.options == PackOptions()


def test_newer_schema_rejected(tmp_path: Path):
    path = tmp_path / "new.json"
    path.write_text('{"name": "x", "schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_preset(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_preset(path)


def test_user_presets_override_builtin(tmp_path: Path):
    save_preset(Preset("cpp", RuleSet(include=["*.cc"])), tmp_path / "cpp.json")
    save_preset(Preset("extra"), tmp_path / "extra.json")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    presets = {p.name: p for p in all_presets(tmp_path)}
    assert presets["cpp"].rules.include == ["*.cc"]
    assert "extra" in presets
    assert find_preset("extra", tmp_path).name == "extra"
    with pytest.raises(KeyError):
        find_preset("nope", tmp_path)


def test_find_preset_by_path(tmp_path: Path):
    path = tmp_path / "x.json"
    save_preset(Preset("by-path"), path)
    assert find_preset(str(path)).name == "by-path"


def test_user_preset_dir_platform(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert user_preset_dir() == tmp_path / "CodePack" / "presets"
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert user_preset_dir() == tmp_path / "codepack" / "presets"


def test_preset_filename():
    assert preset_filename("My C++/Proj") == "My C___Proj.json"
    assert preset_filename("///") == "___.json"
    assert preset_filename("") == "preset.json"
