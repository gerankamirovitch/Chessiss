"""Home screen, game tables, statistics, language switch and interface animations."""
import re
import time
from datetime import datetime, timedelta

import chess
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from core.game import Mode
from core.i18n import set_language
from storage.db import Database, PlayerStats
from ui.app import create_window
from ui.fx import PRESS_SCALE
from ui.history_screen import GameTable, control_text, players_of, relative_date, score_of
from ui.theme import DARK, LIGHT, current_theme

CYRILLIC = re.compile("[Ѐ-ӿ]")
NOW = datetime(2026, 11, 3, 12, 0)
AI_PGN = '[White "Игрок"]\n[Black "Stockfish, уровень 5"]\n[Result "{result}"]\n\n{result}\n'


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


def settle(seconds=0.05):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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
    QApplication.processEvents()


def add_game(db, result="1-0", color=chess.WHITE, control="10+0", date=None, mode=Mode.AI, pgn=None):
    return db.create_game(
        date or datetime.now(), mode.value, color, control, result, pgn or AI_PGN.format(result=result),
    )


def visible_rows(table):
    return [row for row in range(table.rowCount()) if not table.isRowHidden(row)]


# --- relative dates ------------------------------------------------------------

@pytest.mark.parametrize("delta, ru, en", [
    (timedelta(0), "Сегодня", "Today"),
    (timedelta(hours=-11), "Сегодня", "Today"),
    (timedelta(days=-1), "Вчера", "Yesterday"),
    (timedelta(days=-4), "4 дн. назад", "4 days ago"),
    (timedelta(days=-30), "30 дн. назад", "30 days ago"),
    (timedelta(days=2), "Сегодня", "Today"),  # the computer's clock was moved back
])
def test_relative_date(delta, ru, en):
    assert relative_date(NOW + delta, NOW) == ru
    set_language("en")
    assert relative_date(NOW + delta, NOW) == en
    set_language("ru")


def test_relative_date_counts_calendar_days_not_hours():
    assert relative_date(datetime(2026, 11, 2, 23, 59), datetime(2026, 11, 3, 0, 1)) == "Вчера"


# --- table cells ---------------------------------------------------------------

@pytest.mark.parametrize("key, ru, en", [
    ("1+0", "Пуля — 1+0", "Bullet — 1+0"),
    ("2+1", "Пуля — 2+1", "Bullet — 2+1"),
    ("3+0", "Блиц — 3+0", "Blitz — 3+0"),
    ("5+0", "Блиц — 5+0", "Blitz — 5+0"),
    ("10+0", "Рапид — 10+0", "Rapid — 10+0"),
    ("15+0", "Рапид — 15+0", "Rapid — 15+0"),
    ("15+10", "Рапид — 15+10", "Rapid — 15+10"),
    ("30+0", "Классика — 30+0", "Classical — 30+0"),
    ("0+0", "Без таймера", "No timer"),
    ("-", "—", "—"),
])
def test_mode_text(key, ru, en):
    assert control_text(key) == ru
    set_language("en")
    assert control_text(key) == en
    set_language("ru")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    yield database
    database.close()


@pytest.mark.parametrize("result, color, score, tone", [
    ("1-0", chess.WHITE, "1 – 0", "win"),
    ("0-1", chess.BLACK, "1 – 0", "win"),
    ("0-1", chess.WHITE, "0 – 1", "loss"),
    ("1-0", chess.BLACK, "0 – 1", "loss"),
    ("1/2-1/2", chess.WHITE, "½ – ½", "draw"),
    ("*", chess.WHITE, "—", "text_muted"),
    ("1-0", None, "1 – 0", "win"),  # no known side: white's point of view
    ("0-1", None, "0 – 1", "loss"),
])
def test_score_is_from_the_players_side(db, result, color, score, tone):
    game = db.get_game(add_game(db, result, color))
    assert score_of(game) == (score, tone)


