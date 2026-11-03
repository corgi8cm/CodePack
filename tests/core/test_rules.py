from pathlib import Path

from codepack.core.models import ExcludeReason
from codepack.core.rules import GitignoreStack, RuleSet, parse_rule_lines


def test_parse_rule_lines_strips_blanks_and_comments():
    text = "  *.cpp \n\n# comment\nbuild/\n   \n"
    assert parse_rule_lines(text) == ["*.cpp", "build/"]
    assert parse_rule_lines(["a", " ", "#x", "b "]) == ["a", "b"]


def test_empty_rules_include_everything():
    rules = RuleSet().compile()
    assert rules.classify_file("src/a.cpp") is None
    assert rules.classify_dir("src") is None


def test_include_limits_files_but_not_dirs():
    rules = RuleSet(include=["*.cpp", "*.h"]).compile()
    assert rules.classify_file("src/a.cpp") is None
    assert rules.classify_file("include/b.h") is None
    assert rules.classify_file("scripts/run.py") is ExcludeReason.NOT_INCLUDED
    assert rules.classify_dir("scripts") is None


def test_exclude_overrides_include():
    rules = RuleSet(include=["*.cpp"], exclude=["tests/"]).compile()
    assert rules.classify_file("tests/t.cpp") is ExcludeReason.EXCLUDE_RULE
    assert rules.classify_dir("tests") is ExcludeReason.EXCLUDE_RULE
    assert rules.classify_dir("src/tests") is ExcludeReason.EXCLUDE_RULE
    assert rules.classify_file("src/a.cpp") is None


def test_anchored_patterns():
    rules = RuleSet(exclude=["/third_party/", "**/gen_*.cpp"]).compile()
    assert rules.classify_dir("third_party") is ExcludeReason.EXCLUDE_RULE
    assert rules.classify_dir("src/third_party") is None
    assert rules.classify_file("a/b/gen_x.cpp") is ExcludeReason.EXCLUDE_RULE


def test_ruleset_dict_roundtrip():
    rules = RuleSet(include=["*.py"], exclude=["venv/"], use_gitignore=False, max_file_size=10)
    assert RuleSet.from_dict(rules.to_dict()) == rules
    assert RuleSet.from_dict({}) == RuleSet()


def test_gitignore_root_patterns():
    stack = GitignoreStack()
    stack.add_patterns("", ["build/", "*.log", "!keep.log"])
    assert stack.is_ignored("build", is_dir=True)
    assert not stack.is_ignored("build", is_dir=False)
    assert stack.is_ignored("a/debug.log", is_dir=False)
    assert not stack.is_ignored("keep.log", is_dir=False)
    assert not stack.is_ignored("src/a.cpp", is_dir=False)


def test_gitignore_nested_overrides_parent():
    stack = GitignoreStack()
    stack.add_patterns("", ["*.txt"])
    stack.add_patterns("sub", ["!notes.txt", "local.cfg", "/only_here"])
    assert stack.is_ignored("a.txt", False)
    assert stack.is_ignored("sub/other.txt", False)
    assert not stack.is_ignored("sub/notes.txt", False)
    assert stack.is_ignored("sub/deep/local.cfg", False)
    assert not stack.is_ignored("local.cfg", False)
    assert stack.is_ignored("sub/only_here", False)
    assert not stack.is_ignored("sub/x/only_here", False)


def test_gitignore_load_dir_reads_files(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("# c\n*.tmp\r\n", encoding="utf-8")
    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("secret/\n", encoding="utf-8")
    stack = GitignoreStack()
    stack.load_dir(tmp_path, "")
    stack.load_dir(tmp_path, "missing")  # no file: no error
    assert stack.is_ignored("x.tmp", False)
    assert stack.is_ignored("secret", True)
