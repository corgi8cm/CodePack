import json

from codepack.core.deps import (
    CppIncludeResolver,
    DepOptions,
    PythonImportResolver,
    include_dirs_from_compile_commands,
    resolve_dependencies,
)
from codepack.core.models import ExcludeReason
from codepack.core.rules import RuleSet
from codepack.core.scanner import scan_project
from codepack.core.selection import Selection

# --- Python -----------------------------------------------------------------

PY_PROJECT = {
    "app/__init__.py": "",
    "app/main.py": (
        "import os\n"
        "import json as j\n"
        "import requests\n"
        "from app import config\n"
        "from app.core.engine import run\n"
        "from .utils import helper\n"
        "from . import plugins\n"
        "def f():\n"
        "    import app.lazy\n"
    ),
    "app/config.py": "DEBUG = True\n",
    "app/utils.py": "from .core import engine\ndef helper(): pass\n",
    "app/core/__init__.py": "",
    "app/core/engine.py": "def run(): pass\n",
    "app/plugins/__init__.py": "from .a import A\n",
    "app/plugins/a.py": "class A: pass\n",
    "app/lazy.py": "",
    "app/unused.py": "",
    "scripts/tool.py": "import helper_mod\nimport app.config\n",
    "scripts/helper_mod.py": "",
    "src/lib2/__init__.py": "",
    "src/lib2/x.py": "from lib2 import y\n",
    "src/lib2/y.py": "",
    "bad.py": "def (:\n",
}


def test_python_resolver_direct(make_project):
    scan = scan_project(make_project(PY_PROJECT))
    deps = PythonImportResolver(scan).dependencies("app/main.py", PY_PROJECT["app/main.py"])
    assert set(deps.resolved) == {
        "app/config.py", "app/core/engine.py", "app/utils.py", "app/plugins/__init__.py", "app/lazy.py",
    }
    # package __init__ files that only run implicitly are included but not followed
    assert set(deps.leaves) == {"app/__init__.py", "app/core/__init__.py"}
    assert deps.unresolved == ["requests"]  # stdlib is not reported


def test_implicit_package_init_not_followed(make_project):
    scan = scan_project(make_project({
        "pkg/__init__.py": "from pkg.heavy import H\nfrom pkg.light import L\n",
        "pkg/light.py": "L = 1\n",
        "pkg/heavy.py": "H = 1\n",
        "use_light.py": "from pkg.light import L\n",
        "use_pkg.py": "import pkg\n",
        "use_names.py": "from pkg import H\n",
    }))
    assert resolve_dependencies(scan, ["use_light.py"]).files == ["pkg/__init__.py", "pkg/light.py", "use_light.py"]
    # explicitly importing the package (or names defined by it) follows its __init__
    assert "pkg/heavy.py" in resolve_dependencies(scan, ["use_pkg.py"]).files
    assert "pkg/heavy.py" in resolve_dependencies(scan, ["use_names.py"]).files


def test_python_closure(make_project):
    scan = scan_project(make_project(PY_PROJECT))
    result = resolve_dependencies(scan, ["app/main.py"])
    assert "app/plugins/a.py" in result.files  # via plugins/__init__.py
    assert "app/unused.py" not in result.files
    assert result.targets == ["app/main.py"]
    assert "app/utils.py" in result.edges["app/main.py"]


def test_python_script_dir_and_src_layout(make_project):
    scan = scan_project(make_project(PY_PROJECT))
    tool = resolve_dependencies(scan, ["scripts/tool.py"], DepOptions(max_depth=1))
    assert {"scripts/helper_mod.py", "app/config.py", "app/__init__.py"} <= set(tool.files)
    lib = resolve_dependencies(scan, ["src/lib2/x.py"])
    assert "src/lib2/y.py" in lib.files


def test_python_syntax_error(make_project):
    scan = scan_project(make_project(PY_PROJECT))
    result = resolve_dependencies(scan, ["bad.py"])
    assert result.files == ["bad.py"]
    assert "bad.py" in result.unresolved


def test_max_depth(make_project):
    scan = scan_project(make_project(PY_PROJECT))
    direct = resolve_dependencies(scan, ["app/main.py"], DepOptions(max_depth=1))
    assert "app/plugins/a.py" not in direct.files
    none = resolve_dependencies(scan, ["app/main.py"], DepOptions(max_depth=0))
    assert none.files == ["app/main.py"]


# --- C++ --------------------------------------------------------------------

