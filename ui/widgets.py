"""Widgets shared between screens: move list, evaluation graph, explanation chat, ID button."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Optional, Sequence

import chess
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.explain import Mark
from core.i18n import t
from core.pgn_io import display_san
from ui.theme import LIGHT, MARK_COLORS, Theme, current_theme


def header_bar(title: str, on_back) -> tuple[QWidget, QLabel]:
    bar = QWidget()
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(0, 0, 0, 0)
    back = QPushButton(t("← Меню"))
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
        self.setHorizontalHeaderLabels(["", t("Белые"), t("Чёрные")])
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
        item = QTableWidgetItem(display_san(san))
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


ME = "me"
THEM = "them"
SYSTEM = ""

MY_BUBBLE = "#ffffff"
MY_TEXT = "#1d1d1f"
THEIR_BUBBLE = "#3a3a3c"
THEIR_TEXT = "#f5f5f7"
BUBBLE_RADIUS = 18.0
TAIL = 8
BUBBLE_SHARE = 0.84
APPEAR_MS = 220


@dataclass
class ExplanationBlock:
    title: str
    text: str
    mark: Optional[Mark] = None
    pending: bool = False
    side: str = SYSTEM  # ME: right, white; THEM: left, dark; SYSTEM: a note in the middle

    def plain(self) -> str:
        badge = f" {self.mark.label}" if self.mark is not None else ""
        return f"{self.title}{badge}\n{t('Считаю…') if self.pending else self.text}"


class ChatBubble(QFrame):
    """One message. Strongly rounded; its tail at the bottom points to the speaker's side."""

    def __init__(self, block: ExplanationBlock, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.block = block
        self.side = block.side
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        tail_left = TAIL if self.side == THEM else 0
        tail_right = TAIL if self.side == ME else 0
        layout.setContentsMargins(14 + tail_left, 9, 14 + tail_right, 10)
        layout.addWidget(self.label)
        self.refresh()

    def text_color(self) -> str:
        if self.side == ME:
            return MY_TEXT
        if self.side == THEM:
            return THEIR_TEXT
        return current_theme().text_muted

    def refresh(self) -> None:
        block = self.block
        color = MARK_COLORS[block.mark] if block.mark is not None else None
        badge = f' <span style="color:{color}; font-weight:600;">{block.mark.label}</span>' if color else ""
        body = t("Считаю…") if block.pending else block.text
        lines = "<br>".join(html.escape(line) for line in body.split("\n"))
        title = f"<b>{html.escape(block.title)}</b>{badge}<br>" if block.title else ""
        align = "center" if self.side == SYSTEM else "left"
        self.label.setStyleSheet(f"color: {self.text_color()}; background: transparent;")
        self.label.setText(f'<div style="text-align:{align};">{title}{lines}</div>')

    def fit_text(self, max_width: int) -> None:
        """As wide as the longest line needs, up to max_width: short messages stay small,
        long ones use the whole width before they wrap."""
        self.ensurePolished()
        self.label.ensurePolished()  # the stylesheet font, not the default one
        margins = self.layout().contentsMargins()
        room = max_width - margins.left() - margins.right()
        metrics = self.label.fontMetrics()
        body = t("Считаю…") if self.block.pending else self.block.text
        lines = body.split("\n") + [self.block.title + (f" {self.block.mark.label}" if self.block.mark else "")]
        natural = max(metrics.horizontalAdvance(line) for line in lines) * 1.08 + 4  # bold title
        width = max(40, int(min(room, natural)))
        # A wrapped label in a layout often gets a height for some other width, and the
        # rows overlap. Here the size is fixed from the real width.
        height = self.label.heightForWidth(width)
        if height <= 0:
            height = self.label.sizeHint().height()
        self.label.setFixedSize(width, height)
        self.setFixedSize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def bubble_path(self) -> QPainterPath:
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.side == ME:
            body = rect.adjusted(0, 0, -TAIL, 0)
        elif self.side == THEM:
            body = rect.adjusted(TAIL, 0, 0, 0)
        else:
            body = rect
        path = QPainterPath()
        path.addRoundedRect(body, BUBBLE_RADIUS, BUBBLE_RADIUS)
        if self.side in (ME, THEM):
            direction = 1 if self.side == ME else -1
            edge = body.right() if self.side == ME else body.left()
            bottom = body.bottom()
            tail = QPainterPath(QPointF(edge - direction * 16, bottom - 20))
            tail.quadTo(QPointF(edge - direction * 2, bottom - 8), QPointF(edge + direction * TAIL, bottom))
            tail.quadTo(QPointF(edge - direction * 6, bottom + 0.5), QPointF(edge - direction * 22, bottom - 3))
            tail.closeSubpath()
            path = path.united(tail)
        return path

    def paintEvent(self, event) -> None:
        if self.side == SYSTEM:
            return
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = self.bubble_path()
        if self.side == ME:
            border = QColor(theme.border) if not theme.dark else QColor(MY_BUBBLE)
            painter.setPen(QPen(border, 1))
            painter.setBrush(QColor(MY_BUBBLE))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(THEIR_BUBBLE))
        painter.drawPath(path)
        painter.end()


