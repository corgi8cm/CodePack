from codepack.core.packer import PackOptions, build_pack
from codepack.core.scanner import scan_project
from codepack.core.selection import Selection


def test_build_pack_markdown(sample_project):
    scan = scan_project(sample_project)
    files = Selection(scan).checked_files()
    result = build_pack(scan, files)
    assert len(result.parts) == 1
    text = result.text
    assert text.startswith("# Project: proj")
    assert "### `src/main.cpp`" in text
    assert "debug.log" not in text
    assert result.files == files
    assert set(result.per_file_tokens) == set(files)
    assert result.total_tokens > sum(result.per_file_tokens.values())  # includes formatting overhead
    assert result.char_count == len(text)
    assert result.warnings == []


def test_tree_scope(sample_project):
    scan = scan_project(sample_project)
    selected = build_pack(scan, ["src/main.cpp"], PackOptions(tree_scope="selected")).text
    full = build_pack(scan, ["src/main.cpp"], PackOptions(tree_scope="all")).text
    assert "scripts/" not in selected
    assert "scripts/" in full
    no_tree = build_pack(scan, ["src/main.cpp"], PackOptions(include_tree=False)).text
    assert "Directory Structure" not in no_tree


def test_preamble_and_formats(sample_project):
    scan = scan_project(sample_project)
    for fmt in ("markdown", "xml", "plain"):
        result = build_pack(scan, ["src/util.h"], PackOptions(format=fmt, preamble="Explain this"))
        assert "Explain this" in result.text
        assert "#pragma once" in result.text


def test_missing_and_unreadable_files_warn(sample_project):
    scan = scan_project(sample_project)
    (sample_project / "src" / "util.cpp").unlink()
    result = build_pack(scan, ["src/main.cpp", "src/util.cpp", "nope.cpp"])
    assert result.files == ["src/main.cpp"]
    assert len(result.warnings) == 2


def test_crlf_normalized(make_project):
    root = make_project({"a.cpp": b"int a;\r\nint b;\r\n"})
    scan = scan_project(root)
    assert "\r" not in build_pack(scan, ["a.cpp"]).text


def test_options_roundtrip():
    opts = PackOptions(format="xml", include_tree=False, tree_scope="all", preamble="p", max_tokens_per_part=100)
    assert PackOptions.from_dict(opts.to_dict()) == opts
    assert PackOptions.from_dict({"tree_scope": "bogus"}).tree_scope == "selected"
