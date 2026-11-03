"""Dependency tracking: start from target files and follow Python imports
and C/C++ #include directives to the project files they need."""

from codepack.core.deps.base import (
    Dependencies,
    DependencyResolver,
    DependencyResult,
    DepOptions,
    resolve_dependencies,
)
from codepack.core.deps.cpp import CppIncludeResolver, include_dirs_from_compile_commands
from codepack.core.deps.python import PythonImportResolver

__all__ = [
    "CppIncludeResolver",
    "DepOptions",
    "Dependencies",
    "DependencyResolver",
    "DependencyResult",
    "PythonImportResolver",
    "include_dirs_from_compile_commands",
    "resolve_dependencies",
]
