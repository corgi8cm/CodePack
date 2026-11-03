"""User-facing text for core enums."""

from __future__ import annotations

from codepack.core import ExcludeReason

REASON_LABELS = {
    ExcludeReason.GITIGNORE: "被 .gitignore 忽略",
    ExcludeReason.EXCLUDE_RULE: "符合排除規則",
    ExcludeReason.NOT_INCLUDED: "不符合包含規則",
    ExcludeReason.BINARY: "二進位檔",
    ExcludeReason.TOO_LARGE: "檔案過大",
    ExcludeReason.UNREADABLE: "無法讀取",
}

FORMAT_LABELS = {"markdown": "Markdown", "xml": "XML", "plain": "純文字"}


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover
