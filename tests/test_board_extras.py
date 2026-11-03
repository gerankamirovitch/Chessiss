"""Right-button arrows, the turning board, player cards, the chat and the ID button."""
import time

import chess
import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from core.clock import UNTIMED, TimeControl
from core.game import GameSession, GameSetup, Mode
from ui.app import create_window
from ui.board_widget import TURN_MS, BoardWidget
from ui.theme import DARK, LIGHT, apply_theme
from ui.widgets import ME, SYSTEM, THEM, ChatBubble, ExplanationBlock, ExplanationPanel


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def board(app):
    widget = BoardWidget(LIGHT)
    widget.resize(640, 640)
    session = GameSession(GameSetup(Mode.LOCAL, UNTIMED))
    widget.set_controller(session)
    widget.set_position(session.board)
    widget.set_interactive({chess.WHITE})
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.close()


def center(widget, square):
    return QPointF(widget.square_rect(square).center())


def mouse(widget, kind, button, square, buttons=None):
    point = center(widget, square)
    event = QMouseEvent(kind, point, widget.mapToGlobal(point), button, buttons if buttons is not None else button, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def right_drag(widget, start, end):
    mouse(widget, QEvent.MouseButtonPress, Qt.RightButton, start)
    mouse(widget, QEvent.MouseMove, Qt.NoButton, end, Qt.RightButton)
    mouse(widget, QEvent.MouseButtonRelease, Qt.RightButton, end, Qt.NoButton)


# --- right-button arrows -------------------------------------------------------

def test_right_drag_draws_a_green_arrow_and_plays_nothing(board):
    moves = []
    board.moveAttempted.connect(lambda *a: moves.append(a))
    right_drag(board, chess.E2, chess.E4)
    assert board.user_arrows == [(chess.E2, chess.E4)]
    assert moves == []
    image = board.grab().toImage()
    middle = (center(board, chess.E2) + center(board, chess.E4)) / 2
    color = image.pixelColor(middle.toPoint())
    assert color.green() > color.red() and color.green() > color.blue()


def test_the_same_arrow_again_removes_it(board):
    right_drag(board, chess.G1, chess.F3)
    right_drag(board, chess.G1, chess.F3)
    assert board.user_arrows == []


def test_right_click_marks_a_square_and_left_click_clears_everything(board):
    right_drag(board, chess.D5, chess.D5)
    right_drag(board, chess.B1, chess.C3)
    assert board.user_squares == {chess.D5}
    assert board.user_arrows == [(chess.B1, chess.C3)]
    QTest.mouseClick(board, Qt.LeftButton, pos=center(board, chess.H5).toPoint())
    assert board.user_squares == set() and board.user_arrows == []


def test_arrows_work_on_a_read_only_board(board):
    board.set_interactive(set())
    right_drag(board, chess.A1, chess.H8)
    assert board.user_arrows == [(chess.A1, chess.H8)]


def test_a_move_still_works_after_drawing(board):
    moves = []
    board.moveAttempted.connect(lambda *a: moves.append(a))
    right_drag(board, chess.E2, chess.E4)
    QTest.mouseClick(board, Qt.LeftButton, pos=center(board, chess.E2).toPoint())
    QTest.mouseClick(board, Qt.LeftButton, pos=center(board, chess.E4).toPoint())
    assert moves == [(chess.E2, chess.E4, 0)]
    assert board.user_arrows == []


# --- the turning board ---------------------------------------------------------

def test_animated_turn_ends_in_the_new_orientation(board):
    finished = []
    board.turnFinished.connect(lambda: finished.append(True))
    board.set_flipped(True, animate=True)
    assert board.turning and board.flipped
    board.grab()  # mid-turn picture
    QTest.qWait(TURN_MS // 2)
    board.grab()
    assert wait_until(lambda: finished)
    assert not board.turning
    a1 = board.square_rect(chess.A1)
    assert a1.top() < board.height() / 2


def test_turn_waits_for_the_move_animation(board):
    session = GameSession(GameSetup(Mode.LOCAL, UNTIMED))
    move = chess.Move.from_uci("e2e4")
    session.play(move)
    board.set_position(session.board, move, animate=True)
    board.set_flipped(True, animate=True)
    assert board.flipped, "reports where it is going"
    assert board._turn.state() != QAbstractAnimation.Running, "the piece slides first"
    assert wait_until(lambda: board._turn.state() == QAbstractAnimation.Running)
    assert wait_until(lambda: not board.turning)


def test_clicks_are_ignored_while_turning(board):
    board.set_flipped(True, animate=True)
    QTest.mouseClick(board, Qt.LeftButton, pos=center(board, chess.E2).toPoint())
    assert board._selected is None


# --- game screen ---------------------------------------------------------------

@pytest.fixture
def window(app, monkeypatch):
    monkeypatch.setattr("ui.engine_service.find_stockfish", lambda custom=None: None)
    window, db, engine = create_window(app)
    window.resize(1200, 800)
    window.show()
    QApplication.processEvents()
    yield window
    window.close()
    engine.shutdown()
    db.close()


def play(screen, *ucis):
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        screen.board.moveAttempted.emit(move.from_square, move.to_square, 0)


def test_no_flip_button_in_games_and_puzzles_but_in_analysis(window):
    names = lambda screen: [b.text() for b in screen.findChildren(QPushButton)]
    assert "Повернуть" not in names(window.game_screen)
    assert "Повернуть" not in names(window.puzzle_solve)
    assert "Повернуть" in names(window.analysis_screen)


def test_two_player_board_turns_after_each_move_and_undo(window):
    game = window.game_screen
    window._show(game)
    game.start_game(GameSetup(Mode.LOCAL, TimeControl(5)))
    assert not game.board.flipped
    play(game, "e2e4")
    assert game.board.flipped, "black plays from the bottom now"
    assert game.bottom_name.text() == "Чёрные"
    assert game.bottom_card.chip.color == chess.BLACK
    assert game.bottom_card.property("toMove") is True
    assert game.top_card.property("toMove") is False
    assert game.bottom_card.graphicsEffect() is not None, "the cards blink after the swap"
    assert wait_until(lambda: not game.board.turning)
    play(game, "e7e5")
    assert not game.board.flipped
    assert game.bottom_name.text() == "Белые"
    game._on_undo()
    assert game.board.flipped, "undo turns it back to the side to move"
    game._tick()
    assert game.bottom_clock.property("active") is True


def test_ai_game_board_never_turns(window):
    game = window.game_screen
    session = GameSession(GameSetup(Mode.AI, UNTIMED, chess.WHITE, 1))
    game._begin(session)
    game._apply_move(chess.Move.from_uci("e2e4"))
    assert not game.board.flipped and not game.board.turning


def test_resumed_two_player_game_starts_with_the_mover_at_the_bottom(window):
    game = window.game_screen
    session = GameSession(GameSetup(Mode.LOCAL, UNTIMED))
    session.play(chess.Move.from_uci("d2d4"))
    game._begin(session)
    assert game.board.flipped and not game.board.turning


def test_copy_id_button_copies_the_fen_and_there_is_no_fen_field(window):
    game = window.game_screen
    window._show(game)
    game.start_game(GameSetup(Mode.LOCAL, UNTIMED))
    play(game, "e2e4")
    assert game.fen_bar.findChildren(QLineEdit) == []
    assert window.analysis_screen.fen_bar.findChildren(QLineEdit) == []
    assert game.fen_bar.copy_button.text() == "Копировать ID"
    game.fen_bar.copy_button.click()
    assert QGuiApplication.clipboard().text() == game.session.fen
    button = game.fen_bar.copy_button
    board_left = game.board.mapTo(game, game.board.rect().topLeft()).x()
    assert abs(button.mapTo(game, button.rect().topLeft()).x() - board_left) <= 2, "bottom left, under the board"
    assert button.mapTo(game, button.rect().topLeft()).y() > game.board.mapTo(game, game.board.rect().bottomLeft()).y() - 1


# --- chat ----------------------------------------------------------------------

@pytest.fixture
def chat(app):
    panel = ExplanationPanel()
    panel.resize(400, 500)
    panel.show()
    QApplication.processEvents()
    yield panel
    panel.close()


def test_my_moves_on_the_right_theirs_on_the_left(chat):
    chat.show_blocks([
        ExplanationBlock("Ваш ход: e4", "Хороший ход.", side=ME),
        ExplanationBlock("Ход AI: e5", "Ответ в центр.", side=THEM),
    ])
    QApplication.processEvents()
    mine, theirs = chat.bubbles
    width = chat.viewport().width()
    assert mine.x() + mine.width() > width * 0.8 and mine.x() > 10
    assert theirs.x() < width * 0.2
    assert "Хороший ход." in chat.toPlainText() and "Ответ в центр." in chat.toPlainText()


def test_long_messages_use_the_width_short_ones_stay_small(chat):
    chat.show_blocks([
        ExplanationBlock("Ход AI: e5", "Длинное объяснение хода, которое не помещается в одну строку и переносится. " * 3, side=THEM),
        ExplanationBlock("Ваш ход: e4", "Ок.", side=ME),
    ])
    QApplication.processEvents()
    long_one, short_one = chat.bubbles
    assert long_one.width() >= chat._bubble_width() - 2
    assert short_one.width() < long_one.width() * 0.75  # the offscreen test font is wide


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_bubble_colors_and_tails(app, chat, theme):
    apply_theme(app, theme)
    chat.show_blocks([ExplanationBlock("A", "x" * 60, side=ME), ExplanationBlock("B", "y" * 60, side=THEM)])
    QApplication.processEvents()
    mine, theirs = chat.bubbles
    assert wait_until(lambda: mine.graphicsEffect() is None and theirs.graphicsEffect() is None)
    image = mine.grab().toImage()
    assert image.pixelColor(mine.width() // 2, 4).name() == "#ffffff"
    dark = theirs.grab().toImage().pixelColor(theirs.width() // 2, 4)
    assert dark.lightness() < 80
    # tails: the bottom corner on the speaker's side is filled, the other one is not
    mine_path, their_path = mine.bubble_path(), theirs.bubble_path()
    from ui.widgets import TAIL
    h, th = mine.height(), theirs.height()
    assert mine_path.contains(QPointF(mine.width() - TAIL + 1, h - 2.5))
    assert not mine_path.contains(QPointF(1.0, h - 1.0))
    assert their_path.contains(QPointF(TAIL - 1, th - 2.5))
    assert not their_path.contains(QPointF(theirs.width() - 1.0, th - 1.0))
    apply_theme(app, DARK)


def test_only_new_messages_fade_in(chat):
    first = ExplanationBlock("Ваш ход: e4", "Текст", side=ME)
    chat.show_blocks([first])
    assert chat.bubbles[0].graphicsEffect() is not None
    assert wait_until(lambda: chat.bubbles[0].graphicsEffect() is None)
    chat.show_blocks([first, ExplanationBlock("Ход AI: e5", "", pending=True, side=THEM)])
    assert chat.bubbles[0].graphicsEffect() is None, "the old message stays still"
    assert chat.bubbles[1].graphicsEffect() is not None
    assert "Считаю" in chat.toPlainText()


def test_old_messages_leave_when_the_chat_changes(chat):
    for text in ("первый", "второй", "третий"):
        chat.show_blocks([ExplanationBlock("Ход", text, side=ME), ExplanationBlock("Ответ", text, side=THEM)])
        QApplication.processEvents()
    QApplication.processEvents()
    alive = [b for b in chat.findChildren(ChatBubble) if b.isVisible()]
    assert len(alive) == 2
    assert {b.block.text for b in alive} == {"третий"}
    tops = sorted(b.mapTo(chat.widget(), b.rect().topLeft()).y() for b in alive)
    first, second = sorted(alive, key=lambda b: b.mapTo(chat.widget(), b.rect().topLeft()).y())
    assert tops[1] >= tops[0] + first.height(), "messages do not overlap"


def test_plain_note_sits_in_the_middle_without_a_bubble(chat):
    chat.show_text("Откройте файл PGN")
    QApplication.processEvents()
    note = chat.bubbles[0]
    assert note.side == SYSTEM
    width = chat.viewport().width()
    assert abs((note.x() + note.width() / 2) - width / 2) < 20


def test_game_chat_puts_the_player_right_and_the_ai_left(window):
    game = window.game_screen
    session = GameSession(GameSetup(Mode.AI, UNTIMED, chess.BLACK, 1))
    game._begin(session)
    game._apply_move(chess.Move.from_uci("e2e4"))
    game._apply_move(chess.Move.from_uci("e7e5"))
    sides = [b.side for b in game.coach.bubbles]
    assert sides == [THEM, ME]


# --- puzzles -------------------------------------------------------------------

def test_next_puzzle_skips_the_solved_ones(window):
    ids = [p.id for p in window.db.list_puzzles()[:4]]
    window.db.mark_puzzle_solved(ids[1], used_hint=False)
    window.db.mark_puzzle_solved(ids[2], used_hint=False)
    solve = window.puzzle_solve
    solve.open_puzzle(ids[0], ids)
    solve._on_next()
    assert solve.session.puzzle.id == ids[3]


def test_when_everything_ahead_is_solved_next_still_moves_on(window):
    ids = [p.id for p in window.db.list_puzzles()[:3]]
    for pid in ids:
        window.db.mark_puzzle_solved(pid, used_hint=False)
    solve = window.puzzle_solve
    solve.open_puzzle(ids[0], ids)
    solve._on_next()
    assert solve.session.puzzle.id == ids[1]


# --- buttons, themes, lists, sounds ------------------------------------------------

def test_a_button_grows_under_the_mouse_and_returns(window):
    from ui.fx import HOVER_SCALE
    button = window.home.ai_button
    QApplication.sendEvent(button, QEvent(QEvent.Enter))
    assert wait_until(lambda: button.graphicsEffect() is not None and abs(button.graphicsEffect().scale - HOVER_SCALE) < 0.001)
    assert button.graphicsEffect().isEnabled()
    button.grab()
    QApplication.sendEvent(button, QEvent(QEvent.Leave))
    assert wait_until(lambda: button.graphicsEffect().scale == 1.0)
    assert not button.graphicsEffect().isEnabled(), "a still button is drawn without the effect"


def test_every_combo_box_uses_a_list_that_follows_the_stylesheet(window):
    from PySide6.QtWidgets import QComboBox, QStyledItemDelegate
    window._show(window.settings)
    QApplication.processEvents()
    boxes = [box for screen in window._screens() for box in screen.findChildren(QComboBox)]
    assert boxes
    for box in boxes:
        box.ensurePolished()
        assert isinstance(box.itemDelegate(), QStyledItemDelegate)


def test_glass_theme_is_offered_and_paints_its_backdrop(window):
    from ui.theme import GLASS_DARK, GLASS_LIGHT, current_theme
    box = window.settings.theme_box
    assert box.findData("glass") >= 0
    box.setCurrentIndex(box.findData("glass"))
    theme = current_theme()
    assert theme in (GLASS_DARK, GLASS_LIGHT) and theme.glass
    window.show_home()
    image = window.grab().toImage()
    corner = image.pixelColor(5, image.height() - 5)
    assert corner.name() != theme.window, "colored light, not the flat window color"
    assert not window.game_screen.board.testAttribute(Qt.WA_OpaquePaintEvent)
    box.setCurrentIndex(box.findData("dark"))
    assert not current_theme().glass
    assert window.game_screen.board.testAttribute(Qt.WA_OpaquePaintEvent)


def test_move_sound_choice_is_saved_and_used(window):
    box = window.settings.move_sound_box
    assert [box.itemData(i) for i in range(box.count())] == ["wood", "classic", "bubble", "retro"]
    assert window.sound.style == "wood", "wood is the default"
    box.setCurrentIndex(box.findData("bubble"))
    assert window.db.get_setting("move_sound") == "bubble"
    assert window.sound.style == "bubble"
    assert window.sound.file_name("move") == "bubble_move"
    assert window.sound.file_name("check") == "check"


@pytest.mark.parametrize("name", ["wood_move", "wood_capture", "bubble_move", "bubble_capture", "retro_move", "retro_capture"])
def test_every_move_sound_is_short_and_audible(name):
    from ui.sound import _RATE, render
    samples = render(name)
    assert 0.05 < len(samples) / _RATE < 0.3
    assert max(abs(v) for v in samples) > 0.1
    assert abs(samples[0]) < 0.05, "no click at the start"


def test_wood_capture_is_two_knocks(app):
    from ui.sound import _RATE, render
    samples = render("wood_capture")
    window = int(_RATE * 0.005)
    loud = [max(abs(v) for v in samples[i:i + window]) for i in range(0, len(samples) - window, window)]
    first, second = max(loud[:4]), max(loud[11:15])  # at 0 ms and at 55 ms
    gap = min(loud[6:11])
    assert first > 0.3 * max(loud) and second > 0.3 * max(loud)
    assert gap < 0.6 * first, "a quiet moment between the two knocks"
