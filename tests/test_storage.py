from datetime import datetime

import chess
import pytest

from core.clock import TimeControl
from core.game import GameSession, GameSetup, Mode
from core.pgn_io import read_first_game, session_to_pgn
from storage.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def add_game(db, mode="ai", color=chess.WHITE, result="1-0", date=datetime(2026, 1, 1)):
    return db.create_game(date, mode, color, "5+0", result, f'[Result "{result}"]\n\n{result}')


def puzzle(pid="a", theme="fork", rating=1200):
    return {"id": pid, "fen": chess.STARTING_FEN, "solution": ["e2e4", "e7e5"], "theme": theme, "rating": rating}


def test_game_survives_reopening_the_file(tmp_path):
    path = tmp_path / "persist.db"
    session = GameSession(GameSetup(Mode.AI, TimeControl(5, 3), chess.BLACK, 7))
    session.start()
    for uci in ("e2e4", "c7c5", "g1f3"):
        session.play(chess.Move.from_uci(uci))
    session.resign(chess.BLACK)
    pgn = session_to_pgn(session)

    first = Database(path)
    game_id = first.create_game(session.started_at, "ai", chess.BLACK, "5+3", session.outcome.result, pgn)
    for ply, san in enumerate(session.sans, 1):
        first.add_move(game_id, ply, san)
    first.annotate_move(game_id, 2, -35, "Сицилианская", "good")
    first.close()  # nothing else flushes: every write has already committed

    second = Database(path)
    row = second.get_game(game_id)
    assert row.mode == "ai"
    assert row.player_color == chess.BLACK
    assert row.time_control == "5+3"
    assert row.result == "1-0"
    parsed = read_first_game(row.pgn)
    assert parsed.moves == session.moves
    assert parsed.result == "1-0"
    moves = second.get_moves(game_id)
    assert [m.san for m in moves] == ["e4", "c5", "Nf3"]
    assert moves[1].eval_cp == -35 and moves[1].comment == "Сицилианская" and moves[1].mark == "good"
    assert moves[0].eval_cp is None
    second.close()


def test_writes_are_visible_from_a_second_connection_without_close(tmp_path):
    path = tmp_path / "crash.db"
    writer = Database(path)
    game_id = add_game(writer)
    writer.add_move(game_id, 1, "e4")
    writer.set_setting("theme", "dark")
    reader = Database(path)  # stands in for a restart after the process died
    assert reader.get_moves(game_id)[0].san == "e4"
    assert reader.get_setting("theme") == "dark"
    writer.close()
    reader.close()


def test_record_move_writes_everything_a_move_changes(db):
    game_id = add_game(db, result="*")
    db.record_move(game_id, 1, "e4", "*", "1. e4 *", {"game_id": game_id})
    assert db.get_moves(game_id)[0].san == "e4"
    assert db.get_game(game_id).pgn == "1. e4 *"
    assert db.get_json("active_game") == {"game_id": game_id}
    db.record_move(game_id, 2, "e5", "1-0", "1. e4 e5 1-0", None)
    assert db.get_game(game_id).result == "1-0"
    assert db.get_json("active_game") == {"game_id": game_id}, "None leaves the saved state alone"


def test_filter_by_mode_and_result(db):
    add_game(db, "ai", chess.WHITE, "1-0")
    add_game(db, "ai", chess.BLACK, "1-0")
    add_game(db, "ai", chess.BLACK, "0-1")
    add_game(db, "local", None, "1/2-1/2")
    add_game(db, "local", None, "*")
    assert len(db.list_games()) == 5
    assert len(db.list_games(mode="local")) == 2
    assert len(db.list_games(outcome="win")) == 2
    assert len(db.list_games(outcome="loss")) == 1
    assert len(db.list_games(outcome="white")) == 2
    assert len(db.list_games(outcome="draw")) == 1
    assert len(db.list_games(outcome="unfinished")) == 1
    assert len(db.list_games(mode="ai", outcome="black")) == 1


def test_list_is_newest_first_with_limit(db):
    add_game(db, date=datetime(2026, 1, 1))
    newest = add_game(db, date=datetime(2026, 3, 1))
    add_game(db, date=datetime(2026, 2, 1))
    games = db.list_games(limit=2)
    assert len(games) == 2
    assert games[0].id == newest


