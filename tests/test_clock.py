import chess
import pytest

from core.clock import PRESETS, UNTIMED, ChessClock, TimeControl, format_clock, storage_key_from_pgn_tag
from core.game import GameSession, GameSetup, Mode, Termination


def session_with(control, now, fen=chess.STARTING_FEN):
    session = GameSession(GameSetup(Mode.LOCAL, control), fen, now=now)
    session.start()
    return session


def test_presets_match_the_spec():
    assert [(p.minutes, p.increment) for p in PRESETS] == [
        (1, 0), (2, 1), (3, 0), (5, 0), (10, 0), (15, 10), (30, 0),
    ]


@pytest.mark.parametrize("control", [*PRESETS, TimeControl(7, 2), TimeControl(120, 30)])
def test_flag_fires_exactly_when_time_runs_out(control, fake_time):
    session = session_with(control, fake_time)
    fake_time.advance(control.minutes * 60 - 0.001)
    assert session.poll_flag() is None
    fake_time.advance(0.002)
    outcome = session.poll_flag()
    assert outcome.result == "0-1"
    assert outcome.termination == Termination.TIME
    assert not session.clock.is_running


@pytest.mark.parametrize("control", PRESETS)
def test_increment_is_credited_per_move_in_every_control(control, fake_time):
    session = session_with(control, fake_time)
    fake_time.advance(5)
    session.play(chess.Move.from_uci("e2e4"))
    expected = control.initial_ms - 5000 + control.increment * 1000
    assert session.clock.remaining_ms(chess.WHITE) == expected
    fake_time.advance(3)
    assert session.clock.remaining_ms(chess.WHITE) == expected, "white's clock is stopped"
    assert session.clock.remaining_ms(chess.BLACK) == control.initial_ms - 3000


def test_black_flag_gives_white_the_win(fake_time):
    session = session_with(TimeControl(1), fake_time)
    session.play(chess.Move.from_uci("e2e4"))
    fake_time.advance(61)
    assert session.poll_flag().result == "1-0"


@pytest.mark.parametrize(
    "fen,description",
    [
        ("8/8/8/4k3/8/8/4K3/8 w - - 0 1", "lone king"),
        ("8/8/8/4k3/8/8/1P2K3/8 w - - 0 1", "white pawn, black lone king: black cannot mate"),
    ],
)
def test_flag_is_draw_when_opponent_cannot_mate(fen, description, fake_time):
    # White flags. The opponent is black with a bare king in both positions.
    session = session_with(TimeControl(1), fake_time, fen)
    fake_time.advance(61)
    outcome = session.poll_flag()
    assert outcome.result == "1/2-1/2", description
    assert outcome.termination == Termination.TIME_DRAW


def test_flag_is_a_loss_if_opponent_keeps_a_lone_pawn(fake_time):
    session = session_with(TimeControl(1), fake_time, "8/8/8/4k3/4p3/8/4K3/8 w - - 0 1")
    fake_time.advance(61)
    assert session.poll_flag().result == "0-1"


def test_flag_with_opponent_single_knight_is_draw(fake_time):
    session = session_with(TimeControl(1), fake_time, "8/8/4n3/4k3/8/8/4K3/8 w - - 0 1")
    fake_time.advance(61)
    assert session.poll_flag().termination == Termination.TIME_DRAW


def test_late_move_loses_on_time_instead_of_landing(fake_time):
    session = session_with(TimeControl(1, 5), fake_time)
    fake_time.advance(61)
    assert session.play(chess.Move.from_uci("e2e4")) is None
    assert session.ply_count == 0
    assert session.outcome.termination == Termination.TIME


def test_untimed_never_flags(fake_time):
    session = session_with(UNTIMED, fake_time)
    fake_time.advance(10 ** 7)
    assert session.poll_flag() is None
    assert session.play(chess.Move.from_uci("e2e4")) is not None


def test_stop_freezes_and_start_resumes(fake_time):
    clock = ChessClock(TimeControl(1), fake_time)
    clock.start(chess.WHITE)
    fake_time.advance(10)
    clock.stop()
    fake_time.advance(100)
    assert clock.remaining_ms(chess.WHITE) == 50_000
    clock.start(chess.WHITE)
    fake_time.advance(1)
    assert clock.remaining_ms(chess.WHITE) == 49_000


def test_storage_key_round_trip():
    control = TimeControl(15, 10)
    assert TimeControl.from_storage_key(control.storage_key) == TimeControl(15, 10)
    assert TimeControl.from_storage_key(UNTIMED.storage_key).untimed


@pytest.mark.parametrize(
    "ms,text",
    [(300_000, "5:00"), (299_001, "5:00"), (20_000, "0:20"), (19_999, "0:19.9"),
     (7_300, "0:07.3"), (0, "0:00.0"), (3_909_000, "1:05:09")],
)
def test_format_clock(ms, text):
    assert format_clock(ms) == text


@pytest.mark.parametrize(
    "tag,key",
    [("300+3", "5+3"), ("600", "10+0"), ("90+30", "-"), ("-", "-"), ("?", "-"), ("", "-"), ("0", "-")],
)
def test_storage_key_from_pgn_tag(tag, key):
    assert storage_key_from_pgn_tag(tag) == key