class ExplanationPanel(QScrollArea):
    """The coach panel as a messenger: the player's moves on the right in white bubbles,
    the opponent's on the left in dark ones. New messages fade in; the view follows the
    newest one."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("chat")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(120)
        self._content = QWidget()
        self._content.setObjectName("chatContent")
        self._rows = QVBoxLayout(self._content)
        self._rows.setContentsMargins(10, 10, 10, 10)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        self.setWidget(self._content)
        self.bubbles: list[ChatBubble] = []
        self._row_layouts: list[QHBoxLayout] = []
        self._shown: list[ExplanationBlock] = []
        self._animations: list[QPropertyAnimation] = []

    def toPlainText(self) -> str:
        return "\n".join(block.plain() for block in self._shown)

    def show_blocks(self, blocks: Sequence[ExplanationBlock]) -> None:
        blocks = list(blocks)
        if blocks == self._shown:
            return
        before = [(b.side, b.title, b.text, b.mark) for b in self._shown]
        self._clear()
        self._shown = blocks
        for block in blocks:
            bubble = ChatBubble(block)

            bubble.fit_text(self._bubble_width())
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            if block.side != ME:
                row.addWidget(bubble)
            if block.side in (ME, SYSTEM):
                row.insertStretch(0, 1)
            if block.side in (THEM, SYSTEM):
                row.addStretch(1)
            if block.side == ME:
                row.addWidget(bubble)
            self._rows.insertLayout(self._rows.count() - 1, row)
            self._row_layouts.append(row)
            self.bubbles.append(bubble)
            if (block.side, block.title, block.text, block.mark) not in before:
                self._fade_in(bubble)
        QTimer.singleShot(0, self._scroll_to_end)

    def show_text(self, text: str) -> None:
        self.show_blocks([ExplanationBlock("", text)])

    def _bubble_width(self) -> int:
        """From the panel's own width with room kept for the scroll bar, so the bubbles
        do not change size when the bar appears."""
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        inner = self.width() - 2 * self.frameWidth() - bar - 20
        return max(160, int(inner * BUBBLE_SHARE))

    def _clear(self) -> None:
        for animation in self._animations:
            animation.stop()
        self._animations = []
        for row in self._row_layouts:
            self._rows.removeItem(row)
            row.deleteLater()
        for bubble in self.bubbles:
            bubble.hide()  # gone at once; the object itself goes with the next event loop pass
            bubble.setParent(None)
            bubble.deleteLater()
        self._row_layouts = []
        self.bubbles = []

    def _fade_in(self, bubble: ChatBubble) -> None:
        effect = QGraphicsOpacityEffect(bubble)
        effect.setOpacity(0.0)
        bubble.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(APPEAR_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        # The effect goes away at the end: a still bubble is drawn as cheaply as any widget.
        animation.finished.connect(lambda: bubble.setGraphicsEffect(None))
        animation.start()
        self._animations.append(animation)

    def _scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self._bubble_width()
        for bubble in self.bubbles:
            bubble.fit_text(width)


class FenBar(QWidget):
    """One button under the board, bottom left: it copies the position's FEN, its ID."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fen = ""
        self.copy_button = QPushButton(t("Копировать ID"))
        self.copy_button.setAutoDefault(False)
        self.copy_button.setToolTip(t("Копирует FEN позиции в буфер обмена"))
        self.copy_button.clicked.connect(self._copy)
        layout.addWidget(self.copy_button)
        layout.addStretch(1)

    def set_fen(self, fen: str) -> None:
        self.fen = fen

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.fen)


class NavBar(QWidget):
    """|< < > >| buttons for stepping through a game."""

    def __init__(self, on_first, on_prev, on_next, on_last, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for text, handler, tip in (
            ("«", on_first, t("К началу (Home)")),
            ("‹", on_prev, t("Ход назад (←)")),
            ("›", on_next, t("Ход вперёд (→)")),
            ("»", on_last, t("К последнему ходу (End)")),
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
