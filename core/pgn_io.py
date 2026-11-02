"""PGN and FEN: building, parsing, display helpers."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import chess
import chess.pgn

from core.game import GameSession, Mode, Termination

_RU_PIECES = str.maketrans({"N": "К", "B": "С", "R": "Л", "Q": "Ф", "O": "0"})


def ru_san(san: str) -> str:
    """Standard SAN in Russian piece letters, for display only: "Nf3" -> "Кf3"."""
    if san.startswith("K"):
        san = "Кр" + san[1:]
    return san.translate(_RU_PIECES)


def is_valid_fen(fen: str) -> bool:
    try:
        return chess.Board(fen).is_valid()
    except ValueError:
        return False


@dataclass
class ParsedGame:
    start_fen: str
    moves: list[chess.Move]
    sans: list[str]
    headers: dict[str, str]
    result: str
    pgn: str
    errors: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        white = self.headers.get("White", "?")
        black = self.headers.get("Black", "?")
        date = self.headers.get("Date", "")
        return f"{white} — {black}, {date}, {self.result}, ходов: {(len(self.moves) + 1) // 2}"

    def board_at(self, ply: int) -> chess.Board:
        board = chess.Board(self.start_fen)
        for move in self.moves[:ply]:
            board.push(move)
        return board


def session_to_pgn(session: GameSession) -> str:
    board = chess.Board(session.start_fen)
    for move in session.moves:
        board.push(move)
    game = chess.pgn.Game.from_board(board)
    headers = game.headers
    headers["Event"] = "Chessiss"
    headers["Site"] = "Local"
    headers["Date"] = session.started_at.strftime("%Y.%m.%d")
    headers["Round"] = "-"
    white, black = _player_names(session)
    headers["White"] = white
    headers["Black"] = black
    headers["TimeControl"] = session.setup.time_control.pgn_tag
    if session.outcome is not None:
        headers["Result"] = session.outcome.result
        game.headers["Termination"] = (
            "time forfeit"
            if session.outcome.termination in (Termination.TIME, Termination.TIME_DRAW)
            else "normal"
        )
        headers["ChessissTermination"] = session.outcome.termination.value
    else:
        headers["Result"] = "*"
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return game.accept(exporter)


def _player_names(session: GameSession) -> tuple[str, str]:
    if session.mode != Mode.AI:
        return "Белые", "Чёрные"
    engine = f"Stockfish, уровень {session.setup.level}"
    if session.setup.player_color == chess.WHITE:
        return "Игрок", engine
    return engine, "Игрок"


def read_games(text: str) -> list[ParsedGame]:
    """Every game in a PGN text. Games without a single header or move are skipped."""
    stream = io.StringIO(text)
    games: list[ParsedGame] = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            return games
        try:
            parsed = _parse(game)
        except ValueError:  # a [FEN] header that is malformed or describes an impossible position
            continue
        if parsed.moves or parsed.errors or any(
            value not in ("?", "????.??.??", "*") for value in parsed.headers.values()
        ):
            games.append(parsed)


def _parse(game: chess.pgn.Game) -> ParsedGame:
    board = game.board()
    if not board.is_valid():  # Stockfish must never be handed an impossible position
        raise ValueError(f"impossible position: {board.fen()}")
    start_fen = board.fen()
    moves: list[chess.Move] = []
    sans: list[str] = []
    for move in game.mainline_moves():
        sans.append(board.san(move))
        board.push(move)
        moves.append(move)
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return ParsedGame(
        start_fen=start_fen,
        moves=moves,
        sans=sans,
        headers=dict(game.headers),
        result=game.headers.get("Result", "*"),
        pgn=game.accept(exporter),
        errors=[str(error) for error in game.errors],
    )


def read_first_game(text: str) -> Optional[ParsedGame]:
    games = read_games(text)
    return games[0] if games else None
