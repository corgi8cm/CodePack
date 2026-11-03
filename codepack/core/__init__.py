"""CodePack core: scanning, filtering, formatting and token estimation.

This package must not import any GUI toolkit or networking module.
"""

from codepack.core.formatters import available_formats, get_formatter
from codepack.core.models import DirEntry, ExcludeReason, FileEntry, ScanResult
from codepack.core.packer import PackOptions, PackResult, build_pack
from codepack.core.preset import (
    Preset,
    all_presets,
    builtin_presets,
    default_preset,
    find_preset,
    load_preset,
    save_preset,
    user_preset_dir,
)
from codepack.core.rules import RuleSet, parse_rule_lines
from codepack.core.scanner import ScanCancelled, scan_project
from codepack.core.selection import CheckState, Selection
from codepack.core.tokens import CharTokenEstimator, TokenEstimator
from codepack.core.tree_render import render_tree

__all__ = [
    "CharTokenEstimator",
    "CheckState",
    "DirEntry",
    "ExcludeReason",
    "FileEntry",
    "PackOptions",
    "PackResult",
    "Preset",
    "RuleSet",
    "ScanCancelled",
    "ScanResult",
    "Selection",
    "TokenEstimator",
    "all_presets",
    "available_formats",
    "build_pack",
    "builtin_presets",
    "default_preset",
    "find_preset",
    "get_formatter",
    "load_preset",
    "parse_rule_lines",
    "render_tree",
    "save_preset",
    "scan_project",
    "user_preset_dir",
]
