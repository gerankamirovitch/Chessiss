import json
from pathlib import Path

import chess
import pytest

from core.puzzles import THEMES, Attempt, Puzzle, PuzzleSession

SEED = Path(__file__).resolve().parent.parent / "data" / "puzzles.json"


def mate_in_two():
    # A scripted line for the session logic. The bundled set is checked separately below.
    return Puzzle("t", "6k1/5p2/6pQ/8/8/8/8/5RK1 w - - 0 1", ["h6h7", "g8f8", "h7h8"], "mate2", 1000)


def test_correct_sequence_with_reply():
    session = PuzzleSession(mate_in_two())
    assert session.solver == chess.WHITE
    assert session.try_move(chess.Move.from_uci("h6h7")) == Attempt.CORRECT
    assert session.play_reply() == chess.Move.from_uci("g8f8")
    assert session.try_move(chess.Move.from_uci("h7h8")) == Attempt.SOLVED
    assert session.is_solved
    assert session.expected is None
    assert session.legal_targets(chess.F1) == []


def test_wrong_move_changes_nothing_and_counts():
    session = PuzzleSession(mate_in_two())
    fen = session.board.fen()
    assert session.try_move(chess.Move.from_uci("h6g6")) == Attempt.WRONG
    assert session.board.fen() == fen
    assert session.mistakes == 1
    assert session.index == 0


def test_illegal_move_is_wrong():
    session = PuzzleSession(mate_in_two())
    assert session.try_move(chess.Move.from_uci("e2e4")) == Attempt.WRONG
    assert session.mistakes == 0


def test_any_mate_counts_on_the_last_step():
    # Two rook moves mate here; the stored line only has one of them.
    puzzle = Puzzle("m", "7k/R7/6K1/8/8/8/8/1R6 w - - 0 1", ["b1b8"], "mate1", 800)
    session = PuzzleSession(puzzle)
    assert session.try_move(chess.Move.from_uci("a7a8")) == Attempt.SOLVED


def test_other_mating_looking_move_early_in_the_line_is_wrong():
    session = PuzzleSession(mate_in_two())
    assert session.try_move(chess.Move.from_uci("f1e1")) == Attempt.WRONG


def test_hint_returns_expected_move_and_is_recorded():
    session = PuzzleSession(mate_in_two())
    assert session.used_hint is False
    assert session.hint() == chess.Move.from_uci("h6h7")
    assert session.used_hint is True
    session.reset()
    assert session.used_hint is True, "restarting does not erase having peeked"
    assert session.board.fen() == mate_in_two().fen


def test_promotion_detection():
    puzzle = Puzzle("p", "8/P6k/8/8/8/8/8/K7 w - - 0 1", ["a7a8q"], "material", 900)
    session = PuzzleSession(puzzle)
    assert session.needs_promotion(chess.A7, chess.A8)
    assert not session.needs_promotion(chess.A1, chess.A2)
    assert session.try_move(chess.Move.from_uci("a7a8n")) == Attempt.WRONG
    assert session.try_move(chess.Move.from_uci("a7a8q")) == Attempt.SOLVED


def test_theme_name():
    assert mate_in_two().theme_name == "Мат в 2 хода"


# --- the bundled set ---------------------------------------------------------

@pytest.fixture(scope="module")
def seed():
    if not SEED.exists():
        pytest.skip("data/puzzles.json not built yet")
    return json.loads(SEED.read_text(encoding="utf-8"))["puzzles"]


def test_seed_has_several_hundred_puzzles_for_every_theme(seed):
    assert len(seed) >= 300
    counts = {theme: sum(p["theme"] == theme for p in seed) for theme in THEMES}
    assert all(count >= 40 for count in counts.values()), counts


def test_seed_ids_are_unique(seed):
    assert len({p["id"] for p in seed}) == len(seed)


def test_every_seed_puzzle_replays_legally_and_ends_as_its_theme_says(seed):
    for puzzle in seed:
        board = chess.Board(puzzle["fen"])
        assert board.is_valid(), puzzle["id"]
        assert len(puzzle["solution"]) % 2 == 1, "the solver makes the last move: " + puzzle["id"]
        for uci in puzzle["solution"]:
            assert chess.Move.from_uci(uci) in board.legal_moves, puzzle["id"]
            board.push_uci(uci)
        if puzzle["theme"] in ("mate1", "mate2", "mate3"):
            assert board.is_checkmate(), puzzle["id"]
            assert len(puzzle["solution"]) == int(puzzle["theme"][-1]) * 2 - 1, puzzle["id"]


def test_every_seed_puzzle_can_be_solved_through_the_session(seed):
    for raw in seed:
        puzzle = Puzzle(raw["id"], raw["fen"], raw["solution"], raw["theme"], raw["rating"])
        session = PuzzleSession(puzzle)
        while not session.is_solved:
            attempt = session.try_move(session.expected)
            assert attempt != Attempt.WRONG, raw["id"]
            if attempt == Attempt.CORRECT:
                session.play_reply()
