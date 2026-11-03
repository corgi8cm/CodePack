import os
from pathlib import Path

import pytest

from codepack.core.models import ExcludeReason
from codepack.core.rules import RuleSet
from codepack.core.scanner import ScanCancelled, scan_project


def test_scan_classifies_files(sample_project: Path):
    scan = scan_project(sample_project)
    files = scan.files
    assert files["src/main.cpp"].included
    assert files["src/main.cpp"].language == "cpp"
    assert files["src/main.cpp"].tokens > 0
    assert files["CMakeLists.txt"].language == "cmake"
    assert files["debug.log"].excluded is ExcludeReason.GITIGNORE
    assert files["debug.log"].tokens > 0  # excluded text files still get a count
    assert files["assets/logo.png"].excluded is ExcludeReason.BINARY
    assert files[".gitignore"].included


def test_ignored_dir_is_pruned(sample_project: Path):
    scan = scan_project(sample_project)
    assert scan.dirs["build"].pruned is ExcludeReason.GITIGNORE
    assert not any(r.startswith("build/") for r in scan.files)


def test_gitignore_can_be_disabled(sample_project: Path):
    scan = scan_project(sample_project, RuleSet(use_gitignore=False))
    assert scan.dirs["build"].pruned is None
    assert scan.files["build/gen.cpp"].included
    assert scan.files["build/out.o"].excluded is ExcludeReason.BINARY
    assert scan.files["debug.log"].included


def test_include_and_exclude_rules(sample_project: Path):
    rules = RuleSet(include=["*.cpp", "*.h"], exclude=["docs/"])
    scan = scan_project(sample_project, rules)
    assert scan.files["src/util.h"].included
    assert scan.files["scripts/run.py"].excluded is ExcludeReason.NOT_INCLUDED
    assert scan.dirs["docs"].pruned is ExcludeReason.EXCLUDE_RULE
    assert scan.files["debug.log"].excluded is ExcludeReason.GITIGNORE


def test_git_dir_always_skipped(make_project):
    root = make_project({".git/config": "x", ".git/objects/ab": "y", "a.py": "1"})
    scan = scan_project(root, RuleSet(use_gitignore=False))
    assert ".git" not in scan.dirs
    assert list(scan.files) == ["a.py"]


def test_nested_gitignore(make_project):
    root = make_project(
        {
            ".gitignore": "*.txt\n",
            "sub/.gitignore": "!keep.txt\ngen/\n",
            "sub/keep.txt": "k",
            "sub/drop.txt": "d",
            "sub/gen/x.cpp": "x",
            "gen/y.cpp": "y",
        }
    )
    scan = scan_project(root)
    assert scan.files["sub/keep.txt"].included
    assert scan.files["sub/drop.txt"].excluded is ExcludeReason.GITIGNORE
    assert scan.dirs["sub/gen"].pruned is ExcludeReason.GITIGNORE
    assert scan.files["gen/y.cpp"].included


def test_too_large(make_project):
    root = make_project({"big.cpp": "x" * 2000, "small.cpp": "y"})
    scan = scan_project(root, RuleSet(max_file_size=1000))
    assert scan.files["big.cpp"].excluded is ExcludeReason.TOO_LARGE
    assert scan.files["big.cpp"].tokens == 500
    assert scan.files["big.cpp"].checkable
    assert scan.files["small.cpp"].included


def test_binary_by_content(make_project):
    root = make_project({"data.dat": b"\x00\x01\x02\x03", "text.dat": "hello"})
    scan = scan_project(root)
    assert scan.files["data.dat"].excluded is ExcludeReason.BINARY
    assert not scan.files["data.dat"].checkable
    assert scan.files["text.dat"].included


def test_children_order(sample_project: Path):
    scan = scan_project(sample_project)
    top = scan.children("")
    dirs = [c for c in top if c in scan.dirs]
    assert dirs == ["assets", "build", "docs", "scripts", "src"]
    assert top[: len(dirs)] == dirs


def test_progress_and_cancel(sample_project: Path):
    seen = []
    scan_project(sample_project, progress=lambda n, rel: seen.append((n, rel)))
    assert seen and seen[-1][0] == len(seen)

    with pytest.raises(ScanCancelled):
        scan_project(sample_project, cancel=lambda: True)


def test_not_a_directory(tmp_path: Path):
    with pytest.raises(NotADirectoryError):
        scan_project(tmp_path / "missing")


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinked_dir_not_followed(make_project):
    root = make_project({"real/a.py": "1"})
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    scan = scan_project(root)
    assert "link/a.py" not in scan.files
