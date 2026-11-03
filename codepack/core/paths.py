"""Per-user configuration locations."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_config_dir() -> Path:
    """Windows: %APPDATA%\\CodePack; Linux: $XDG_CONFIG_HOME/codepack (~/.config/codepack)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "CodePack"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "codepack"
