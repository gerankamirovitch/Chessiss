"""AI strength through the real engine. Small samples of far-apart levels, so a result
here means a real regression and not chance. Adjacent levels need about 30 games each."""
import chess
import pytest

from core.engine import Engine
from core.game import outcome_of


def play_out(white, black, level_white, level_black, opening):
    board = chess.Board()
    for uci in opening:
        board.push_uci(uci)
    while outcome_of(board) is None and board.ply() < 200:
        engine, level = (white, level_white) if board.turn == chess.WHITE else (black, level_black)
        board.push(engine.best_move(board, level, remaining_ms=2500))
    outcome = outcome_of(board)
    return outcome.result if outcome else "*"


@pytest.fixture(scope="module")
def engines(stockfish_path):
    pair = Engine(stockfish_path, hash_mb=16), Engine(stockfish_path, hash_mb=16)
    for engine in pair:
        engine.start()
    yield pair
    for engine in pair:
        engine.stop()


@pytest.mark.parametrize(
    "strong,weak,opening",
    [
        (20, 1, ("e2e4", "e7e5")),
        (10, 2, ("d2d4", "d7d5")),
    ],
)
def test_stronger_level_does_not_lose_with_either_color(engines, strong, weak, opening):
    a, b = engines
    as_white = play_out(a, b, strong, weak, opening)
    as_black = play_out(a, b, weak, strong, opening)
    assert as_white == "1-0", f"level {strong} as white: {as_white}"
    assert as_black == "0-1", f"level {strong} as black: {as_black}"
