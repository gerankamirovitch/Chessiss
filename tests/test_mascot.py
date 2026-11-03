"""Home screen: the mascot, her speech bubble, the animated title and the new layout."""
import math
import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.i18n import set_language, t
from ui.app import create_window
from ui.logo import TEXT, AnimatedLogo
from ui.mascot import ACTIVE_MS, CALM_MS, CURSOR_RADIUS, CX, EDGE, HEIGHT, WIDTH, GREETING, POKE_LINES, STEP, WELCOME_BACK, Mascot
from ui.theme import current_theme


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
def mascot(app):
    widget = Mascot()
    widget.cursor_source = lambda: QPointF(CX, 600)
    yield widget
    widget.close()


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
    set_language("ru")


def run(widget, seconds):
    for _ in range(round(seconds / STEP)):
        widget.advance(STEP)


# --- the girl ------------------------------------------------------------------

@pytest.mark.parametrize("cursor, sign", [(QPointF(-600, 140), -1), (QPointF(900, 140), 1)])
def test_head_and_eyes_turn_to_the_cursor(mascot, cursor, sign):
    mascot.cursor_source = lambda: cursor
    run(mascot, 1.5)
    look_x, _ = mascot.look
    assert look_x * sign > 0.9
    assert mascot.pose.yaw * sign > 0.9
    assert mascot.pose.tilt * sign > 0


def test_eyes_look_down_at_a_cursor_below(mascot):
    mascot.cursor_source = lambda: QPointF(CX, 900)
    run(mascot, 1.0)
    assert mascot.look[1] > 0.9


def test_hair_lags_behind_and_keeps_its_length(mascot):
    mascot.cursor_source = lambda: QPointF(900, 140)
    run(mascot, 2.0)
    tail = mascot.strands["tails"][1]
    tip_before = tail.points[-1][:]
    mascot.cursor_source = lambda: QPointF(-600, 140)
    run(mascot, 0.1)
    assert tail.motion > 1.0, "the tail is still swinging after the head turned"
    run(mascot, 0.6)
    assert math.dist(tip_before, tail.points[-1]) > 10
    for group in mascot.strands.values():
        for strand in group:
            for (a, b), length in zip(zip(strand.points, strand.points[1:]), strand.lengths):
                assert math.dist(a, b) == pytest.approx(length, abs=0.5)


def test_hair_settles_when_nothing_moves(mascot):
    run(mascot, 6.0)
    mascot._next_blink = 1e9
    run(mascot, 0.2)
    assert not mascot.moving


def test_cursor_pushes_the_hair_aside(mascot):
    run(mascot, 2.0)
    bang = mascot.strands["bangs"][3]
    x, y = bang.points[-1]
    mascot.cursor_source = lambda: QPointF(x, y)
    run(mascot, 0.3)
    assert math.dist((x, y), bang.points[-1]) > CURSOR_RADIUS * 0.4


def test_a_touch_moves_hair_gently(mascot):
    run(mascot, 2.0)
    bang = mascot.strands["bangs"][3]
    x, y = bang.points[-1]
    mascot.cursor_source = lambda: QPointF(x, y)
    mascot.advance(STEP)
    assert math.dist((x, y), bang.points[-1]) < 4, "no jump in a single frame"


def test_hair_never_leaves_the_widget(mascot):
    for cursor in (QPointF(-2000, 140), QPointF(3000, 140), QPointF(-2000, 140), QPointF(CX, -900)):
        mascot.cursor_source = lambda c=cursor: c
        for _ in range(40):
            mascot.advance(STEP)
            mascot.poke()
            for group in mascot.strands.values():
                for strand in group:
                    for x, y in strand.points:
                        assert EDGE - 0.01 <= x <= WIDTH - EDGE + 0.01
                        assert EDGE - 0.01 <= y <= HEIGHT - EDGE + 0.01


def test_bubble_does_not_cover_her_face(window):
    stage = window.home.stage
    bubble_left = stage.bubble.x()
    face_right = stage.mascot.x() + CX + 85
    assert bubble_left >= face_right


def test_frame_timer_runs_only_on_screen_and_slows_down_at_rest(mascot):
    assert not mascot.running
    mascot.show()
    assert mascot.running
    run(mascot, 6.0)
    mascot._next_blink = 1e9
    mascot._last_cursor = mascot.cursor_source()
    mascot._tick()
    assert mascot._timer.interval() == CALM_MS
    mascot.cursor_source = lambda: QPointF(10, 10)
    mascot._tick()
    if QApplication.applicationState() == Qt.ApplicationActive:
        assert mascot._timer.interval() == ACTIVE_MS
    mascot.hide()
    assert not mascot.running


def test_a_click_makes_her_happy_and_shakes_the_hair(mascot):
    mascot.show()
    run(mascot, 2.0)
    poked = []
    mascot.poked.connect(lambda: poked.append(True))
    QTest.mouseClick(mascot, Qt.LeftButton, pos=QPoint(round(CX), 150))
    assert poked
    assert mascot.happy
    run(mascot, 0.05)
    assert max(mascot._motion_report().values()) > 0.5
    run(mascot, 1.0)
    assert not mascot.happy


def test_wave_raises_and_lowers_the_arm(mascot):
    mascot.wave()
    assert mascot.waving
    run(mascot, 0.8)
    mascot.grab()
    run(mascot, 2.0)
    assert not mascot.waving


def test_every_pose_paints(mascot):
    for action in (lambda: None, mascot.wave, mascot.poke, lambda: mascot.talk(1.0)):
        action()
        run(mascot, 0.2)
        image = mascot.grab().toImage()
        assert not image.isNull()
    mascot._blink_left = 0.07
    run(mascot, STEP)
    mascot.grab()


def test_she_draws_no_background(mascot):
    image = QImage(mascot.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    mascot.paint_into(painter)
    painter.end()
    assert image.pixelColor(2, 2).alpha() == 0
    assert image.pixelColor(round(CX), 160).alpha() == 255  # her face


def test_home_background_shows_around_her(window):
    mascot = window.home.stage.mascot
    picture = window.grab().toImage()
    corner = mascot.mapTo(window, QPoint(3, 3))
    assert picture.pixelColor(corner).name() == current_theme().window


# --- home screen ---------------------------------------------------------------

def test_she_greets_and_answers_clicks(window):
    stage = window.home.stage
    assert stage.bubble.text == t(GREETING)
    assert stage.mascot.waving
    assert stage.mascot.talking
    assert wait_until(lambda: stage.bubble.visible_text == stage.bubble.text)
    stage.mascot.poke()
    assert stage.bubble.text == t(POKE_LINES[0])
    stage.mascot.poke()
    assert stage.bubble.text == t(POKE_LINES[1])
    window.show_history()
    window.show_home()
    assert stage.bubble.text == t(WELCOME_BACK)


def test_she_speaks_english(window):
    window._show(window.settings)
    window.settings.language_box.setCurrentIndex(1)
    window.show_home()
    assert window.home.stage.bubble.text == "Hi! Fancy a game?"  # the screens are rebuilt in the new language
    window.home.stage.mascot.poke()
    assert window.home.stage.bubble.text == "Hey, that tickles!"


def test_mascot_stops_when_another_screen_opens(window):
    mascot = window.home.stage.mascot
    assert wait_until(lambda: mascot.running)
    window.show_history()
    assert wait_until(lambda: not mascot.running)


def test_mode_buttons_sit_under_her_in_the_middle(window):
    home = window.home
    buttons = [home.ai_button, home.puzzles_button, home.local_button, home.analysis_button]
    assert [b.text().split("\n")[0] for b in buttons] == ["Против AI", "Пазлы", "Вдвоём", "Анализ партии"]
    assert len({(b.width(), b.height()) for b in buttons}) == 1
    assert buttons[0].height() >= 100
    stage_bottom = home.stage.mapTo(home, QPoint(0, home.stage.height())).y()
    left = min(b.mapTo(home, QPoint(0, 0)).x() for b in buttons)
    right = max(b.mapTo(home, QPoint(b.width(), 0)).x() for b in buttons)
    assert all(b.mapTo(home, QPoint(0, 0)).y() >= stage_bottom for b in buttons)
    assert abs(left - (home.width() - right)) <= 12  # the scroll bar takes a few pixels on one side
    assert right - left < home.width() * 0.7, "not stretched over the window"
    window.resize(1600, 900)
    QApplication.processEvents()
    assert buttons[0].width() == buttons[1].width() == home.ai_button.width()


def test_statistics_card_is_below_the_buttons_centered_and_narrow(window):
    home = window.home
    card = home.stats
    card_left = card.mapTo(home, QPoint(0, 0))
    assert card_left.y() > home.analysis_button.mapTo(home, QPoint(0, home.analysis_button.height())).y()
    assert abs(card_left.x() - (home.width() - card_left.x() - card.width())) <= 12
    window.resize(1600, 900)
    QApplication.processEvents()
    assert card.width() < 500


def test_statistics_no_longer_names_ai_games(window):
    texts = [label.text() for label in window.home.stats.findChildren(type(window.home.stats.caption))]
    assert "Партии против AI" not in texts
    assert window.home.stats.caption.text() == "Пока нет партий"


# --- the title -----------------------------------------------------------------

@pytest.fixture
def logo(app):
    widget = AnimatedLogo()
    widget.resize(900, 100)
    yield widget
    widget.close()


def test_title_letters_run_in_bump_and_assemble(logo):
    logo.play()
    assert not logo.finished
    assert all(letter.x > logo.width() for letter in logo.letters), "they start outside on the right"
    seen_pieces = 0
    order = []
    for _ in range(round(6 / STEP)):
        logo.advance(STEP)
        seen_pieces = max(seen_pieces, len(logo.pieces))
        for index, letter in enumerate(logo.letters):
            if letter.state != "wait" and index not in order:
                order.append(index)
        if logo.finished:
            break
    assert logo.finished
    assert order == list(range(len(TEXT))), "one after another"
    assert logo.hits == len(TEXT) - 1, "each letter hits the one in front"
    assert seen_pieces >= 9
    assert not logo.pieces
    assert [round(letter.x, 3) for letter in logo.letters] == [round(letter.target, 3) for letter in logo.letters]
    for left, right in zip(logo.letters, logo.letters[1:]):
        assert right.target == pytest.approx(left.target + left.advance)


def test_letters_never_overlap_once_they_meet(logo):
    logo.play()
    for _ in range(round(4 / STEP)):
        logo.advance(STEP)
        for left, right in zip(logo.letters, logo.letters[1:]):
            if left.state == right.state == "settle":
                assert right.x >= left.x + left.advance - 0.5


def test_title_paints_every_stage_and_the_timer_stops(app):
    logo = AnimatedLogo()
    logo.resize(900, 100)
    logo.show()
    logo.play()
    assert logo.running
    for _ in range(10):
        logo.advance(0.2)
        logo.grab()
    assert wait_until(lambda: logo.finished and not logo.running, timeout=8)
    QTest.mouseClick(logo, Qt.LeftButton)
    assert logo.running, "a click replays it"
    logo.hide()
    assert logo.finished and not logo.running
    logo.close()


def test_hits_throw_chess_pieces_that_fall(logo):
    logo.play()
    while not logo.pieces:
        logo.advance(STEP)
    piece = logo.pieces[0]
    assert piece[9] in "KQRBNP"
    assert 8 <= piece[4] <= 13, "as small as the bubbles were"
    rising = piece[3]
    for _ in range(20):
        logo.advance(STEP)
    assert piece[3] > rising, "gravity pulls them down"


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_title_letters_are_white(app, theme_name):
    from ui.theme import THEMES, apply_theme
    apply_theme(app, THEMES[theme_name])
    logo = AnimatedLogo()
    logo.resize(900, 100)
    image = logo.grab().toImage()
    letter = logo.letters[0]
    y = round(logo.baseline() - logo._cap * 0.5)
    colors = {image.pixelColor(x, y).name() for x in range(round(letter.x), round(letter.x + letter.advance))}
    assert "#ffffff" in colors
    apply_theme(app, THEMES["dark"])


def test_title_is_centered_after_a_resize(logo):
    logo.show()
    logo.resize(1200, 100)
    QApplication.processEvents()
    left = logo.letters[0].x
    right = logo.letters[-1].x + logo.letters[-1].advance
    assert left == pytest.approx(1200 - right, abs=0.5)


def test_title_runs_once_per_start(window):
    logo = window.home.logo
    assert not logo.finished or logo.hits
    logo.stop()
    window.show_history()
    window.show_home()
    assert logo.finished, "coming back home does not replay it"
