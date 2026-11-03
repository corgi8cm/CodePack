"""Command-line interface. Only uses codepack.core (and the toolkit-free clipboard helper)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from codepack import __version__
from codepack.core import (
    PackOptions,
    Preset,
    RuleSet,
    Selection,
    all_presets,
    available_formats,
    build_pack,
    find_preset,
    get_formatter,
    render_tree,
    scan_project,
)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", type=Path, help="project directory")
    p.add_argument("--preset", default="default", help="preset name or path to a .json preset (default: default)")
    p.add_argument("-i", "--include", action="append", default=[], metavar="GLOB",
                   help="include pattern (gitignore syntax); repeatable")
    p.add_argument("-e", "--exclude", action="append", default=[], metavar="GLOB",
                   help="exclude pattern (gitignore syntax); repeatable")
    p.add_argument("--no-gitignore", action="store_true", help="do not apply .gitignore files")
    p.add_argument("--max-file-size", type=int, metavar="BYTES", help="skip files larger than this")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codepack", description="Pack a project into one text file for AI chat.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="pack files into a single document")
    _add_common(p)
    p.add_argument("-f", "--format", choices=available_formats() + ["md", "txt"], help="output format")
    p.add_argument("-o", "--output", type=Path, help="write to this file")
    p.add_argument("-c", "--copy", action="store_true", help="copy the result to the clipboard")
    p.add_argument("--no-tree", action="store_true", help="omit the directory tree")
    p.add_argument("--tree-scope", choices=["selected", "all"], help="which files the tree shows")
    p.add_argument("--preamble", help="text placed before the files (e.g. a prompt)")
    p.add_argument("--force", action="append", default=[], metavar="PATH",
                   help="include this file even if rules exclude it; repeatable")

    p = sub.add_parser("tree", help="show the project tree with exclusion reasons")
    _add_common(p)
    p.add_argument("--selected", action="store_true", help="only show files that would be packed")

    p = sub.add_parser("stats", help="show token estimates per file")
    _add_common(p)
    p.add_argument("--sort", choices=["tokens", "path"], default="tokens")
    p.add_argument("--top", type=int, metavar="N", help="only show the N largest files")

    sub.add_parser("presets", help="list available presets")
    return parser


def _resolve_preset(args: argparse.Namespace) -> Preset:
    preset = find_preset(args.preset)
    rules = preset.rules
    rules = RuleSet(
        include=rules.include + args.include,
        exclude=rules.exclude + args.exclude,
        use_gitignore=rules.use_gitignore and not args.no_gitignore,
        max_file_size=args.max_file_size or rules.max_file_size,
    )
    return Preset(preset.name, rules, preset.options, preset.description)


def _ensure_utf8_output() -> None:
    # Redirected output on Windows would otherwise use the ANSI code page and
    # fail on tree-drawing or CJK characters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def _cmd_pack(args: argparse.Namespace, preset: Preset) -> int:
    from codepack.clipboard import ClipboardError, copy_text

    scan = scan_project(args.directory, preset.rules)
    selection = Selection(scan)
    for rel in args.force:
        rel = rel.replace("\\", "/").strip("/")
        if not selection.set_file(rel, True):
            print(f"warning: cannot force {rel!r} (missing or binary)", file=sys.stderr)

    opts = preset.options
    options = PackOptions(
        format=args.format or opts.format,
        include_tree=opts.include_tree and not args.no_tree,
        tree_scope=args.tree_scope or opts.tree_scope,
        preamble=args.preamble if args.preamble is not None else opts.preamble,
    )
    result = build_pack(scan, selection.checked_files(), options)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.text, encoding="utf-8", newline="\n")
    if args.copy:
        try:
            copy_text(result.text)
        except ClipboardError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if not args.output and not args.copy:
        sys.stdout.write(result.text)

    dest = []
    if args.output:
        dest.append(str(args.output))
    if args.copy:
        dest.append("clipboard")
    print(
        f"packed {len(result.files)} files, ~{result.total_tokens:,} tokens"
        + (f" -> {', '.join(dest)}" if dest else ""),
        file=sys.stderr,
    )
    return 0


def _cmd_tree(args: argparse.Namespace, preset: Preset) -> int:
    scan = scan_project(args.directory, preset.rules)
    files = Selection(scan).checked_files() if args.selected else None
    print(render_tree(scan, files, annotate_excluded=not args.selected))
    return 0


def _cmd_stats(args: argparse.Namespace, preset: Preset) -> int:
    scan = scan_project(args.directory, preset.rules)
    files = Selection(scan).checked_files()
    rows = [(rel, scan.files[rel].tokens, scan.files[rel].size) for rel in files]
    if args.sort == "tokens":
        rows.sort(key=lambda r: (-r[1], r[0]))
    shown = rows[: args.top] if args.top else rows
    width = max((len(r[0]) for r in shown), default=4)
    print(f"{'file':<{width}}  {'tokens':>10}  {'bytes':>10}")
    for rel, tokens, size in shown:
        print(f"{rel:<{width}}  {tokens:>10,}  {size:>10,}")
    total_tokens = sum(r[1] for r in rows)
    total_size = sum(r[2] for r in rows)
    print(f"{len(rows)} files, ~{total_tokens:,} tokens, {total_size:,} bytes "
          f"({len(scan.files) - len(rows)} excluded)")
    return 0


def _cmd_presets() -> int:
    for p in all_presets():
        tag = "built-in" if p.builtin else "user"
        print(f"{p.name:<16} [{tag}] {p.description}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_output()
    args = build_parser().parse_args(argv)
    if args.command == "presets":
        return _cmd_presets()
    try:
        preset = _resolve_preset(args)
        if args.command == "pack":
            if args.format:
                get_formatter(args.format)
            return _cmd_pack(args, preset)
        if args.command == "tree":
            return _cmd_tree(args, preset)
        return _cmd_stats(args, preset)
    except (KeyError, ValueError, OSError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) else exc
        print(f"error: {msg}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
