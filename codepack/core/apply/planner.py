"""Turn parsed edits into a reviewable change plan, then apply it with a backup."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Iterable, Literal

from codepack.core.apply.backup import CODEPACK_DIR, BackupInfo, create_backup
from codepack.core.apply.parser import FileDelete, FilePatch, FileReplace, parse_reply
from codepack.core.apply.patch import apply_hunks
from codepack.core.deps.base import normalize_rel
from codepack.core.reader import decode_bytes
from codepack.core.scanners.secrets import SecretMasker, find_placeholders, unmask

ChangeKind = Literal["create", "modify", "delete"]
_FORBIDDEN_PARTS = {".git", CODEPACK_DIR}


class ApplyError(RuntimeError):
    pass


@dataclass
class FileChange:
    path: str
    kind: ChangeKind
    old_text: str | None
    new_text: str | None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    encoding: str = "utf-8"
    crlf: bool = False
    old_digest: str = ""
    """sha256 of the file bytes at planning time; checked again before writing."""

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def unchanged(self) -> bool:
        return self.kind == "modify" and self.old_text == self.new_text

    @property
    def applicable(self) -> bool:
        return self.ok and not self.unchanged

    def diff(self, context: int = 3) -> str:
        old = (self.old_text or "").splitlines(keepends=True)
        new = (self.new_text or "").splitlines(keepends=True)
        a = "/dev/null" if self.kind == "create" else f"a/{self.path}"
        b = "/dev/null" if self.kind == "delete" else f"b/{self.path}"
        lines = difflib.unified_diff(old, new, a, b, n=context)
        return "".join(ln if ln.endswith("\n") else ln + "\n" for ln in lines)

    def stats(self) -> tuple[int, int]:
        added = removed = 0
        for ln in self.diff(0).splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                added += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                removed += 1
        return added, removed


@dataclass
class ChangePlan:
    root: Path
    changes: list[FileChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> list[FileChange]:
        return [c for c in self.changes if c.applicable]


@dataclass
class ApplyResult:
    backup: BackupInfo | None
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safe_rel_path(root: Path, raw: str) -> str:
    """Validate a path from the reply; raises ApplyError if it is unsafe."""
    if not raw or raw == "/dev/null":
        raise ApplyError("empty path")
    if raw.startswith(("/", "~")) or PureWindowsPath(raw).drive:
        raise ApplyError(f"absolute path not allowed: {raw}")
    rel = normalize_rel(raw)
    if rel is None:
        raise ApplyError(f"path escapes the project: {raw}")
    if _FORBIDDEN_PARTS & set(rel.split("/")):
        raise ApplyError(f"refusing to touch {rel}")
    resolved = (root / rel).resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        raise ApplyError(f"path escapes the project via a link: {raw}")
    return rel


def _digest(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else ""


def _read(root: Path, rel: str) -> tuple[bytes | None, str | None, str, bool]:
    path = root / rel
    if not path.is_file():
        return None, None, "utf-8", False
    data = path.read_bytes()
    text, encoding = decode_bytes(data)
    return data, text, encoding, b"\r\n" in data


class _SecretRestorer:
    """Restores <REDACTED:...> placeholders using secrets found in project files."""

    def __init__(self, root: Path, masker: SecretMasker | None):
        self.root = root
        self.masker = masker
        self._project_map: dict[str, str] | None = None

    def _project_mapping(self) -> dict[str, str]:
        if self._project_map is None:
            from codepack.core.scanner import scan_project

            mapping: dict[str, str] = {}
            assert self.masker is not None
            scan = scan_project(self.root)
            for rel, entry in scan.files.items():
                if entry.checkable:
                    try:
                        mapping.update(self.masker.mapping(decode_bytes((self.root / rel).read_bytes())[0]))
                    except OSError:
                        continue
            self._project_map = mapping
        return self._project_map

    def restore(self, new_text: str, old_text: str | None) -> tuple[str, list[str]]:
        if not find_placeholders(new_text):
            return new_text, []
        if self.masker is None:
            self.masker = SecretMasker()
        text, unresolved = unmask(new_text, self.masker.mapping(old_text or ""))
        if unresolved:
            text, unresolved = unmask(text, self._project_mapping())
        return text, unresolved


def plan_changes(root: Path | str, reply_text: str, masker: SecretMasker | None = None) -> ChangePlan:
    root = Path(root)
    parsed = parse_reply(reply_text)
    plan = ChangePlan(root=root, errors=list(parsed.errors))
    restorer = _SecretRestorer(root, masker)

    changes: dict[str, FileChange] = {}
    for edit in parsed.edits:
        raw = edit.old_path if isinstance(edit, FilePatch) and edit.is_delete else edit.path
        try:
            rel = safe_rel_path(root, raw)
        except ApplyError as exc:
            plan.errors.append(str(exc))
            continue

        change = changes.get(rel)
        if change is None:
            data, text, encoding, crlf = _read(root, rel)
            change = FileChange(rel, "modify" if text is not None else "create", text, text,
                                encoding=encoding, crlf=crlf, old_digest=_digest(data))
            changes[rel] = change
        if not change.ok:
            continue
        current = change.new_text

        if isinstance(edit, FileDelete) or (isinstance(edit, FilePatch) and edit.is_delete):
            if change.old_text is None:
                change.error = "要刪除的檔案不存在(file to delete does not exist)"
            change.kind, change.new_text = "delete", None
            continue

        if isinstance(edit, FileReplace):
            new_text = edit.content
        else:
            assert isinstance(edit, FilePatch)
            if edit.is_new or current is None:
                if current is not None and edit.is_new:
                    change.warnings.append("diff 標示為新檔案，但檔案已存在，將以內容覆蓋")
                if not edit.is_new:
                    change.error = "要修改的檔案不存在(file to patch does not exist)"
                    continue
                new_text = "\n".join(ln for h in edit.hunks for ln in h.new_lines) + "\n"
            else:
                patched = apply_hunks(current, edit.hunks)
                if patched.failed:
                    change.error = (
                        f"{len(patched.failed)}/{len(edit.hunks)} 個 hunk 無法套用(context 不符):"
                        + "; ".join(h or "@@" for h in patched.failed)
                    )
                    continue
                if patched.fuzzy:
                    change.warnings.append(f"{len(patched.fuzzy)} 個 hunk 忽略空白差異後才對上，請檢查 diff")
                new_text = patched.text

        new_text, unresolved = restorer.restore(new_text, change.old_text)
        if unresolved:
            change.warnings.append(f"有 {len(unresolved)} 個機密 placeholder 無法還原，會原樣寫入:{unresolved[0]}")
        if change.kind == "delete":
            change.kind = "modify" if change.old_text is not None else "create"
        change.new_text = new_text

    plan.changes = list(changes.values())
    return plan


def _encode(change: FileChange) -> tuple[bytes, str | None]:
    text = change.new_text or ""
    if change.crlf:
        text = text.replace("\n", "\r\n")
    try:
        return text.encode(change.encoding), None
    except (UnicodeEncodeError, LookupError):
        return text.encode("utf-8"), f"{change.path}: 無法用原編碼 {change.encoding} 寫入，改用 UTF-8"


def apply_plan(
    plan: ChangePlan,
    paths: Iterable[str] | None = None,
    backup: bool = True,
    git_stash: bool = True,
    description: str = "",
) -> ApplyResult:
    """Write the selected (default: all applicable) changes, after backing up their targets."""
    wanted = set(paths) if paths is not None else None
    changes = [c for c in plan.applicable if wanted is None or c.path in wanted]
    if not changes:
        return ApplyResult(backup=None)

    for c in changes:  # refuse if anything changed on disk since the preview
        data, _, _, _ = _read(plan.root, c.path)
        if _digest(data) != c.old_digest:
            raise ApplyError(f"{c.path} 在預覽之後被修改過，請重新解析(changed on disk since preview)")

    info = None
    if backup:
        info = create_backup(plan.root, [c.path for c in changes], description, git_stash=git_stash)

    result = ApplyResult(backup=info)
    for c in changes:
        target = plan.root / c.path
        if c.kind == "delete":
            target.unlink()
            result.deleted.append(c.path)
            continue
        data, warning = _encode(c)
        if warning:
            result.warnings.append(warning)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        result.written.append(c.path)
    return result
