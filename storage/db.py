"""SQLite storage. Every write commits at once, so closing the app at any moment
loses nothing. The `mark` and `used_hint` columns extend the base schema: move
marks must survive restarts, and statistics count puzzles solved with a hint."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import chess

from core.puzzles import Puzzle

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    mode TEXT NOT NULL,
    player_color TEXT,
    time_control TEXT NOT NULL,
    result TEXT NOT NULL,
    pgn TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS games_date ON games(date DESC);
CREATE TABLE IF NOT EXISTS moves (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    ply INTEGER NOT NULL,
    move_san TEXT NOT NULL,
    eval_cp INTEGER,
    comment TEXT,
    mark TEXT,
    PRIMARY KEY (game_id, ply)
);
CREATE TABLE IF NOT EXISTS puzzles (
    id TEXT PRIMARY KEY,
    fen TEXT NOT NULL,
    solution_moves TEXT NOT NULL,
    theme TEXT NOT NULL,
    rating INTEGER NOT NULL,
    solved INTEGER NOT NULL DEFAULT 0,
    used_hint INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS puzzles_theme ON puzzles(theme, rating);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    "theme": "light",
    "sound": "1",
    "language": "ru",
    "ai_level": "5",
    "stockfish_path": "",
}

COLOR_NAMES = {chess.WHITE: "white", chess.BLACK: "black"}
COLORS_BY_NAME = {name: color for color, name in COLOR_NAMES.items()}


@dataclass
class GameRow:
    id: int
    date: datetime
    mode: str
    player_color: Optional[bool]
    time_control: str
    result: str
    pgn: str


@dataclass
class MoveRow:
    ply: int
    san: str
    eval_cp: Optional[int]
    comment: Optional[str]
    mark: Optional[str]


@dataclass(frozen=True)
class PuzzleStats:
    total: int
    solved: int
    solved_with_hint: int


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        with self._db:
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    # --- settings ------------------------------------------------------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            return row["value"]
        return DEFAULT_SETTINGS.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM settings WHERE key = ?", (key,))

    def get_json(self, key: str, default=None):
        raw = self.get_setting(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def set_json(self, key: str, value) -> None:
        self.set_setting(key, json.dumps(value, ensure_ascii=False))

    def seen_terms(self) -> set[str]:
        return set(self.get_json("seen_terms", []))

    def save_seen_terms(self, terms: Iterable[str]) -> None:
        self.set_json("seen_terms", sorted(terms))

    # --- games ---------------------------------------------------------------

    def create_game(
        self,
        date: datetime,
        mode: str,
        player_color: Optional[bool],
        time_control: str,
        result: str,
        pgn: str,
    ) -> int:
        color = COLOR_NAMES[player_color] if player_color is not None else None
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO games(date, mode, player_color, time_control, result, pgn) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (date.isoformat(timespec="seconds"), mode, color, time_control, result, pgn),
            )
        return int(cursor.lastrowid)

    def update_game(self, game_id: int, result: str, pgn: str) -> None:
        with self._db:
            self._db.execute("UPDATE games SET result = ?, pgn = ? WHERE id = ?", (result, pgn, game_id))

    def get_game(self, game_id: int) -> Optional[GameRow]:
        row = self._db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return _game_from_row(row) if row else None

    def delete_game(self, game_id: int) -> None:
        with self._db:
            self._db.execute("DELETE FROM games WHERE id = ?", (game_id,))

    def find_game_by_pgn(self, pgn: str) -> Optional[int]:
        row = self._db.execute("SELECT id FROM games WHERE pgn = ?", (pgn,)).fetchone()
        return int(row["id"]) if row else None

    def list_games(
        self, mode: Optional[str] = None, outcome: Optional[str] = None, limit: Optional[int] = None
    ) -> list[GameRow]:
        """`outcome`: "win"/"loss" from the player's side (AI games only), or the
        board result: "white", "black", "draw", "unfinished"."""
        where, args = [], []
        if mode:
            where.append("mode = ?")
            args.append(mode)
        condition = _OUTCOME_FILTERS.get(outcome) if outcome else None
        if condition:
            where.append(condition)
        sql = "SELECT * FROM games"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_game_from_row(row) for row in self._db.execute(sql, args)]

    # --- moves ---------------------------------------------------------------

    def add_move(self, game_id: int, ply: int, san: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO moves(game_id, ply, move_san) VALUES(?, ?, ?)",
                (game_id, ply, san),
            )

    def record_move(
        self, game_id: int, ply: int, san: str, result: str, pgn: str, active_state: Optional[dict]
    ) -> None:
        """Everything a played move changes, in one transaction and one disk flush."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO moves(game_id, ply, move_san) VALUES(?, ?, ?)", (game_id, ply, san)
            )
            self._db.execute("UPDATE games SET result = ?, pgn = ? WHERE id = ?", (result, pgn, game_id))
            if active_state is not None:
                self._db.execute(
                    "INSERT INTO settings(key, value) VALUES('active_game', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (json.dumps(active_state, ensure_ascii=False),),
                )

    def annotate_move(self, game_id: int, ply: int, eval_cp: int, comment: str, mark: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE moves SET eval_cp = ?, comment = ?, mark = ? WHERE game_id = ? AND ply = ?",
                (eval_cp, comment, mark, game_id, ply),
            )

    def save_review(self, game_id: int, rows: Iterable[tuple[int, str, int, str, str]]) -> None:
        """Replaces annotations for a whole game in one transaction.
        Rows are (ply, san, eval_cp, comment, mark)."""
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO moves(game_id, ply, move_san, eval_cp, comment, mark) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [(game_id, *row) for row in rows],
            )

    def delete_moves_from(self, game_id: int, first_ply: int) -> None:
        with self._db:
            self._db.execute("DELETE FROM moves WHERE game_id = ? AND ply >= ?", (game_id, first_ply))

    def get_moves(self, game_id: int) -> list[MoveRow]:
        rows = self._db.execute(
            "SELECT ply, move_san, eval_cp, comment, mark FROM moves WHERE game_id = ? ORDER BY ply",
            (game_id,),
        )
        return [MoveRow(r["ply"], r["move_san"], r["eval_cp"], r["comment"], r["mark"]) for r in rows]

    # --- puzzles -------------------------------------------------------------

    def seed_puzzles(self, puzzles: Iterable[dict]) -> int:
        """Adds new puzzles and keeps progress on existing ones. Returns how many were new."""
        with self._db:
            before = self._db.total_changes
            self._db.executemany(
                "INSERT OR IGNORE INTO puzzles(id, fen, solution_moves, theme, rating) VALUES(?, ?, ?, ?, ?)",
                [(p["id"], p["fen"], " ".join(p["solution"]), p["theme"], p["rating"]) for p in puzzles],
            )
            return self._db.total_changes - before

    def seed_puzzles_from_file(self, path: Path) -> int:
        version = str(path.stat().st_size)
        if self.get_setting("puzzle_seed") == version and self.puzzle_count() > 0:
            return 0
        with path.open(encoding="utf-8") as stream:
            added = self.seed_puzzles(json.load(stream)["puzzles"])
        self.set_setting("puzzle_seed", version)
        return added

    def puzzle_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0])

    def list_puzzles(self, theme: Optional[str] = None, unsolved_only: bool = False) -> list[Puzzle]:
        where, args = [], []
        if theme:
            where.append("theme = ?")
            args.append(theme)
        if unsolved_only:
            where.append("solved = 0")
        sql = "SELECT * FROM puzzles"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rating, id"
        return [_puzzle_from_row(row) for row in self._db.execute(sql, args)]

    def get_puzzle(self, puzzle_id: str) -> Optional[Puzzle]:
        row = self._db.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
        return _puzzle_from_row(row) if row else None

    def mark_puzzle_solved(self, puzzle_id: str, used_hint: bool) -> None:
        """A puzzle once solved without help stays that way after a later replay with a hint."""
        with self._db:
            self._db.execute(
                "UPDATE puzzles SET used_hint = CASE WHEN solved = 1 THEN used_hint AND ? ELSE ? END, "
                "solved = 1 WHERE id = ?",
                (int(used_hint), int(used_hint), puzzle_id),
            )

    def puzzle_stats(self, theme: Optional[str] = None) -> PuzzleStats:
        sql = "SELECT COUNT(*) AS total, COALESCE(SUM(solved), 0) AS solved, " \
              "COALESCE(SUM(solved AND used_hint), 0) AS hinted FROM puzzles"
        args: tuple = ()
        if theme:
            sql += " WHERE theme = ?"
            args = (theme,)
        row = self._db.execute(sql, args).fetchone()
        return PuzzleStats(int(row["total"]), int(row["solved"]), int(row["hinted"]))


_OUTCOME_FILTERS = {
    "win": "((player_color = 'white' AND result = '1-0') OR (player_color = 'black' AND result = '0-1'))",
    "loss": "((player_color = 'white' AND result = '0-1') OR (player_color = 'black' AND result = '1-0'))",
    "white": "result = '1-0'",
    "black": "result = '0-1'",
    "draw": "result = '1/2-1/2'",
    "unfinished": "result = '*'",
}


def _game_from_row(row: sqlite3.Row) -> GameRow:
    return GameRow(
        id=int(row["id"]),
        date=datetime.fromisoformat(row["date"]),
        mode=row["mode"],
        player_color=COLORS_BY_NAME.get(row["player_color"]),
        time_control=row["time_control"],
        result=row["result"],
        pgn=row["pgn"],
    )


def _puzzle_from_row(row: sqlite3.Row) -> Puzzle:
    return Puzzle(
        id=row["id"],
        fen=row["fen"],
        solution=row["solution_moves"].split(),
        theme=row["theme"],
        rating=int(row["rating"]),
        solved=bool(row["solved"]),
        used_hint=bool(row["used_hint"]),
    )
