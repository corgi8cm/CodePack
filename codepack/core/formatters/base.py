from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PackedFile:
    rel_path: str
    language: str
    content: str
    tokens: int = 0


@dataclass
class PackDocument:
    project_name: str
    tree: str = ""
    files: list[PackedFile] = field(default_factory=list)
    preamble: str = ""


class Formatter(ABC):
    name: str = ""
    label: str = ""
    extension: str = ".txt"

    @abstractmethod
    def render(self, doc: PackDocument) -> str: ...


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"
