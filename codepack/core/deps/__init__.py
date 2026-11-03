"""Phase 2: C++ dependency analysis (not implemented yet).

Planned interface::

    class DependencyResolver(Protocol):
        def resolve(self, source: Path, ctx: BuildContext) -> list[Path]: ...

Implementations: a regex #include parser, then g++ -MM and MSVC /showIncludes.
BuildContext will be populated from compile_commands.json.
"""
