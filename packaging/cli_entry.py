"""PyInstaller entry point for codepack-cli.exe (console)."""

from codepack.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