CPP_PROJECT = {
    "src/main.cpp": (
        '#include "app.h"\n'
        "#include <vector>\n"
        "#include <mylib/math.hpp>\n"
        '  #  include "detail/impl.h"\n'
        "// #include \"commented.h\" is still counted by design? no: line starts with //\n"
    ),
    "src/app.h": '#pragma once\n#include "util/strings.h"\n',
    "src/app.cpp": '#include "app.h"\n',
    "src/detail/impl.h": "#pragma once\n",
    "include/mylib/math.hpp": '#pragma once\n#include "../../src/detail/impl.h"\n',
    "lib/util/strings.h": "#pragma once\n",
    "lib/util/strings.cpp": '#include "strings.h"\n',
    "third_party/json.hpp": "",
    "other/util/strings.h": "",
}


def test_cpp_resolution_order(make_project):
    scan = scan_project(make_project(CPP_PROJECT))
    r = CppIncludeResolver(scan)
    assert r.resolve_include("src/main.cpp", "app.h", quoted=True) == "src/app.h"
    assert r.resolve_include("src/main.cpp", "mylib/math.hpp", quoted=False) == "include/mylib/math.hpp"
    assert r.resolve_include("include/mylib/math.hpp", "../../src/detail/impl.h", True) == "src/detail/impl.h"
    assert r.resolve_include("src/main.cpp", "vector", quoted=False) is None
    # suffix fallback picks the candidate sharing the longest path prefix
    assert r.resolve_include("lib/x.cpp", "util/strings.h", True) == "lib/util/strings.h"
    assert r.resolve_include("other/x.cpp", "util/strings.h", True) == "other/util/strings.h"


def test_cpp_closure(make_project):
    scan = scan_project(make_project(CPP_PROJECT))
    result = resolve_dependencies(scan, ["src/main.cpp"])
    assert set(result.files) >= {
        "src/main.cpp", "src/app.h", "include/mylib/math.hpp", "src/detail/impl.h",
    }
    assert "src/app.cpp" not in result.files
    assert "vector" in result.unresolved["src/main.cpp"]
    assert "commented.h" not in str(result.unresolved)


def test_cpp_pair_sources(make_project):
    scan = scan_project(make_project(CPP_PROJECT))
    result = resolve_dependencies(scan, ["src/main.cpp"], DepOptions(pair_sources=True))
    assert "src/app.cpp" in result.files
    header_only = resolve_dependencies(scan, ["src/app.h"], DepOptions(pair_sources=True, max_depth=1))
    assert "src/app.cpp" in header_only.files


def test_extra_include_dirs(make_project):
    files = dict(CPP_PROJECT, **{"src/x.cpp": "#include <json.hpp>\n"})
    scan = scan_project(make_project(files))
    assert resolve_dependencies(scan, ["src/x.cpp"]).files == ["src/x.cpp", "third_party/json.hpp"]  # suffix match
    r = CppIncludeResolver(scan, DepOptions(include_dirs=["third_party/"]))
    assert "third_party" in r.include_dirs


def test_compile_commands(make_project, tmp_path):
    root = make_project(dict(CPP_PROJECT))
    db = [
        {"directory": str(root / "build"), "file": "../src/main.cpp",
         "command": f'g++ -I../lib -isystem {root / "include"} -I/usr/include -DX=1 -c ../src/main.cpp'},
        {"directory": str(root), "file": "src/app.cpp", "arguments": ["cl", "/Ilib/util", "/c", "src/app.cpp"]},
    ]
    (root / "build").mkdir()
    (root / "build" / "compile_commands.json").write_text(json.dumps(db), encoding="utf-8")
    dirs = include_dirs_from_compile_commands(root)
    assert dirs == ["lib", "include", "lib/util"]
    scan = scan_project(root, RuleSet(use_gitignore=False))
    r = CppIncludeResolver(scan)
    assert "lib" in r.include_dirs
    assert r.resolve_include("src/main.cpp", "util/strings.h", quoted=False) == "lib/util/strings.h"


def test_excluded_dependencies_are_skipped_or_followed(make_project):
    scan = scan_project(make_project(CPP_PROJECT), RuleSet(include=["*.cpp", "*.h"]))
    result = resolve_dependencies(scan, ["src/main.cpp"])
    assert result.skipped == {"include/mylib/math.hpp": ExcludeReason.NOT_INCLUDED}
    assert "include/mylib/math.hpp" not in result.files
    forced = resolve_dependencies(scan, ["src/main.cpp"], DepOptions(follow_excluded=True))
    assert "include/mylib/math.hpp" in forced.files
    sel = Selection(scan)
    assert sel.select_only(forced.files) == []
    assert sel.checked_files() == forced.files


def test_unknown_targets_and_file_types(make_project):
    scan = scan_project(make_project({"a.txt": "x", "b.py": "import c\n"}))
    result = resolve_dependencies(scan, ["a.txt", "missing.py"])
    assert result.files == ["a.txt"]
    assert result.targets == ["a.txt"]
