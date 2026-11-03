"""Apply unified-diff hunks with tolerance for AI-generated diffs.

Line numbers in hunks are treated as hints: each hunk's old lines are
searched for near the stated position, first exactly, then ignoring
trailing whitespace, then ignoring all surrounding whitespace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from codepack.core.apply.parser import Hunk

Normalizer = Callable[[str], str]
_NORMALIZERS: tuple[Normalizer, ...] = (lambda s: s, str.rstrip, str.strip)


@dataclass
class PatchResult:
    text: str
    failed: list[str] = field(default_factory=list)
    """Headers of hunks that could not be placed."""
    fuzzy: list[str] = field(default_factory=list)
    """Headers of hunks matched only after ignoring whitespace."""


def _find(lines: list[str], block: list[str], expected: int, start: int, norm: Normalizer) -> int:
    """Index where ``block`` occurs in ``lines`` at or after ``start``, nearest to ``expected``."""
    if not block:
        return max(start, min(expected, len(lines)))
    target = [norm(b) for b in block]
    last = len(lines) - len(block)
    if last < start:
        return -1
    expected = min(max(expected, start), last)
    for distance in range(0, max(expected - start, last - expected) + 1):
        for pos in (expected - distance, expected + distance) if distance else (expected,):
            if start <= pos <= last and all(norm(lines[pos + k]) == target[k] for k in range(len(block))):
                return pos
    return -1


def apply_hunks(text: str, hunks: list[Hunk]) -> PatchResult:
    trailing_newline = text.endswith("\n") or text == ""
    lines = text.split("\n")
    if trailing_newline and lines and lines[-1] == "":
        lines.pop()

    result = PatchResult(text="")
    start = 0  # hunks must apply in order
    delta = 0  # how far earlier hunks shifted line numbers
    for hunk in hunks:
        old = hunk.old_lines
        expected = (hunk.old_start - 1 + delta) if hunk.old_start else start
        pos = -1
        for level, norm in enumerate(_NORMALIZERS):
            pos = _find(lines, old, expected, start, norm)
            if pos >= 0:
                if level:
                    result.fuzzy.append(hunk.header)
                break
        if pos < 0:
            result.failed.append(hunk.header)
            continue
        replacement: list[str] = []
        k = pos
        for ln in hunk.lines:
            tag, body = ln[0], ln[1:]
            if tag == " ":
                replacement.append(lines[k])  # keep the original context line verbatim
                k += 1
            elif tag == "-":
                k += 1
            else:
                replacement.append(body)
        lines[pos:pos + len(old)] = replacement
        start = pos + len(replacement)
        delta += len(replacement) - len(old)

    result.text = "\n".join(lines) + ("\n" if trailing_newline and lines else "")
    return result
