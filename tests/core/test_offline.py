"""Architecture guards: no networking anywhere, no GUI toolkit in core."""

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "codepack"

NETWORK_MODULES = {
    "socket", "ssl", "urllib", "http", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "xmlrpc", "requests", "httpx", "aiohttp", "urllib3", "tiktoken", "websocket", "websockets",
}
GUI_MODULES = {"PySide6", "PySide2", "PyQt5", "PyQt6", "tkinter", "wx", "gi"}
QT_NETWORK = {"PySide6.QtNetwork", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _top(name: str) -> str:
    return name.split(".")[0]


def test_no_network_imports_anywhere():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for name in _imports(path):
            if _top(name) in NETWORK_MODULES or name in QT_NETWORK:
                offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
    assert offenders == []


def test_core_does_not_import_gui():
    offenders = []
    for path in (PACKAGE / "core").rglob("*.py"):
        for name in _imports(path):
            if _top(name) in GUI_MODULES or _top(name) == "codepack" and ".gui" in name:
                offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
    assert offenders == []


def test_importing_core_and_cli_loads_no_gui_or_network():
    code = (
        "import sys, codepack.core, codepack.cli; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'tkinter', 'requests', 'urllib3')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=PACKAGE.parent, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
