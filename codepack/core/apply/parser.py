"""Parse an AI reply into file edits.

Two formats are recognized, and may be mixed in one reply:

* full files:   ``=== FILE: path ===`` ... ``=== END FILE ===`` and ``=== DELETE: path ===``
* unified diff: ``--- a/path`` / ``+++ b/path`` / ``@@ ... @@`` hunks, usually in a ```diff block

LLM output is loose, so the parser is forgiving: hunk line counts are
ignored, blank lines inside hunks count as context, and code fences
wrapped around a file's content are removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Markers may be decorated by chat UIs, e.g. "**=== FILE: x ===**" or "## === FILE: x ===".
_FILE_RE = re.compile(r"^\s*(?:[*#>]+\s*)?={3,}\s*FILE:\s*(.+?)\s*={3,}\s*\**\s*$")
_END_RE = re.compile(r"^\s*(?:[*#>]+\s*)?={3,}\s*END(?:\s+FILE)?\s*={3,}\s*\**\s*$")
_DELETE_RE = re.compile(r"^\s*(?:[*#>]+\s*)?={3,}\s*DELETE:\s*(.+?)\s*={3,}\s*\**\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_HUNK_LOOSE_RE = re.compile(r"^@@.*@@")

DEV_NULL = "/dev/null"


@dataclass
class FileReplace:
    path: str
    content: str


@dataclass
class FileDelete:
    path: str


@dataclass
class Hunk:
    old_start: int
    new_start: int
    lines: list[str] = field(default_factory=list)
    """Lines prefixed with ' ', '-' or '+'."""
    header: str = ""

    @property
    def old_lines(self) -> list[str]:
        return [ln[1:] for ln in self.lines if ln[0] in " -"]

    @property
    def new_lines(self) -> list[str]:
        return [ln[1:] for ln in self.lines if ln[0] in " +"]


@dataclass
class FilePatch:
    path: str
    old_path: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def is_new(self) -> bool:
        return self.old_path == DEV_NULL

    @property
    def is_delete(self) -> bool:
        return self.path == DEV_NULL


Edit = FileReplace | FileDelete | FilePatch


@dataclass
class ParsedReply:
    edits: list[Edit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def clean_path(raw: str) -> str:
    path = raw.strip().strip("`'\"*").strip()
    path = path.split("\t")[0].strip()
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _diff_path(raw: str) -> str:
    path = clean_path(raw)
    if path == DEV_NULL:
        return path
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _strip_fence(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if len(lines) >= 2 and _FENCE_RE.match(lines[0]) and _FENCE_RE.match(lines[-1]) and not lines[-1].strip("`~ \t"):
        lines = lines[1:-1]
    return lines


def _is_marker(line: str) -> bool:
    return bool(_FILE_RE.match(line) or _END_RE.match(line) or _DELETE_RE.match(line))


def _parse_file_blocks(lines: list[str], reply: ParsedReply) -> set[int]:
    """Parse FILE/DELETE blocks; return the indexes of lines they consumed."""
    used: set[int] = set()
    i = 0
    while i < len(lines):
        m_del = _DELETE_RE.match(lines[i])
        if m_del:
            reply.edits.append(FileDelete(clean_path(m_del.group(1))))
            used.add(i)
            i += 1
            continue
        m = _FILE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        path = clean_path(m.group(1))
        start = i
        j = i + 1
        while j < len(lines) and not _is_marker(lines[j]):
            j += 1
        if j >= len(lines) or not _END_RE.match(lines[j]):
            reply.errors.append(f"{path}: missing '=== END FILE ===' marker; block taken up to the next marker")
        body = _strip_fence(lines[i + 1:j])
        # A fence opened before the FILE marker may close right after the content;
        # an odd number of fence lines means the last one is not part of the file.
        fences = sum(1 for ln in body if _FENCE_RE.match(ln))
        if fences % 2 and _FENCE_RE.match(body[-1]) and not body[-1].strip("`~ \t"):
            body = _strip_fence(body[:-1])
        reply.edits.append(FileReplace(path, "\n".join(body) + "\n" if body else ""))
        end = j if j < len(lines) and _END_RE.match(lines[j]) else j - 1
        used.update(range(start, end + 1))
        i = end + 1
    return used


def _parse_diffs(lines: list[str], used: set[int], reply: ParsedReply) -> None:
    i = 0
    n = len(lines)
    while i < n:
        if i in used or not (lines[i].startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ ")):
            i += 1
            continue
        patch = FilePatch(path=_diff_path(lines[i + 1][4:]), old_path=_diff_path(lines[i][4:]))
        i += 2
        while i < n:
            line = lines[i]
            m = _HUNK_RE.match(line)
            if not m and _HUNK_LOOSE_RE.match(line):
                # "@@ ... @@" without numbers: position is found by context search.
                hunk = Hunk(0, 0, header=line)
            elif m:
                hunk = Hunk(int(m.group(1)), int(m.group(3)), header=line)
            else:
                break
            i += 1
            while i < n:
                line = lines[i]
                if line.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
                    break
                if _HUNK_LOOSE_RE.match(line):
                    break
                if line.startswith(("+", "-", " ")):
                    hunk.lines.append(line)
                elif line.startswith("\\"):
                    pass  # "\ No newline at end of file"
                elif line == "":
                    # Blank context line with its leading space stripped -- but only
                    # if the hunk continues afterwards.
                    k = i + 1
                    while k < n and lines[k] == "":
                        k += 1
                    if k < n and lines[k].startswith(("+", "-", " ")) and not (
                        lines[k].startswith("--- ") and k + 1 < n and lines[k + 1].startswith("+++ ")
                    ):
                        hunk.lines.append(" ")
                    else:
                        break
                else:
                    break
                i += 1
            if hunk.lines:
                patch.hunks.append(hunk)
        if patch.hunks or patch.is_delete:
            reply.edits.append(patch)
        else:
            reply.errors.append(f"{patch.path}: diff header without hunks")


def parse_reply(text: str) -> ParsedReply:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    reply = ParsedReply()
    used = _parse_file_blocks(lines, reply)
    _parse_diffs(lines, used, reply)
    if not reply.edits and not reply.errors:
        reply.errors.append("no file blocks or diffs found in the reply")
    return reply
