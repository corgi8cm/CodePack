"""Detect and mask secrets: API keys, passwords, private keys, internal IPs.

Placeholders look like ``<REDACTED:password:1a2b3c4d>``. The suffix is an
HMAC of the secret value under a per-install random key, so:

* the same value always maps to the same placeholder (across files and runs),
  which lets ``unmask`` restore secrets in code returned by the AI;
* the placeholder reveals nothing about the value to whoever reads the pack.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets as _secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from codepack.core.paths import user_config_dir

KEY_FILENAME = "mask.key"

PLACEHOLDER_RE = re.compile(r"<REDACTED:([a-z_]+):([0-9a-f]{8})>")

_IGNORED_VALUES = re.compile(
    r"^(?:\$\{.*\}|\{\{.*\}\}|<.*>|%\(.*\)s?|\*+|x+|\.\.\.|changeme|change_me|your[_-].*|placeholder|example|none|null|true|false)$",
    re.IGNORECASE,
)

_SECRET_NAME = r"[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?key|credential)[\w.-]*"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"


@dataclass(frozen=True)
class SecretRule:
    kind: str
    pattern: re.Pattern[str]
    group: int = 0
    """Which regex group holds the secret value (0 = whole match)."""


# Ordered by priority: when matches overlap, the earlier rule wins.
RULES: tuple[SecretRule, ...] = (
    SecretRule(
        "private_key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ),
    SecretRule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretRule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}(?![\w-])")),
    SecretRule("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    SecretRule("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    SecretRule("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    SecretRule("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    SecretRule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    SecretRule("url_password", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@'\"]+:([^\s@/'\"]+)@"), 1),
    SecretRule("conn_password", re.compile(r"(?i)(?:;|\"|')\s*(?:password|pwd)\s*=\s*([^;'\"\s]+)"), 1),
    SecretRule(
        "password",
        re.compile(rf"(?i)\b{_SECRET_NAME}[\"']?\s*(?::=|=>|[:=])\s*(?:[rbuf]{{0,2}})([\"'])([^\"'\n]{{4,}})\1"),
        2,
    ),
    SecretRule(
        "private_ip",
        re.compile(
            rf"(?<![\w.])(?:10\.{_OCTET}\.{_OCTET}\.{_OCTET}|192\.168\.{_OCTET}\.{_OCTET}"
            rf"|172\.(?:1[6-9]|2\d|3[01])\.{_OCTET}\.{_OCTET})(?![\w]|\.\d)"
        ),
    ),
)

ALL_KINDS = tuple(r.kind for r in RULES)


@dataclass(frozen=True)
class SecretMatch:
    kind: str
    start: int
    end: int
    value: str


@dataclass(frozen=True)
class SecretFinding:
    rel_path: str
    line: int
    kind: str
    placeholder: str
    preview: str
    """A heavily truncated hint of the value, for local display only."""


def _preview(value: str) -> str:
    first_line = value.splitlines()[0] if value else ""
    return (first_line[:4] + "…") if len(first_line) > 4 else "…"


def load_or_create_key(path: Path | None = None) -> bytes:
    path = path or user_config_dir() / KEY_FILENAME
    try:
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pass
    key = _secrets.token_bytes(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key.hex(), encoding="ascii")
    except OSError:
        pass  # still usable for this session; placeholders just won't be stable across runs
    return key


class SecretMasker:
    def __init__(self, key: bytes | None = None, kinds: Iterable[str] | None = None):
        self.key = key if key is not None else load_or_create_key()
        enabled = set(kinds) if kinds is not None else set(ALL_KINDS)
        self.rules = [r for r in RULES if r.kind in enabled]

    def placeholder(self, kind: str, value: str) -> str:
        digest = hmac.new(self.key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
        return f"<REDACTED:{kind}:{digest}>"

    def find(self, text: str) -> list[SecretMatch]:
        taken: list[tuple[int, int]] = []
        found: list[SecretMatch] = []
        for rule in self.rules:
            for m in rule.pattern.finditer(text):
                start, end = m.span(rule.group)
                value = m.group(rule.group)
                if not value or _IGNORED_VALUES.match(value) or PLACEHOLDER_RE.search(value):
                    continue
                if any(start < t_end and t_start < end for t_start, t_end in taken):
                    continue
                taken.append((start, end))
                found.append(SecretMatch(rule.kind, start, end, value))
        found.sort(key=lambda s: s.start)
        return found

    def mask(self, text: str, rel_path: str = "") -> tuple[str, list[SecretFinding]]:
        matches = self.find(text)
        if not matches:
            return text, []
        out: list[str] = []
        findings: list[SecretFinding] = []
        pos = 0
        for m in matches:
            ph = self.placeholder(m.kind, m.value)
            out.append(text[pos:m.start])
            out.append(ph)
            pos = m.end
            line = text.count("\n", 0, m.start) + 1
            findings.append(SecretFinding(rel_path, line, m.kind, ph, _preview(m.value)))
        out.append(text[pos:])
        return "".join(out), findings

    def mapping(self, text: str) -> dict[str, str]:
        """Placeholder -> original value for every secret in ``text``."""
        return {self.placeholder(m.kind, m.value): m.value for m in self.find(text)}


def find_placeholders(text: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(text)]


def unmask(text: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Replace known placeholders with their values. Returns ``(text, unresolved)``."""
    unresolved: list[str] = []

    def repl(m: re.Match[str]) -> str:
        value = mapping.get(m.group(0))
        if value is None:
            if m.group(0) not in unresolved:
                unresolved.append(m.group(0))
            return m.group(0)
        return value

    return PLACEHOLDER_RE.sub(repl, text), unresolved
