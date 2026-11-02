import chess
import pytest

from core.clock import TimeControl, UNTIMED
from core.game import GameSession, GameSetup, Mode, Termination, outcome_of


def local(fen=chess.STARTING_FEN, control=UNTIMED, now=None):
    kwargs = {"now": now} if now else {}
    session = GameSession(GameSetup(Mode.LOCAL, control), fen, **kwargs)
    session.start()
    return session


def play(session, *ucis):
    for uci in ucis:
        assert session.play(chess.Move.from_uci(uci)) is not None


def test_kingside_castling_moves_the_rook():
    session = local("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert chess.G1 in session.legal_targets(chess.E1)
    assert chess.C1 in session.legal_targets(chess.E1)
    move = session.build_move(chess.E1, chess.G1)
    played = session.play(move)
    assert played.san == "O-O"
    assert session.board.piece_type_at(chess.F1) == chess.ROOK


def test_cannot_castle_through_attack():
    session = local("4k3/8/8/8/8/5r2/8/R3K2R w KQ - 0 1")
    assert chess.G1 not in session.legal_targets(chess.E1)
    assert chess.C1 in session.legal_targets(chess.E1)


def test_en_passant_only_right_after_double_step():
    session = local("4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1")
    play(session, "d7d5")
    assert chess.D6 in session.legal_targets(chess.E5)
    played = session.play(session.build_move(chess.E5, chess.D6))
    assert played.is_capture
    assert session.board.piece_at(chess.D5) is None


def test_promotion_requires_choice_and_supports_underpromotion():
    session = local("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert session.needs_promotion(chess.A7, chess.A8)
    assert session.build_move(chess.A7, chess.A8) is None
    played = session.play(session.build_move(chess.A7, chess.A8, chess.KNIGHT))
    assert played.san == "a8=N"
    assert session.board.piece_type_at(chess.A8) == chess.KNIGHT


def test_illegal_move_is_rejected_and_board_unchanged():
    session = local()
    with pytest.raises(ValueError):
        session.play(chess.Move.from_uci("e2e5"))
    assert session.ply_count == 0
    assert session.build_move(chess.E2, chess.E5) is None


def test_checkmate_ends_game():
    session = local()
    play(session, "f2f3", "e7e5", "g2g4", "d8h4")
    assert session.outcome.result == "0-1"
    assert session.outcome.termination == Termination.CHECKMATE
    assert not session.clock.is_running
    assert session.legal_targets(chess.E1) == []


def test_stalemate_is_draw():
    session = local("7k/5Q2/8/6K1/8/8/8/8 w - - 0 1")
    play(session, "g5g6")
    assert session.outcome.result == "1/2-1/2"
    assert session.outcome.termination == Termination.STALEMATE


def test_insufficient_material_is_draw():
    session = local("4k3/8/8/8/8/8/4p3/4K3 w - - 0 1")
    play(session, "e1e2")
    assert session.outcome.termination == Termination.INSUFFICIENT


def test_threefold_repetition_ends_exactly_on_third_occurrence():
    session = local()
    shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"]
    play(session, *shuffle)
    assert session.outcome is None
    play(session, *shuffle[:3])
    assert session.outcome is None, "a claimable-next-move position must not end the game"
    play(session, shuffle[3])
    assert session.outcome.termination == Termination.THREEFOLD
    assert session.outcome.result == "1/2-1/2"


def test_fifty_move_rule():
    session = local("4k3/8/8/8/8/8/R7/4K3 w - - 99 80")
    play(session, "a2a3")
    assert session.outcome.termination == Termination.FIFTY_MOVES


def test_fifty_move_rule_gives_way_to_checkmate():
    board = chess.Board("7k/8/6K1/8/8/8/8/R7 w - - 99 80")
    board.push_uci("a1a8")
    assert outcome_of(board).termination == Termination.CHECKMATE


def test_agreed_draw_and_resignation():
    session = local()
    assert session.agree_draw().termination == Termination.AGREEMENT
    session = local()
    assert session.resign(chess.WHITE).result == "0-1"
    session = local()
    assert session.resign(chess.BLACK).result == "1-0"


def test_finished_game_rejects_moves():
    session = local()
    session.resign(chess.WHITE)
    with pytest.raises(ValueError):
        session.play(chess.Move.from_uci("e2e4"))


def test_undo_of_castling_restores_the_rook_and_castling_rights():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    session = local(fen)
    play(session, "e1g1")
    assert not session.board.has_castling_rights(chess.WHITE)
    session.undo()
    assert session.fen == fen
    assert session.board.piece_type_at(chess.H1) == chess.ROOK
    assert chess.G1 in session.legal_targets(chess.E1)


def test_undo_of_en_passant_and_promotion_restores_captured_and_promoted():
    session = local("4k3/P7/8/8/3pP3/8/8/4K3 b - e3 0 1")
    start = session.fen
    play(session, "d4e3")
    assert session.board.piece_at(chess.E4) is None
    session.undo()
    assert session.fen == start
    play(session, "e8e7", "a7a8q")
    session.undo()
    assert session.board.piece_type_at(chess.A7) == chess.PAWN


def test_undo_local_takes_one_ply_and_restores_clock(fake_time):
    session = local(control=TimeControl(5, 3), now=fake_time)
    fake_time.advance(10)
    play(session, "e2e4")
    assert session.clock.remaining_ms(chess.WHITE) == 293_000
    assert session.undo_size() == 1
    assert session.undo() == 1
    assert session.ply_count == 0
    assert session.board.turn == chess.WHITE
    assert session.clock.remaining_ms(chess.WHITE) == 290_000
    assert session.clock.running_color == chess.WHITE
    assert session.undo_size() == 0


def ai_session(color):
    session = GameSession(GameSetup(Mode.AI, UNTIMED, color, 5))
    session.start()
    return session


def test_undo_vs_ai_returns_move_to_human():
    session = ai_session(chess.WHITE)
    assert session.undo_size() == 0
    play(session, "e2e4")
    assert session.undo_size() == 1, "AI still thinking"
    play(session, "e7e5")
    assert session.undo_size() == 2
    assert session.undo() == 2
    assert session.ply_count == 0
    assert session.board.turn == chess.WHITE


def test_undo_vs_ai_as_black_cannot_remove_the_ai_first_move():
    session = ai_session(chess.BLACK)
    assert session.is_ai_turn
    play(session, "e2e4")
    assert not session.is_ai_turn
    assert session.undo_size() == 0


def test_undo_disabled_after_game_end():
    session = local()
    play(session, "e2e4")
    session.resign(chess.WHITE)
    assert session.undo_size() == 0


def test_board_at_replays_any_ply():
    session = local()
    play(session, "e2e4", "e7e5", "g1f3")
    assert session.board_at(0).fen() == chess.STARTING_FEN
    assert session.board_at(2).piece_at(chess.E5) is not None
    assert session.board_at(3).fen() == session.fen
    assert session.sans == ["e4", "e5", "Nf3"]


def test_resume_rebuilds_position_and_clock():
    moves = [chess.Move.from_uci(u) for u in ("e2e4", "e7e5")]
    setup = GameSetup(Mode.AI, TimeControl(5), chess.WHITE, 7)
    session = GameSession.resume(setup, chess.STARTING_FEN, moves, 200_000, 150_000, game_id=9)
    assert session.ply_count == 2
    assert session.sans == ["e4", "e5"]
    assert session.game_id == 9
    assert session.clock.remaining_ms(chess.BLACK) == 150_000
