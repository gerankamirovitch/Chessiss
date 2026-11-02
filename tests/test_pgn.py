import chess
import pytest

from core.clock import TimeControl, UNTIMED
from core.game import GameSession, GameSetup, Mode, Termination
from core.pgn_io import is_valid_fen, read_first_game, read_games, ru_san, session_to_pgn


def finished_session(fen=chess.STARTING_FEN, ucis=("e2e4", "e7e5", "g1f3"), finish=None):
    session = GameSession(GameSetup(Mode.AI, TimeControl(5, 3), chess.WHITE, 12), fen)
    session.start()
    for uci in ucis:
        session.play(chess.Move.from_uci(uci))
    if finish:
        finish(session)
    return session


@pytest.mark.parametrize(
    "finish,result",
    [
        (lambda s: s.resign(chess.WHITE), "0-1"),
        (lambda s: s.resign(chess.BLACK), "1-0"),
        (lambda s: s.agree_draw(), "1/2-1/2"),
        (None, "*"),
    ],
)
def test_round_trip_keeps_moves_and_result(finish, result):
    session = finished_session(finish=finish)
    parsed = read_first_game(session_to_pgn(session))
    assert parsed.moves == session.moves
    assert parsed.sans == session.sans
    assert parsed.result == result
    assert parsed.errors == []


def test_round_trip_through_special_moves():
    ucis = """e2e4 a7a6 e4e5 d7d5 e5d6 e7d6 g1f3 b7b5 f1e2 c8b7 e1g1 b8c6 a2a4 d8d7 a4b5 e8c8""".split()
    session = finished_session(ucis=ucis)
    parsed = read_first_game(session_to_pgn(session))
    assert parsed.moves == session.moves
    assert "O-O" in parsed.sans and "O-O-O" in parsed.sans and "exd6" in parsed.sans


def test_round_trip_with_promotion_from_fen_start():
    fen = "8/P6k/8/8/8/8/8/K7 w - - 0 1"
    session = finished_session(fen=fen, ucis=("a7a8q",))
    pgn = session_to_pgn(session)
    assert '[SetUp "1"]' in pgn and fen in pgn
    parsed = read_first_game(pgn)
    assert parsed.start_fen == fen
    assert parsed.sans == ["a8=Q+"] or parsed.sans == ["a8=Q"]
    assert parsed.board_at(1).piece_type_at(chess.A8) == chess.QUEEN


def test_headers_describe_the_game():
    session = finished_session(finish=lambda s: s.resign(chess.BLACK))
    headers = read_first_game(session_to_pgn(session)).headers
    assert headers["TimeControl"] == "300+3"
    assert headers["White"] == "Игрок"
    assert headers["Black"] == "Stockfish, уровень 12"
    assert headers["ChessissTermination"] == Termination.RESIGNATION.value
    assert headers["Termination"] == "normal"


def test_time_forfeit_is_marked_in_pgn(fake_time):
    session = GameSession(GameSetup(Mode.LOCAL, TimeControl(1)), now=fake_time)
    session.start()
    fake_time.advance(61)
    session.poll_flag()
    headers = read_first_game(session_to_pgn(session)).headers
    assert headers["Termination"] == "time forfeit"
    assert headers["Result"] == "0-1"


def test_untimed_tag():
    session = GameSession(GameSetup(Mode.LOCAL, UNTIMED))
    assert '[TimeControl "-"]' in session_to_pgn(session)


def test_read_games_finds_every_game_and_keeps_order():
    text = (
        '[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n\n'
        '[White "C"]\n[Black "D"]\n[Result "0-1"]\n\n1. d4 d5 2. c4 0-1\n'
    )
    games = read_games(text)
    assert [g.headers["White"] for g in games] == ["A", "C"]
    assert [g.result for g in games] == ["1-0", "0-1"]
    assert games[1].sans == ["d4", "d5", "c4"]


def test_garbage_is_not_a_game():
    assert read_first_game("") is None
    assert read_games("   \n\n") == []


def test_broken_movetext_is_reported_not_raised():
    parsed = read_first_game('[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Ke5 Nf6 *\n')
    assert parsed.errors
    assert parsed.sans == ["e4", "e5"]


@pytest.mark.parametrize(
    "san,ru",
    [("Nf3", "Кf3"), ("Bxc6+", "Сxc6+"), ("Rad1", "Лad1"), ("Qh7#", "Фh7#"),
     ("Kd2", "Крd2"), ("Kxf7", "Крxf7"), ("O-O", "0-0"), ("O-O-O", "0-0-0"),
     ("a8=Q", "a8=Ф"), ("exd6", "exd6")],
)
def test_ru_san(san, ru):
    assert ru_san(san) == ru


def test_fen_validation():
    assert is_valid_fen(chess.STARTING_FEN)
    assert not is_valid_fen("not a fen")
    assert not is_valid_fen("8/8/8/8/8/8/8/8 w - - 0 1")
