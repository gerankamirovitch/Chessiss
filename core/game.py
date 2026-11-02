"""One game of chess: rules through python-chess, clock, undo, result."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Sequence

import chess

from core.clock import ChessClock, TimeControl


class Mode(str, Enum):
    AI = "ai"
    LOCAL = "local"
    IMPORT = "import"


MODE_NAMES = {
    Mode.AI: "Против AI",
    Mode.LOCAL: "Вдвоём",
    Mode.IMPORT: "Импорт PGN",
}


class Termination(str, Enum):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT = "insufficient"
    FIFTY_MOVES = "fifty_moves"
    THREEFOLD = "threefold"
    SEVENTYFIVE_MOVES = "seventyfive_moves"
    FIVEFOLD = "fivefold"
    AGREEMENT = "agreement"
    RESIGNATION = "resignation"
    TIME = "time"
    TIME_DRAW = "time_draw"


TERMINATION_TEXT = {
    Termination.CHECKMATE: "мат",
    Termination.STALEMATE: "пат",
    Termination.INSUFFICIENT: "недостаточно материала для мата",
    Termination.FIFTY_MOVES: "правило 50 ходов",
    Termination.THREEFOLD: "троекратное повторение позиции",
    Termination.SEVENTYFIVE_MOVES: "правило 75 ходов",
    Termination.FIVEFOLD: "пятикратное повторение позиции",
    Termination.AGREEMENT: "соглашение сторон",
    Termination.RESIGNATION: "сдача",
    Termination.TIME: "просрочка времени",
    Termination.TIME_DRAW: "просрочка времени, но у соперника нечем поставить мат",
}

_OUTCOME_TERMINATIONS = {
    chess.Termination.CHECKMATE: Termination.CHECKMATE,
    chess.Termination.STALEMATE: Termination.STALEMATE,
    chess.Termination.INSUFFICIENT_MATERIAL: Termination.INSUFFICIENT,
    chess.Termination.SEVENTYFIVE_MOVES: Termination.SEVENTYFIVE_MOVES,
    chess.Termination.FIVEFOLD_REPETITION: Termination.FIVEFOLD,
}


@dataclass(frozen=True)
class GameOutcome:
    result: str  # "1-0", "0-1", "1/2-1/2"
    termination: Termination

    @property
    def winner(self) -> Optional[bool]:
        if self.result == "1-0":
            return chess.WHITE
        if self.result == "0-1":
            return chess.BLACK
        return None

    @property
    def text(self) -> str:
        reason = TERMINATION_TEXT[self.termination]
        if self.winner is None:
            return f"Ничья: {reason}."
        side = "Белые" if self.winner == chess.WHITE else "Чёрные"
        return f"{side} выиграли: {reason}."


@dataclass(frozen=True)
class GameSetup:
    mode: Mode
    time_control: TimeControl
    player_color: Optional[bool] = None  # None for two humans at one computer
    level: int = 5


@dataclass(frozen=True)
class PlayedMove:
    move: chess.Move
    san: str
    ply: int  # 1-based
    color: bool
    is_capture: bool
    is_check: bool
    board_before: chess.Board


def outcome_of(board: chess.Board) -> Optional[GameOutcome]:
    """Game end by the rules on the board. Threefold and 50 moves end the game
    automatically: the app has no separate "claim a draw" button."""
    outcome = board.outcome()
    if outcome is not None:
        return GameOutcome(outcome.result(), _OUTCOME_TERMINATIONS[outcome.termination])
    if board.is_repetition(3):
        return GameOutcome("1/2-1/2", Termination.THREEFOLD)
    if board.is_fifty_moves():
        return GameOutcome("1/2-1/2", Termination.FIFTY_MOVES)
    return None


def flag_outcome(board: chess.Board, flagged: bool) -> GameOutcome:
    opponent = not flagged
    if board.has_insufficient_material(opponent):
        return GameOutcome("1/2-1/2", Termination.TIME_DRAW)
    return GameOutcome("1-0" if opponent == chess.WHITE else "0-1", Termination.TIME)


class GameSession:
    def __init__(
        self,
        setup: GameSetup,
        start_fen: str = chess.STARTING_FEN,
        now: Callable[[], float] = time.monotonic,
        white_ms: Optional[int] = None,
        black_ms: Optional[int] = None,
    ) -> None:
        self.setup = setup
        self.start_fen = start_fen
        self.board = chess.Board(start_fen)
        self.clock = ChessClock(setup.time_control, now, white_ms, black_ms)
        self.outcome: Optional[GameOutcome] = None
        self.started_at = datetime.now()
        self.game_id: Optional[int] = None
        self._sans: list[str] = []
        self._clock_stack: list[tuple[int, int]] = []

    @classmethod
    def resume(
        cls,
        setup: GameSetup,
        start_fen: str,
        moves: Sequence[chess.Move],
        white_ms: int,
        black_ms: int,
        started_at: Optional[datetime] = None,
        game_id: Optional[int] = None,
        now: Callable[[], float] = time.monotonic,
    ) -> "GameSession":
        session = cls(setup, start_fen, now, white_ms, black_ms)
        for move in moves:
            session._clock_stack.append((white_ms, black_ms))
            session._sans.append(session.board.san(move))
            session.board.push(move)
        session.game_id = game_id
        if started_at is not None:
            session.started_at = started_at
        return session

    # --- queries -------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return self.setup.mode

    @property
    def is_over(self) -> bool:
        return self.outcome is not None

    @property
    def ply_count(self) -> int:
        return len(self.board.move_stack)

    @property
    def sans(self) -> list[str]:
        return list(self._sans)

    @property
    def moves(self) -> list[chess.Move]:
        return list(self.board.move_stack)

    @property
    def is_ai_turn(self) -> bool:
        return (
            self.mode == Mode.AI
            and not self.is_over
            and self.board.turn != self.setup.player_color
        )

    @property
    def fen(self) -> str:
        return self.board.fen()

    @property
    def can_pause(self) -> bool:
        return self.mode == Mode.LOCAL and not self.setup.time_control.untimed and not self.is_over

    def board_at(self, ply: int) -> chess.Board:
        board = chess.Board(self.start_fen)
        for move in self.board.move_stack[:ply]:
            board.push(move)
        return board

    def legal_targets(self, square: int) -> list[int]:
        if self.is_over:
            return []
        return [m.to_square for m in self.board.legal_moves if m.from_square == square]

    def needs_promotion(self, from_square: int, to_square: int) -> bool:
        if self.is_over:
            return False
        return self.board.piece_type_at(from_square) == chess.PAWN and any(
            m.from_square == from_square and m.to_square == to_square and m.promotion
            for m in self.board.legal_moves
        )

    def build_move(
        self, from_square: int, to_square: int, promotion: Optional[int] = None
    ) -> Optional[chess.Move]:
        move = chess.Move(from_square, to_square, promotion)
        return move if move in self.board.legal_moves else None

    # --- actions -------------------------------------------------------------

    def start(self) -> None:
        if not self.is_over:
            self.clock.start(self.board.turn)

    def play(self, move: chess.Move) -> Optional[PlayedMove]:
        """Apply a legal move. Returns None if time ran out before the move landed
        (self.outcome is set in that case)."""
        if self.is_over:
            raise ValueError("game is over")
        if move not in self.board.legal_moves:
            raise ValueError(f"illegal move {move.uci()} in {self.board.fen()}")
        if self.poll_flag() is not None:
            return None

        before = self.board.copy()
        color = self.board.turn
        san = self.board.san(move)
        is_capture = self.board.is_capture(move)
        self._clock_stack.append(self.clock.snapshot())
        self.board.push(move)
        self._sans.append(san)
        self.clock.press(color)

        self.outcome = outcome_of(self.board)
        if self.outcome is not None:
            self.clock.stop()
        return PlayedMove(
            move, san, self.ply_count, color, is_capture, self.board.is_check(), before
        )

    def undo_size(self) -> int:
        """How many plies "undo" takes back. In a game against the AI it returns the
        move to the human, so one ply while the AI thinks and two after it replied."""
        if self.is_over or self.mode == Mode.IMPORT:
            return 0
        if self.mode == Mode.LOCAL:
            return 1 if self.ply_count >= 1 else 0
        size = 1 if self.board.turn != self.setup.player_color else 2
        return size if self.ply_count >= size else 0

    def undo(self) -> int:
        size = self.undo_size()
        for _ in range(size):
            self.board.pop()
            self._sans.pop()
            snapshot = self._clock_stack.pop()
        if size:
            self.clock.restore(snapshot, self.board.turn if self.clock.is_running else None)
        return size

    def resign(self, color: bool) -> GameOutcome:
        return self._finish(
            GameOutcome("0-1" if color == chess.WHITE else "1-0", Termination.RESIGNATION)
        )

    def agree_draw(self) -> GameOutcome:
        return self._finish(GameOutcome("1/2-1/2", Termination.AGREEMENT))

    def poll_flag(self) -> Optional[GameOutcome]:
        """Ends the game if the clock of the side to move ran out."""
        if self.is_over:
            return self.outcome
        flagged = self.clock.flagged()
        if flagged is None:
            return None
        return self._finish(flag_outcome(self.board, flagged))

    def _finish(self, outcome: GameOutcome) -> GameOutcome:
        self.outcome = outcome
        self.clock.stop()
        return outcome
