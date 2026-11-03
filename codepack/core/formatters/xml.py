from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from codepack.core.formatters.base import Formatter, PackDocument, ensure_trailing_newline


def cdata(text: str) -> str:
    """Wrap text in CDATA, splitting any ``]]>`` it contains."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


class XmlFormatter(Formatter):
    name = "xml"
    label = "XML"
    extension = ".xml"

    def render(self, doc: PackDocument) -> str:
        out = [f"<project name={quoteattr(doc.project_name)}>"]
        if doc.preamble.strip():
            out.append(f"<instructions>\n{escape(doc.preamble.strip())}\n</instructions>")
        if doc.tree:
            out.append(f"<directory_structure>\n{escape(doc.tree)}\n</directory_structure>")
        out.append("<files>")
        for f in doc.files:
            attrs = f"path={quoteattr(f.rel_path)}"
            if f.language:
                attrs += f" language={quoteattr(f.language)}"
            out.append(f"<file {attrs}>\n{cdata(ensure_trailing_newline(f.content))}\n</file>")
        out.append("</files>")
        out.append("</project>")
        return "\n".join(out) + "\n"
