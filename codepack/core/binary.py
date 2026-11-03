"""Binary file detection."""

from __future__ import annotations

from pathlib import Path

SAMPLE_SIZE = 8192

BINARY_EXTENSIONS = frozenset(
    {
        # compiled / linked
        ".o", ".obj", ".a", ".lib", ".so", ".dll", ".dylib", ".exe", ".pdb", ".ilk",
        ".exp", ".pch", ".gch", ".idb", ".ipch", ".pyc", ".pyo", ".pyd", ".class", ".jar",
        ".wasm", ".bin", ".elf", ".out",
        # archives
        ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".zst", ".whl", ".egg",
        # images / media / fonts
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tif", ".tiff", ".webp", ".psd",
        ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".avi", ".mov", ".mkv", ".webm",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        # documents / data
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".sqlite", ".db",
        ".npy", ".npz", ".pkl", ".pickle", ".h5", ".onnx", ".pt", ".pth",
    }
)

_TEXT_CONTROL = {0x09, 0x0A, 0x0C, 0x0D, 0x08, 0x1B}
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def has_binary_extension(name: str) -> bool:
    dot = name.rfind(".")
    return dot >= 0 and name[dot:].lower() in BINARY_EXTENSIONS


def is_binary_bytes(sample: bytes) -> bool:
    """Heuristic: NUL bytes or >30% non-text control characters."""
    if not sample:
        return False
    if sample.startswith(_UTF16_BOMS):
        return False
    if b"\x00" in sample:
        return True
    control = sum(1 for b in sample if b < 0x20 and b not in _TEXT_CONTROL)
    return control / len(sample) > 0.30


def is_binary(path: Path, sample_size: int = SAMPLE_SIZE) -> bool:
    if has_binary_extension(path.name):
        return True
    with open(path, "rb") as fh:
        return is_binary_bytes(fh.read(sample_size))
