"""Interface animations: button press and screen change. The board never goes through
an effect, so moves stay at full frame rate."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QGraphicsOpacityEffect, QLabel, QPushButton, QWidget

PRESS_SCALE = 0.95
PRESS_MS = 90
RELEASE_MS = 160
FADE_MS = 200
SLIDE_PX = 14


class _PressEffect(QGraphicsEffect):
    """Scales the button around its center. Off at rest, so an idle button is drawn as usual."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._scale = 1.0
        self.setEnabled(False)

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        self._scale = scale
        self.setEnabled(scale < 1.0)
        self.update()

    def draw(self, painter: QPainter) -> None:
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates)
        center = QPointF(self.sourceBoundingRect(Qt.LogicalCoordinates).center())
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()


class PressAnimator(QObject):
    """App-wide event filter, so every QPushButton gets the animation, those in standard
    dialogs too. The color change on press comes from the stylesheet. Also marks focus that
    came from the keyboard: only that focus draws a ring, a mouse user never needs one."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._animations: dict[int, QVariantAnimation] = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.MouseButtonPress or kind == QEvent.MouseButtonDblClick:
            if isinstance(watched, QPushButton) and watched.isEnabled():
                self._animate(watched, PRESS_SCALE, PRESS_MS)
        elif kind == QEvent.MouseButtonRelease or kind == QEvent.Hide:
            if isinstance(watched, QPushButton) and id(watched) in self._animations:
                self._animate(watched, 1.0, RELEASE_MS)
        elif kind == QEvent.FocusIn or kind == QEvent.FocusOut:
            if isinstance(watched, QPushButton):
                by_keyboard = kind == QEvent.FocusIn and event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
                if bool(watched.property("keyboardFocus")) != by_keyboard:
                    watched.setProperty("keyboardFocus", by_keyboard)
                    watched.style().unpolish(watched)
                    watched.style().polish(watched)
        return False

    def _animate(self, button: QPushButton, target: float, duration: int) -> None:
        effect = button.graphicsEffect()
        if effect is None:
            effect = _PressEffect(button)
            button.setGraphicsEffect(effect)
        elif not isinstance(effect, _PressEffect):
            return
        key = id(button)
        animation = self._animations.get(key)
        if animation is None:
            animation = QVariantAnimation(button)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.valueChanged.connect(effect.set_scale)
            button.destroyed.connect(lambda: self._animations.pop(key, None))
            self._animations[key] = animation
        animation.stop()
        animation.setDuration(duration)
        animation.setStartValue(effect.scale)
        animation.setEndValue(target)
        animation.start()


def install_press_animation(app: QApplication) -> None:
    if app.findChild(PressAnimator) is None:
        app.installEventFilter(PressAnimator(app))


def cross_fade(area: QWidget, change: Callable[[], None]) -> None:
    """Runs `change`, which swaps what `area` shows, while a picture of the old view
    fades out and slides up on top of it."""
    if not area.isVisible():
        change()
        return
    cover = QLabel(area)
    cover.setPixmap(area.grab())
    cover.setGeometry(area.rect())
    cover.setAttribute(Qt.WA_TransparentForMouseEvents)
    change()
    opacity = QGraphicsOpacityEffect(cover)
    cover.setGraphicsEffect(opacity)
    cover.show()
    cover.raise_()

    def step(progress: float) -> None:
        opacity.setOpacity(1.0 - progress)
        cover.move(0, round(-SLIDE_PX * progress))

    animation = QVariantAnimation(cover)
    animation.setDuration(FADE_MS)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.valueChanged.connect(step)
    animation.finished.connect(cover.deleteLater)
    animation.start()
