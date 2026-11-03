"""Puzzle list by theme and the solving screen."""
from __future__ import annotations

from typing import Optional

import chess
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t
from core.pgn_io import display_san
from core.puzzles import THEMES, Attempt, Puzzle, PuzzleSession
from storage.db import Database
from ui.board_widget import BoardWidget
from ui.sound import SoundPlayer
from ui.theme import Theme
from ui.widgets import header_bar

REPLY_DELAY_MS = 350
HINT_SQUARE_COLOR = "#2f7d4f70"


class PuzzleListScreen(QWidget):
    backRequested = Signal()
    puzzleChosen = Signal(str, object)  # puzzle id, the list it came from

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._puzzles: list[Puzzle] = []

        header, _ = header_bar(t("Пазлы"), self.backRequested.emit)
        self.stats = QLabel()
        self.theme_box = QComboBox()
        self.theme_box.addItem(t("Все темы"), None)
        for key, name in THEMES.items():
            self.theme_box.addItem(t(name), key)
        self.theme_box.currentIndexChanged.connect(self.refresh)
        self.unsolved = QCheckBox(t("Только нерешённые"))
        self.unsolved.toggled.connect(self.refresh)
        self.start_button = QPushButton(t("Решать"))
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_selected)

        filters = QHBoxLayout()
        filters.addWidget(QLabel(t("Тема")))
        filters.addWidget(self.theme_box)
        filters.addWidget(self.unsolved)
        filters.addStretch(1)
        filters.addWidget(self.start_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t("Тема"), t("Сложность"), t("Ход"), t("Статус")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.cellDoubleClicked.connect(lambda row, _: self._start(row))

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(header)
        root.addWidget(self.stats)
        root.addLayout(filters)
        root.addWidget(self.table, 1)

    def refresh(self) -> None:
        theme = self.theme_box.currentData()
        self._puzzles = self.db.list_puzzles(theme, self.unsolved.isChecked())
        self.table.setRowCount(len(self._puzzles))
        for row, puzzle in enumerate(self._puzzles):
            status = t("не решён")
            if puzzle.solved:
                status = t("решён с подсказкой") if puzzle.used_hint else t("решён")
            side = t("белые") if chess.Board(puzzle.fen).turn == chess.WHITE else t("чёрные")
            for column, text in enumerate((puzzle.theme_name, str(puzzle.rating), side, status)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        stats = self.db.puzzle_stats(theme)
        self.stats.setText(
            t(
                "Всего: {total}. Решено: {solved}, из них с подсказкой: {hinted}.",
                total=stats.total, solved=stats.solved, hinted=stats.solved_with_hint,
            )
        )
        self.start_button.setEnabled(bool(self._puzzles))
        if self._puzzles:
            self.table.selectRow(0)

    def _start_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._start(rows[0].row())

    def _start(self, row: int) -> None:
        if 0 <= row < len(self._puzzles):
            self.puzzleChosen.emit(self._puzzles[row].id, [p.id for p in self._puzzles])


class PuzzleSolveScreen(QWidget):
    backRequested = Signal()

    def __init__(self, db: Database, sound: SoundPlayer, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.sound = sound
        self.session: Optional[PuzzleSession] = None
        self._queue: list[str] = []
        self._position = 0

        header, self.title = header_bar(t("Пазл"), self.backRequested.emit)
        self.board = BoardWidget(theme)
        self.board.moveAttempted.connect(self._on_move)

        self.task = QLabel()
        self.task.setObjectName("status")
        self.task.setWordWrap(True)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.info = QLabel()
        self.info.setObjectName("muted")

        self.hint_button = QPushButton(t("Подсказка"))
        self.hint_button.clicked.connect(self._on_hint)
        self.reset_button = QPushButton(t("Сначала"))
        self.reset_button.clicked.connect(self._on_reset)
        self.flip_button = QPushButton(t("Повернуть"))
        self.flip_button.clicked.connect(lambda: self.board.set_flipped(not self.board.flipped))
        self.next_button = QPushButton(t("Следующий"))
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._on_next)
        for button in (self.hint_button, self.reset_button, self.flip_button, self.next_button):
            button.setAutoDefault(False)

        side = QVBoxLayout()
        side.addWidget(self.task)
        side.addWidget(self.info)
        side.addWidget(self.feedback)
        side.addStretch(1)
        for button in (self.hint_button, self.reset_button, self.flip_button, self.next_button):
            side.addWidget(button)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(300)

        body = QHBoxLayout()
        body.addWidget(self.board, 1)
        body.addWidget(side_widget)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(header)
        root.addLayout(body, 1)

    def set_theme(self, theme: Theme) -> None:
        self.board.set_theme(theme)

    def open_puzzle(self, puzzle_id: str, queue: Optional[list[str]] = None) -> None:
        if queue is not None:
            self._queue = queue
            self._position = queue.index(puzzle_id) if puzzle_id in queue else 0
        puzzle = self.db.get_puzzle(puzzle_id)
        if puzzle is None:
            return
        self.session = PuzzleSession(puzzle)
        self.board.set_controller(self.session)
        self.board.set_flipped(self.session.solver == chess.BLACK)
        self.board.set_marked_squares({})
        side = t("белых") if self.session.solver == chess.WHITE else t("чёрных")
        self.title.setText(t("Пазл: {theme}", theme=puzzle.theme_name))
        self.task.setText(t("Ход {side}. Найдите лучшее продолжение.", side=side))
        self.info.setText(t("Сложность {rating} · {queue}", rating=puzzle.rating, queue=self._queue_text()))
        self.feedback.setText("")
        self.next_button.setEnabled(self._position + 1 < len(self._queue))
        self._refresh_board(animate=False)

    def _queue_text(self) -> str:
        if not self._queue:
            return ""
        return t("{index} из {total}", index=self._position + 1, total=len(self._queue))

    def _refresh_board(self, animate: bool) -> None:
        session = self.session
        last = session.board.peek() if session.board.move_stack else None
        self.board.set_position(session.board, last, animate)
        solving = not session.is_solved and session.board.turn == session.solver
        self.board.set_interactive({session.solver} if solving else set())
        self.hint_button.setEnabled(solving)

    def _on_move(self, from_square: int, to_square: int, promotion: int) -> None:
        session = self.session
        if session is None:
            return
        self.board.set_marked_squares({})
        move = chess.Move(from_square, to_square, promotion or None)
        attempt = session.try_move(move)
        if attempt == Attempt.WRONG:
            self.sound.play("wrong")
            self.feedback.setText(t("Не то. Попробуйте ещё раз."))
            self._refresh_board(animate=False)
            return
        self._refresh_board(animate=True)
        if attempt == Attempt.SOLVED:
            self._on_solved()
            return
        self.sound.play("correct")
        self.feedback.setText(t("Верно. Продолжайте."))
        expected_session = session
        self.board.set_interactive(set())
        QTimer.singleShot(REPLY_DELAY_MS, lambda: self._play_reply(expected_session))

    def _play_reply(self, session: PuzzleSession) -> None:
        if session is not self.session or session.is_solved:
            return
        if session.play_reply() is None:
            return
        self.sound.play("move")
        self._refresh_board(animate=True)

    def _on_solved(self) -> None:
        session = self.session
        self.db.mark_puzzle_solved(session.puzzle.id, session.used_hint)
        self.sound.play("correct")
        suffix = t(" Подсказка учтена в статистике.") if session.used_hint else ""
        self.feedback.setText(t("Решено!{suffix}", suffix=suffix))
        self.task.setText(t("Пазл решён."))

    def _on_hint(self) -> None:
        session = self.session
        if session is None:
            return
        move = session.hint()
        if move is None:
            return
        self.board.set_marked_squares({move.from_square: HINT_SQUARE_COLOR, move.to_square: HINT_SQUARE_COLOR})
        san = session.board.san(move)
        self.feedback.setText(t("Подсказка: {move}.", move=display_san(san)))

    def _on_reset(self) -> None:
        if self.session is None:
            return
        self.session.reset()
        self.board.set_marked_squares({})
        self.feedback.setText("")
        side = t("белых") if self.session.solver == chess.WHITE else t("чёрных")
        self.task.setText(t("Ход {side}. Найдите лучшее продолжение.", side=side))
        self._refresh_board(animate=False)

    def _on_next(self) -> None:
        if self._position + 1 < len(self._queue):
            self._position += 1
            self.open_puzzle(self._queue[self._position])
