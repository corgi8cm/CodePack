from __future__ import annotations

from codepack.core.formatters.base import Formatter, PackDocument, ensure_trailing_newline

SEPARATOR = "=" * 64


class PlainFormatter(Formatter):
    name = "plain"
    label = "Plain text"
    extension = ".txt"

    def render(self, doc: PackDocument) -> str:
        out = [f"Project: {doc.project_name}\n"]
        if doc.preamble.strip():
            out.append(doc.preamble.strip() + "\n")
        if doc.tree:
            out.append(f"{SEPARATOR}\nDirectory Structure\n{SEPARATOR}\n{ensure_trailing_newline(doc.tree)}")
        for f in doc.files:
            out.append(f"{SEPARATOR}\nFile: {f.rel_path}\n{SEPARATOR}\n{ensure_trailing_newline(f.content)}")
        for s in doc.sections:
            out.append(f"{SEPARATOR}\n{s.title}\n{SEPARATOR}\n{ensure_trailing_newline(s.content)}")
        if doc.postscript.strip():
            out.append(f"{SEPARATOR}\n{doc.postscript.strip()}\n")
        return "\n".join(out)
