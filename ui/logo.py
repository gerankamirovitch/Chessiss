"""The animated "Chessiss" title of the home screen.

The letters run in from the right one after another. Each one bumps into the letter in
front of it, both bounce, small chess pieces fly out of the hit, and springs pull the
letters together into the word. A light sweep and a small pulse finish it. The timer stops when
the word is still, so an idle home screen costs nothing.
"""
from __future__ import annotations

import math
import random

import chess
import chess.svg
from PySide6.QtCore import QByteArray, QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui.theme import current_theme

TEXT = "Chessiss"
STEP = 1 / 60
FONT_PX = 56
HEIGHT = 100
START_GAP = 0.17
RUN_SPEED = 1150.0
HOP = 9.0
STRIDE = 46.0
SPRING = 170.0
DAMPING = 11.0
BOUNCE_BACK = 0.3
PUSH_SHARE = 0.4
FINALE_SECONDS = 0.9
OVERLAP_PASSES = len(TEXT)
PIECE_SYMBOLS = "KQRBNP"  # white pieces have a black outline: visible on both themes
PIECE_PIXELS = 48  # cached picture, drawn much smaller, so it stays sharp at any scale
FALL = 520.0
LIGHT_OUTLINE = "#b9b9c2"


class _Letter:
    def __init__(self, path: QPainterPath, advance: float, start: float) -> None:
        self.path = path
        self.advance = advance
        self.start = start
        self.target = 0.0
        self.x = 0.0
        self.velocity = 0.0
        self.hop = 0.0
        self.squash = 0.0
        self.squash_velocity = 0.0
        self.state = "wait"  # wait, run, settle
        self.travelled = 0.0


