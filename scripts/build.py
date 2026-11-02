"""Builds the portable Windows x64 folder dist/Chessiss with Stockfish inside.
Run scripts/fetch_stockfish.py first. Needs requirements-dev.txt."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engines" / "stockfish"
SEP = ";"

# Qt modules and stdlib packages the app does not use. Cuts size and startup time.
EXCLUDES = (
    "tkinter", "unittest", "pydoc", "pytest", "zstandard",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
    "PySide6.QtOpenGL", "PySide6.QtDBus",
)


def main() -> int:
    if not (ENGINE / "stockfish.exe").exists():
        print("engines/stockfish/stockfish.exe is missing, run scripts/fetch_stockfish.py", file=sys.stderr)
        return 1
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", "Chessiss",
        "--specpath", str(ROOT / "build"),
        "--workpath", str(ROOT / "build"),
        "--distpath", str(ROOT / "dist"),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'data' / 'puzzles.json'}{SEP}data",
        "--add-binary", f"{ENGINE / 'stockfish.exe'}{SEP}engines/stockfish",
        "--add-data", f"{ENGINE / 'Copying.txt'}{SEP}engines/stockfish",
    ]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command.append(str(ROOT / "main.py"))
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
