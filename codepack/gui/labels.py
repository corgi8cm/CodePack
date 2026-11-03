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

SECRET_LABELS = {
    "private_key": "私鑰",
    "aws_access_key": "AWS 金鑰",
    "google_api_key": "Google API key",
    "github_token": "GitHub token",
    "slack_token": "Slack token",
    "anthropic_key": "Anthropic API key",
    "openai_key": "OpenAI API key",
    "jwt": "JWT",
    "url_password": "連線字串密碼",
    "conn_password": "連線字串密碼",
    "password": "密碼/金鑰",
    "private_ip": "內部 IP",
}

CHANGE_LABELS = {"create": "新增", "modify": "修改", "delete": "刪除"}


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover
