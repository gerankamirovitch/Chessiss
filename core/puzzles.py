"""Solving one tactical puzzle: checks moves, plays the forced replies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import chess

THEMES = {
    "fork": "Вилка",
    "pin": "Связка",
    "mate1": "Мат в 1 ход",
    "mate2": "Мат в 2 хода",
    "mate3": "Мат в 3 хода",
    "material": "Выигрыш материала",
}


@dataclass
class Puzzle:
    id: str
    fen: str
    solution: list[str]  # UCI, the solver moves first
    theme: str
    rating: int
    solved: bool = False
    used_hint: bool = False

    @property
    def theme_name(self) -> str:
        return THEMES.get(self.theme, self.theme)


class Attempt(Enum):
    WRONG = "wrong"
    CORRECT = "correct"  # the line goes on
    SOLVED = "solved"


class PuzzleSession:
    def __init__(self, puzzle: Puzzle) -> None:
        self.puzzle = puzzle
        self.board = chess.Board(puzzle.fen)
        self.solver = self.board.turn
        self.index = 0
        self.used_hint = False
        self.mistakes = 0

    @property
    def is_solved(self) -> bool:
        return self.index >= len(self.puzzle.solution)

    @property
    def expected(self) -> Optional[chess.Move]:
        if self.is_solved:
            return None
        return chess.Move.from_uci(self.puzzle.solution[self.index])

    def legal_targets(self, square: int) -> list[int]:
        if self.is_solved:
            return []
        return [m.to_square for m in self.board.legal_moves if m.from_square == square]

    def needs_promotion(self, from_square: int, to_square: int) -> bool:
        return not self.is_solved and self.board.piece_type_at(from_square) == chess.PAWN and any(
            m.from_square == from_square and m.to_square == to_square and m.promotion
            for m in self.board.legal_moves
        )

    def try_move(self, move: chess.Move) -> Attempt:
        """A wrong move leaves the board as it was. A different move that also mates
        on the last step counts: Lichess accepts any checkmate there."""
        if self.is_solved or move not in self.board.legal_moves:
            return Attempt.WRONG
        if move != self.expected and not self._is_alternative_mate(move):
            self.mistakes += 1
            return Attempt.WRONG
        self.board.push(move)
        self.index += 1
        return Attempt.SOLVED if self.is_solved else Attempt.CORRECT

    def play_reply(self) -> Optional[chess.Move]:
        """The forced answer of the other side, after a CORRECT attempt."""
        if self.is_solved or self.board.turn == self.solver:
            return None
        reply = chess.Move.from_uci(self.puzzle.solution[self.index])
        self.board.push(reply)
        self.index += 1
        return reply

    def hint(self) -> Optional[chess.Move]:
        move = self.expected
        if move is not None:
            self.used_hint = True
        return move

    def reset(self) -> None:
        self.board = chess.Board(self.puzzle.fen)
        self.index = 0

    def _is_alternative_mate(self, move: chess.Move) -> bool:
        if self.index != len(self.puzzle.solution) - 1:
            return False
        self.board.push(move)
        mate = self.board.is_checkmate()
        self.board.pop()
        return mate
