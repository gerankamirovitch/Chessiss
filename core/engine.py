"""Stockfish over UCI. Every call blocks, so the UI runs them on worker threads."""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chess
import chess.engine

from core.paths import bundled_engine_dir

MIN_LEVEL = 1
MAX_LEVEL = 20

# Scores are clamped to this many centipawns everywhere: past it the size of
# the advantage carries no information for a learner, and a mate counts as this.
EVAL_CLAMP = 1000


class EngineFailure(Exception):
    """Missing, broken or crashed engine. The message is shown to the user as is."""


@dataclass(frozen=True)
class LevelParams:
    skill: int  # UCI "Skill Level", 0..20
    depth: int
    movetime_ms: int


# Measured in matches: with equal depth a higher Skill Level alone can play worse
# (level 6 lost to level 5 at depth 3, +10 =3 -17), so depth grows from level 5 on.
_DEPTHS = (1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 22, 30)
_MOVETIMES = (50, 50, 60, 70, 80, 100, 120, 150, 180, 220,
              260, 300, 350, 400, 500, 600, 800, 1000, 1500, 2000)


def level_params(level: int) -> LevelParams:
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise ValueError(f"level must be {MIN_LEVEL}..{MAX_LEVEL}, got {level}")
    index = level - 1
    return LevelParams(round(index * 20 / 19), _DEPTHS[index], _MOVETIMES[index])


def move_time_ms(level: int, remaining_ms: Optional[int], increment_ms: int = 0) -> int:
    """Thinking time for a move: the level's limit, shortened when the clock is low."""
    limit = level_params(level).movetime_ms
    if remaining_ms is None:
        return limit
    return max(20, min(limit, remaining_ms // 25 + increment_ms // 2))


@dataclass(frozen=True)
class Score:
    """Evaluation from white's point of view."""

    cp: int = 0
    mate: Optional[int] = None  # moves to mate, positive when white mates

    @classmethod
    def from_pov(cls, pov: chess.engine.PovScore) -> "Score":
        white = pov.white()
        if white.is_mate():
            return cls(EVAL_CLAMP if white.mate() > 0 else -EVAL_CLAMP, white.mate())
        return cls(max(-EVAL_CLAMP, min(EVAL_CLAMP, white.score())))

    def for_color(self, color: bool) -> int:
        return self.cp if color == chess.WHITE else -self.cp

    def mate_for(self, color: bool) -> Optional[int]:
        if self.mate is None:
            return None
        return self.mate if color == chess.WHITE else -self.mate


@dataclass(frozen=True)
class Line:
    score: Score
    pv: tuple[chess.Move, ...]

    @property
    def move(self) -> chess.Move:
        return self.pv[0]


def find_stockfish(custom_path: Optional[str] = None) -> Optional[Path]:
    """Path from settings, then the bundled binary, then PATH."""
    if custom_path:
        path = Path(custom_path)
        return path if path.is_file() else None
    directory = bundled_engine_dir()
    if directory.is_dir():
        for candidate in sorted(directory.glob("stockfish*.exe")):
            return candidate
    found = shutil.which("stockfish")
    return Path(found) if found else None


class Engine:
    """One Stockfish process. Thread-safe: python-chess cancels the running command
    when a new one arrives, so calls are serialized with a lock."""

    def __init__(self, path: Path | str, threads: int = 1, hash_mb: int = 64) -> None:
        self.path = Path(path)
        self._options = {"Threads": threads, "Hash": hash_mb}
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._lock = threading.Lock()
        self._skill: Optional[int] = None

    @property
    def name(self) -> str:
        with self._lock:
            return self._engine.id.get("name", "") if self._engine else ""

    @property
    def is_running(self) -> bool:
        return self._engine is not None

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def restart(self) -> None:
        with self._lock:
            self._stop_locked()
            self._start_locked()

    def best_move(
        self, board: chess.Board, level: int, remaining_ms: Optional[int] = None, increment_ms: int = 0
    ) -> chess.Move:
        params = level_params(level)
        limit = chess.engine.Limit(
            depth=params.depth, time=move_time_ms(level, remaining_ms, increment_ms) / 1000
        )
        with self._lock:
            engine = self._require()
            try:
                if self._skill != params.skill:
                    engine.configure({"Skill Level": params.skill})
                    self._skill = params.skill
                move = engine.play(board, limit).move
            except Exception as error:
                self._fail(error)
        if move is None:
            raise EngineFailure("Stockfish не вернул ход.")
        return move

    def analyse(
        self, board: chess.Board, depth: int = 14, time_s: float = 0.5, multipv: int = 1
    ) -> list[Line]:
        limit = chess.engine.Limit(depth=depth, time=time_s)
        with self._lock:
            engine = self._require()
            try:
                infos = engine.analyse(board, limit, multipv=multipv)
            except Exception as error:
                self._fail(error)
        lines = [
            Line(Score.from_pov(info["score"]), tuple(info.get("pv", ())))
            for info in infos
            if "score" in info and info.get("pv")
        ]
        if not lines:
            raise EngineFailure("Stockfish не вернул оценку позиции.")
        return lines

    def _require(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            raise EngineFailure("Stockfish не запущен.")
        return self._engine

    def _start_locked(self) -> None:
        if self._engine is not None:
            return
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(
                str(self.path), timeout=10.0, **kwargs
            )
            self._engine.configure(self._options)
        except Exception as error:
            self._stop_locked()
            raise EngineFailure(
                f"Не удалось запустить Stockfish ({self.path}): {error or type(error).__name__}"
            ) from error
        self._skill = None

    def _stop_locked(self) -> None:
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            engine.close()
        except Exception:
            pass

    def _fail(self, error: Exception) -> None:
        self._stop_locked()
        raise EngineFailure(
            f"Stockfish перестал отвечать: {error or type(error).__name__}"
        ) from error
