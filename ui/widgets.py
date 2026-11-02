"""Widgets shared between screens: move list, evaluation graph, explanation panel, FEN bar."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional, Sequence

import chess
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QWidget,
)

from core.explain import Mark
from core.pgn_io import ru_san
from ui.theme import LIGHT, MARK_COLORS, Theme


def header_bar(title: str, on_back) -> tuple[QWidget, QLabel]:
    bar = QWidget()
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(0, 0, 0, 0)
    back = QPushButton("← Меню")
    back.clicked.connect(lambda: on_back())
    back.setAutoDefault(False)
    label = QLabel(title)
    label.setObjectName("screenTitle")
    layout.addWidget(back)
    layout.addSpacing(8)
    layout.addWidget(label)
    layout.addStretch(1)
    return bar, label


class MoveList(QTableWidget):
    """Numbered two-column notation. Click a move to jump to that position."""

    plySelected = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["", "Белые", "Чёрные"])
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.cellClicked.connect(self._on_clicked)
        self._black_first = False
        self._first_move_number = 1
        self._count = 0
        self._ply = 0

    def set_start(self, board: chess.Board) -> None:
        self._black_first = board.turn == chess.BLACK
        self._first_move_number = board.fullmove_number
        self.clear_moves()

    def clear_moves(self) -> None:
        self.setRowCount(0)
        self._count = 0
        self._ply = 0

    def set_moves(self, sans: Sequence[str]) -> None:
        self.clear_moves()
        for san in sans:
            self.append_move(san)

    def append_move(self, san: str) -> None:
        self._count += 1
        row, column = self._cell(self._count)
        if row >= self.rowCount():
            self.insertRow(row)
            number = QTableWidgetItem(f"{self._first_move_number + row}.")
            number.setFlags(Qt.ItemIsEnabled)
            number.setForeground(self.palette().placeholderText())
            self.setItem(row, 0, number)
        item = QTableWidgetItem(ru_san(san))
        self.setItem(row, column, item)

    def pop_moves(self, count: int) -> None:
        for _ in range(count):
            if self._count == 0:
                return
            row, column = self._cell(self._count)
            self.takeItem(row, column)
            self._count -= 1
            if self._row_is_empty(row):
                self.removeRow(row)

    def set_mark(self, ply: int, mark: Optional[Mark]) -> None:
        row, column = self._cell(ply)
        item = self.item(row, column)
        if item is None:
            return
        base = item.text().rstrip("?!")
        if mark is None:
            item.setText(base)
            item.setData(Qt.ForegroundRole, None)
            return
        item.setText(base + mark.glyph)
        if mark in (Mark.INACCURACY, Mark.MISTAKE, Mark.BLUNDER):
            item.setForeground(QColor(MARK_COLORS[mark]))
        item.setToolTip(mark.label)

    def set_current_ply(self, ply: int) -> None:
        self._ply = ply
        self.clearSelection()
        if ply <= 0:
            self.setCurrentCell(-1, -1)
            return
        row, column = self._cell(ply)
        self.setCurrentCell(row, column)
        item = self.item(row, column)
        if item is not None:
            self.scrollToItem(item)

    def _row_is_empty(self, row: int) -> bool:
        return self.item(row, 1) is None and self.item(row, 2) is None

    def _cell(self, ply: int) -> tuple[int, int]:
        index = ply - 1 + (1 if self._black_first else 0)
        return index // 2, 1 + index % 2

    def _on_clicked(self, row: int, column: int) -> None:
        if column == 0 or self.item(row, column) is None:
            return
        ply = row * 2 + column - (1 if self._black_first else 0)
        if 1 <= ply <= self._count:
            self.plySelected.emit(ply)


class EvalGraph(QWidget):
    """Evaluation by ply: the light area grows as white's advantage grows. Click to jump to a move."""

    plySelected = Signal(int)
    _SCALE_CP = 600

    def __init__(self, theme: Theme = LIGHT, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._evals: list[Optional[int]] = []
        self._marks: list[Optional[Mark]] = []
        self._ply = 0
        self.setMinimumHeight(90)
        self.setMaximumHeight(130)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(360, 110)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_data(self, evals: Sequence[Optional[int]], marks: Sequence[Optional[Mark]]) -> None:
        self._evals = list(evals)
        self._marks = list(marks)
        self.update()

    def set_current_ply(self, ply: int) -> None:
        self._ply = ply
        self.update()

    def _x(self, ply: int, width: float) -> float:
        return width * ply / max(1, len(self._evals))

    def _y(self, cp: int, height: float) -> float:
        clamped = max(-self._SCALE_CP, min(self._SCALE_CP, cp))
        return height / 2 - clamped / self._SCALE_CP * (height / 2 - 2)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor(self._theme.graph_black))
        width, height = rect.width(), rect.height()
        points = [(i + 1, cp) for i, cp in enumerate(self._evals) if cp is not None]
        if points:
            path = QPainterPath(QPointF(0, height))
            path.lineTo(0, height / 2)
            for ply, cp in points:
                path.lineTo(self._x(ply, width), self._y(cp, height))
            path.lineTo(self._x(points[-1][0], width), height)
            path.closeSubpath()
            painter.fillPath(path, QColor(self._theme.graph_white))
            painter.setPen(QPen(QColor(self._theme.graph_line), 1.5))
            line = QPainterPath(QPointF(0, height / 2))
            for ply, cp in points:
                line.lineTo(self._x(ply, width), self._y(cp, height))
            painter.drawPath(line)
        painter.setPen(QPen(QColor(128, 128, 128, 160), 1, Qt.DashLine))
        painter.drawLine(QPointF(0, height / 2), QPointF(width, height / 2))
        for ply, cp in points:
            mark = self._marks[ply - 1] if ply - 1 < len(self._marks) else None
            if mark in (Mark.MISTAKE, Mark.BLUNDER, Mark.INACCURACY):
                radius = 3.5 if mark != Mark.INACCURACY else 2.5
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(MARK_COLORS[mark]))
                painter.drawEllipse(QPointF(self._x(ply, width), self._y(cp, height)), radius, radius)
        if self._ply > 0 and self._evals:
            x = self._x(self._ply, width)
            painter.setPen(QPen(QColor(self._theme.accent), 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        painter.end()

    def mousePressEvent(self, event) -> None:
        if not self._evals:
            return
        fraction = event.position().x() / max(1, self.width())
        self.plySelected.emit(max(0, min(len(self._evals), round(fraction * len(self._evals)))))


@dataclass
class ExplanationBlock:
    title: str
    text: str
    mark: Optional[Mark] = None
    pending: bool = False


class ExplanationPanel(QTextBrowser):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(120)

    def show_blocks(self, blocks: Sequence[ExplanationBlock]) -> None:
        parts = []
        for block in blocks:
            color = MARK_COLORS[block.mark] if block.mark is not None else None
            badge = f' <span style="color:{color}; font-weight:600;">{block.mark.label}</span>' if color else ""
            parts.append(f"<p style='margin:0 0 2px 0;'><b>{html.escape(block.title)}</b>{badge}</p>")
            body = "Считаю…" if block.pending else block.text
            lines = "<br>".join(html.escape(line) for line in body.split("\n"))
            parts.append(f"<p style='margin:0 0 10px 0;'>{lines}</p>")
        self.setHtml("".join(parts))

    def show_text(self, text: str) -> None:
        self.setHtml("<br>".join(html.escape(line) for line in text.split("\n")))


class FenBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("FEN")
        label.setObjectName("muted")
        self.field = QLineEdit()
        self.field.setReadOnly(True)
        self.copy_button = QPushButton("Копировать")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self._copy)
        layout.addWidget(label)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.copy_button)

    def set_fen(self, fen: str) -> None:
        self.field.setText(fen)
        self.field.setCursorPosition(0)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.field.text())


class NavBar(QWidget):
    """|< < > >| buttons for stepping through a game."""

    def __init__(self, on_first, on_prev, on_next, on_last, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for text, handler, tip in (
            ("«", on_first, "К началу (Home)"),
            ("‹", on_prev, "Ход назад (←)"),
            ("›", on_next, "Ход вперёд (→)"),
            ("»", on_last, "К последнему ходу (End)"),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(handler)
            layout.addWidget(button)


def navigation_shortcuts(widget: QWidget, first, previous, following, last) -> None:
    """Arrow keys step through moves. Qt ignores shortcuts of hidden screens."""
    for key, handler in (
        (Qt.Key_Home, first),
        (Qt.Key_Left, previous),
        (Qt.Key_Right, following),
        (Qt.Key_End, last),
    ):
        QShortcut(QKeySequence(key), widget, activated=handler, context=Qt.WindowShortcut)
