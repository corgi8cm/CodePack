from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest


def _write_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_bytes(content.encode("utf-8"))
    return root


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory, monkeypatch) -> Path:
    """Keep presets and the masking key out of the real user profile."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.setenv("APPDATA", str(config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    return config


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[[dict[str, str | bytes]], Path]:
    """Create a fake project: ``make_project({"src/a.cpp": "int x;"})``."""

    def factory(files: dict[str, str | bytes], name: str = "proj") -> Path:
        root = tmp_path / name
        root.mkdir(exist_ok=True)
        return _write_tree(root, files)

    return factory


@pytest.fixture
def sample_project(make_project) -> Path:
    return make_project(
        {
            ".gitignore": "build/\n*.log\n",
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\n",
            "src/main.cpp": '#include "util.h"\nint main() { return 0; }\n',
            "src/util.h": "#pragma once\nint add(int a, int b);\n",
            "src/util.cpp": '#include "util.h"\nint add(int a, int b) { return a + b; }\n',
            "scripts/run.py": "print('hi')\n",
            "build/out.o": b"\x7fELF\x00\x00\x00",
            "build/gen.cpp": "// generated\n",
            "debug.log": "log line\n",
            "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
            "docs/readme.md": "# Docs\n",
        }
    )