def test_players_of_each_kind_of_game(db):
    white = db.get_game(add_game(db, color=chess.WHITE))
    assert players_of(white) == ("Вы", "Stockfish, уровень 5")
    black_pgn = '[White "Stockfish, уровень 9"]\n[Black "Игрок"]\n[Result "*"]\n\n*\n'
    black = db.get_game(add_game(db, "*", chess.BLACK, pgn=black_pgn))
    assert players_of(black) == ("Вы", "Stockfish, уровень 9")
    local_pgn = '[White "Белые"]\n[Black "Чёрные"]\n[Result "*"]\n\n*\n'
    local = db.get_game(add_game(db, "*", None, mode=Mode.LOCAL, pgn=local_pgn))
    assert players_of(local) == ("Белые", "Чёрные")
    imported_pgn = '[White "Carlsen"]\n[Black "?"]\n[Result "1-0"]\n\n1-0\n'
    imported = db.get_game(add_game(db, "1-0", None, mode=Mode.IMPORT, pgn=imported_pgn))
    assert players_of(imported) == ("Carlsen", "Чёрные")


def test_table_columns_are_equal_and_aligned_with_their_headers(window):
    db = window.db
    add_game(db, "1-0")
    add_game(db, "0-1")
    add_game(db, "1/2-1/2")
    window.refresh_home()
    table = window.home.recent
    assert [table.horizontalHeaderItem(c).text() for c in range(5)] == [
        "Кто играл", "С кем играл", "Счёт", "Режим", "Дата",
    ]
    header = table.horizontalHeader()
    assert all(header.sectionResizeMode(c) == QHeaderView.Stretch for c in range(5))
    widths = [table.columnWidth(c) for c in range(5)]
    assert max(widths) - min(widths) <= 1
    for column in range(5):
        expected = table.horizontalHeaderItem(column).textAlignment()
        for row in range(table.rowCount()):
            assert table.item(row, column).textAlignment() == expected


def test_scores_are_colored_by_result_in_both_themes(window):
    db = window.db
    add_game(db, "1/2-1/2", date=datetime(2026, 1, 1))
    add_game(db, "0-1", date=datetime(2026, 1, 2))
    add_game(db, "1-0", date=datetime(2026, 1, 3))
    for name, theme in (("dark", DARK), ("light", LIGHT)):
        window.apply_theme_name(name)
        table = window.home.recent
        colors = [table.item(row, 2).foreground().color() for row in range(3)]
        assert colors == [QColor(theme.win), QColor(theme.loss), QColor(theme.draw)]


# --- recent games --------------------------------------------------------------

def test_three_games_are_shown_and_the_rest_unfold(window):
    db = window.db
    for day in range(1, 6):
        add_game(db, date=datetime(2026, 1, day))
    window.refresh_home()
    home = window.home
    assert home.recent.rowCount() == 5
    assert visible_rows(home.recent) == [0, 1, 2]
    assert home.expand_button.isVisibleTo(home)
    assert home.expand_button.text() == "Показать все"
    collapsed = home.recent.height()
    assert collapsed == home.recent.height_for_rows(3)

    home.expand_button.click()
    assert home.expand_button.text() == "Свернуть"
    assert wait_until(lambda: home.recent.height() == home.recent.height_for_rows(5))
    assert visible_rows(home.recent) == [0, 1, 2, 3, 4]

    home.expand_button.click()
    assert home.expand_button.text() == "Показать все"
    assert wait_until(lambda: home.recent.height() == collapsed and visible_rows(home.recent) == [0, 1, 2])


def test_three_or_fewer_games_need_no_expand_button(window):
    db = window.db
    for _ in range(3):
        add_game(db)
    window.refresh_home()
    assert not window.home.expand_button.isVisibleTo(window.home)
    assert visible_rows(window.home.recent) == [0, 1, 2]


def test_a_refresh_keeps_the_expanded_list_open(window):
    db = window.db
    for _ in range(5):
        add_game(db)
    window.refresh_home()
    window.home.expand_button.click()
    window.refresh_home()
    assert visible_rows(window.home.recent) == [0, 1, 2, 3, 4]
    assert window.home.recent.height() == window.home.recent.height_for_rows(5)


