"""Runs Stockfish over positions and hands the numbers to the explanation generator."""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import chess

from core.engine import Engine, Line
from core.explain import Hint, Mark, MoveExplanation, ai_accepts_draw, build_hints, explain_move
from core.game import outcome_of

LIVE_DEPTH = 14
LIVE_TIME_S = 0.4
REVIEW_DEPTH = 16
REVIEW_TIME_S = 0.8
_CACHE_SIZE = 512


@dataclass
class GameReview:
    explanations: list[MoveExplanation] = field(default_factory=list)
    complete: bool = True

    @property
    def evals(self) -> list[int]:
        return [item.score.cp for item in self.explanations]

    def counts(self, color: bool) -> Counter:
        return Counter(item.mark for item in self.explanations if item.color == color)


class Analyzer:
    """Evaluations are cached by position, so the "after" of one move is the
    "before" of the next and the engine runs once per position."""

    def __init__(self, engine: Engine, depth: int = LIVE_DEPTH, time_s: float = LIVE_TIME_S) -> None:
        self.engine = engine
        self.depth = depth
        self.time_s = time_s
        self._cache: "OrderedDict[tuple[str, int], list[Line]]" = OrderedDict()

    def lines(self, board: chess.Board, multipv: int = 1) -> list[Line]:
        key = (board.fen(), multipv)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        lines = self.engine.analyse(board, self.depth, self.time_s, multipv)
        self._cache[key] = lines
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return lines

    def top_line(self, board: chess.Board) -> Line:
        return self.lines(board)[0]

    def explain(self, board: chess.Board, move: chess.Move, game_continues: bool = False) -> MoveExplanation:
        """`game_continues`: the record has more moves after this one, so a repetition
        or the 50-move rule was not claimed here and the position is still being played."""
        best = self.top_line(board)
        after = board.copy()
        after.push(move)
        final = after.outcome() is not None if game_continues else outcome_of(after) is not None
        return explain_move(board, move, best, None if final else self.top_line(after))

    def hints(self, board: chess.Board, count: int = 3) -> list[Hint]:
        return build_hints(board, self.lines(board, multipv=count), limit=count)

    def accepts_draw(self, board: chess.Board, ai_color: bool) -> bool:
        return ai_accepts_draw(self.top_line(board).score, ai_color, board.fullmove_number)


def review_game(
    engine: Engine,
    start_fen: str,
    moves: Sequence[chess.Move],
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    depth: int = REVIEW_DEPTH,
    time_s: float = REVIEW_TIME_S,
) -> GameReview:
    analyzer = Analyzer(engine, depth, time_s)
    review = GameReview()
    board = chess.Board(start_fen)
    for index, move in enumerate(moves):
        if should_stop is not None and should_stop():
            review.complete = False
            return review
        review.explanations.append(analyzer.explain(board, move, game_continues=index < len(moves) - 1))
        board.push(move)
        if on_progress is not None:
            on_progress(index + 1, len(moves))
    return review


__all__ = ["Analyzer", "GameReview", "Hint", "Mark", "review_game"]
