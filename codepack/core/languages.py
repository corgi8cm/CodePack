"""Map file names to code-fence language identifiers."""

from __future__ import annotations

EXTENSION_LANGUAGES = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c++": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".hxx": "cpp", ".h++": "cpp", ".inl": "cpp", ".ipp": "cpp", ".tpp": "cpp", ".ixx": "cpp",
    ".cu": "cuda", ".cuh": "cuda",
    ".py": "python", ".pyi": "python", ".pyw": "python", ".pyx": "cython", ".pxd": "cython",
    ".cmake": "cmake",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "jsx",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".kt": "kotlin", ".cs": "csharp", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".m": "objectivec", ".mm": "objectivec",
    ".lua": "lua", ".r": "r", ".jl": "julia", ".dart": "dart", ".scala": "scala",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell", ".bat": "batch",
    ".cmd": "batch",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".vue": "vue",
    ".json": "json", ".jsonc": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".xml": "xml", ".sql": "sql", ".proto": "protobuf",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl", ".hlsl": "hlsl",
    ".gradle": "groovy", ".qml": "qml", ".ui": "xml", ".qrc": "xml",
}

FILENAME_LANGUAGES = {
    "cmakelists.txt": "cmake",
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "dockerfile": "dockerfile",
    "meson.build": "meson",
    "sconstruct": "python",
    "sconscript": "python",
    ".gitignore": "gitignore",
    ".clang-format": "yaml",
    ".clang-tidy": "yaml",
}


def detect_language(name: str) -> str:
    lower = name.lower()
    if lower in FILENAME_LANGUAGES:
        return FILENAME_LANGUAGES[lower]
    dot = lower.rfind(".")
    if dot > 0 or (dot == 0 and lower.count(".") > 1):
        return EXTENSION_LANGUAGES.get(lower[dot:], "")
    return ""
