"""The interface driven through real widgets on the offscreen Qt platform, with the
real Stockfish where a test needs an engine."""
import os
import subprocess
import sys
import time
from pathlib import Path

import chess
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from core.clock import TimeControl, UNTIMED
from core.engine import Score
from core.explain import Mark, MoveExplanation
from core.game import GameSession, GameSetup, Mode, Termination
from core.pgn_io import read_first_game
from storage.db import Database
from ui.app import create_window
from ui.board_widget import BoardWidget
from ui.game_screen import ACTIVE_GAME_KEY
from ui.new_game_dialog import NewGameDialog
from ui.theme import LIGHT

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


class Harness:
    def __init__(self, app):
        self.app = app
        self.window, self.db, self.engine = create_window(app)
        self.window.resize(1200, 800)
        self.window.show()
        QApplication.processEvents()
        self.closed = False

    @property
    def game(self):
        return self.window.game_screen

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.window.close()
        self.engine.shutdown()
        self.db.close()
        QApplication.processEvents()


@pytest.fixture
def harness(app, stockfish_path):
    h = Harness(app)
    yield h
    h.close()


@pytest.fixture
def no_engine(app, monkeypatch):
    """The real situation of a missing binary: nothing bundled, nothing on PATH."""
    monkeypatch.setattr("ui.engine_service.find_stockfish", lambda custom=None: None)
    h = Harness(app)
    h.engine.warm_up()
    assert wait_until(lambda: not h.engine.available)
    yield h
    h.close()


@pytest.fixture
def answers_yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *a: seen.append(text))
    return seen


def play(screen, *ucis):
    """Plays moves as a user would, through the board's own signal."""
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        screen.board.moveAttempted.emit(move.from_square, move.to_square, move.promotion or 0)


def local_setup(control=UNTIMED):
    return GameSetup(Mode.LOCAL, control)


def ai_setup(color=chess.WHITE, control=UNTIMED, level=1):
    return GameSetup(Mode.AI, control, color, level)


# --- architecture ------------------------------------------------------------

@pytest.mark.parametrize("package", ["core", "storage"])
def test_logic_layers_do_not_import_qt(package):
    for path in (ROOT / package).rglob("*.py"):
        assert "PySide6" not in path.read_text(encoding="utf-8"), path


def test_core_imports_without_qt():
    code = (
        "import sys; import core.game, core.engine, core.explain, core.analysis, core.pgn_io, storage.db;"
        "sys.exit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0


# --- board input -------------------------------------------------------------

@pytest.fixture
def board_widget(app):
    widget = BoardWidget(LIGHT)
    widget.resize(640, 640)
    session = GameSession(local_setup())
    widget.set_controller(session)
    widget.set_position(session.board)
    widget.set_interactive({chess.WHITE})
    widget.show()
    QApplication.processEvents()
    yield widget, session
    widget.close()


def center(widget, square) -> QPoint:
    return widget.square_rect(square).center()


def collect(widget):
    moves = []
    widget.moveAttempted.connect(lambda a, b, c: moves.append((a, b, c)))
    return moves


def test_click_click_makes_a_move(board_widget):
    widget, _ = board_widget
    moves = collect(widget)
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.E2))
    assert widget._selected == chess.E2
    assert set(widget._targets) == {chess.E3, chess.E4}
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.E4))
    assert moves == [(chess.E2, chess.E4, 0)]
    assert widget._selected is None


def test_drag_and_drop_makes_a_move(board_widget):
    widget, _ = board_widget
    moves = collect(widget)
    QTest.mousePress(widget, Qt.LeftButton, pos=center(widget, chess.G1))
    QTest.mouseMove(widget, center(widget, chess.G2))
    QApplication.processEvents()
    QTest.mouseMove(widget, center(widget, chess.F3))
    QApplication.processEvents()
    assert widget._dragging
    QTest.mouseRelease(widget, Qt.LeftButton, pos=center(widget, chess.F3))
    assert moves == [(chess.G1, chess.F3, 0)]


def test_drop_on_illegal_square_cancels(board_widget):
    widget, _ = board_widget
    moves = collect(widget)
    QTest.mousePress(widget, Qt.LeftButton, pos=center(widget, chess.E2))
    QTest.mouseMove(widget, center(widget, chess.E5))
    QApplication.processEvents()
    QTest.mouseRelease(widget, Qt.LeftButton, pos=center(widget, chess.E5))
    assert moves == []
    assert not widget._dragging


def test_cannot_pick_up_the_other_color(board_widget):
    widget, _ = board_widget
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.E7))
    assert widget._selected is None


def test_second_click_deselects_and_other_piece_reselects(board_widget):
    widget, _ = board_widget
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.E2))
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.D2))
    assert widget._selected == chess.D2
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.D2))
    assert widget._selected is None


def test_read_only_board_ignores_input(board_widget):
    widget, _ = board_widget
    moves = collect(widget)
    widget.set_interactive(set())
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.E2))
    assert widget._selected is None and moves == []


