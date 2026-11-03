"""Output formatter registry."""

from __future__ import annotations

from codepack.core.formatters.base import ExtraSection, Formatter, PackDocument, PackedFile
from codepack.core.formatters.markdown import MarkdownFormatter
from codepack.core.formatters.plain import PlainFormatter
from codepack.core.formatters.xml import XmlFormatter

_REGISTRY: dict[str, type[Formatter]] = {}
_ALIASES = {"md": "markdown", "txt": "plain", "text": "plain"}


def register_formatter(cls: type[Formatter]) -> type[Formatter]:
    _REGISTRY[cls.name] = cls
    return cls


for _cls in (MarkdownFormatter, XmlFormatter, PlainFormatter):
    register_formatter(_cls)


def available_formats() -> list[str]:
    return list(_REGISTRY)


def get_formatter(name: str) -> Formatter:
    key = _ALIASES.get(name.lower(), name.lower())
    try:
        return _REGISTRY[key]()
    except KeyError:
        raise ValueError(f"unknown format {name!r}; choose from {available_formats()}") from None


__all__ = [
    "ExtraSection",
    "Formatter",
    "PackDocument",
    "PackedFile",
    "available_formats",
    "get_formatter",
    "register_formatter",
]
