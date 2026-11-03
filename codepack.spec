# PyInstaller spec: builds two single-file executables.
#   CodePack.exe      windowed GUI
#   codepack-cli.exe  console CLI (no Qt inside, so it is small and starts fast)
# Build with:  python packaging/build.py

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "codepack" / "__init__.py").read_text(encoding="utf-8")).group(1)
ICON = str(ROOT / "codepack" / "gui" / "codepack.ico")

PRESETS = (str(ROOT / "codepack" / "core" / "presets" / "*.json"), "codepack/core/presets")
GUI_DATAS = [PRESETS, (ICON, "codepack/gui")]

# Everything Qt-related the GUI does not use. QtNetwork is excluded on purpose:
# CodePack must never open a network connection.
QT_UNUSED = [
    "PySide6.QtNetwork", "PySide6.QtNetworkAuth", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvg",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtXml",
]
STDLIB_UNUSED = ["tkinter", "unittest", "pydoc", "xmlrpc", "http.server", "ftplib", "smtplib"]

# Qt plugins collected by PyInstaller's hooks that drag networking back in:
# the PDF image plugin needs Qt6Pdf -> Qt6Qml/Qt6Quick -> Qt6Network, and the
# TUIO touch plugin listens on UDP. Drop them and every Qt networking/QML DLL.
UNWANTED_BINARIES = re.compile(
    r"(Qt6(Network|Pdf|Qml|Quick|WebEngine|WebChannel|WebSockets|Positioning)\w*\.dll"
    r"|qtuiotouchplugin|imageformats[\\/]qpdf|[\\/]tls[\\/]|networkinformation)",
    re.IGNORECASE,
)


def version_info(internal_name: str, description: str):
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("ProductName", "CodePack"),
                StringStruct("FileDescription", description),
                StringStruct("InternalName", internal_name),
                StringStruct("OriginalFilename", f"{internal_name}.exe"),
                StringStruct("FileVersion", VERSION),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


def build(entry: str, name: str, datas, excludes, console: bool, description: str):
    a = Analysis(
        [str(ROOT / "packaging" / entry)],
        pathex=[str(ROOT)],
        datas=datas,
        excludes=excludes,
        noarchive=False,
    )
    a.binaries = [b for b in a.binaries if not UNWANTED_BINARIES.search(b[0])]
    pyz = PYZ(a.pure)
    return EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=name,
        console=console,
        icon=ICON,
        version=version_info(name, description),
        upx=False,  # UPX-packed executables trigger more antivirus false positives
        strip=False,
    )


gui_exe = build(
    "gui_entry.py", "CodePack", GUI_DATAS, QT_UNUSED + STDLIB_UNUSED,
    console=False, description="CodePack - pack projects for AI chat",
)
cli_exe = build(
    "cli_entry.py", "codepack-cli", [PRESETS], ["PySide6", "shiboken6"] + STDLIB_UNUSED,
    console=True, description="CodePack command-line interface",
)
