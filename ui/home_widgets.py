"""Home screen pieces: icon buttons with a sliding label and the statistics card."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.i18n import t
from storage.db import PlayerStats
from ui.theme import current_theme

ICON_BUTTON_SIZE = 44
ICON_SIZE = 22.0
LABEL_GAP = 14
SLIDE_MS = 220
DONUT_SIZE = 124
DONUT_WIDTH = 15
DONUT_MS = 900
SECTOR_GAP_DEGREES = 2.5


def _draw_gear(painter: QPainter, center: QPointF, size: float) -> None:
    radius = size / 2
    painter.drawEllipse(center, radius * 0.62, radius * 0.62)
    painter.drawEllipse(center, radius * 0.24, radius * 0.24)
    for tooth in range(8):
        angle = math.radians(tooth * 45)
        direction = QPointF(math.cos(angle), math.sin(angle))
        painter.drawLine(center + direction * radius * 0.62, center + direction * radius)


def _draw_history(painter: QPainter, center: QPointF, size: float) -> None:
    radius = size / 2 * 0.86
    circle = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    painter.drawArc(circle, 200 * 16, -310 * 16)  # clockwise, open at the lower left
    tip = center + QPointF(math.cos(math.radians(200)) * radius, -math.sin(math.radians(200)) * radius)
    painter.drawLine(tip, tip + QPointF(-radius * 0.34, -radius * 0.28))
    painter.drawLine(tip, tip + QPointF(radius * 0.36, -radius * 0.24))
    painter.drawLine(center, center + QPointF(0, -radius * 0.56))
    painter.drawLine(center, center + QPointF(radius * 0.42, radius * 0.24))


_ICONS = {"settings": _draw_gear, "history": _draw_history}


class ExpandingIconButton(QPushButton):
    """An icon whose label slides out on hover. The icon keeps its place at the right
    edge and the button grows to the left, pushing the neighbour in the layout aside."""

    def __init__(self, icon: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.label = label
        self._draw_icon = _ICONS[icon]
        self._progress = 0.0
        self.setObjectName("iconButton")
        self.setAccessibleName(label)
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(ICON_BUTTON_SIZE)
        self.setFixedWidth(ICON_BUTTON_SIZE)
        self._slide = QVariantAnimation(self)
        self._slide.setDuration(SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(self._set_progress)

    @property
    def progress(self) -> float:
        return self._progress

    def _full_label_width(self) -> int:
        return self.fontMetrics().horizontalAdvance(self.label) + LABEL_GAP

    def _set_progress(self, progress: float) -> None:
        self._progress = progress
        self.setFixedWidth(ICON_BUTTON_SIZE + round(self._full_label_width() * progress))
        self.update()

    def _slide_to(self, target: float) -> None:
        self._slide.stop()
        self._slide.setStartValue(self._progress)
        self._slide.setEndValue(target)
        self._slide.start()

    def enterEvent(self, event) -> None:
        self._slide_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._slide_to(0.0)
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._slide.stop()  # the leave event never comes when a click opens another screen
        self._set_progress(0.0)
        super().hideEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), ICON_BUTTON_SIZE)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self.palette().buttonText().color()
        icon_area = QRectF(self.width() - ICON_BUTTON_SIZE, 0, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
        if self._progress > 0:
            painter.setOpacity(self._progress)
            painter.setPen(color)
            painter.drawText(
                QRectF(0, 0, self.width() - ICON_BUTTON_SIZE + LABEL_GAP / 2, ICON_BUTTON_SIZE),
                Qt.AlignRight | Qt.AlignVCenter,
                self.label,
            )
            painter.setOpacity(1.0)
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        self._draw_icon(painter, icon_area.center(), ICON_SIZE)
        painter.end()


class DonutChart(QWidget):
    """Wins, draws and losses as a ring that draws itself clockwise from the top."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stats = PlayerStats(0, 0, 0)
        self._progress = 1.0
        self.setFixedSize(DONUT_SIZE, DONUT_SIZE)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(DONUT_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._set_progress)

    @property
    def progress(self) -> float:
        return self._progress

    def _set_progress(self, progress: float) -> None:
        self._progress = progress
        self.update()

    def set_stats(self, stats: PlayerStats) -> None:
        self._stats = stats
        self.update()

    def play(self) -> None:
        self._animation.stop()
        self._progress = 0.0
        self._animation.start()

    def paintEvent(self, event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        inset = DONUT_WIDTH / 2 + 1
        ring = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        pen = QPen(QColor(theme.surface_alt), DONUT_WIDTH)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawEllipse(ring)

        stats = self._stats
        total = stats.total
        if total:
            drawn_until = 360.0 * self._progress
            start = 0.0
            for count, color in ((stats.wins, theme.win), (stats.draws, theme.draw), (stats.losses, theme.loss)):
                if not count:
                    continue
                sweep = 360.0 * count / total
                gap = SECTOR_GAP_DEGREES if count != total else 0.0
                visible = min(start + sweep - gap, drawn_until) - start
                if visible > 0:
                    pen.setColor(QColor(color))
                    painter.setPen(pen)
                    # Qt counts angles counter-clockwise from 3 o'clock, in 1/16 of a degree.
                    painter.drawArc(ring, round((90 - start) * 16), round(-visible * 16))
                start += sweep

        painter.setPen(QColor(theme.text))
        font = painter.font()
        font.setPointSizeF(19)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        share = round(100 * stats.wins / total * self._progress) if total else 0
        center_text = f"{share}%" if total else "—"
        painter.drawText(self.rect().adjusted(0, -10, 0, -10), Qt.AlignCenter, center_text)
        font.setPointSizeF(9)
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(theme.text_muted))
        painter.drawText(self.rect().adjusted(0, 22, 0, 22), Qt.AlignCenter, t("Победы"))
        painter.end()


