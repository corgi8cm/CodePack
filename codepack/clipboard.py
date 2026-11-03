"""Clipboard access for the CLI without any GUI toolkit.

Windows uses the Win32 API through ctypes; Linux uses wl-copy, xclip or xsel.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


class ClipboardError(RuntimeError):
    pass


def _copy_windows(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    data = text.replace("\n", "\r\n").encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise ClipboardError("cannot open clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ClipboardError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise ClipboardError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


_LINUX_COMMANDS = (
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
    ["xsel", "--clipboard", "--input"],
)


def _copy_unix(text: str) -> None:
    for cmd in _LINUX_COMMANDS:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=10)
                return
            except (OSError, subprocess.SubprocessError) as exc:
                raise ClipboardError(f"{cmd[0]} failed: {exc}") from exc
    raise ClipboardError("no clipboard tool found; install wl-clipboard, xclip or xsel")


def copy_text(text: str) -> None:
    if sys.platform == "win32":
        _copy_windows(text)
    else:
        _copy_unix(text)
