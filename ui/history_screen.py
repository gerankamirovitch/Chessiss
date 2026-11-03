"""List of saved games with filters, import and export."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import chess
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.clock import TimeControl
from core.game import MODE_NAMES, Mode
from core.i18n import t
from core.pgn_io import display_player
from storage.db import Database, GameRow
from ui.analysis_screen import export_game_pgn, load_pgn_file, store_imported
from ui.theme import current_theme
from ui.widgets import header_bar

ROW_HEIGHT = 44
BOTTOM_INSET = 6  # keeps the last row's line clear of the table's rounded corners


def result_text(game: GameRow) -> str:
    if game.result not in ("1-0", "0-1", "1/2-1/2"):
        return t("не завершена")
    if game.result == "1/2-1/2":
        return t("ничья")
    if game.player_color is None:
        return t("белые выиграли") if game.result == "1-0" else t("чёрные выиграли")
    won = (game.result == "1-0") == (game.player_color == chess.WHITE)
    return t("победа") if won else t("поражение")


def control_text(key: str) -> str:
    """"15+0" -> "Рапид — 15+0". The category follows the estimated game length
    (minutes plus 40 increments), which also places any custom control."""
    try:
        control = TimeControl.from_storage_key(key)
    except ValueError:
        return "—"
    if control.untimed:
        return t("Без таймера")
    seconds = control.minutes * 60 + control.increment * 40
    if seconds < 180:
        category = t("Пуля")
    elif seconds < 480:
        category = t("Блиц")
    elif seconds < 1500:
        category = t("Рапид")
    else:
        category = t("Классика")
    return f"{category} — {key}"


def relative_date(date: datetime, now: Optional[datetime] = None) -> str:
    days = ((now or datetime.now()).date() - date.date()).days
    if days <= 0:
        return t("Сегодня")
    if days == 1:
        return t("Вчера")
    return t("{days} дн. назад", days=days)


def _pgn_name(pgn: str, tag: str, fallback: str) -> str:
    match = re.search(rf'\[{tag} "([^"]*)"\]', pgn)
    name = match.group(1) if match else "?"
    return fallback if name in ("", "?") else display_player(name)


def players_of(game: GameRow) -> tuple[str, str]:
    """Who played and against whom. Without a known side, white counts as the player."""
    white = _pgn_name(game.pgn, "White", t("Белые"))
    black = _pgn_name(game.pgn, "Black", t("Чёрные"))
    if game.player_color is None:
        return white, black
    return t("Вы"), black if game.player_color == chess.WHITE else white


def score_of(game: GameRow) -> tuple[str, str]:
    """The score from the player's side and the name of its color in the theme."""
    if game.result == "1/2-1/2":
        return "½ – ½", "draw"
    if game.result not in ("1-0", "0-1"):
        return "—", "text_muted"
    won = (game.result == "1-0") == (game.player_color != chess.BLACK)
    return ("1 – 0", "win") if won else ("0 – 1", "loss")


