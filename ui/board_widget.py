"""The chess board: painting, click-click and drag-and-drop input, move animation.
Knows nothing about the rules. Legal targets come from a controller object
(core.game.GameSession or core.puzzles.PuzzleSession)."""
from __future__ import annotations

from typing import Iterable, Optional, Protocol

import chess
import chess.svg
from PySide6.QtCore import QByteArray, QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui.theme import LIGHT, Theme

ANIMATION_MS = 160
DRAG_THRESHOLD_PX = 4
PROMOTION_CHOICES = (chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP)

_SVG = {
    symbol: QByteArray(chess.svg.piece(chess.Piece.from_symbol(symbol)).encode("utf-8"))
    for symbol in "PNBRQKpnbrqk"
}


class MoveController(Protocol):
    def legal_targets(self, square: int) -> list[int]: ...
    def needs_promotion(self, from_square: int, to_square: int) -> bool: ...


class BoardWidget(QWidget):
    moveAttempted = Signal(int, int, int)  # from, to, promotion piece type or 0

    def __init__(self, theme: Theme = LIGHT, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.ClickFocus)

        self._theme = theme
        self._controller: Optional[MoveController] = None
        self._pieces: dict[int, chess.Piece] = chess.Board().piece_map()
        self._flipped = False
        self._interactive: set[bool] = set()
        self._last_move: Optional[chess.Move] = None
        self._check_square: Optional[int] = None
        self._arrows: list[tuple[int, int, float]] = []
        self._marked: dict[int, str] = {}

        self._selected: Optional[int] = None
        self._targets: list[int] = []
        self._press_pos: Optional[QPointF] = None
        self._press_was_selected = False
        self._dragging = False
        self._drag_pos = QPointF()
        self._dropped = False
        self._promotion: Optional[tuple[int, int, bool]] = None

        self._background: Optional[QPixmap] = None
        self._background_key: Optional[tuple] = None
        self._piece_cache: dict[str, QPixmap] = {}
        self._piece_cache_key: Optional[tuple[int, float]] = None

        self._moving: list[tuple[chess.Piece, int, int]] = []
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(lambda _: self.update())
        self._animation.finished.connect(self._on_animation_finished)

    # --- public API ----------------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._background_key = None
        self.update()

    def set_controller(self, controller: Optional[MoveController]) -> None:
        self._controller = controller
        self.clear_selection()

    def set_interactive(self, colors: Iterable[bool]) -> None:
        """Colors the user may move now. Empty means read-only."""
        self._interactive = set(colors)
        self.clear_selection()

    def set_position(self, board: chess.Board, last_move: Optional[chess.Move] = None, animate: bool = False) -> None:
        previous = self._pieces
        self._pieces = board.piece_map()
        self._last_move = last_move
        self._check_square = board.king(board.turn) if board.is_check() else None
        self.clear_selection()

        self._animation.stop()
        self._moving = []
        if animate and last_move is not None and not self._dropped:
            self._moving = self._moved_pieces(previous, last_move)
            if self._moving:
                self._animation.start()
        self._dropped = False
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        if flipped != self._flipped:
            self._flipped = flipped
            self._background_key = None
            self.update()

    @property
    def flipped(self) -> bool:
        return self._flipped

    def set_arrows(self, arrows: Iterable[tuple[int, int, float]]) -> None:
        """(from, to, opacity) triples."""
        self._arrows = list(arrows)
        self.update()

    def set_marked_squares(self, marked: dict[int, str]) -> None:
        self._marked = dict(marked)
        self.update()

    def clear_selection(self) -> None:
        self._selected = None
        self._targets = []
        self._dragging = False
        self._press_pos = None
        self._promotion = None
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 640)

    # --- geometry ------------------------------------------------------------

    def _square_size(self) -> int:
        return max(1, min(self.width(), self.height()) // 8)

    def _origin(self) -> tuple[int, int]:
        size = self._square_size() * 8
        return (self.width() - size) // 2, (self.height() - size) // 2

    def square_rect(self, square: int) -> QRect:
        size = self._square_size()
        x0, y0 = self._origin()
        file, rank = chess.square_file(square), chess.square_rank(square)
        column = 7 - file if self._flipped else file
        row = rank if self._flipped else 7 - rank
        return QRect(x0 + column * size, y0 + row * size, size, size)

    def square_at(self, pos: QPointF) -> Optional[int]:
        size = self._square_size()
        x0, y0 = self._origin()
        column = int((pos.x() - x0) // size)
        row = int((pos.y() - y0) // size)
        if not (0 <= column < 8 and 0 <= row < 8):
            return None
        file = 7 - column if self._flipped else column
        rank = row if self._flipped else 7 - row
        return chess.square(file, rank)

    # --- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), self.palette().window())
        painter.drawPixmap(self._origin()[0], self._origin()[1], self._background_pixmap())

        self._paint_square_highlights(painter)
        self._paint_pieces(painter)
        self._paint_targets(painter)
        self._paint_arrows(painter)
        if self._dragging and self._selected is not None:
            self._paint_dragged_piece(painter)
        if self._promotion is not None:
            self._paint_promotion(painter)
        painter.end()

    def _background_pixmap(self) -> QPixmap:
        size = self._square_size()
        ratio = self.devicePixelRatioF()
        key = (size, ratio, self._flipped, self._theme.name)
        if self._background is not None and key == self._background_key:
            return self._background
        pixmap = QPixmap(QSize(size * 8, size * 8) * ratio)
        pixmap.setDevicePixelRatio(ratio)
        painter = QPainter(pixmap)
        light, dark = QColor(self._theme.board_light), QColor(self._theme.board_dark)
        font = QFont(self.font())
        font.setPixelSize(max(9, size // 6))
        font.setBold(True)
        painter.setFont(font)
        for square in chess.SQUARES:
            file, rank = chess.square_file(square), chess.square_rank(square)
            column = 7 - file if self._flipped else file
            row = rank if self._flipped else 7 - rank
            is_light = (file + rank) % 2 == 1
            rect = QRect(column * size, row * size, size, size)
            painter.fillRect(rect, light if is_light else dark)
            painter.setPen(dark if is_light else light)
            inset = rect.adjusted(3, 2, -3, -2)
            if row == 7:
                painter.drawText(inset, Qt.AlignRight | Qt.AlignBottom, chess.FILE_NAMES[file])
            if column == 0:
                painter.drawText(inset, Qt.AlignLeft | Qt.AlignTop, chess.RANK_NAMES[rank])
        painter.end()
        self._background, self._background_key = pixmap, key
        return pixmap

    def _piece_pixmap(self, symbol: str) -> QPixmap:
        size = self._square_size()
        ratio = self.devicePixelRatioF()
        key = (size, ratio)
        if key != self._piece_cache_key:
            self._piece_cache = {}
            self._piece_cache_key = key
        cached = self._piece_cache.get(symbol)
        if cached is not None:
            return cached
        pixels = int(size * ratio)
        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(_SVG[symbol]).render(painter, QRectF(0, 0, pixels, pixels))
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        self._piece_cache[symbol] = pixmap
        return pixmap

    def _paint_square_highlights(self, painter: QPainter) -> None:
        if self._last_move is not None:
            color = _qcolor(self._theme.last_move)
            painter.fillRect(self.square_rect(self._last_move.from_square), color)
            painter.fillRect(self.square_rect(self._last_move.to_square), color)
        if self._selected is not None:
            painter.fillRect(self.square_rect(self._selected), _qcolor(self._theme.selected))
        for square, color in self._marked.items():
            painter.fillRect(self.square_rect(square), _qcolor(color))
        if self._check_square is not None:
            rect = self.square_rect(self._check_square)
            gradient = QRadialGradient(QPointF(rect.center()), rect.width() * 0.7)
            gradient.setColorAt(0.0, QColor(self._theme.check))
            transparent = QColor(self._theme.check)
            transparent.setAlpha(0)
            gradient.setColorAt(1.0, transparent)
            painter.fillRect(rect, QBrush(gradient))

    def _paint_pieces(self, painter: QPainter) -> None:
        animating = self._animation.state() == QVariantAnimation.Running and self._moving
        moving_to = {to for _, _, to in self._moving} if animating else set()
        for square, piece in self._pieces.items():
            if square in moving_to:
                continue
            if self._dragging and square == self._selected:
                continue
            painter.drawPixmap(self.square_rect(square).topLeft(), self._piece_pixmap(piece.symbol()))
        if animating:
            progress = float(self._animation.currentValue() or 0.0)
            for piece, start, end in self._moving:
                a, b = self.square_rect(start).topLeft(), self.square_rect(end).topLeft()
                x = a.x() + (b.x() - a.x()) * progress
                y = a.y() + (b.y() - a.y()) * progress
                painter.drawPixmap(QPointF(x, y), self._piece_pixmap(piece.symbol()))

    def _paint_targets(self, painter: QPainter) -> None:
        if not self._targets:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        color = _qcolor(self._theme.target)
        for square in self._targets:
            rect = QRectF(self.square_rect(square))
            if square in self._pieces:
                pen = QPen(color, rect.width() * 0.08)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                inset = rect.width() * 0.06
                painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                radius = rect.width() * 0.16
                painter.drawEllipse(rect.center(), radius, radius)
        painter.restore()

    def _paint_arrows(self, painter: QPainter) -> None:
        if not self._arrows:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        base = _qcolor(self._theme.arrow)
        for start, end, opacity in self._arrows:
            color = QColor(base)
            color.setAlphaF(base.alphaF() * opacity)
            a = QPointF(self.square_rect(start).center())
            b = QPointF(self.square_rect(end).center())
            dx, dy = b.x() - a.x(), b.y() - a.y()
            length = (dx * dx + dy * dy) ** 0.5 or 1.0
            ux, uy = dx / length, dy / length
            size = float(self._square_size())
            width, head = size * 0.14, size * 0.38
            neck = QPointF(b.x() - ux * head, b.y() - uy * head)
            painter.setPen(QPen(color, width, Qt.SolidLine, Qt.FlatCap))
            painter.drawLine(a, neck)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            nx, ny = -uy * head * 0.55, ux * head * 0.55
            painter.drawPolygon(QPolygonF([
                b,
                QPointF(neck.x() + nx, neck.y() + ny),
                QPointF(neck.x() - nx, neck.y() - ny),
            ]))
        painter.restore()

    def _paint_dragged_piece(self, painter: QPainter) -> None:
        piece = self._pieces.get(self._selected)
        if piece is None:
            return
        size = self._square_size()
        painter.drawPixmap(
            QPointF(self._drag_pos.x() - size / 2, self._drag_pos.y() - size / 2),
            self._piece_pixmap(piece.symbol()),
        )

    def _promotion_rects(self) -> list[tuple[int, QRect]]:
        assert self._promotion is not None
        _, to_square, _ = self._promotion
        target = self.square_rect(to_square)
        size = self._square_size()
        x0, y0 = self._origin()
        downward = target.top() == y0
        rects = []
        for index, piece_type in enumerate(PROMOTION_CHOICES):
            top = y0 + index * size if downward else y0 + (7 - index) * size
            rects.append((piece_type, QRect(target.left(), top, size, size)))
        return rects

    def _paint_promotion(self, painter: QPainter) -> None:
        assert self._promotion is not None
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        _, _, color = self._promotion
        for piece_type, rect in self._promotion_rects():
            painter.fillRect(rect, QColor(self._theme.surface))
            painter.drawPixmap(rect.topLeft(), self._piece_pixmap(chess.Piece(piece_type, color).symbol()))

    # --- animation -----------------------------------------------------------

    def _moved_pieces(self, previous: dict[int, chess.Piece], move: chess.Move) -> list[tuple[chess.Piece, int, int]]:
        piece = self._pieces.get(move.to_square) or previous.get(move.from_square)
        if piece is None:
            return []
        moving = [(piece, move.from_square, move.to_square)]
        origin = previous.get(move.from_square)
        if origin is not None and origin.piece_type == chess.KING:
            distance = chess.square_file(move.to_square) - chess.square_file(move.from_square)
            if abs(distance) == 2:
                rank = chess.square_rank(move.from_square)
                rook_from = chess.square(7 if distance > 0 else 0, rank)
                rook_to = chess.square(5 if distance > 0 else 3, rank)
                rook = self._pieces.get(rook_to)
                if rook is not None:
                    moving.append((rook, rook_from, rook_to))
        return moving

    def _on_animation_finished(self) -> None:
        self._moving = []
        self.update()

    # --- input ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() != Qt.LeftButton:
            self.clear_selection()
            return
        if self._promotion is not None:
            self._press_promotion(pos)
            return
        if self._controller is None or not self._interactive:
            return
        square = self.square_at(pos)
        if square is None:
            self.clear_selection()
            return
        if self._selected is not None and square in self._targets:
            self._attempt(self._selected, square, dragged=False)
            return
        piece = self._pieces.get(square)
        if piece is not None and piece.color in self._interactive:
            self._press_was_selected = self._selected == square
            self._selected = square
            self._targets = self._controller.legal_targets(square)
            self._press_pos = pos
            self._drag_pos = pos
            self.update()
        else:
            self.clear_selection()

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or self._selected is None:
            return
        pos = event.position()
        if not self._dragging:
            delta = pos - self._press_pos
            if abs(delta.x()) + abs(delta.y()) < DRAG_THRESHOLD_PX:
                return
            self._dragging = True
        self._drag_pos = pos
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._press_pos is None:
            return
        self._press_pos = None
        if not self._dragging:
            if self._press_was_selected:
                self.clear_selection()
            return
        self._dragging = False
        square = self.square_at(event.position())
        if square is not None and self._selected is not None and square in self._targets:
            self._attempt(self._selected, square, dragged=True)
        else:
            self.update()

    def _attempt(self, from_square: int, to_square: int, dragged: bool) -> None:
        controller = self._controller
        piece = self._pieces.get(from_square)
        if controller is not None and piece is not None and controller.needs_promotion(from_square, to_square):
            self._selected = from_square
            self._targets = []
            self._press_pos = None
            self._promotion = (from_square, to_square, piece.color)
            self._dropped = dragged
            self.update()
            return
        self._dropped = dragged
        self.clear_selection()
        self.moveAttempted.emit(from_square, to_square, 0)

    def _press_promotion(self, pos: QPointF) -> None:
        from_square, to_square, _ = self._promotion
        choice = 0
        for piece_type, rect in self._promotion_rects():
            if rect.contains(pos.toPoint()):
                choice = piece_type
                break
        self.clear_selection()
        if choice:
            self.moveAttempted.emit(from_square, to_square, choice)


def _qcolor(value: str) -> QColor:
    """Accepts #rrggbbaa, which QColor would read as #aarrggbb."""
    if len(value) == 9:
        color = QColor(value[:7])
        color.setAlpha(int(value[7:9], 16))
        return color
    return QColor(value)
