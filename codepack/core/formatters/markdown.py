from __future__ import annotations

import re

from codepack.core.formatters.base import Formatter, PackDocument, ensure_trailing_newline

_BACKTICK_RUN = re.compile(r"`{3,}")


def fence_for(content: str) -> str:
    """A backtick fence longer than any run inside ``content``."""
    longest = max((len(m.group(0)) for m in _BACKTICK_RUN.finditer(content)), default=2)
    return "`" * max(3, longest + 1)


class MarkdownFormatter(Formatter):
    name = "markdown"
    label = "Markdown"
    extension = ".md"

    def render(self, doc: PackDocument) -> str:
        out = [f"# Project: {doc.project_name}\n"]
        if doc.preamble.strip():
            out.append(doc.preamble.strip() + "\n")
        if doc.tree:
            fence = fence_for(doc.tree)
            out.append(f"## Directory Structure\n\n{fence}text\n{ensure_trailing_newline(doc.tree)}{fence}\n")
        if doc.files:
            out.append("## Files\n")
        for f in doc.files:
            fence = fence_for(f.content)
            out.append(
                f"### `{f.rel_path}`\n\n{fence}{f.language}\n{ensure_trailing_newline(f.content)}{fence}\n"
            )
        for s in doc.sections:
            fence = fence_for(s.content)
            out.append(f"## {s.title}\n\n{fence}{s.language}\n{ensure_trailing_newline(s.content)}{fence}\n")
        if doc.postscript.strip():
            out.append(doc.postscript.strip() + "\n")
        return "\n".join(out)
