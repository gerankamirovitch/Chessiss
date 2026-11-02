"""Integration with the real binary: start, stop, missing file, crash."""
import os
import sys

import chess
import pytest

from core.engine import (
    EVAL_CLAMP,
    Engine,
    EngineFailure,
    Score,
    find_stockfish,
    level_params,
    move_time_ms,
)


def test_level_params_cover_full_range_and_grow():
    params = [level_params(level) for level in range(1, 21)]
    assert params[0].skill == 0 and params[-1].skill == 20
    assert all(a.skill <= b.skill for a, b in zip(params, params[1:]))
    assert all(a.depth <= b.depth for a, b in zip(params, params[1:]))
    assert all(a.movetime_ms <= b.movetime_ms for a, b in zip(params, params[1:]))
    assert len({p.skill for p in params}) == 20
    for bad in (0, 21):
        with pytest.raises(ValueError):
            level_params(bad)


def test_move_time_never_burns_the_clock():
    assert move_time_ms(20, None) == 2000
    assert move_time_ms(20, 600_000) == 2000
    assert move_time_ms(20, 10_000) == 400
    assert move_time_ms(20, 10_000, 2000) == 1400
    assert move_time_ms(20, 100) == 20


def test_score_is_clamped_and_mate_saturates():
    import chess.engine as ce

    assert Score.from_pov(ce.PovScore(ce.Cp(5000), chess.WHITE)).cp == EVAL_CLAMP
    assert Score.from_pov(ce.PovScore(ce.Cp(5000), chess.BLACK)).cp == -EVAL_CLAMP
    mate = Score.from_pov(ce.PovScore(ce.Mate(3), chess.BLACK))
    assert mate.mate == -3 and mate.cp == -EVAL_CLAMP
    assert mate.for_color(chess.BLACK) == EVAL_CLAMP


def test_find_stockfish_rejects_bad_custom_path(tmp_path):
    assert find_stockfish(str(tmp_path / "nope.exe")) is None
    real = tmp_path / "sf.exe"
    real.write_bytes(b"x")
    assert find_stockfish(str(real)) == real


def test_missing_binary_raises_clear_error(tmp_path):
    engine = Engine(tmp_path / "missing.exe")
    with pytest.raises(EngineFailure, match="Не удалось запустить"):
        engine.start()
    assert not engine.is_running


def test_non_executable_file_raises_clear_error(tmp_path):
    fake = tmp_path / "stockfish.exe"
    fake.write_text("this is not an engine")
    engine = Engine(fake)
    with pytest.raises(EngineFailure):
        engine.start()
    assert not engine.is_running


def test_program_that_is_not_uci_times_out_into_clear_error(tmp_path):
    engine = Engine(sys.executable)  # python waits on stdin and never answers "uciok"
    engine._options = {}
    with pytest.raises(EngineFailure):
        engine.start()


def test_call_before_start_raises():
    engine = Engine("whatever")
    with pytest.raises(EngineFailure):
        engine.analyse(chess.Board())


def test_start_stop_restart(stockfish_path):
    engine = Engine(stockfish_path)
    engine.start()
    assert "Stockfish" in engine.name
    engine.stop()
    assert not engine.is_running
    engine.stop()  # idempotent
    engine.restart()
    assert engine.best_move(chess.Board(), 1) in chess.Board().legal_moves
    engine.stop()


@pytest.mark.parametrize("level", [1, 10, 20])
def test_best_move_is_legal_at_levels(stockfish_path, level):
    engine = Engine(stockfish_path)
    engine.start()
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    assert engine.best_move(board, level, remaining_ms=20_000) in board.legal_moves
    engine.stop()


def test_analyse_finds_mate_and_returns_requested_lines(stockfish_path):
    engine = Engine(stockfish_path)
    engine.start()
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    lines = engine.analyse(board, depth=10, multipv=3)
    assert len(lines) == 3
    assert lines[0].move == chess.Move.from_uci("h5f7")
    assert lines[0].score.mate == 1
    engine.stop()


def test_crash_mid_session_becomes_engine_failure_then_restart_recovers(stockfish_path):
    engine = Engine(stockfish_path)
    engine.start()
    pid = engine._engine.transport.get_pid()
    os.kill(pid, 9)
    with pytest.raises(EngineFailure):
        for _ in range(3):
            engine.analyse(chess.Board(), depth=1)
    assert not engine.is_running
    engine.start()
    assert engine.analyse(chess.Board(), depth=1)
    engine.stop()
