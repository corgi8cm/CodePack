"""Command-line interface. Only uses codepack.core (and the toolkit-free clipboard helper)."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from codepack import __version__
from codepack.core import (
    PackOptions,
    Preset,
    RuleSet,
    ScanResult,
    Selection,
    all_presets,
    available_formats,
    build_pack,
    find_preset,
    get_formatter,
    render_tree,
    scan_project,
)
from codepack.core.apply import (
    REPLY_FORMATS,
    ApplyError,
    BackupError,
    apply_plan,
    list_backups,
    plan_changes,
    restore_backup,
)
from codepack.core.collectors.git import GitError, changed_files
from codepack.core.deps import DepOptions, resolve_dependencies
from codepack.core.reader import read_text
from codepack.core.scanners.secrets import SecretMasker

# Inside the PyInstaller build the console program is codepack-cli.exe.
PROG = "codepack-cli" if getattr(sys, "frozen", False) else "codepack"


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", type=Path, help="project directory")
    p.add_argument("--preset", default="default", help="preset name or path to a .json preset (default: default)")
    p.add_argument("-i", "--include", action="append", default=[], metavar="GLOB",
                   help="include pattern (gitignore syntax); repeatable")
    p.add_argument("-e", "--exclude", action="append", default=[], metavar="GLOB",
                   help="exclude pattern (gitignore syntax); repeatable")
    p.add_argument("--no-gitignore", action="store_true", help="do not apply .gitignore files")
    p.add_argument("--max-file-size", type=int, metavar="BYTES", help="skip files larger than this")


def _add_dep_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("dependency tracking")
    g.add_argument("--deps-depth", type=int, metavar="N", help="follow imports/includes N levels deep (default: all)")
    g.add_argument("--deps-pair", action="store_true", help="for each C/C++ header, also add its .cpp")
    g.add_argument("--deps-follow-excluded", action="store_true", help="also add dependencies the rules exclude")
    g.add_argument("--include-dir", action="append", default=[], metavar="DIR",
                   help="extra C/C++ include directory (relative); repeatable")


def _add_git_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("git")
    g.add_argument("--git-base", default="", metavar="REF",
                   help="compare against the merge-base with REF (e.g. main) instead of HEAD")
    g.add_argument("--git-staged", action="store_true", help="only staged changes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Pack a project into one text file for AI chat.")
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
    p.add_argument("--no-mask", action="store_true", help="do not mask secrets")
    p.add_argument("--reply-format", choices=REPLY_FORMATS,
                   help="ask the AI to reply in a format `codepack apply` understands")
    p.add_argument("--deps", action="append", default=[], metavar="PATH",
                   help="pack only this file and what it imports/includes; repeatable")
    _add_dep_options(p)
    p.add_argument("--git-changed", action="store_true", help="pack only files changed in git")
    p.add_argument("--git-diff", action="store_true", help="append the git diff")
    _add_git_options(p)

    p = sub.add_parser("tree", help="show the project tree with exclusion reasons")
    _add_common(p)
    p.add_argument("--selected", action="store_true", help="only show files that would be packed")

    p = sub.add_parser("stats", help="show token estimates per file")
    _add_common(p)
    p.add_argument("--sort", choices=["tokens", "path"], default="tokens")
    p.add_argument("--top", type=int, metavar="N", help="only show the N largest files")

    p = sub.add_parser("deps", help="list the files a target imports/includes")
    _add_common(p)
    p.add_argument("targets", nargs="+", metavar="TARGET", help="target file(s), relative to the directory")
    _add_dep_options(p)

    p = sub.add_parser("secrets", help="list secrets that would be masked")
    _add_common(p)

    p = sub.add_parser("apply", help="apply an AI reply (full files or unified diff) to the project")
    p.add_argument("directory", type=Path, help="project directory")
    p.add_argument("reply", nargs="?", default="-", help="file containing the reply, or - for stdin (default)")
    p.add_argument("-n", "--dry-run", action="store_true", help="only show what would change")
    p.add_argument("-y", "--yes", action="store_true", help="apply without asking")
    p.add_argument("--diff", action="store_true", help="print the full diff of every change")
    p.add_argument("--no-backup", action="store_true", help="do not back up files before writing")
    p.add_argument("--no-git-stash", action="store_true", help="do not record a git stash snapshot")

    p = sub.add_parser("backups", help="list backups made by `apply`")
    p.add_argument("directory", type=Path, help="project directory")

    p = sub.add_parser("restore", help="restore files from a backup (default: the latest)")
    p.add_argument("directory", type=Path, help="project directory")
    p.add_argument("backup_id", nargs="?", help="backup id (see `codepack backups`)")
    p.add_argument("-y", "--yes", action="store_true", help="restore without asking")

    sub.add_parser("presets", help="list available presets")

    p = sub.add_parser("prompt", help="list question templates, or print/copy one")
    p.add_argument("name", nargs="?", help="template name (omit to list them)")
    p.add_argument("-c", "--copy", action="store_true", help="copy the template to the clipboard")
    return parser


# --- helpers ---------------------------------------------------------------

def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


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


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").strip("/")


def _dep_options(args: argparse.Namespace) -> DepOptions:
    return DepOptions(
        max_depth=args.deps_depth,
        pair_sources=args.deps_pair,
        follow_excluded=args.deps_follow_excluded,
        include_dirs=args.include_dir,
    )


def _check_targets(scan: ScanResult, targets: list[str]) -> list[str]:
    missing = [t for t in targets if t not in scan.files]
    if missing:
        raise ValueError(f"not found in the project (or pruned by rules): {', '.join(missing)}")
    return targets


# --- commands ---------------------------------------------------------------

def _cmd_pack(args: argparse.Namespace, preset: Preset) -> int:
    from codepack.clipboard import ClipboardError, copy_text

    scan = scan_project(args.directory, preset.rules)
    selection = Selection(scan)

    narrowed: set[str] | None = None
    if args.deps:
        targets = _check_targets(scan, [_norm(t) for t in args.deps])
        result = resolve_dependencies(scan, targets, _dep_options(args))
        narrowed = set(result.files)
        _err(f"dependencies: {len(result.files)} files from {len(targets)} target(s)")
        if result.skipped:
            _err(f"  {len(result.skipped)} excluded by rules, not added (use --deps-follow-excluded)")
    if args.git_changed:
        changed = {f for f in changed_files(args.directory, args.git_base, args.git_staged) if f in scan.files}
        narrowed = changed if narrowed is None else narrowed | changed
        _err(f"git: {len(changed)} changed files")
    if narrowed is not None:
        for rel in selection.select_only(sorted(narrowed)):
            _err(f"warning: skipped {rel} (binary or unreadable)")

    for rel in args.force:
        rel = _norm(rel)
        if not selection.set_file(rel, True):
            _err(f"warning: cannot force {rel!r} (missing or binary)")

    opts = preset.options
    options = PackOptions(
        format=args.format or opts.format,
        include_tree=opts.include_tree and not args.no_tree,
        tree_scope=args.tree_scope or opts.tree_scope,
        preamble=args.preamble if args.preamble is not None else opts.preamble,
        mask_secrets=opts.mask_secrets and not args.no_mask,
        reply_format=args.reply_format or opts.reply_format,
        git_diff=args.git_diff or opts.git_diff,
        git_base=args.git_base or opts.git_base,
        git_staged=args.git_staged or opts.git_staged,
    )
    result = build_pack(scan, selection.checked_files(), options)
    for warning in result.warnings:
        _err(f"warning: {warning}")
    if result.findings:
        kinds = Counter(f.kind for f in result.findings)
        _err(f"masked {len(result.findings)} secrets: " + ", ".join(f"{k} x{n}" for k, n in kinds.items()))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.text, encoding="utf-8", newline="\n")
    if args.copy:
        try:
            copy_text(result.text)
        except ClipboardError as exc:
            _err(f"error: {exc}")
            return 1
    if not args.output and not args.copy:
        sys.stdout.write(result.text)

    dest = []
    if args.output:
        dest.append(str(args.output))
    if args.copy:
        dest.append("clipboard")
    _err(f"packed {len(result.files)} files, ~{result.total_tokens:,} tokens" + (f" -> {', '.join(dest)}" if dest else ""))
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


def _cmd_deps(args: argparse.Namespace, preset: Preset) -> int:
    scan = scan_project(args.directory, preset.rules)
    targets = _check_targets(scan, [_norm(t) for t in args.targets])
    result = resolve_dependencies(scan, targets, _dep_options(args))
    tokens = 0
    for rel in result.files:
        tokens += scan.files[rel].tokens
        print(("* " if rel in targets else "  ") + rel)
    print(f"{len(result.files)} files, ~{tokens:,} tokens")
    for rel, reason in sorted(result.skipped.items()):
        _err(f"skipped (excluded: {reason.value}): {rel}")
    external = sorted({name for names in result.unresolved.values() for name in names})
    if external:
        _err(f"not in project ({len(external)}): " + ", ".join(external[:20]) + (" ..." if len(external) > 20 else ""))
    return 0


def _cmd_secrets(args: argparse.Namespace, preset: Preset) -> int:
    scan = scan_project(args.directory, preset.rules)
    masker = SecretMasker()
    total = 0
    for rel in Selection(scan).checked_files():
        try:
            _, findings = masker.mask(read_text(scan.root / rel), rel)
        except OSError:
            continue
        for f in findings:
            print(f"{f.rel_path}:{f.line}  {f.kind:<16} {f.preview}")
        total += len(findings)
    print(f"{total} secrets found (they are masked by default when packing)")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    if args.reply == "-":
        reply = sys.stdin.read()
        from_stdin = True
    else:
        reply = Path(args.reply).read_text(encoding="utf-8", errors="replace")
        from_stdin = False
    root = args.directory.resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    plan = plan_changes(root, reply)
    for error in plan.errors:
        _err(f"warning: {error}")
    marks = {"create": "A", "modify": "M", "delete": "D"}
    for c in plan.changes:
        if c.error:
            print(f"  ! {c.path}: {c.error}")
            continue
        if c.unchanged:
            print(f"  = {c.path} (unchanged)")
            continue
        added, removed = c.stats()
        print(f"  {marks[c.kind]} {c.path}  +{added} -{removed}")
        for w in c.warnings:
            print(f"      warning: {w}")
        if args.diff:
            print(c.diff())

    changes = plan.applicable
    if not changes:
        _err("nothing to apply")
        return 1 if plan.errors or any(c.error for c in plan.changes) else 0
    if args.dry_run:
        _err(f"dry run: {len(changes)} file(s) would change")
        return 0
    if not args.yes:
        if from_stdin:
            _err("reply was read from stdin; pass --yes to apply (or --dry-run to preview)")
            return 2
        if not _confirm(f"Apply {len(changes)} change(s)?"):
            _err("aborted")
            return 1

    result = apply_plan(plan, backup=not args.no_backup, git_stash=not args.no_git_stash,
                        description=f"codepack apply ({len(changes)} files)")
    for w in result.warnings:
        _err(f"warning: {w}")
    _err(f"applied: {len(result.written)} written, {len(result.deleted)} deleted")
    if result.backup:
        _err(f"backup: {result.backup.id}  (undo with: {PROG} restore {args.directory} {result.backup.id})")
    return 0


def _cmd_backups(args: argparse.Namespace) -> int:
    backups = list_backups(args.directory)
    if not backups:
        print("no backups")
    for b in backups:
        stash = f"  git stash {b.git_stash[:10]}" if b.git_stash else ""
        print(f"{b.id}  {b.created}  {len(b.entries)} files  {b.description}{stash}")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    backups = list_backups(args.directory)
    target = next((b for b in backups if b.id == args.backup_id), None) if args.backup_id else (backups[0] if backups else None)
    if target is None:
        raise BackupError("no such backup" if args.backup_id else "no backups")
    if not args.yes and not _confirm(f"Restore {len(target.entries)} file(s) from backup {target.id}?"):
        _err("aborted (use --yes to skip the question)")
        return 1
    info = restore_backup(args.directory, target.id)
    for e in info.entries:
        print(f"  {'restored' if e.existed else 'removed '} {e.path}")
    return 0


def _cmd_presets() -> int:
    for p in all_presets():
        tag = "built-in" if p.builtin else "user"
        print(f"{p.name:<16} [{tag}] {p.description}")
    return 0


def _cmd_prompt(args: argparse.Namespace) -> int:
    from codepack.core.prompts import all_templates, find_template

    if not args.name:
        tags = {"builtin": "built-in", "override": "built-in, edited", "user": "user"}
        for t in all_templates():
            print(f"{t.name}  [{tags[t.source]}]")
        return 0
    template = find_template(args.name)
    if args.copy:
        from codepack.clipboard import ClipboardError, copy_text

        try:
            copy_text(template.text)
        except ClipboardError as exc:
            _err(f"error: {exc}")
            return 1
        _err(f"copied template {template.name!r} to the clipboard")
    else:
        sys.stdout.write(template.text)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "presets":
            return _cmd_presets()
        if args.command == "prompt":
            return _cmd_prompt(args)
        if args.command == "apply":
            return _cmd_apply(args)
        if args.command == "backups":
            return _cmd_backups(args)
        if args.command == "restore":
            return _cmd_restore(args)
        preset = _resolve_preset(args)
        if args.command == "pack":
            if args.format:
                get_formatter(args.format)
            return _cmd_pack(args, preset)
        if args.command == "tree":
            return _cmd_tree(args, preset)
        if args.command == "deps":
            return _cmd_deps(args, preset)
        if args.command == "secrets":
            return _cmd_secrets(args, preset)
        return _cmd_stats(args, preset)
    except (KeyError, ValueError, OSError, GitError, ApplyError, BackupError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) else exc
        _err(f"error: {msg}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
