import json
import sys

import pytest

from codepack.core.projects import (
    ProjectList,
    load_projects,
    normalize_path,
    projects_path,
    save_projects,
)


def test_add_find_remove(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    pl = ProjectList()
    ea = pl.add(a)
    assert ea.path == normalize_path(a) and ea.display_name == "a"
    assert pl.add(a / "." ) is ea  # same folder: no duplicate
    pl.add(b, name="後端")
    assert [p.display_name for p in pl.projects] == ["a", "後端"]
    assert pl.find(str(b)).name == "後端"
    pl.current = ea.path
    assert pl.current_entry() is ea
    assert pl.remove(a) and pl.current == ""
    assert not pl.remove(a)
    assert pl.find(a) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths are case-insensitive")
def test_find_ignores_case_on_windows(tmp_path):
    pl = ProjectList()
    pl.add(tmp_path)
    assert pl.find(str(tmp_path).upper()) is not None


def test_move(tmp_path):
    pl = ProjectList()
    for n in "abc":
        pl.add(tmp_path / n)
    pl.move(tmp_path / "c", -5)
    assert [p.display_name for p in pl.projects] == ["c", "a", "b"]
    pl.move(tmp_path / "c", 1)
    assert [p.display_name for p in pl.projects] == ["a", "c", "b"]


def test_resolve(tmp_path):
    (tmp_path / "proj").mkdir()
    pl = ProjectList()
    pl.add(tmp_path / "proj", name="Engine")
    assert pl.resolve(str(tmp_path / "proj")) == tmp_path / "proj"
    assert pl.resolve("engine") == tmp_path.resolve() / "proj"
    assert pl.resolve("nope") is None
    pl.add(tmp_path / "other", name="engine")  # now ambiguous
    assert pl.resolve("engine") is None


def test_round_trip_keeps_state(tmp_path):
    path = tmp_path / "projects.json"
    pl = ProjectList()
    e = pl.add(tmp_path / "x", name="X")
    e.preset = "cpp"
    e.rules = {"include": ["*.cpp"]}
    e.options = {"format": "xml"}
    e.forced_on = ["b.log", "a.log"]
    e.forced_off = ["src/big.cpp"]
    pl.current = e.path
    save_projects(pl, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["projects"][0]["forced_on"] == ["a.log", "b.log"]
    loaded = load_projects(path)
    got = loaded.current_entry()
    assert (got.name, got.preset, got.rules, got.options) == ("X", "cpp", {"include": ["*.cpp"]}, {"format": "xml"})
    assert sorted(got.forced_on) == ["a.log", "b.log"] and got.forced_off == ["src/big.cpp"]


def test_old_or_partial_entries_get_defaults(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"projects": [{"path": str(tmp_path)}, {"name": "no path"}, "junk"]}), encoding="utf-8")
    pl = load_projects(path)
    assert len(pl.projects) == 1
    e = pl.projects[0]
    assert (e.preset, e.rules, e.options, e.forced_on) == ("", None, None, [])


def test_bad_files_give_empty_list(tmp_path):
    path = tmp_path / "projects.json"
    assert load_projects(path).projects == []
    path.write_text("{broken", encoding="utf-8")
    assert load_projects(path).projects == []
    path.write_text('{"schema_version": 99, "projects": [{"path": "x"}]}', encoding="utf-8")
    assert load_projects(path).projects == []


def test_default_path_in_config_dir(isolated_config, tmp_path):
    pl = ProjectList()
    pl.add(tmp_path)
    save_projects(pl)
    assert projects_path().is_file()
    assert isolated_config in projects_path().parents
