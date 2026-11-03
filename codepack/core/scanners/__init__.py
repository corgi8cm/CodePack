"""Phase 2: content scanners such as secret detection (not implemented yet).

Planned interface::

    class ContentScanner(Protocol):
        def scan(self, rel_path: str, text: str) -> list[Finding]: ...
"""
