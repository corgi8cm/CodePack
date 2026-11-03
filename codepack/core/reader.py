"""Text decoding with encoding fallback (common for Windows C++ sources)."""

from __future__ import annotations

from pathlib import Path

FALLBACK_ENCODINGS = ("utf-8", "cp950", "gbk", "shift_jis", "latin-1")


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode bytes, returning ``(text, encoding)``. Never raises.

    Line endings are normalized to ``\\n``.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        text, enc = data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text, enc = data.decode("utf-16", errors="replace"), "utf-16"
    else:
        for enc in FALLBACK_ENCODINGS:
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:  # pragma: no cover - latin-1 decodes anything
            text, enc = data.decode("utf-8", errors="replace"), "utf-8"
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc


def read_text(path: Path) -> str:
    return decode_bytes(path.read_bytes())[0]
