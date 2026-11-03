"""Tests for binary detection, decoding, language detection, tokens and models."""

from pathlib import Path

import pytest

from codepack.core.binary import has_binary_extension, is_binary, is_binary_bytes
from codepack.core.languages import detect_language
from codepack.core.models import (
    DirEntry,
    ExcludeReason,
    FileEntry,
    ScanResult,
    is_under,
    join_rel,
    parent_of,
)
from codepack.core.reader import decode_bytes, read_text
from codepack.core.tokens import CharTokenEstimator, TokenEstimator


# --- binary ---------------------------------------------------------------

def test_binary_extension():
    assert has_binary_extension("a.DLL")
    assert has_binary_extension("x.pyc")
    assert not has_binary_extension("a.cpp")
    assert not has_binary_extension("Makefile")


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", False),
        (b"int main() {}\n\ttab\r\n", False),
        ("中文註解".encode("utf-8"), False),
        ("中文".encode("cp950"), False),
        (b"abc\x00def", True),
        (bytes(range(1, 32)) * 10, True),
        ("text".encode("utf-16"), False),
    ],
)
def test_is_binary_bytes(data, expected):
    assert is_binary_bytes(data) is expected


def test_is_binary_file(tmp_path: Path):
    (tmp_path / "a.png").write_text("not really png")
    (tmp_path / "blob").write_bytes(b"\x00\x01\x02")
    (tmp_path / "a.cpp").write_text("int x;")
    assert is_binary(tmp_path / "a.png")
    assert is_binary(tmp_path / "blob")
    assert not is_binary(tmp_path / "a.cpp")


# --- reader ---------------------------------------------------------------

def test_decode_utf8_and_crlf():
    text, enc = decode_bytes(b"a\r\nb\rc\n")
    assert text == "a\nb\nc\n"
    assert enc == "utf-8"


def test_decode_bom_variants():
    assert decode_bytes(b"\xef\xbb\xbfhi") == ("hi", "utf-8-sig")
    assert decode_bytes("hi".encode("utf-16")) == ("hi", "utf-16")


def test_decode_cp950_fallback():
    text, enc = decode_bytes("// 中文註解\n".encode("cp950"))
    assert text == "// 中文註解\n"
    assert enc == "cp950"


def test_decode_never_raises():
    text, _ = decode_bytes(bytes(range(128, 256)))
    assert isinstance(text, str)


def test_read_text(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_bytes(b"print(1)\r\n")
    assert read_text(p) == "print(1)\n"


# --- languages ------------------------------------------------------------

@pytest.mark.parametrize(
    "name,lang",
    [
        ("main.cpp", "cpp"),
        ("util.H", "c"),
        ("x.hpp", "cpp"),
        ("run.py", "python"),
        ("CMakeLists.txt", "cmake"),
        ("Makefile", "makefile"),
        ("notes.txt", "text"),
        ("LICENSE", ""),
        (".bashrc", ""),
        (".gitignore", "gitignore"),
    ],
)
def test_detect_language(name, lang):
    assert detect_language(name) == lang


# --- tokens ---------------------------------------------------------------

def test_char_estimator_ascii_and_cjk():
    est = CharTokenEstimator()
    assert isinstance(est, TokenEstimator)
    assert est.estimate("") == 0
    assert est.estimate("abcd") == 1
    assert est.estimate("abcde") == 2
    assert est.estimate("中文字") == 3
    assert est.estimate("abcd中文") == 3


def test_char_estimator_custom_ratio():
    est = CharTokenEstimator(chars_per_token=2, cjk_weight=0.5)
    assert est.estimate("abcd") == 2
    assert est.estimate("中文") == 1
    assert est.estimate_from_size(10) == 5
    with pytest.raises(ValueError):
        CharTokenEstimator(chars_per_token=0)


# --- models ---------------------------------------------------------------

def test_path_helpers():
    assert parent_of("a/b/c.py") == "a/b"
    assert parent_of("c.py") == ""
    assert join_rel("", "a") == "a"
    assert join_rel("a", "b") == "a/b"
    assert is_under("a/b", "a")
    assert is_under("a", "a")
    assert not is_under("ab/c", "a")
    assert is_under("anything", "")


def test_exclude_reason_forceable():
    assert ExcludeReason.GITIGNORE.forceable
    assert ExcludeReason.TOO_LARGE.forceable
    assert not ExcludeReason.BINARY.forceable
    assert not ExcludeReason.UNREADABLE.forceable


def test_scan_result_index(tmp_path: Path):
    scan = ScanResult(
        root=tmp_path,
        files={
            "z.txt": FileEntry("z.txt", 1, 1),
            "B.txt": FileEntry("B.txt", 1, 1, ExcludeReason.BINARY),
            "src/a.cpp": FileEntry("src/a.cpp", 2, 1),
            "src/sub/b.h": FileEntry("src/sub/b.h", 3, 1),
        },
        dirs={"": DirEntry(""), "src": DirEntry("src"), "src/sub": DirEntry("src/sub"),
              "build": DirEntry("build", ExcludeReason.GITIGNORE)},
    )
    assert scan.children("") == ["build", "src", "B.txt", "z.txt"]
    assert scan.children("src") == ["src/sub", "src/a.cpp"]
    assert scan.children("build") == []
    assert scan.files_under("src") == ["src/a.cpp", "src/sub/b.h"]
    assert len(scan.files_under("")) == 4
    assert scan.included_files() == ["src/a.cpp", "src/sub/b.h", "z.txt"]
    assert scan.total_size == 7
    assert scan.project_name == tmp_path.name
