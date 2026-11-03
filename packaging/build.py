"""Build CodePack.exe and codepack-cli.exe with PyInstaller.

Usage (from the project root, with the venv's Python):
    pip install -e .[build]
    python packaging/build.py

Outputs go to dist/. Works on Linux too (producing ELF binaries without icons).
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN_DLLS = ("qt6network.dll", "qt6webenginecore.dll", "qt6websockets.dll")
_DLL_RE = re.compile(r"'([A-Za-z]:\\\\[^']+\.(?:dll|pyd))'")


def bundled_binaries(workpath: Path) -> list[Path]:
    paths: set[str] = set()
    for toc in workpath.glob("*/EXE-*.toc"):
        paths.update(m.replace("\\\\", "\\") for m in _DLL_RE.findall(toc.read_text(encoding="utf-8")))
    return sorted(Path(p) for p in paths)


def verify_offline(workpath: Path) -> list[str]:
    """Problems found: networking DLLs bundled, or DLLs importing them."""
    problems = []
    binaries = bundled_binaries(workpath)
    names = {b.name.lower() for b in binaries}
    for name in FORBIDDEN_DLLS:
        if name in names:
            problems.append(f"bundled networking DLL: {name}")
    if sys.platform == "win32":
        import pefile  # installed with PyInstaller on Windows

        for path in binaries:
            try:
                pe = pefile.PE(str(path), fast_load=True)
                pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            except (OSError, pefile.PEFormatError):
                continue
            imports = {e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])}
            for dll in imports & set(FORBIDDEN_DLLS):
                problems.append(f"{path.name} imports {dll}")
    return problems


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:  pip install -e .[build]", file=sys.stderr)
        return 1
    # Intermediate files go to the temp folder: synced folders such as OneDrive
    # lock files in build/ and make PyInstaller's --clean fail.
    workpath = Path(tempfile.gettempdir()) / "codepack-pyinstaller"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist"), "--workpath", str(workpath),
        str(ROOT / "codepack.spec"),
    ]
    code = subprocess.call(cmd, cwd=ROOT)
    if code != 0:
        return code
    problems = verify_offline(workpath)
    for p in problems:
        print(f"offline check failed: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"offline check passed ({len(bundled_binaries(workpath))} binaries inspected)")
    suffix = ".exe" if sys.platform == "win32" else ""
    for name in ("CodePack", "codepack-cli"):
        exe = ROOT / "dist" / f"{name}{suffix}"
        if exe.exists():
            print(f"built {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
        else:
            print(f"missing {exe}", file=sys.stderr)
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