def test_no_games_shows_the_placeholder(window):
    window.refresh_home()
    assert window.home.recent_empty.isVisibleTo(window.home)
    assert not window.home.recent.isVisibleTo(window.home)
    assert not window.home.expand_button.isVisibleTo(window.home)


def test_history_lists_every_game_in_the_same_table(window):
    db = window.db
    for _ in range(5):
        add_game(db)
    window.show_history()
    assert isinstance(window.history.table, GameTable)
    assert visible_rows(window.history.table) == [0, 1, 2, 3, 4]


# --- statistics ----------------------------------------------------------------

def test_stats_count_ai_games_from_the_players_side(db):
    assert db.player_stats() == PlayerStats(0, 0, 0)
    add_game(db, "1-0", chess.WHITE)
    add_game(db, "0-1", chess.BLACK)
    add_game(db, "0-1", chess.WHITE)
    add_game(db, "1/2-1/2", chess.BLACK)
    add_game(db, "*", chess.WHITE)  # unfinished
    add_game(db, "1-0", None, mode=Mode.LOCAL)
    add_game(db, "1/2-1/2", None, mode=Mode.IMPORT)
    stats = db.player_stats()
    assert stats == PlayerStats(wins=2, draws=1, losses=1)
    assert stats.total == 4


def test_stats_card_shows_counts_and_percents(window):
    db = window.db
    add_game(db, "1-0")
    add_game(db, "1-0")
    add_game(db, "0-1")
    add_game(db, "1/2-1/2")
    window.show_home()
    card = window.home.stats
    assert card.counts["wins"].text() == "2"
    assert card.shares["wins"].text() == "50%"
    assert card.counts["draws"].text() == "1"
    assert card.shares["losses"].text() == "25%"


def test_donut_grows_from_zero_to_full(window):
    chart = window.home.stats.chart
    chart.play()
    assert chart.progress == 0.0
    seen = []
    assert wait_until(lambda: seen.append(chart.progress) or chart.progress == 1.0)
    assert any(0.0 < value < 1.0 for value in seen)
    assert seen == sorted(seen)
    chart.grab()


def test_donut_draws_its_three_colors(window):
    db = window.db
    add_game(db, "1-0")
    add_game(db, "1/2-1/2")
    add_game(db, "0-1")
    window.refresh_home()
    chart = window.home.stats.chart
    chart.play()
    assert wait_until(lambda: chart.progress == 1.0)
    image = chart.grab().toImage()
    theme = current_theme()
    size = image.width()
    radius = size / 2 - 8.5
    samples = {}
    import math
    for name, degrees in (("win", 60), ("draw", 180), ("loss", 300)):  # clockwise from the top
        x = size / 2 + radius * math.sin(math.radians(degrees))
        y = size / 2 - radius * math.cos(math.radians(degrees))
        samples[name] = image.pixelColor(round(x), round(y)).name()
    assert samples == {"win": theme.win, "draw": theme.draw, "loss": theme.loss}


# --- top right icons -----------------------------------------------------------

def hover(button, inside=True):
    point = QPointF(5, 5)
    if inside:
        QApplication.sendEvent(button, QEnterEvent(point, point, QPointF(button.mapToGlobal(QPoint(5, 5)))))
    else:
        QApplication.sendEvent(button, QEvent(QEvent.Leave))


def test_icons_sit_in_the_top_right_corner_without_text(window):
    home = window.home
    settle()
    for button in (home.history_button, home.settings_button):
        assert button.text() == ""
        assert button.accessibleName()
        assert button.width() == button.height()
    right_edge = home.settings_button.mapTo(home, QPoint(home.settings_button.width(), 0))
    assert home.width() - right_edge.x() <= 16
    assert right_edge.y() <= 60
    assert home.history_button.x() < home.settings_button.x()