@pytest.mark.parametrize("flipped", [False, True])
def test_square_geometry_round_trips(board_widget, flipped):
    widget, _ = board_widget
    widget.set_flipped(flipped)
    for square in chess.SQUARES:
        assert widget.square_at(QPointF(center(widget, square))) == square
    a1 = widget.square_rect(chess.A1)
    assert (a1.top() < widget.height() / 2) == flipped


def test_outside_board_is_no_square(app):
    widget = BoardWidget(LIGHT)
    widget.resize(800, 400)
    assert widget.square_at(QPointF(5, 200)) is None
    assert widget.square_at(QPointF(400, 200)) is not None


@pytest.mark.parametrize("flipped", [False, True])
def test_promotion_chooser_returns_the_picked_piece(app, flipped):
    widget = BoardWidget(LIGHT)
    widget.resize(640, 640)
    session = GameSession(local_setup(), "8/P6k/8/8/8/8/8/K7 w - - 0 1")
    widget.set_controller(session)
    widget.set_position(session.board)
    widget.set_interactive({chess.WHITE})
    widget.set_flipped(flipped)
    widget.show()
    moves = collect(widget)
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.A7))
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.A8))
    assert moves == [], "nothing is played before the choice"
    assert widget._promotion is not None
    knight_rect = dict(widget._promotion_rects())[chess.KNIGHT]
    assert widget.rect().contains(knight_rect)
    QTest.mouseClick(widget, Qt.LeftButton, pos=knight_rect.center())
    assert moves == [(chess.A7, chess.A8, chess.KNIGHT)]
    widget.close()


def test_promotion_chooser_can_be_cancelled(app):
    widget = BoardWidget(LIGHT)
    widget.resize(640, 640)
    session = GameSession(local_setup(), "8/P6k/8/8/8/8/8/K7 w - - 0 1")
    widget.set_controller(session)
    widget.set_position(session.board)
    widget.set_interactive({chess.WHITE})
    widget.show()
    moves = collect(widget)
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.A7))
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.A8))
    QTest.mouseClick(widget, Qt.LeftButton, pos=center(widget, chess.H1))
    assert moves == [] and widget._promotion is None
    widget.close()


def test_board_paints_with_every_overlay(board_widget):
    widget, session = board_widget
    session.play(chess.Move.from_uci("e2e4"))
    widget.set_position(session.board, chess.Move.from_uci("e2e4"), animate=True)
    widget.set_arrows([(chess.G8, chess.F6, 1.0), (chess.B8, chess.C6, 0.5)])
    widget.set_marked_squares({chess.E7: "#2f7d4f70"})
    image = widget.grab().toImage()
    assert not image.isNull()
    colors = {image.pixelColor(x, y).name() for x in range(0, 640, 11) for y in range(0, 640, 11)}
    assert len(colors) > 10, "pieces, squares and overlays are all visible"


def test_keeps_rendering_at_high_dpi(board_widget):
    widget, _ = board_widget
    pixmap = widget._piece_pixmap("K")
    assert pixmap.width() == int(widget._square_size() * widget.devicePixelRatioF())


# --- local game --------------------------------------------------------------

