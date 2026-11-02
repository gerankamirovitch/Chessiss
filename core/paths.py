"""Locations of bundled resources and of user data on disk."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Project root when run from source, the unpacked bundle when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Folder for the database, generated sounds and the error log."""
    override = os.environ.get("CHESSISS_DATA_DIR")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / "Chessiss"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "chessiss.db"


def puzzle_seed_path() -> Path:
    return resource_root() / "data" / "puzzles.json"


def bundled_engine_dir() -> Path:
    return resource_root() / "engines" / "stockfish"