def test_hover_slides_the_label_out_and_pushes_the_neighbour(window):
    home = window.home
    settle()
    history, settings = home.history_button, home.settings_button
    history_x, history_width = history.x(), history.width()
    settings_right = settings.x() + settings.width()

    hover(settings)
    assert wait_until(lambda: settings.progress == 1.0)
    settle()
    assert settings.width() > settings.height()
    assert settings.x() + settings.width() == settings_right, "the icon stays where the cursor is"
    assert history.progress == 0.0, "the neighbour shows no label"
    assert history.width() == history_width
    assert history.x() < history_x, "the neighbour moved aside"

    hover(settings, inside=False)
    assert wait_until(lambda: settings.progress == 0.0)
    settle()
    assert settings.width() == settings.height()
    assert history.x() == history_x, "the neighbour came back"


def test_hovered_left_icon_opens_without_moving_the_right_one(window):
    home = window.home
    settle()
    history, settings = home.history_button, home.settings_button
    settings_x = settings.x()
    hover(history)
    assert wait_until(lambda: history.progress == 1.0)
    settle()
    assert history.width() > history.height()
    assert settings.progress == 0.0
    assert settings.x() == settings_x
    hover(history, inside=False)


def test_label_is_gone_after_a_click_opens_another_screen(window):
    home = window.home
    hover(home.settings_button)
    assert wait_until(lambda: home.settings_button.progress == 1.0)
    home.settings_button.click()
    QApplication.processEvents()
    assert window.stack.currentWidget() is window.settings
    assert home.settings_button.progress == 0.0
    window.show_home()


def test_icons_open_their_screens(window):
    window.home.history_button.click()
    assert window.stack.currentWidget() is window.history
    window.show_home()
    window.home.settings_button.click()
    assert window.stack.currentWidget() is window.settings


# --- animations ----------------------------------------------------------------

def test_every_push_button_shrinks_on_press_and_returns(window):
    button = window.home.ai_button
    QTest.mousePress(button, Qt.LeftButton)
    assert wait_until(lambda: button.graphicsEffect() is not None and button.graphicsEffect().scale <= PRESS_SCALE + 0.001)
    assert button.graphicsEffect().isEnabled()
    button.grab()  # the effect has to be able to paint in the pressed state
    QTest.qWait(1)
    button.setDown(False)
    QApplication.sendEvent(button, QEvent(QEvent.Hide))
    assert wait_until(lambda: button.graphicsEffect().scale == 1.0)
    assert not button.graphicsEffect().isEnabled()


def test_press_animation_reaches_standard_dialog_buttons(window):
    box = QMessageBox(window)
    box.setText("x")
    box.show()
    button = box.findChild(QAbstractButton)
    QTest.mousePress(button, Qt.LeftButton)
    assert wait_until(lambda: button.graphicsEffect() is not None)
    button.setDown(False)
    box.close()


def test_a_disabled_button_does_not_animate(window):
    button = window.game_screen.hint_button
    button.setEnabled(False)
    window._show(window.game_screen)
    QTest.mousePress(button, Qt.LeftButton)
    assert button.graphicsEffect() is None


def test_screen_change_covers_with_a_fading_picture_that_goes_away(window):
    window._show(window.history)
    assert window.stack.currentWidget() is window.history
    covers = [c for c in window.stack.findChildren(QLabel, options=Qt.FindDirectChildrenOnly)]
    assert covers, "a picture of the old screen fades on top"
    assert covers[0].testAttribute(Qt.WA_TransparentForMouseEvents), "it never blocks a click"
    assert wait_until(lambda: not window.stack.findChildren(QLabel, options=Qt.FindDirectChildrenOnly))


# --- language ------------------------------------------------------------------

def _all_texts(root):
    for widget in root.findChildren(QLabel):
        yield widget.text()
    for widget in root.findChildren(QAbstractButton):
        yield widget.text()
        yield widget.toolTip()
        yield widget.accessibleName()
    for widget in root.findChildren(QComboBox):
        for index in range(widget.count()):
            yield widget.itemText(index)
    for widget in root.findChildren(QLineEdit):
        yield widget.placeholderText()
    for widget in root.findChildren(QTableWidget):
        for column in range(widget.columnCount()):
            header = widget.horizontalHeaderItem(column)
            if header is not None:
                yield header.text()
        for row in range(widget.rowCount()):
            for column in range(widget.columnCount()):
                item = widget.item(row, column)
                if item is not None:
                    yield item.text()
                    yield item.toolTip()


