"""List of saved games with filters, import and export."""
from __future__ import annotations

import chess
from PySide6.QtCore import Qt, Signal
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
from storage.db import Database, GameRow
from ui.analysis_screen import export_game_pgn, load_pgn_file, store_imported
from ui.widgets import header_bar


def result_text(game: GameRow) -> str:
    if game.result == "*":
        return "не завершена"
    if game.result == "1/2-1/2":
        return "ничья"
    if game.player_color is None:
        return "белые выиграли" if game.result == "1-0" else "чёрные выиграли"
    won = (game.result == "1-0") == (game.player_color == chess.WHITE)
    return "победа" if won else "поражение"


def control_text(key: str) -> str:
    try:
        return TimeControl.from_storage_key(key).label
    except ValueError:
        return key


def color_text(color) -> str:
    if color is None:
        return "—"
    return "белые" if color == chess.WHITE else "чёрные"


def mode_text(mode: str) -> str:
    try:
        return MODE_NAMES[Mode(mode)]
    except ValueError:
        return mode


class GameTable(QTableWidget):
    """Rows of games. The home screen and the history screen share it."""

    gameActivated = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["Дата", "Режим", "Цвет", "Время", "Результат"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.cellDoubleClicked.connect(self._activated)
        self._ids: list[int] = []

    def set_games(self, games: list[GameRow]) -> None:
        self._ids = [game.id for game in games]
        self.setRowCount(len(games))
        for row, game in enumerate(games):
            cells = (
                game.date.strftime("%d.%m.%Y %H:%M"),
                mode_text(game.mode),
                color_text(game.player_color),
                control_text(game.time_control),
                result_text(game),
            )
            for column, text in enumerate(cells):
                self.setItem(row, column, QTableWidgetItem(text))

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
        header, _ = header_bar("История партий", self.backRequested.emit)

        self.mode_box = QComboBox()
        self.mode_box.addItem("Все режимы", None)
        for mode in Mode:
            self.mode_box.addItem(MODE_NAMES[mode], mode.value)
        self.result_box = QComboBox()
        for text, value in (
            ("Любой результат", None),
            ("Победа", "win"),
            ("Поражение", "loss"),
            ("Белые выиграли", "white"),
            ("Чёрные выиграли", "black"),
            ("Ничья", "draw"),
            ("Не завершена", "unfinished"),
        ):
            self.result_box.addItem(text, value)
        self.mode_box.currentIndexChanged.connect(self.refresh)
        self.result_box.currentIndexChanged.connect(self.refresh)

        self.open_button = QPushButton("Открыть")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open_selected)
        self.export_button = QPushButton("Экспорт PGN")
        self.export_button.clicked.connect(self._export_selected)
        self.import_button = QPushButton("Импорт PGN")
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
        self.empty = QLabel("Партий с такими условиями нет.")
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
        path, _ = QFileDialog.getOpenFileName(self, "Импорт PGN", "", "PGN (*.pgn);;Все файлы (*)")
        if not path:
            return
        game = load_pgn_file(self, path)
        if game is None:
            return
        game_id = store_imported(self.db, game)
        self.refresh()
        self.openGame.emit(game_id)