def test_undo_removes_moves_and_delete_game_cascades(db):
    game_id = add_game(db)
    for ply, san in enumerate(("e4", "e5", "Nf3"), 1):
        db.add_move(game_id, ply, san)
    db.delete_moves_from(game_id, 2)
    assert [m.san for m in db.get_moves(game_id)] == ["e4"]
    db.delete_game(game_id)
    assert db.get_moves(game_id) == []
    assert db.get_game(game_id) is None


def test_save_review_replaces_annotations(db):
    game_id = add_game(db)
    db.add_move(game_id, 1, "e4")
    db.save_review(game_id, [(1, "e4", 30, "Лучший ход", "excellent"), (2, "e5", 25, "Ответ", "good")])
    moves = db.get_moves(game_id)
    assert [m.mark for m in moves] == ["excellent", "good"]


def test_settings_defaults_and_overrides(db):
    assert db.get_setting("theme") == "dark"
    assert db.get_setting("unknown") is None
    assert db.get_setting("unknown", "x") == "x"
    db.set_setting("theme", "dark")
    db.set_setting("theme", "light")
    assert db.get_setting("theme") == "light"
    db.set_json("active", {"game": 1})
    assert db.get_json("active") == {"game": 1}
    db.delete_setting("active")
    assert db.get_json("active") is None


def test_seen_terms_persist(db):
    assert db.seen_terms() == set()
    db.save_seen_terms({"вилка", "связка"})
    assert db.seen_terms() == {"вилка", "связка"}


def test_seed_is_idempotent_and_keeps_progress(db):
    assert db.seed_puzzles([puzzle("a"), puzzle("b")]) == 2
    db.mark_puzzle_solved("a", used_hint=False)
    assert db.seed_puzzles([puzzle("a"), puzzle("b"), puzzle("c")]) == 1
    assert db.puzzle_count() == 3
    assert db.get_puzzle("a").solved is True


def test_puzzle_round_trip_and_filters(db):
    db.seed_puzzles([puzzle("a", "fork", 1500), puzzle("b", "fork", 900), puzzle("c", "pin", 1000)])
    assert [p.id for p in db.list_puzzles("fork")] == ["b", "a"]
    assert db.get_puzzle("a").solution == ["e2e4", "e7e5"]
    db.mark_puzzle_solved("b", used_hint=False)
    assert [p.id for p in db.list_puzzles("fork", unsolved_only=True)] == ["a"]


def test_puzzle_stats_count_hints(db):
    db.seed_puzzles([puzzle("a"), puzzle("b"), puzzle("c", "pin")])
    db.mark_puzzle_solved("a", used_hint=True)
    db.mark_puzzle_solved("c", used_hint=False)
    assert db.puzzle_stats() == (db.puzzle_stats().__class__(3, 2, 1))
    fork = db.puzzle_stats("fork")
    assert (fork.total, fork.solved, fork.solved_with_hint) == (2, 1, 1)
    assert db.puzzle_stats("missing").total == 0


def test_solving_without_hint_later_clears_the_hint_flag_and_never_sets_it_back(db):
    db.seed_puzzles([puzzle("a")])
    db.mark_puzzle_solved("a", used_hint=True)
    assert db.get_puzzle("a").used_hint is True
    db.mark_puzzle_solved("a", used_hint=False)
    assert db.get_puzzle("a").used_hint is False
    db.mark_puzzle_solved("a", used_hint=True)
    assert db.get_puzzle("a").used_hint is False


def test_first_solve_with_hint_on_unsolved_puzzle_sets_flag(db):
    db.seed_puzzles([puzzle("a")])
    assert db.get_puzzle("a").used_hint is False
    db.mark_puzzle_solved("a", used_hint=True)
    assert db.get_puzzle("a").solved and db.get_puzzle("a").used_hint


def test_a_new_puzzle_file_replaces_unsolved_old_puzzles_and_keeps_solved_ones(db, tmp_path):
    import json
    db.seed_puzzles([puzzle("old_solved"), puzzle("old_open"), puzzle("kept")])
    db.mark_puzzle_solved("old_solved", used_hint=False)
    seed = tmp_path / "puzzles.json"
    seed.write_text(json.dumps({"puzzles": [puzzle("kept"), puzzle("new")]}), encoding="utf-8")
    assert db.seed_puzzles_from_file(seed) == 1
    assert {p.id for p in db.list_puzzles()} == {"old_solved", "kept", "new"}
    assert db.get_puzzle("old_solved").solved is True
    assert db.seed_puzzles_from_file(seed) == 0, "the same file twice changes nothing"