def test_local_game_to_mate_saves_everything(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    h.window._show(h.game)
    play(h.game, "f2f3", "e7e5", "g2g4", "d8h4")
    session = h.game.session
    assert session.outcome.termination == Termination.CHECKMATE
    assert h.game.status.text() == "Чёрные выиграли: мат."
    assert h.game.review_button.isVisible() and h.game.rematch_button.isVisible()
    row = h.db.get_game(session.game_id)
    assert row.result == "0-1" and row.mode == "local"
    assert [m.san for m in h.db.get_moves(row.id)] == ["f3", "e5", "g4", "Qh4#"]
    assert read_first_game(row.pgn).sans == ["f3", "e5", "g4", "Qh4#"]
    assert h.db.get_json(ACTIVE_GAME_KEY) is None


def test_illegal_move_through_the_signal_is_ignored(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e5")
    assert h.game.session.ply_count == 0


def test_local_undo_and_navigation(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e4", "e7e5", "g1f3")
    assert h.game.moves.rowCount() == 2
    h.game._go_to_ply(1)
    assert h.game.fen_bar.field.text().startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR")
    assert h.game.board._interactive == set(), "no moves while looking at an older position"
    h.game._go_to_latest()
    assert h.game.board._interactive == {chess.BLACK}
    h.game._on_undo()
    assert h.game.session.ply_count == 2
    assert [m.san for m in h.db.get_moves(h.game.session.game_id)] == ["e4", "e5"]
    assert h.game.moves.item(1, 1) is None
    h.game._on_undo()
    h.game._on_undo()
    assert h.game.moves.rowCount() == 0
    assert not h.game.undo_button.isEnabled()


def test_black_first_position_numbering(no_engine):
    h = no_engine
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 3 7"
    h.game._begin(GameSession(local_setup(), fen))
    play(h.game, "f8c5", "f1c4")
    assert h.game.moves.item(0, 0).text() == "7."
    assert h.game.moves.item(0, 1) is None
    assert h.game.moves.item(0, 2).text() == "Сc5"
    assert h.game.moves.item(1, 1).text() == "Сc4"
    h.game.moves.cellClicked.emit(0, 2)
    assert h.game._view_ply == 1
    h.game._go_to_latest()
    h.game._on_undo()
    h.game._on_undo()
    assert h.game.moves.rowCount() == 0


def test_flag_in_local_game_ends_and_saves(no_engine, fake_time):
    h = no_engine
    h.game._begin(GameSession(local_setup(TimeControl(1)), now=fake_time))
    fake_time.advance(30)
    play(h.game, "e2e4")
    fake_time.advance(61)
    h.game._tick()
    session = h.game.session
    assert session.outcome.result == "1-0"
    row = h.db.get_game(session.game_id)
    assert row.result == "1-0"
    assert read_first_game(row.pgn).headers["Termination"] == "time forfeit"


def test_flag_with_bare_king_opponent_is_a_draw_in_ui(no_engine, fake_time):
    h = no_engine
    h.game._begin(GameSession(local_setup(TimeControl(1)), "8/8/8/4k3/8/8/1P2K3/8 w - - 0 1", now=fake_time))
    fake_time.advance(61)
    h.game._tick()
    assert h.game.session.outcome.termination == Termination.TIME_DRAW
    assert "Ничья" in h.game.status.text()


def test_clock_labels_show_time_and_low_state(no_engine, fake_time):
    h = no_engine
    h.game._begin(GameSession(local_setup(TimeControl(5)), now=fake_time))
    h.game._tick()
    assert h.game.bottom_clock.text() == "5:00"
    assert h.game.bottom_clock.property("active") is True
    assert h.game.top_clock.property("active") is False
    fake_time.advance(285)
    h.game._tick()
    assert h.game.bottom_clock.text().startswith("0:15")
    assert h.game.bottom_clock.property("low") is True


def test_pause_freezes_the_clock_and_board(no_engine, fake_time):
    h = no_engine
    h.game._begin(GameSession(local_setup(TimeControl(5)), now=fake_time))
    h.window._show(h.game)
    assert h.game.pause_button.isVisible() and h.game.pause_button.isEnabled()
    h.game._on_pause()
    fake_time.advance(100)
    assert h.game.session.clock.remaining_ms(chess.WHITE) == 300_000
    assert h.game.board._interactive == set()
    assert h.game.status.text() == "Пауза"
    h.game._on_pause()
    fake_time.advance(1)
    assert h.game.session.clock.remaining_ms(chess.WHITE) == 299_000


def test_untimed_game_has_no_running_timer(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    assert h.game.bottom_clock.text() == "∞"
    assert not h.game.pause_button.isEnabled()
    assert not h.game._timer.isActive()


def test_local_resign_and_draw_with_confirmation(no_engine, answers_yes):
    h = no_engine
    h.game.start_game(local_setup())
    h.game._on_draw()
    assert h.game.session.outcome.termination == Termination.AGREEMENT
    h.game._on_rematch()
    assert h.game.session.ply_count == 0 and not h.game.session.is_over
    h.game._on_resign()
    assert h.game.session.outcome.result == "0-1", "white was to move"


def test_flip_swaps_clock_owners(no_engine, fake_time):
    h = no_engine
    h.game._begin(GameSession(local_setup(TimeControl(5)), now=fake_time))
    assert h.game.bottom_name.text() == "Белые"
    h.game._on_flip()
    assert h.game.bottom_name.text() == "Чёрные"
    h.game._tick()
    assert h.game.top_clock.property("active") is True


def test_fen_can_be_copied(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e4")
    h.game.fen_bar.copy_button.click()
    assert QGuiApplication.clipboard().text() == h.game.session.fen


# --- missing engine ----------------------------------------------------------

def test_missing_engine_blocks_ai_game_with_clear_message(no_engine, warnings):
    h = no_engine
    h.window.new_game(Mode.AI)
    assert "Stockfish не найден" in warnings[0]
    assert h.window.stack.currentWidget() is h.window.home
    assert h.window.home.engine_warning.isVisibleTo(h.window.home)


def test_local_game_tells_explanations_are_off_without_engine(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e4")
    assert wait_until(lambda: 1 in h.game._comments or "Stockfish" in h.game.coach.toPlainText())
    assert "Stockfish" in h.game.coach.toPlainText()
    assert not h.game.hint_button.isEnabled()


def test_broken_binary_reports_failure_and_does_not_crash(app, tmp_path):
    fake = tmp_path / "stockfish.exe"
    fake.write_text("not a program")
    h = Harness(app)
    try:
        h.db.set_setting("stockfish_path", str(fake))
        h.engine.set_custom_path(str(fake))
        assert wait_until(lambda: not h.engine.available)
        assert "Не удалось запустить" in h.engine.message
        assert h.window.settings.engine_status.text() == h.engine.message
    finally:
        h.close()


def test_ai_game_survives_engine_failure_and_offers_retry(app, stockfish_path, tmp_path):
    h = Harness(app)
    try:
        h.engine.warm_up()
        assert wait_until(lambda: h.engine._analysis is not None)
        h.game.start_game(ai_setup())
        wait_until(lambda: not h.game._ai_ticket)
        # The binary disappears while the game is running.
        h.engine._play_pool.submit(h.engine._drop_play).result()
        h.engine._custom_path = str(tmp_path / "gone.exe")
        play(h.game, h.game.session.board.parse_san("e4").uci())
        assert wait_until(lambda: h.game._ai_error)
        assert h.game.retry_button.isVisibleTo(h.game)
        assert not h.game.session.clock.is_running
        assert "Stockfish не отвечает" in h.game.status.text()
        h.engine._custom_path = str(stockfish_path)
        h.game._on_retry_ai()
        assert wait_until(lambda: h.game.session.ply_count == 2)
        assert not h.game._ai_error
    finally:
        h.close()


def test_engine_crash_during_ai_game_is_recovered_automatically(harness):
    h = harness
    h.game.start_game(ai_setup())
    play(h.game, "e2e4")
    assert wait_until(lambda: h.game.session.ply_count == 2)
    pid = h.engine._play._engine.transport.get_pid()
    os.kill(pid, 9)
    time.sleep(0.1)
    play(h.game, "d2d4")
    assert wait_until(lambda: h.game.session.ply_count == 4, 15)
    assert not h.game._ai_error


# --- game against AI ---------------------------------------------------------

def test_ai_replies_and_both_moves_get_explained(harness):
    h = harness
    h.game.start_game(ai_setup(level=3))
    assert h.game.status.text() == "Ваш ход"
    play(h.game, "e2e4")
    assert h.game.status.text() == "AI думает…"
    assert h.game.board._interactive == set()
    assert wait_until(lambda: h.game.session.ply_count == 2)
    assert h.game.board._interactive == {chess.WHITE}
    assert wait_until(lambda: {1, 2} <= set(h.game._comments))
    text = h.game.coach.toPlainText()
    assert "Ваш ход: e4" in text and "Ход AI:" in text and "Оценка" in text
    assert "[[" not in text
    moves = h.db.get_moves(h.game.session.game_id)
    assert moves[0].eval_cp is not None and moves[0].mark and moves[0].comment


def test_ai_plays_first_when_human_is_black(harness):
    h = harness
    h.game.start_game(ai_setup(chess.BLACK))
    assert h.game.board.flipped
    assert wait_until(lambda: h.game.session.ply_count == 1)
    assert h.game.board._interactive == {chess.BLACK}


def test_board_stays_responsive_while_ai_thinks_at_top_level(harness):
    h = harness
    h.game.start_game(ai_setup(level=20))
    play(h.game, "e2e4")
    longest = 0.0
    started = time.perf_counter()
    last = started
    while h.game.session.ply_count < 2 and time.perf_counter() - started < 15:
        QApplication.processEvents()
        h.game.board.grab()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
    assert h.game.session.ply_count == 2
    assert longest < 0.1, f"the UI thread stalled for {longest:.3f}s"


def test_undo_cancels_thinking_ai(harness):
    h = harness
    h.game.start_game(ai_setup(level=20))
    play(h.game, "a2a3")
    h.game._on_undo()
    assert h.game.session.ply_count == 0
    assert h.game.status.text() == "Ваш ход"
    play(h.game, "e2e4")
    assert wait_until(lambda: h.game.session.ply_count == 2, 15)
    assert h.game.session.sans[0] == "e4"


def test_explanation_of_an_undone_move_does_not_land_on_its_replacement(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    session = h.game.session
    stale = session.play(chess.Move.from_uci("a2a3"))
    session.undo()
    session.play(chess.Move.from_uci("e2e4"))
    explanation = MoveExplanation("a3", chess.WHITE, Score(-50), 80, Mark.INACCURACY, False, "e4", None, [], ["устарело"])
    h.game._on_explanation(session, stale, explanation)
    assert 1 not in h.game._comments


def test_ai_flag_ends_game_when_its_clock_runs_out(harness, fake_time):
    h = harness
    h.game._begin(GameSession(ai_setup(control=TimeControl(1)), now=fake_time))
    play(h.game, "e2e4")
    fake_time.advance(61)
    h.game._tick()
    assert h.game.session.outcome.result == "1-0"
    time.sleep(0.3)
    QApplication.processEvents()
    assert h.game.session.ply_count == 1, "a late engine reply must not land"


def test_hint_gives_candidates_with_reasons_and_arrows(harness):
    h = harness
    fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    h.game._begin(GameSession(local_setup(), fen))
    h.game._on_hint()
    assert wait_until(lambda: h.game._hint_text not in ("", "Считаю…"))
    assert "Фxf7" in h.game._hint_text and "мат" in h.game._hint_text
    assert h.game.board._arrows
    assert "Подсказка" in h.game.coach.toPlainText()
    assert "[[" not in h.game.coach.toPlainText()
    play(h.game, "h5f7")
    assert h.game.board._arrows == [] and h.game._hint_text == ""


def test_draw_offer_declined_when_ai_is_winning(harness):
    h = harness
    fen = "4k3/8/8/8/8/8/PPPPPPPP/RNBQKBNR b KQ - 0 1"  # the human (black) is hopeless
    h.game._begin(GameSession(ai_setup(chess.BLACK), fen))
    h.game._cancel_ai()
    h.game._on_draw()
    assert not h.game.draw_button.isEnabled(), "one offer per move"
    assert wait_until(lambda: "отказался" in h.game.status.text())
    assert not h.game.session.is_over


def test_draw_offer_accepted_when_ai_is_losing(harness):
    h = harness
    fen = "rnbqkbnr/pppppppp/8/8/8/8/8/4K3 b kq - 0 1"  # the AI (white) is hopeless
    h.game._begin(GameSession(ai_setup(chess.BLACK), fen))
    h.game._on_draw()
    assert wait_until(lambda: h.game.session.is_over)
    assert h.game.session.outcome.termination == Termination.AGREEMENT
    assert h.db.get_game(h.game.session.game_id).result == "1/2-1/2"


def test_rematch_keeps_mode_level_and_control(harness, answers_yes):
    h = harness
    control = TimeControl(3)
    h.game.start_game(ai_setup(control=control, level=4), "white")
    h.game._on_resign()
    assert h.game.session.outcome.result == "0-1"
    first_id = h.game.session.game_id
    h.game._on_rematch()
    setup = h.game.session.setup
    assert (setup.mode, setup.level, setup.time_control) == (Mode.AI, 4, control)
    assert h.game.session.game_id is None
    assert h.db.get_game(first_id).result == "0-1"


# --- persistence between runs ------------------------------------------------

def test_game_in_progress_resumes_after_restart(app, stockfish_path):
    first = Harness(app)
    first.game.start_game(ai_setup(control=TimeControl(10, 5), level=2))
    play(first.game, "d2d4")
    assert wait_until(lambda: first.game.session.ply_count == 2)
    assert wait_until(lambda: 1 in first.game._comments)
    fen = first.game.session.fen
    game_id = first.game.session.game_id
    white_ms = first.game.session.clock.remaining_ms(chess.WHITE)
    first.close()  # the window closes with no explicit exit from the game

    second = Harness(app)
    try:
        assert second.window.home.resume_button.isVisibleTo(second.window.home)
        second.window.resume_game()
        session = second.game.session
        assert session.fen == fen and session.game_id == game_id
        assert session.setup.level == 2 and session.setup.time_control == TimeControl(10, 5)
        assert abs(session.clock.remaining_ms(chess.WHITE) - white_ms) < 1500
        assert 1 in second.game._comments
        assert second.game.moves.item(0, 1).text().startswith("d4")
        play(second.game, "c2c4")
        assert wait_until(lambda: session.ply_count == 4)
        assert read_first_game(second.db.get_game(game_id).pgn).moves == session.moves
    finally:
        second.close()


def test_moves_are_on_disk_without_a_clean_close(app, stockfish_path, tmp_path):
    h = Harness(app)
    try:
        h.game.start_game(local_setup())
        play(h.game, "e2e4", "c7c5")
        other = Database(h.db.path)  # what a restart after a killed process would read
        assert [m.san for m in other.get_moves(h.game.session.game_id)] == ["e4", "c5"]
        assert other.get_json(ACTIVE_GAME_KEY)["game_id"] == h.game.session.game_id
        assert read_first_game(other.get_game(h.game.session.game_id).pgn).sans == ["e4", "c5"]
        other.close()
    finally:
        h.close()


def test_settings_and_seen_terms_survive_restart(app, stockfish_path):
    first = Harness(app)
    first.window.settings.theme_box.setCurrentIndex(first.window.settings.theme_box.findData("dark"))
    first.window.settings.sound_box.setChecked(False)
    first.window.settings.level_box.setValue(13)
    first.db.save_seen_terms({"вилка"})
    first.close()
    second = Harness(app)
    try:
        assert second.db.get_setting("theme") == "dark"
        assert second.window.settings.theme_box.currentData() == "dark"
        assert second.window.settings.sound_box.isChecked() is False
        assert second.window.sound.enabled is False
        assert second.window.settings.level_box.value() == 13
        assert "вилка" in second.db.seen_terms()
        second.window.apply_theme_name("light")
    finally:
        second.close()


# --- analysis ----------------------------------------------------------------

SCHOLARS = '[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n'


def write_pgn(tmp_path, text=SCHOLARS, name="game.pgn"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_review_marks_blunder_draws_graph_and_persists(harness, tmp_path):
    h = harness
    screen = h.window.analysis_screen
    assert screen.open_file(write_pgn(tmp_path))
    assert screen.game.result == "1-0"
    screen.start_review()
    assert wait_until(lambda: screen._ticket is None, 60)
    assert screen._marks[6] == Mark.BLUNDER, "3...Nf6 allows mate"
    assert "мат" in screen._comments[6]
    assert screen._evals[7] == 1000
    assert None not in screen.graph._evals
    assert screen.moves.item(2, 2).text() == "Кf6??"
    assert "зевок" in screen.summary.text()
    stored = h.db.get_moves(screen.game_id)
    assert len(stored) == 7 and stored[5].mark == "blunder"


def test_saved_review_opens_without_rerun_and_without_engine(app, tmp_path, monkeypatch, stockfish_path):
    first = Harness(app)
    screen = first.window.analysis_screen
    screen.open_file(write_pgn(tmp_path))
    game_id = screen.game_id
    screen.start_review()
    assert wait_until(lambda: screen._ticket is None, 60)
    first.close()

    monkeypatch.setattr("ui.engine_service.find_stockfish", lambda custom=None: None)
    second = Harness(app)
    try:
        screen = second.window.analysis_screen
        screen.show_saved_game(game_id)
        assert screen._marks[6] == Mark.BLUNDER
        screen.go_to(6)
        assert "Зевок" in screen.coach.toPlainText()
    finally:
        second.close()


def test_review_can_be_cancelled_and_navigated(harness, tmp_path):
    h = harness
    screen = h.window.analysis_screen
    screen.open_file(write_pgn(tmp_path))
    screen.start_review()
    assert screen.cancel_button.isVisibleTo(screen)
    screen.cancel_review()
    assert screen._ticket is None and not screen.progress.isVisibleTo(screen)
    assert screen._marks == {}
    screen.go_to(3)
    assert screen.board._last_move == chess.Move.from_uci("f1c4")
    screen.graph.set_data([0] * 7, [None] * 7)
    screen.moves.cellClicked.emit(0, 2)
    assert screen._ply == 2
    screen.go_to(100)
    assert screen._ply == 7
    screen.go_to(-3)
    assert screen._ply == 0


def test_review_without_engine_shows_message(no_engine, tmp_path, warnings):
    screen = no_engine.window.analysis_screen
    screen.open_file(write_pgn(tmp_path))
    screen.start_review()
    assert wait_until(lambda: screen._ticket is None)
    assert "Stockfish не найден" in warnings[0]
    assert screen.analyze_button.isVisibleTo(screen)


def test_end_of_game_opens_review_of_that_game(harness, answers_yes):
    h = harness
    h.game.start_game(ai_setup())
    play(h.game, "e2e4")
    assert wait_until(lambda: h.game.session.ply_count == 2)
    h.game._on_resign()
    game_id = h.game.session.game_id
    h.game._on_review()
    screen = h.window.analysis_screen
    assert h.window.stack.currentWidget() is screen
    assert screen.game_id == game_id
    assert wait_until(lambda: screen._ticket is None, 30)
    assert set(screen._marks) == {1, 2}


def test_multi_game_file_asks_which_game(no_engine, tmp_path, monkeypatch):
    text = SCHOLARS + '\n[White "C"]\n[Black "D"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n'
    monkeypatch.setattr(QInputDialog, "getItem", lambda parent, title, label, items, *a: (items[1], True))
    screen = no_engine.window.analysis_screen
    assert screen.open_file(write_pgn(tmp_path, text))
    assert screen.game.headers["White"] == "C"
    assert screen.game.sans[-1] == "Qh4#"


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_pgn_files_give_a_message(no_engine, tmp_path, warnings, text):
    screen = no_engine.window.analysis_screen
    assert screen.open_file(write_pgn(tmp_path, text)) is False
    assert "нет ни одной партии" in warnings[0]
    assert screen.game is None


def test_garbage_pgn_is_reported_and_loads_no_moves(no_engine, tmp_path, warnings):
    screen = no_engine.window.analysis_screen
    screen.open_file(write_pgn(tmp_path, "total garbage without moves"))
    assert warnings, "the user is told something is wrong"
    assert screen.game is None or screen.game.moves == []


def test_missing_file_gives_a_message(no_engine, tmp_path, warnings):
    assert no_engine.window.analysis_screen.open_file(str(tmp_path / "no.pgn")) is False
    assert "Не удалось прочитать" in warnings[0]


def test_cp1251_pgn_is_readable(no_engine, tmp_path):
    path = tmp_path / "ru.pgn"
    path.write_bytes('[White "Иванов"]\n[Black "Петров"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'.encode("cp1251"))
    screen = no_engine.window.analysis_screen
    assert screen.open_file(str(path))
    assert screen.game.headers["White"] == "Иванов"


def test_same_pgn_imported_twice_is_one_game(no_engine, tmp_path):
    screen = no_engine.window.analysis_screen
    path = write_pgn(tmp_path)
    screen.open_file(path)
    first = screen.game_id
    screen.open_file(path)
    assert screen.game_id == first
    assert len(no_engine.db.list_games(mode="import")) == 1


# --- history -----------------------------------------------------------------

def test_history_filters_export_and_open(no_engine, tmp_path, monkeypatch, answers_yes):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "f2f3", "e7e5", "g2g4", "d8h4")
    h.game.start_game(local_setup(TimeControl(5, 3)))
    play(h.game, "e2e4")
    h.game._on_draw()
    h.window.show_history()
    assert h.window.history.table.rowCount() == 2
    assert h.window.history.table.item(0, 3).text() == "5+3"
    assert h.window.history.table.item(0, 4).text() == "ничья"
    assert h.window.history.table.item(1, 4).text() == "чёрные выиграли"
    box = h.window.history.result_box
    box.setCurrentIndex(box.findData("black"))
    assert h.window.history.table.rowCount() == 1
    box.setCurrentIndex(box.findData("white"))
    assert h.window.history.table.rowCount() == 0
    assert h.window.history.empty.isVisibleTo(h.window.history)
    box.setCurrentIndex(0)
    mode = h.window.history.mode_box
    mode.setCurrentIndex(mode.findData("ai"))
    assert h.window.history.table.rowCount() == 0
    mode.setCurrentIndex(mode.findData("local"))
    assert h.window.history.table.rowCount() == 2

    target = tmp_path / "out.pgn"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    h.window.history.table.selectRow(1)
    h.window.history._export_selected()
    parsed = read_first_game(target.read_text(encoding="utf-8"))
    assert parsed.sans == ["f3", "e5", "g4", "Qh4#"] and parsed.result == "0-1"

    h.window.history._open_selected()
    assert h.window.stack.currentWidget() is h.window.analysis_screen
    assert h.window.analysis_screen.game.sans[-1] == "Qh4#"


def test_import_export_round_trip_through_the_app(no_engine, tmp_path, monkeypatch):
    h = no_engine
    source = write_pgn(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (source, ""))
    h.window.history._import()
    assert h.window.analysis_screen.game.sans[-1] == "Qxf7#"
    assert h.window.analysis_screen.game.result == "1-0"
    target = tmp_path / "again.pgn"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    h.window.analysis_screen.export_pgn()
    again = read_first_game(target.read_text(encoding="utf-8"))
    assert again.moves == read_first_game(SCHOLARS).moves
    assert again.result == "1-0"


def test_home_lists_recent_games_and_opens_them(no_engine, answers_yes):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e4")
    h.game._on_draw()
    h.window.show_home()
    assert h.window.home.recent.rowCount() == 1
    h.window.home.recent.cellDoubleClicked.emit(0, 0)
    assert h.window.stack.currentWidget() is h.window.analysis_screen


# --- puzzles -----------------------------------------------------------------

def test_puzzle_set_is_seeded_and_listed(no_engine):
    h = no_engine
    h.window.show_puzzles()
    screen = h.window.puzzle_list
    assert screen.table.rowCount() == h.db.puzzle_count() >= 300
    assert "Решено: 0" in screen.stats.text()
    screen.theme_box.setCurrentIndex(screen.theme_box.findData("fork"))
    assert 0 < screen.table.rowCount() < h.db.puzzle_count()
    assert screen.table.item(0, 0).text() == "Вилка"


def solve_current(screen, use_hint=False):
    session = screen.session
    while not session.is_solved:
        if use_hint:
            screen._on_hint()
            use_hint = False
        move = session.expected
        screen.board.moveAttempted.emit(move.from_square, move.to_square, move.promotion or 0)
        wait_until(lambda: session.is_solved or session.board.turn == session.solver, 3)


def test_puzzle_full_flow_and_statistics(no_engine):
    h = no_engine
    h.window.show_puzzles()
    lst = h.window.puzzle_list
    lst.theme_box.setCurrentIndex(lst.theme_box.findData("mate2"))
    lst._start_selected()
    solve = h.window.puzzle_solve
    assert h.window.stack.currentWidget() is solve
    first = solve.session.puzzle.id
    assert solve.board.flipped == (solve.session.solver == chess.BLACK)

    wrong = next(
        m for m in solve.session.board.legal_moves
        if m != solve.session.expected
        and not (lambda b: (b.push(m), b.is_checkmate())[1])(solve.session.board.copy())
    )
    fen = solve.session.board.fen()
    solve.board.moveAttempted.emit(wrong.from_square, wrong.to_square, wrong.promotion or 0)
    assert "ещё раз" in solve.feedback.text()
    assert solve.session.board.fen() == fen

    solve_current(solve)
    assert "Решено" in solve.feedback.text()
    assert h.db.get_puzzle(first).solved and not h.db.get_puzzle(first).used_hint
    assert solve.board._interactive == set()

    solve._on_next()
    second = solve.session.puzzle.id
    assert second != first
    solve_current(solve, use_hint=True)
    assert "Подсказка учтена" in solve.feedback.text()
    assert h.db.get_puzzle(second).used_hint

    h.window.show_puzzles()
    assert "Решено: 2, из них с подсказкой: 1" in lst.stats.text()
    assert lst.table.item(0, 3).text() in ("решён", "решён с подсказкой")
    lst.unsolved.setChecked(True)
    assert lst.table.rowCount() == h.db.puzzle_stats("mate2").total - 2


def test_puzzle_hint_marks_squares_and_reset_restores(no_engine):
    h = no_engine
    h.window.show_puzzles()
    h.window.puzzle_list._start_selected()
    solve = h.window.puzzle_solve
    expected = solve.session.expected
    solve._on_hint()
    assert set(solve.board._marked) == {expected.from_square, expected.to_square}
    assert "Подсказка" in solve.feedback.text()
    start = solve.session.board.fen()
    solve.board.moveAttempted.emit(expected.from_square, expected.to_square, expected.promotion or 0)
    solve._on_reset()
    assert solve.session.board.fen() == start
    assert solve.board._marked == {}
    wait_until(lambda: False, 0.5)
    assert solve.session.board.fen() == start, "a pending reply must not land after a reset"


def test_puzzle_progress_survives_restart(app, stockfish_path):
    first = Harness(app)
    first.window.show_puzzles()
    first.window.puzzle_list._start_selected()
    solve = first.window.puzzle_solve
    puzzle_id = solve.session.puzzle.id
    solve_current(solve)
    first.close()
    second = Harness(app)
    try:
        assert second.db.get_puzzle(puzzle_id).solved
        assert second.db.puzzle_stats().solved == 1
    finally:
        second.close()


# --- dialogs and screens -----------------------------------------------------

def test_new_game_dialog_presets_custom_and_untimed(app):
    dialog = NewGameDialog(Mode.AI, default_level=7)
    assert dialog.level_slider.value() == 7
    assert dialog.time_control().storage_key == "5+0"
    dialog.color_box.setCurrentIndex(dialog.color_box.findData("black"))
    setup = dialog.setup()
    assert setup.player_color == chess.BLACK and setup.level == 7 and setup.mode == Mode.AI

    index = dialog.control_box.findData("custom")
    dialog.control_box.setCurrentIndex(index)
    assert dialog.minutes.isEnabled()
    dialog.minutes.setValue(7)
    dialog.increment.setValue(4)
    assert dialog.time_control() == TimeControl(7, 4)

    dialog.control_box.setCurrentIndex(dialog.control_box.findData("0+0"))
    assert dialog.time_control().untimed


def test_new_game_dialog_remembers_custom_control(app):
    dialog = NewGameDialog(Mode.LOCAL, last_control="7+4")
    assert dialog.control_box.currentData() == "custom"
    assert dialog.time_control() == TimeControl(7, 4)
    setup = dialog.setup()
    assert setup.player_color is None
    dialog = NewGameDialog(Mode.LOCAL, last_control="15+10")
    assert dialog.time_control().category == "Rapid"


def test_new_game_goes_through_dialog(no_engine, monkeypatch):
    h = no_engine
    monkeypatch.setattr(NewGameDialog, "exec", lambda self: QDialog.Accepted)
    h.window.new_game(Mode.LOCAL)
    assert h.window.stack.currentWidget() is h.game
    assert h.game.session.mode == Mode.LOCAL
    assert h.db.get_setting("last_time_control") == h.game.session.setup.time_control.storage_key


def test_back_button_saves_and_returns_home(no_engine):
    h = no_engine
    h.game.start_game(local_setup(TimeControl(5)))
    h.window._show(h.game)
    play(h.game, "e2e4")
    h.game._on_back()
    assert h.window.stack.currentWidget() is h.window.home
    assert h.window.home.resume_button.isVisibleTo(h.window.home)
    assert not h.game._timer.isActive()


def test_all_screens_render_in_both_themes(no_engine):
    h = no_engine
    h.game.start_game(local_setup())
    play(h.game, "e2e4")
    h.window.show_puzzles()
    h.window.puzzle_list._start_selected()
    for theme in ("light", "dark"):
        h.window.apply_theme_name(theme)
        for index in range(h.window.stack.count()):
            h.window.stack.setCurrentIndex(index)
            QApplication.processEvents()
            assert not h.window.grab().toImage().isNull()


def test_real_time_flag_through_the_screen_timer(no_engine):
    """No fake clock: the screen's own QTimer notices a clock running out in real time."""
    h = no_engine
    session = GameSession(local_setup(TimeControl(1)), white_ms=400, black_ms=60_000)
    started = time.monotonic()
    h.game._begin(session)
    assert wait_until(lambda: session.is_over, 3)
    elapsed = time.monotonic() - started
    assert 0.39 <= elapsed <= 0.6, f"flagged after {elapsed:.3f}s"
    assert session.outcome.result == "0-1"
    assert h.db.get_game(session.game_id).result == "0-1"