def test_language_box_offers_english_and_switches_live(window):
    box = window.settings.language_box
    assert box.isEnabled()
    assert [box.itemData(i) for i in range(box.count())] == ["ru", "en"]
    window._show(window.settings)
    box.setCurrentIndex(box.findData("en"))
    assert window.db.get_setting("language") == "en"
    assert window.settings.language_box.currentData() == "en", "the new screen shows the choice"
    assert window.stack.currentWidget() is window.settings
    assert window.stack.count() == 7
    assert wait_until(lambda: not window.stack.findChildren(QLabel, options=Qt.FindDirectChildrenOnly))
    settle()


def test_no_screen_has_russian_left_in_english(window):
    db = window.db
    add_game(db, "1-0", chess.WHITE, "15+0")
    add_game(db, "0-1", chess.WHITE, "30+0", date=datetime.now() - timedelta(days=1))
    add_game(db, "1/2-1/2", chess.BLACK, "3+0", date=datetime.now() - timedelta(days=4))
    local = '[White "Белые"]\n[Black "Чёрные"]\n[Result "1-0"]\n\n1-0\n'
    add_game(db, "1-0", None, "5+0", mode=Mode.LOCAL, pgn=local)
    window._show(window.settings)
    window.settings.language_box.setCurrentIndex(1)
    window.refresh_home()
    window.history.refresh()
    window.puzzle_list.refresh()
    for screen in window._screens():
        russian = [text for text in _all_texts(screen) if text and CYRILLIC.search(text)]
        # "Русский" is the language's own name in the language box.
        assert [text for text in russian if text != "Русский"] == [], type(screen).__name__
    home = window.home
    assert home.recent.item(0, 0).text() == "White"
    assert home.recent.item(1, 1).text() == "Stockfish, level 5"
    assert home.history_button.label == "History"
    assert home.settings_button.label == "Settings"
    assert home.expand_button.text() == "Show all"


def test_language_choice_survives_a_restart(app, monkeypatch):
    monkeypatch.setattr("ui.engine_service.find_stockfish", lambda custom=None: None)
    first, db, engine = create_window(app)
    first.show()
    first.settings.language_box.setCurrentIndex(1)
    first.close()
    engine.shutdown()
    db.close()
    second, db, engine = create_window(app)
    try:
        assert second.home.settings_button.label == "Settings"
        assert second.settings.language_box.currentData() == "en"
    finally:
        second.close()
        engine.shutdown()
        db.close()
        set_language("ru")


def test_engine_message_is_rewritten_in_the_new_language(window):
    window.engine.warm_up()
    assert wait_until(lambda: not window.engine.available)
    assert "Stockfish не найден" in window.engine.message
    window._show(window.settings)
    window.settings.language_box.setCurrentIndex(1)
    assert wait_until(lambda: "was not found" in window.engine.message)
    assert wait_until(lambda: "was not found" in window.settings.engine_status.text())
    assert wait_until(lambda: "was not found" in window.home.engine_warning.text())


def test_interrupted_game_stays_resumable_after_switching_language(window):
    session_setup = __import__("core.game", fromlist=["GameSetup"]).GameSetup
    from core.clock import UNTIMED

    window._show(window.game_screen)
    window.game_screen.start_game(session_setup(Mode.LOCAL, UNTIMED))
    window.game_screen.board.moveAttempted.emit(chess.E2, chess.E4, 0)
    window.game_screen._on_back()
    window._show(window.settings)
    window.settings.language_box.setCurrentIndex(1)
    assert window.home.resume_button.isVisibleTo(window.home)
    window.resume_game()
    assert window.game_screen.session.ply_count == 1
    assert window.game_screen.title.text() == "Two-player game"
    assert window.game_screen.top_name.text() in ("White", "Black")
    assert "e4" in window.game_screen.moves.item(0, 1).text()
