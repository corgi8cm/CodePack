import json

import pytest

from codepack.core.apply import parse_reply
from codepack.core.prompts import (
    all_templates,
    builtin_templates,
    delete_template,
    find_template,
    load_user_templates,
    prompts_path,
    set_template,
)


def test_builtins():
    names = [t.name for t in builtin_templates()]
    assert names[0] == "修改程式(完整檔案格式)"
    assert len(names) == len(set(names))
    first = builtin_templates()[0]
    assert first.source == "builtin"
    assert "=== FILE: 相對路徑 ===" in first.text and "=== END FILE ===" in first.text
    assert first.text.rstrip().endswith("我想問:")


def test_file_format_example_is_parseable():
    # The example block in the template must match what `apply` understands.
    text = find_template("修改程式(完整檔案格式)").text
    parsed = parse_reply(text)
    assert [e.path for e in parsed.edits] == ["相對路徑", "相對路徑"]  # FILE block + DELETE line


def test_user_template_add_edit_delete(tmp_path):
    path = tmp_path / "prompts.json"
    set_template("效能分析", "請找出效能瓶頸。\n", path)
    assert find_template("效能分析", path).source == "user"
    set_template("效能分析", "改過的內容\n", path)
    assert find_template("效能分析", path).text == "改過的內容\n"
    assert [t.name for t in all_templates(path)][-1] == "效能分析"
    delete_template("效能分析", path)
    with pytest.raises(KeyError):
        find_template("效能分析", path)
    with pytest.raises(KeyError):
        delete_template("不存在", path)
    with pytest.raises(ValueError):
        set_template("  ", "x", path)


def test_override_and_restore_builtin(tmp_path):
    path = tmp_path / "prompts.json"
    name = builtin_templates()[2].name
    original = builtin_templates()[2].text
    set_template(name, "我的版本\n", path)
    t = find_template(name, path)
    assert (t.text, t.source) == ("我的版本\n", "override")
    names = [x.name for x in all_templates(path)]
    assert names.count(name) == 1 and names.index(name) == 2  # stays in place
    delete_template(name, path)  # restore default
    assert find_template(name, path).text == original
    delete_template(name, path)  # already default: no error
    set_template(name, original, path)  # saving the default text stores nothing
    assert load_user_templates(path) == []


def test_file_format_is_json_with_schema(tmp_path):
    path = tmp_path / "prompts.json"
    set_template("A", "中文內容", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"schema_version": 1, "templates": [{"name": "A", "text": "中文內容"}]}


def test_bad_files_are_ignored(tmp_path):
    path = tmp_path / "prompts.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_user_templates(path) == []
    path.write_text('{"schema_version": 99, "templates": [{"name": "x", "text": "y"}]}', encoding="utf-8")
    assert load_user_templates(path) == []
    path.write_text('{"templates": [{"name": "", "text": "y"}, "junk", {"name": "ok"}]}', encoding="utf-8")
    assert [t.name for t in load_user_templates(path)] == ["ok"]


def test_default_path_in_config_dir(isolated_config):
    set_template("X", "y")
    assert prompts_path().is_file()
    assert isolated_config in prompts_path().parents