class AnimatedLogo(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(TEXT)
        font = QFont(self.font())
        font.setPixelSize(FONT_PX)
        font.setWeight(QFont.Bold)
        metrics = QFontMetricsF(font)
        self._ascent = metrics.ascent()
        self._cap = metrics.capHeight()
        self.letters: list[_Letter] = []
        for index, char in enumerate(TEXT):
            path = QPainterPath()
            path.addText(0, 0, font, char)
            self.letters.append(_Letter(path, metrics.horizontalAdvance(char), index * START_GAP))
        self.word_width = sum(letter.advance for letter in self.letters)
        self.pieces: list[list] = []  # x, y, vx, vy, size, life, total life, angle, spin, symbol
        self._piece_pixmaps: dict[str, QPixmap] = {}
        self.hits = 0
        self.time = 0.0
        self.finale = -1.0  # seconds into the finale, -1 before it
        self.finished = True
        self._lag = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._place_targets()
        self._snap()

    def sizeHint(self) -> QSize:
        return QSize(round(self.word_width) + 80, HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.word_width) + 20, HEIGHT)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def baseline(self) -> float:
        return (HEIGHT + self._cap) / 2

    def _place_targets(self) -> None:
        x = (self.width() - self.word_width) / 2
        for letter in self.letters:
            letter.target = x
            x += letter.advance

    def _snap(self) -> None:
        for letter in self.letters:
            letter.x, letter.velocity, letter.hop, letter.squash, letter.squash_velocity = letter.target, 0.0, 0.0, 0.0, 0.0
            letter.state = "settle"

    def play(self) -> None:
        self._place_targets()
        for letter in self.letters:
            letter.x = self.width() + 20 + letter.advance
            letter.velocity = 0.0
            letter.hop = 0.0
            letter.squash = letter.squash_velocity = 0.0
            letter.state = "wait"
            letter.travelled = 0.0
        self.pieces.clear()
        self.hits = 0
        self.time = 0.0
        self.finale = -1.0
        self.finished = False
        self._lag = 0.0
        if self.isVisible():
            self._clock.start()
            self._timer.start()

    def stop(self) -> None:
        """Jumps to the end: the word in place, nothing moving."""
        self._timer.stop()
        self.pieces.clear()
        self._place_targets()
        self._snap()
        self.finale = -1.0
        self.finished = True
        self.update()

    def advance(self, seconds: float) -> None:
        self._lag += min(seconds, 0.25)
        while self._lag >= STEP and not self.finished:
            self._lag -= STEP
            self._step()

    # --- simulation ----------------------------------------------------------

    def _spawn(self, x: float, y: float, count: int, power: float) -> None:
        for _ in range(count):
            angle = random.uniform(-math.pi * 0.95, -math.pi * 0.05)
            speed = random.uniform(0.35, 1.0) * power
            life = random.uniform(0.6, 1.1)
            self.pieces.append([
                x, y + random.uniform(-8, 8), math.cos(angle) * speed, math.sin(angle) * speed,
                random.uniform(8.0, 13.0), life, life, random.uniform(0, 360), random.uniform(-540, 540),
                random.choice(PIECE_SYMBOLS),
            ])

    def _step(self) -> None:
        self.time += STEP
        letters = self.letters
        for index, letter in enumerate(letters):
            if letter.state == "wait" and self.time >= letter.start:
                letter.state = "run"
                letter.velocity = -RUN_SPEED
            if letter.state == "run":
                letter.x += letter.velocity * STEP
                letter.travelled += RUN_SPEED * STEP
                letter.hop = abs(math.sin(letter.travelled / STRIDE * math.pi)) * HOP
                ahead = letters[index - 1] if index else None
                if ahead is not None and ahead.state != "wait" and letter.x <= ahead.x + ahead.advance:
                    self._hit(ahead, letter)
                elif ahead is None and letter.x <= letter.target:
                    letter.state = "settle"  # the first letter skids past its place and springs back
                    letter.velocity *= 0.22
                    self._spawn(letter.x + letter.advance * 0.5, self.baseline(), 4, 90)
            elif letter.state == "settle":
                letter.velocity += (SPRING * (letter.target - letter.x) - DAMPING * letter.velocity) * STEP
                letter.x += letter.velocity * STEP
                letter.hop *= 0.7
            letter.squash_velocity += (-420 * letter.squash - 14 * letter.squash_velocity) * STEP
            letter.squash += letter.squash_velocity * STEP

        for _ in range(OVERLAP_PASSES):  # letters never overlap; a push can travel down the line
            for index in range(1, len(letters)):
                ahead, behind = letters[index - 1], letters[index]
                if behind.state == "settle" and ahead.state == "settle":
                    overlap = ahead.x + ahead.advance - behind.x
                    if overlap > 0:
                        ahead.x -= overlap / 2
                        behind.x += overlap / 2
                        if behind.velocity < ahead.velocity:
                            behind.velocity, ahead.velocity = ahead.velocity, behind.velocity

        for piece in self.pieces:
            piece[3] += FALL * STEP  # pieces are heavy: up from the hit, then down
            piece[2] *= 0.99
            piece[0] += piece[2] * STEP
            piece[1] += piece[3] * STEP
            piece[5] -= STEP
            piece[7] += piece[8] * STEP
        self.pieces = [piece for piece in self.pieces if piece[5] > 0]

        if self.finale < 0 and self._resting():
            self.finale = 0.0
            self._spawn(letters[0].target, self.baseline() - self._cap / 2, 5, 120)
            self._spawn(letters[-1].target + letters[-1].advance, self.baseline() - self._cap / 2, 5, 120)
        elif self.finale >= 0:
            self.finale += STEP
            if self.finale >= FINALE_SECONDS and not self.pieces:
                self._snap()
                self.finished = True

    def _hit(self, ahead: _Letter, letter: _Letter) -> None:
        impact = letter.velocity
        letter.x = ahead.x + ahead.advance
        ahead.velocity += impact * PUSH_SHARE
        if ahead.state != "settle":
            ahead.state = "settle"
        letter.velocity = -impact * BOUNCE_BACK
        letter.state = "settle"
        ahead.squash_velocity += 9.0
        letter.squash_velocity += 7.0
        self.hits += 1
        self._spawn(letter.x, self.baseline() - self._cap * 0.45 - letter.hop, 9, 260)

    def _resting(self) -> bool:
        return all(
            letter.state == "settle" and abs(letter.velocity) < 3 and abs(letter.x - letter.target) < 0.6
            and abs(letter.squash) < 0.01
            for letter in self.letters
        )

    def _tick(self) -> None:
        self.advance(self._clock.restart() / 1000.0)
        if self.finished:
            self._timer.stop()
        self.update()

    # --- events --------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        old = [letter.target for letter in self.letters]
        self._place_targets()
        for letter, before in zip(self.letters, old):
            letter.x += letter.target - before
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        if not self.finished:
            self._clock.start()
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        if not self.finished:
            self.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.play()
        super().mousePressEvent(event)

    # --- drawing -------------------------------------------------------------

    def _letter_transform(self, letter: _Letter) -> QTransform:
        squash = max(min(letter.squash, 0.35), -0.35)
        base_x = letter.x + letter.advance / 2
        transform = QTransform()
        transform.translate(base_x, self.baseline() - letter.hop)
        if self.finale >= 0:
            pulse = 1 + 0.06 * math.sin(min(self.finale / 0.45, 1.0) * math.pi)
            transform.scale(pulse, pulse)
        transform.scale(1 - squash, 1 + squash * 0.6)
        transform.translate(-letter.advance / 2, 0)
        return transform

    def _piece_pixmap(self, symbol: str) -> QPixmap:
        pixmap = self._piece_pixmaps.get(symbol)
        if pixmap is None:
            pixmap = QPixmap(PIECE_PIXELS, PIECE_PIXELS)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            svg = chess.svg.piece(chess.Piece.from_symbol(symbol)).encode("utf-8")
            QSvgRenderer(QByteArray(svg)).render(painter, QRectF(0, 0, PIECE_PIXELS, PIECE_PIXELS))
            painter.end()
            self._piece_pixmaps[symbol] = pixmap
        return pixmap

    def paintEvent(self, event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        word = QPainterPath()
        for letter in self.letters:
            if letter.x < self.width() + letter.advance:
                word.addPath(self._letter_transform(letter).map(letter.path))
        light = not theme.dark
        shadow = QColor("#000000")
        shadow.setAlpha(55 if light else 60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawPath(word.translated(0, 3))
        # White letters; on a light window a thin grey edge keeps them readable.
        painter.setPen(QPen(QColor(LIGHT_OUTLINE), 1.2) if light else Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(word)

        if 0 <= self.finale < FINALE_SECONDS:
            left = (self.width() - self.word_width) / 2
            sweep = left - 60 + (self.word_width + 120) * (self.finale / FINALE_SECONDS)
            shine = QLinearGradient(QPointF(sweep - 40, 0), QPointF(sweep + 40, 0))
            tint = QColor(theme.accent)
            tint.setAlpha(0)
            shine.setColorAt(0, tint)
            tint.setAlpha(120)
            shine.setColorAt(0.5, tint)
            tint.setAlpha(0)
            shine.setColorAt(1, tint)
            painter.save()
            painter.setClipPath(word)
            painter.fillRect(self.rect(), shine)
            painter.restore()

        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        source = QRectF(0, 0, PIECE_PIXELS, PIECE_PIXELS)
        for x, y, _, _, size, life, total, angle, _, symbol in self.pieces:
            painter.save()
            painter.setOpacity(min(1.0, life / total * 2.5))
            painter.translate(x, y)
            painter.rotate(angle)
            painter.drawPixmap(QRectF(-size / 2, -size / 2, size, size), self._piece_pixmap(symbol), source)
            painter.restore()
        painter.end()
