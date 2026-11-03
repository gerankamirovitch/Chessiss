"""The window background of the liquid glass theme: soft colored light behind frosted
surfaces. It is painted once per window size into a picture, so a repaint costs one copy
of that picture and nothing moves on its own."""
from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui.theme import Theme

GRAIN_SIZE = 128
GRAIN_ALPHA = 9  # out of 255: a hint of grain, like frosted glass
# (x, y, radius) as shares of the window, and the color of each patch of light
DARK_LIGHTS = ((0.12, 0.10, 0.65, "#5b3df5"), (0.88, 0.20, 0.60, "#0a84ff"), (0.70, 0.95, 0.70, "#ff4f9a"), (0.10, 0.90, 0.50, "#18b6a0"))
LIGHT_LIGHTS = ((0.12, 0.10, 0.65, "#b9a6ff"), (0.88, 0.20, 0.60, "#8ec5ff"), (0.70, 0.95, 0.70, "#ffb3d4"), (0.10, 0.90, 0.50, "#9be8d8"))


def _grain() -> QImage:
    rng = random.Random(7)  # the same grain on every start
    image = QImage(GRAIN_SIZE, GRAIN_SIZE, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    for y in range(GRAIN_SIZE):
        for x in range(GRAIN_SIZE):
            value = rng.randrange(256)
            alpha = rng.randrange(GRAIN_ALPHA + 1)
            image.setPixelColor(x, y, QColor(value, value, value, alpha))
    return image


class Backdrop(QWidget):
    """Holds the screens. Paints the glass backdrop when the theme asks for it and is
    invisible otherwise."""

    _grain_image: Optional[QImage] = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme: Optional[Theme] = None
        self._picture: Optional[QPixmap] = None
        self._key: Optional[tuple] = None

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._picture = None
        self.update()

    def picture(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        key = (self.width(), self.height(), ratio, self._theme)
        if self._picture is None or key != self._key:
            self._picture = self._paint_picture(QSize(self.width(), self.height()), ratio)
            self._key = key
        return self._picture

    def _paint_picture(self, size: QSize, ratio: float) -> QPixmap:
        theme = self._theme
        pixmap = QPixmap(size * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(theme.window))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = size.width(), size.height()
        longest = max(width, height, 1)
        for x, y, radius, color in DARK_LIGHTS if theme.dark else LIGHT_LIGHTS:
            center = QPointF(x * width, y * height)
            gradient = QRadialGradient(center, radius * longest)
            inner = QColor(color)
            inner.setAlpha(150 if theme.dark else 170)
            outer = QColor(color)
            outer.setAlpha(0)
            gradient.setColorAt(0.0, inner)
            gradient.setColorAt(1.0, outer)
            painter.fillRect(0, 0, width, height, gradient)
        if Backdrop._grain_image is None:
            Backdrop._grain_image = _grain()
        for top in range(0, height, GRAIN_SIZE):
            for left in range(0, width, GRAIN_SIZE):
                painter.drawImage(left, top, Backdrop._grain_image)
        painter.end()
        return pixmap

    def paintEvent(self, event) -> None:
        if self._theme is None or not self._theme.glass:
            return
        painter = QPainter(self)
        rect = event.rect()
        ratio = self.devicePixelRatioF()
        source = QRectF(rect.x() * ratio, rect.y() * ratio, rect.width() * ratio, rect.height() * ratio)
        painter.drawPixmap(QPointF(rect.topLeft()), self.picture(), source)
        painter.end()
