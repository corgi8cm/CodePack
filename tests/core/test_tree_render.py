from codepack.core.scanner import scan_project
from codepack.core.tree_render import render_tree


def test_render_selected_files(make_project):
    root = make_project({"src/a.cpp": "a", "src/sub/b.h": "b", "main.py": "m", "other.txt": "o"})
    scan = scan_project(root)
    tree = render_tree(scan, ["src/a.cpp", "src/sub/b.h", "main.py"])
    assert tree == "\n".join(
        [
            "proj/",
            "├── src/",
            "│   ├── sub/",
            "│   │   └── b.h",
            "│   └── a.cpp",
            "└── main.py",
        ]
    )


def test_render_all_with_annotations(sample_project):
    scan = scan_project(sample_project)
    tree = render_tree(scan, annotate_excluded=True)
    assert "build/  [gitignore]" in tree
    assert "logo.png  [binary]" in tree
    assert "debug.log  [gitignore]" in tree
    assert "main.cpp" in tree


def test_render_ignores_unknown_and_empty(make_project):
    root = make_project({"a.py": "1"})
    scan = scan_project(root)
    assert render_tree(scan, []) == "proj/"
    assert render_tree(scan, ["nope.py"]) == "proj/"
