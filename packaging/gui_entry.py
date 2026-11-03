"""PyInstaller entry point for CodePack.exe (windowed GUI)."""

from codepack.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
