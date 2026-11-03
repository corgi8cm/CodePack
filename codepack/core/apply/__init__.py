"""Apply an AI reply back to the project: parse, preview, write with backup, restore."""

from codepack.core.apply.backup import BackupError, BackupInfo, create_backup, list_backups, restore_backup
from codepack.core.apply.formats import REPLY_DIFF, REPLY_FILES, REPLY_FORMATS, REPLY_NONE, reply_instructions
from codepack.core.apply.parser import ParsedReply, parse_reply
from codepack.core.apply.planner import (
    ApplyError,
    ApplyResult,
    ChangePlan,
    FileChange,
    apply_plan,
    plan_changes,
)

__all__ = [
    "REPLY_DIFF",
    "REPLY_FILES",
    "REPLY_FORMATS",
    "REPLY_NONE",
    "ApplyError",
    "ApplyResult",
    "BackupError",
    "BackupInfo",
    "ChangePlan",
    "FileChange",
    "ParsedReply",
    "apply_plan",
    "create_backup",
    "list_backups",
    "parse_reply",
    "plan_changes",
    "reply_instructions",
    "restore_backup",
]