class _LegendDot(QWidget):
    def __init__(self, color_name: str, parent=None) -> None:
        super().__init__(parent)
        self._color_name = color_name
        self.setFixedSize(10, 10)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(QRectF(self.rect()))
        painter.fillPath(path, QColor(getattr(current_theme(), self._color_name)))
        painter.end()


class StatsCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        title = QLabel(t("Статистика"))
        title.setObjectName("status")
        self.caption = QLabel(t("Пока нет партий"))
        self.caption.setObjectName("muted")
        self.chart = DonutChart()
        self.counts: dict[str, QLabel] = {}
        self.shares: dict[str, QLabel] = {}

        legend = QGridLayout()
        legend.setHorizontalSpacing(8)
        legend.setVerticalSpacing(10)
        for row, (key, name, color) in enumerate((
            ("wins", t("Победы"), "win"),
            ("draws", t("Ничьи"), "draw"),
            ("losses", t("Поражения"), "loss"),
        )):
            count, share = QLabel("0"), QLabel("0%")
            count.setObjectName("status")
            share.setObjectName("muted")
            count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            share.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.counts[key], self.shares[key] = count, share
            legend.addWidget(_LegendDot(color), row, 0)
            legend.addWidget(QLabel(name), row, 1)
            legend.addWidget(count, row, 2)
            legend.addWidget(share, row, 3)
        legend.setColumnStretch(1, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.chart)
        body.addLayout(legend, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(self.caption)
        layout.addStretch(1)
        layout.addLayout(body)
        layout.addStretch(1)

    def set_stats(self, stats: PlayerStats) -> None:
        self.chart.set_stats(stats)
        self.caption.setVisible(not stats.total)
        for key, count in (("wins", stats.wins), ("draws", stats.draws), ("losses", stats.losses)):
            self.counts[key].setText(str(count))
            self.shares[key].setText(f"{round(100 * count / stats.total) if stats.total else 0}%")
