"""Backups taken before applying changes, and restoring them.

Each backup copies the files about to be touched into
``<project>/.codepack/backups/<id>/`` with a manifest. This works with or
without git and never touches other uncommitted work. In a git repository
a ``git stash create`` snapshot is also recorded in the stash list (this
does not modify the working tree, unlike ``git stash push``).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

CODEPACK_DIR = ".codepack"
BACKUP_SUBDIR = "backups"
MANIFEST = "manifest.json"


class BackupError(RuntimeError):
    pass


@dataclass
class BackupEntry:
    path: str
    existed: bool


@dataclass
class BackupInfo:
    id: str
    created: str
    description: str
    entries: list[BackupEntry] = field(default_factory=list)
    git_stash: str = ""
    """Commit id of the git stash snapshot, if one was recorded."""
    directory: Path | None = None

    @property
    def paths(self) -> list[str]:
        return [e.path for e in self.entries]


def backups_root(project: Path) -> Path:
    return project / CODEPACK_DIR / BACKUP_SUBDIR


def _ensure_codepack_dir(project: Path) -> None:
    folder = project / CODEPACK_DIR
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# CodePack backups; not meant for version control\n*\n", encoding="utf-8")


def _new_id(root: Path) -> str:
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, n = base, 1
    while (root / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _git_snapshot(project: Path, message: str) -> str:
    from codepack.core.collectors.git import GitError, is_git_repo, run_git

    if not is_git_repo(project):
        return ""
    try:
        commit = run_git(project, "stash", "create", message).strip()
        if commit:
            run_git(project, "stash", "store", "-m", message, commit)
        return commit
    except GitError:
        return ""


def create_backup(project: Path, paths: Iterable[str], description: str = "", git_stash: bool = True) -> BackupInfo:
    project = Path(project)
    _ensure_codepack_dir(project)
    root = backups_root(project)
    backup_id = _new_id(root)
    folder = root / backup_id
    files_dir = folder / "files"
    files_dir.mkdir(parents=True)

    entries = []
    for rel in dict.fromkeys(paths):
        src = project / rel
        existed = src.is_file()
        if existed:
            dest = files_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        entries.append(BackupEntry(rel, existed))

    info = BackupInfo(
        id=backup_id,
        created=datetime.now().isoformat(timespec="seconds"),
        description=description,
        entries=entries,
        directory=folder,
    )
    if git_stash:
        info.git_stash = _git_snapshot(project, f"codepack backup {backup_id}")
    (folder / MANIFEST).write_text(
        json.dumps(
            {
                "id": info.id,
                "created": info.created,
                "description": info.description,
                "git_stash": info.git_stash,
                "entries": [{"path": e.path, "existed": e.existed} for e in entries],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return info


def _load(folder: Path) -> BackupInfo | None:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        return BackupInfo(
            id=str(data["id"]),
            created=str(data.get("created", "")),
            description=str(data.get("description", "")),
            entries=[BackupEntry(str(e["path"]), bool(e["existed"])) for e in data.get("entries", [])],
            git_stash=str(data.get("git_stash", "")),
            directory=folder,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def list_backups(project: Path) -> list[BackupInfo]:
    """Newest first."""
    root = backups_root(Path(project))
    if not root.is_dir():
        return []
    infos = [info for d in root.iterdir() if d.is_dir() and (info := _load(d)) is not None]
    infos.sort(key=lambda b: (b.created, b.id), reverse=True)
    return infos


def restore_backup(project: Path, backup_id: str | None = None) -> BackupInfo:
    """Put every file recorded in the backup back as it was; files that the
    applied change created are deleted. Defaults to the newest backup."""
    project = Path(project)
    backups = list_backups(project)
    if not backups:
        raise BackupError("沒有可還原的備份(no backups)")
    if backup_id is None:
        info = backups[0]
    else:
        matches = [b for b in backups if b.id == backup_id]
        if not matches:
            raise BackupError(f"backup {backup_id!r} not found")
        info = matches[0]
    assert info.directory is not None
    for entry in info.entries:
        target = project / entry.path
        if entry.existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(info.directory / "files" / entry.path, target)
        elif target.exists():
            target.unlink()
    return info