class GameTable(QTableWidget):
    """Rows of games. The home screen and the history screen share it."""

    gameActivated = Signal(int)

    _LEFT = Qt.AlignLeft | Qt.AlignVCenter
    _CENTER = Qt.AlignCenter
    _RIGHT = Qt.AlignRight | Qt.AlignVCenter
    # Text columns on the left, the score in the middle, the date closes the row on the right.
    _ALIGNMENT = (_LEFT, _LEFT, _CENTER, _LEFT, _RIGHT)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setObjectName("gameTable")
        titles = (t("Кто играл"), t("С кем играл"), t("Счёт"), t("Режим"), t("Дата"))
        for column, title in enumerate(titles):
            header = QTableWidgetItem(title)
            header.setTextAlignment(self._ALIGNMENT[column])
            self.setHorizontalHeaderItem(column, header)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setHighlightSections(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.cellDoubleClicked.connect(self._activated)
        self._ids: list[int] = []

    def set_games(self, games: list[GameRow]) -> None:
        theme = current_theme()
        self._ids = [game.id for game in games]
        self.setRowCount(len(games))
        for row, game in enumerate(games):
            player, opponent = players_of(game)
            score, tone = score_of(game)
            cells = (player, opponent, score, control_text(game.time_control), relative_date(game.date))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(self._ALIGNMENT[column])
                item.setToolTip(text)
                self.setItem(row, column, item)
            result = self.item(row, 2)
            result.setForeground(QColor(getattr(theme, tone)))
            result.setToolTip(result_text(game))
            font = result.font()
            font.setBold(True)
            result.setFont(font)
            self.item(row, 4).setToolTip(game.date.strftime("%d.%m.%Y %H:%M"))

    def height_for_rows(self, rows: int) -> int:
        return self.horizontalHeader().sizeHint().height() + rows * ROW_HEIGHT + 2 * self.frameWidth() + BOTTOM_INSET

    def selected_id(self):
        rows = self.selectionModel().selectedRows()
        return self._ids[rows[0].row()] if rows else None

    def _activated(self, row: int, _column: int) -> None:
        self.gameActivated.emit(self._ids[row])


class HistoryScreen(QWidget):
    backRequested = Signal()
    openGame = Signal(int)

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        header, _ = header_bar(t("История партий"), self.backRequested.emit)

        self.mode_box = QComboBox()
        self.mode_box.addItem(t("Все режимы"), None)
        for mode in Mode:
            self.mode_box.addItem(t(MODE_NAMES[mode]), mode.value)
        self.result_box = QComboBox()
        for text, value in (
            (t("Любой результат"), None),
            (t("Победа"), "win"),
            (t("Поражение"), "loss"),
            (t("Белые выиграли"), "white"),
            (t("Чёрные выиграли"), "black"),
            (t("Ничья"), "draw"),
            (t("Не завершена"), "unfinished"),
        ):
            self.result_box.addItem(text, value)
        self.mode_box.currentIndexChanged.connect(self.refresh)
        self.result_box.currentIndexChanged.connect(self.refresh)

        self.open_button = QPushButton(t("Открыть"))
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open_selected)
        self.export_button = QPushButton(t("Экспорт PGN"))
        self.export_button.clicked.connect(self._export_selected)
        self.import_button = QPushButton(t("Импорт PGN"))
        self.import_button.clicked.connect(self._import)

        filters = QHBoxLayout()
        filters.addWidget(self.mode_box)
        filters.addWidget(self.result_box)
        filters.addStretch(1)
        filters.addWidget(self.import_button)
        filters.addWidget(self.export_button)
        filters.addWidget(self.open_button)

        self.table = GameTable()
        self.table.gameActivated.connect(self.openGame.emit)
        self.empty = QLabel(t("Партий с такими условиями нет."))
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(header)
        root.addLayout(filters)
        root.addWidget(self.table, 1)
        root.addWidget(self.empty)

    def refresh(self) -> None:
        games = self.db.list_games(self.mode_box.currentData(), self.result_box.currentData())
        self.table.set_games(games)
        self.empty.setVisible(not games)
        self.open_button.setEnabled(bool(games))
        self.export_button.setEnabled(bool(games))
        if games:
            self.table.selectRow(0)

    def _open_selected(self) -> None:
        game_id = self.table.selected_id()
        if game_id is not None:
            self.openGame.emit(game_id)

    def _export_selected(self) -> None:
        game_id = self.table.selected_id()
        if game_id is None:
            return
        game = self.db.get_game(game_id)
        if game is not None:
            export_game_pgn(self, game.pgn)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Импорт PGN"), "", t("PGN (*.pgn);;Все файлы (*)"))
        if not path:
            return
        game = load_pgn_file(self, path)
        if game is None:
            return
        game_id = store_imported(self.db, game)
        self.refresh()
        self.openGame.emit(game_id)
