"""Home screen mascot: an original anime-style girl drawn with QPainter, no picture files.

Twin tails, side locks, bangs, the cowlick and the bow ribbons are verlet strands: they
hang under gravity, lag behind the head, swing back and get pushed aside by the cursor.
The head and the eyes follow the mouse anywhere on the screen. The frame timer runs only
while she is on screen and slows down when the app is in the background.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Optional

from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from core.i18n import t
from ui.theme import current_theme

WIDTH, HEIGHT = 440, 350  # wide enough that a swinging tail never reaches the edge
EDGE = 6.0
CX = WIDTH / 2
NECK = QPointF(CX, 226.0)
HEAD = QPointF(CX, 140.0)
STEP = 1 / 60
ACTIVE_MS = 16
CALM_MS = 66
STILL_PX = 0.25
HIDDEN_MS = 250
GRAVITY = 1100.0
CURSOR_RADIUS = 18.0
CURSOR_PUSH = 0.16  # share of the overlap removed per step: hair gives way softly

HAIR = "#f3a6c8"
HAIR_DARK = "#d97aa6"
HAIR_LIGHT = "#ffd9ea"
HAIR_TIP = "#f9c3dc"
HAIR_LINE = "#9a456d"
SKIN = "#ffe8db"
SKIN_SHADE = "#f7cdb9"
SKIN_LINE = "#c98a78"
IRIS_TOP = "#2f1c58"
IRIS_MID = "#7354ee"
IRIS_LOW = "#cbbcff"
PUPIL = "#1b1033"
LASH = "#2b1730"
OUTFIT = "#28304d"
OUTFIT_LIGHT = "#3d4877"
COLLAR = "#f5f6fb"
RIBBON = "#e8455f"
RIBBON_DARK = "#a9223b"
BLUSH = "#ff8fae"

WAVE_SECONDS = 2.4
HAPPY_SECONDS = 0.9


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


class Strand:
    """A chain of points. Point 0 is pinned to the head, the rest follow by verlet
    integration, a pull back to the rest shape (stiffness) and fixed segment lengths."""

    def __init__(
        self,
        root: tuple[float, float],
        segments: list[tuple[float, float]],
        widths: list[float],
        stiffness: float,
        damping: float = 0.92,
        gravity: float = 1.0,
        parallax: float = 0.0,
        colors: tuple[str, str, str] = (HAIR_DARK, HAIR, HAIR_TIP),
        line: str = HAIR_LINE,
        sway: float = 0.0,
    ) -> None:
        self.root = root
        self.rest = segments
        self.lengths = [math.hypot(dx, dy) for dx, dy in segments]
        self.widths = widths
        self.stiffness = stiffness
        self.damping = damping
        self.gravity = gravity
        self.parallax = parallax
        self.colors = colors
        self.line = line
        self._stops = [QColor(color) for color in colors]  # built once, not every frame
        self._pen = QPen(QColor(line), 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.sway = sway
        self.phase = random.uniform(0, math.tau)
        self.motion = 0.0
        x, y = root
        self.points = [[x, y]]
        for dx, dy in segments:
            x, y = x + dx, y + dy
            self.points.append([x, y])
        self.previous = [point[:] for point in self.points]

    def step(self, head: "_HeadPose", time: float, cursor: Optional[QPointF]) -> None:
        points, previous = self.points, self.previous
        root_x, root_y = head.map(self.root[0], self.root[1], self.parallax)
        points[0][0], points[0][1] = root_x, root_y
        previous[0][0], previous[0][1] = root_x, root_y
        drop = GRAVITY * self.gravity * STEP * STEP
        breeze = self.sway * math.sin(time * 1.3 + self.phase) * STEP * STEP
        motion = 0.0
        for index in range(1, len(points)):
            point, before = points[index], previous[index]
            velocity_x = (point[0] - before[0]) * self.damping
            velocity_y = (point[1] - before[1]) * self.damping
            before[0], before[1] = point[0], point[1]
            motion = max(motion, abs(velocity_x), abs(velocity_y))
            point[0] += velocity_x + breeze * index
            point[1] += velocity_y + drop

        cos_a, sin_a = head.cos, head.sin
        for index in range(1, len(points)):
            dx, dy = self.rest[index - 1]
            target_x = points[index - 1][0] + dx * cos_a - dy * sin_a
            target_y = points[index - 1][1] + dx * sin_a + dy * cos_a
            points[index][0] += (target_x - points[index][0]) * self.stiffness
            points[index][1] += (target_y - points[index][1]) * self.stiffness

        if cursor is not None:
            cx, cy = cursor.x(), cursor.y()
            for point in points[1:]:
                dx, dy = point[0] - cx, point[1] - cy
                distance = math.hypot(dx, dy)
                if 0.001 < distance < CURSOR_RADIUS:
                    push = (CURSOR_RADIUS - distance) / distance * CURSOR_PUSH
                    point[0] += dx * push
                    point[1] += dy * push

        for _ in range(2):
            for index in range(1, len(points)):
                parent, point = points[index - 1], points[index]
                dx, dy = point[0] - parent[0], point[1] - parent[1]
                distance = math.hypot(dx, dy) or 0.001
                scale = self.lengths[index - 1] / distance
                point[0] = parent[0] + dx * scale
                point[1] = parent[1] + dy * scale
        for point in points:  # hair stays inside the widget, nothing gets cut off
            point[0] = min(max(point[0], EDGE), WIDTH - EDGE)
            point[1] = min(max(point[1], EDGE), HEIGHT - EDGE)
        self.motion = motion

    def kick(self, strength: float) -> None:
        for index, before in enumerate(self.previous[1:], start=1):
            before[0] += random.uniform(-strength, strength) * index / len(self.previous)
            before[1] += strength * index / len(self.previous)

    def paint(self, painter: QPainter) -> None:
        fill, outline = _ribbon_paths(self.points, self.widths)
        start, end = self.points[0], self.points[-1]
        gradient = QLinearGradient(QPointF(*start), QPointF(*end))
        gradient.setColorAt(0.0, self._stops[0])
        gradient.setColorAt(0.35, self._stops[1])
        gradient.setColorAt(1.0, self._stops[2])
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fill)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(self._pen)
        painter.drawPath(outline)


def _ribbon_paths(points: list[list[float]], widths: list[float]) -> tuple[QPainterPath, QPainterPath]:
    """A smooth band around the points, tapering to the given widths. The outline path
    leaves the root edge open, so a strand grows out of the hair without a seam."""
    count = len(points)
    left: list[QPointF] = []
    right: list[QPointF] = []
    for index in range(count):
        before = points[max(index - 1, 0)]
        after = points[min(index + 1, count - 1)]
        tx, ty = after[0] - before[0], after[1] - before[1]
        length = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / length, tx / length
        half = widths[index] / 2
        x, y = points[index]
        left.append(QPointF(x + nx * half, y + ny * half))
        right.append(QPointF(x - nx * half, y - ny * half))

    def mid(a: QPointF, b: QPointF) -> QPointF:
        return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)

    side = QPainterPath(left[0])
    for index in range(1, count - 1):
        side.quadTo(left[index], mid(left[index], left[index + 1]))
    side.lineTo(left[-1])
    side.lineTo(right[-1])
    for index in range(count - 2, 0, -1):
        side.quadTo(right[index], mid(right[index], right[index - 1]))
    side.lineTo(right[0])
    fill = QPainterPath(side)
    fill.closeSubpath()
    return fill, side


class _HeadPose:
    """Where the head is this frame: a turn toward the cursor (yaw, pitch), a tilt around
    the neck and a shift. Features closer to the viewer move more with the yaw."""

    def __init__(self) -> None:
        self.yaw = 0.0
        self.pitch = 0.0
        self.tilt = 0.0
        self.shift_x = 0.0
        self.shift_y = 0.0
        self.cos = 1.0
        self.sin = 0.0

    def update(self, yaw: float, pitch: float, bounce: float) -> None:
        self.yaw, self.pitch = yaw, pitch
        self.tilt = yaw * 5.0
        self.shift_x = yaw * 6.0
        self.shift_y = pitch * 4.0 + bounce
        radians = math.radians(self.tilt)
        self.cos, self.sin = math.cos(radians), math.sin(radians)

    def map(self, x: float, y: float, parallax: float = 0.0) -> tuple[float, float]:
        x += self.yaw * parallax
        y += self.pitch * parallax * 0.6
        dx, dy = x - NECK.x(), y - NECK.y()
        return (
            NECK.x() + dx * self.cos - dy * self.sin + self.shift_x,
            NECK.y() + dx * self.sin + dy * self.cos + self.shift_y,
        )

    def apply(self, painter: QPainter) -> None:
        painter.translate(self.shift_x, self.shift_y)
        painter.translate(NECK)
        painter.rotate(self.tilt)
        painter.translate(-NECK)


def _down(count: int, length: float, start_x: float, end_x: float) -> list[tuple[float, float]]:
    """Segments of a strand that bends from start_x to end_x sideways per segment."""
    segments = []
    for index in range(count):
        share = index / max(count - 1, 1)
        dx = start_x + (end_x - start_x) * share
        dy = math.sqrt(max(length * length - dx * dx, 1.0))
        segments.append((dx, dy))
    return segments


def _taper(root: float, count: int, bulge: float = 1.0) -> list[float]:
    widths = []
    for index in range(count + 1):
        share = index / count
        widths.append(root * (1 - share) ** 0.9 * (1 + (bulge - 1) * math.sin(share * math.pi)))
    widths[-1] = 0.0
    return widths


def _make_strands() -> dict[str, list[Strand]]:
    tails = []
    for side in (-1, 1):
        tails.append(Strand(
            (CX + side * 84, 92), _down(8, 24, side * 13, side * 2), _taper(30, 8, 1.55),
            stiffness=0.09, damping=0.92, gravity=1.0, parallax=-3, sway=60 * side,
        ))
    locks = []
    for side in (-1, 1):
        locks.append(Strand(
            (CX + side * 78, 104), _down(6, 17, side * 1, side * 5), _taper(17, 6, 1.1),
            stiffness=0.12, damping=0.88, gravity=0.8, parallax=4,
        ))
    bangs = []
    for offset in (-66, -46, -24, -2, 20, 43, 64):
        lean = offset / 64
        root_y = 70 + lean * lean * 16
        reach = 54 - abs(lean) * 8 if offset not in (-2, 43) else 46
        bangs.append(Strand(
            (CX + offset, root_y), _down(3, reach / 3, lean * 4 - 1, lean * 7 + 1), _taper(24 - abs(lean) * 4, 3, 1.05),
            stiffness=0.22, damping=0.85, gravity=0.6, parallax=5, colors=(HAIR, HAIR, HAIR_TIP),
        ))
    cowlick = [Strand(
        (CX + 8, 48), [(4, -10), (9, -7), (10, 1), (6, 7)], [7, 6, 4.5, 2.5, 0],
        stiffness=0.3, damping=0.82, gravity=0.35, parallax=2, colors=(HAIR, HAIR, HAIR_TIP),
    )]
    ribbons = []
    for side in (-1, 1):
        for spread in (-1, 1):
            ribbons.append(Strand(
                (CX + side * 82, 92), _down(3, 10, side * 2 + spread * 3, side * 1 + spread * 2), [7, 7.5, 7, 0],
                stiffness=0.12, damping=0.9, gravity=0.7, parallax=-1,
                colors=(RIBBON, RIBBON, RIBBON), line=RIBBON_DARK,
            ))
    return {"tails": tails, "locks": locks, "bangs": bangs, "cowlick": cowlick, "ribbons": ribbons}


class Mascot(QWidget):
    """The girl. Click her and she reacts; poked() lets the home screen answer in words."""

    poked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(t("Помощница"))
        self.cursor_source: Callable[[], QPointF] = lambda: QPointF(self.mapFromGlobal(QCursor.pos()))
        self.time = 0.0
        self.pose = _HeadPose()
        self.strands = _make_strands()
        self._springs = {name: [0.0, 0.0] for name in ("yaw", "pitch", "look_x", "look_y", "bounce")}
        self._next_blink = random.uniform(1.5, 4.0)
        self._blink_left = 0.0
        self.openness = 1.0
        self._happy_left = 0.0
        self._talk_left = 0.0
        self._wave_left = 0.0
        self._frames = 0
        self._last_cursor: Optional[QPointF] = None
        self._cursor_moved = False
        self._clock = QElapsedTimer()
        self._lag = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        for _ in range(90):  # let the hair settle before the first frame
            self.advance(STEP)

    # --- public --------------------------------------------------------------

    @property
    def look(self) -> tuple[float, float]:
        return self._springs["look_x"][0], self._springs["look_y"][0]

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def waving(self) -> bool:
        return self._wave_left > 0

    @property
    def happy(self) -> bool:
        return self._happy_left > 0

    @property
    def talking(self) -> bool:
        return self._talk_left > 0

    @property
    def moving(self) -> bool:
        """Anything faster than breathing on screen. When she only breathes, half the
        frame rate looks the same and costs half."""
        if self._cursor_moved or self._blink_left > 0 or self._wave_left > 0 or self._talk_left > 0 or self._happy_left > 0:
            return True
        if any(abs(state[1]) > 0.15 for name, state in self._springs.items() if name != "bounce") or abs(self._springs["bounce"][1]) > 2:
            return True
        return any(strand.motion > STILL_PX for group in self.strands.values() for strand in group)

    def _motion_report(self) -> dict[str, float]:
        """Fastest strand of each group, in pixels per step. For tuning STILL_PX."""
        return {name: max(strand.motion for strand in group) for name, group in self.strands.items()}

    def wave(self) -> None:
        self._wave_left = WAVE_SECONDS

    def talk(self, seconds: float) -> None:
        self._talk_left = max(self._talk_left, seconds)

    def poke(self) -> None:
        self._happy_left = HAPPY_SECONDS
        self._springs["bounce"][1] -= 140.0
        for group in self.strands.values():
            for strand in group:
                strand.kick(3.0)
        self.poked.emit()

    def advance(self, seconds: float) -> None:
        """Runs the simulation in fixed steps, so it behaves the same at any frame rate."""
        self._lag += min(seconds, 0.25)
        while self._lag >= STEP:
            self._lag -= STEP
            self._step()

    # --- simulation ----------------------------------------------------------

    def _cursor(self) -> Optional[QPointF]:
        try:
            return self.cursor_source()
        except RuntimeError:
            return None

    def _spring(self, name: str, target: float, stiffness: float, damping: float) -> float:
        state = self._springs[name]
        state[1] += (stiffness * (target - state[0]) - damping * state[1]) * STEP
        state[0] += state[1] * STEP
        return state[0]

    def _step(self) -> None:
        self.time += STEP
        cursor = self._cursor()
        if cursor is not None:
            dx, dy = cursor.x() - HEAD.x(), cursor.y() - HEAD.y()
        else:
            dx = dy = 0.0
        yaw = self._spring("yaw", _clamp(dx / 420), 60, 13)
        pitch = self._spring("pitch", _clamp(dy / 420), 60, 13)
        self._spring("look_x", _clamp(dx / 240), 220, 26)
        self._spring("look_y", _clamp(dy / 240), 220, 26)
        bounce = self._spring("bounce", 0.0, 260, 14)
        self.pose.update(yaw, pitch, bounce + math.sin(self.time * 2.0) * 0.8)

        near = cursor if cursor is not None and QRectF(-20, -20, WIDTH + 40, HEIGHT + 40).contains(cursor) else None
        for group in self.strands.values():
            for strand in group:
                strand.step(self.pose, self.time, near)

        self._next_blink -= STEP
        if self._blink_left > 0:
            self._blink_left -= STEP
            self.openness = 1 - math.sin(math.pi * max(self._blink_left, 0) / 0.14)
        elif self._next_blink <= 0:
            self._blink_left = 0.14
            self._next_blink = random.uniform(2.0, 5.5)
        else:
            self.openness = 1.0
        for name in ("_happy_left", "_talk_left", "_wave_left"):
            setattr(self, name, max(getattr(self, name) - STEP, 0.0))

    def _tick(self) -> None:
        elapsed = self._clock.restart() / 1000.0
        window = self.window()
        if window.isMinimized() or not self.isVisible():
            self._timer.setInterval(HIDDEN_MS)
            return
        cursor = self._cursor()
        self._cursor_moved = cursor != self._last_cursor
        self._last_cursor = cursor
        self.advance(elapsed)
        active = QApplication.applicationState() == Qt.ApplicationActive
        self._timer.setInterval(ACTIVE_MS if active and self.moving else CALM_MS)
        self._frames += 1
        self.update()

    def showEvent(self, event) -> None:
        self._clock.start()
        self._timer.start(ACTIVE_MS)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.poke()
        super().mousePressEvent(event)

    # --- drawing -------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_into(painter)
        painter.end()

    def paint_into(self, painter: QPainter) -> None:
        breath = math.sin(self.time * 2.0)
        painter.save()
        self.pose.apply(painter)
        _paint_back_hair(painter, self.pose.yaw)
        painter.restore()

        _paint_body(painter, breath)
        for strand in self.strands["tails"]:
            strand.paint(painter)

        painter.save()
        self.pose.apply(painter)
        _paint_face(painter, self)
        _paint_hair_cap(painter, self.pose.yaw)
        painter.restore()

        for name in ("locks", "bangs", "cowlick", "ribbons"):
            for strand in self.strands[name]:
                strand.paint(painter)
        painter.save()
        self.pose.apply(painter)
        for side in (-1, 1):
            _paint_bow(painter, QPointF(CX + side * 82 - self.pose.yaw * 3, 90), side)
        painter.restore()

        if self._wave_left > 0:
            _paint_waving_arm(painter, WAVE_SECONDS - self._wave_left)


_PENS: dict[tuple[str, float], QPen] = {}


def _outline(color: str, width: float = 1.4) -> QPen:
    pen = _PENS.get((color, width))
    if pen is None:
        pen = _PENS[(color, width)] = QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    return pen


def _paint_back_hair(painter: QPainter, yaw: float) -> None:
    shift = -yaw * 3
    path = QPainterPath(QPointF(CX - 88 + shift, 126))
    path.cubicTo(QPointF(CX - 96 + shift, 30), QPointF(CX + 96 + shift, 30), QPointF(CX + 88 + shift, 126))
    path.cubicTo(QPointF(CX + 100 + shift, 190), QPointF(CX + 96, 230), QPointF(CX + 92, 262))
    for x, y in ((CX + 70, 246), (CX + 56, 270), (CX + 30, 250), (CX, 262), (CX - 30, 250), (CX - 56, 270), (CX - 70, 246)):
        path.lineTo(QPointF(x, y))
    path.lineTo(QPointF(CX - 92, 262))
    path.cubicTo(QPointF(CX - 96, 230), QPointF(CX - 100 + shift, 190), QPointF(CX - 88 + shift, 126))
    gradient = QLinearGradient(QPointF(CX, 40), QPointF(CX, 270))
    gradient.setColorAt(0, QColor(HAIR))
    gradient.setColorAt(1, QColor(HAIR_DARK))
    painter.setPen(_outline(HAIR_LINE))
    painter.setBrush(gradient)
    painter.drawPath(path)


def _paint_body(painter: QPainter, breath: float) -> None:
    lift = breath * 1.2
    body = QPainterPath(QPointF(CX - 124, HEIGHT + 2))
    body.cubicTo(QPointF(CX - 122, 284 + lift), QPointF(CX - 100, 258 + lift), QPointF(CX - 62, 250 + lift))
    body.quadTo(QPointF(CX - 30, 242 + lift), QPointF(CX - 15, 236))
    body.lineTo(QPointF(CX + 15, 236))
    body.quadTo(QPointF(CX + 30, 242 + lift), QPointF(CX + 62, 250 + lift))
    body.cubicTo(QPointF(CX + 100, 258 + lift), QPointF(CX + 122, 284 + lift), QPointF(CX + 124, HEIGHT + 2))
    body.closeSubpath()
    gradient = QLinearGradient(QPointF(CX, 240), QPointF(CX, HEIGHT))
    gradient.setColorAt(0, QColor(OUTFIT_LIGHT))
    gradient.setColorAt(1, QColor(OUTFIT))
    painter.setPen(_outline("#171b2e"))
    painter.setBrush(gradient)
    painter.drawPath(body)

    neck = QPainterPath(QPointF(CX - 15, 196))
    neck.lineTo(QPointF(CX - 15, 238))
    neck.quadTo(QPointF(CX, 250), QPointF(CX + 15, 238))
    neck.lineTo(QPointF(CX + 15, 196))
    neck.closeSubpath()
    shade = QLinearGradient(QPointF(CX, 200), QPointF(CX, 240))
    shade.setColorAt(0, QColor(SKIN_SHADE))
    shade.setColorAt(0.5, QColor(SKIN))
    painter.setPen(_outline(SKIN_LINE, 1.1))
    painter.setBrush(shade)
    painter.drawPath(neck)

    for side in (-1, 1):  # sailor collar flaps with a stripe
        flap = QPainterPath(QPointF(CX + side * 15, 236))
        flap.lineTo(QPointF(CX + side * 68, 251 + lift))
        flap.lineTo(QPointF(CX + side * 44, 300 + lift))
        flap.lineTo(QPointF(CX, 292 + lift))
        flap.closeSubpath()
        painter.setPen(_outline("#9aa0b8", 1.1))
        painter.setBrush(QColor(COLLAR))
        painter.drawPath(flap)
        painter.setPen(QPen(QColor(OUTFIT), 2.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(CX + side * 58, 255 + lift), QPointF(CX + side * 38, 292 + lift))

    knot = QPointF(CX, 292 + lift)
    for side in (-1, 1):
        loop = QPainterPath(knot)
        loop.cubicTo(QPointF(CX + side * 18, 278 + lift), QPointF(CX + side * 30, 288 + lift), QPointF(CX + side * 26, 300 + lift))
        loop.cubicTo(QPointF(CX + side * 20, 306 + lift), QPointF(CX + side * 8, 300 + lift), knot)
        tail = QPainterPath(knot)
        tail.lineTo(QPointF(CX + side * 14, 330 + lift))
        tail.lineTo(QPointF(CX + side * 6, 326 + lift))
        tail.lineTo(QPointF(CX + side * 2, 334 + lift))
        tail.closeSubpath()
        painter.setPen(_outline(RIBBON_DARK, 1.1))
        painter.setBrush(QColor(RIBBON))
        painter.drawPath(tail)
        painter.drawPath(loop)
    painter.drawEllipse(knot, 5.5, 5)


def _face_path(shift: float) -> QPainterPath:
    path = QPainterPath(QPointF(CX - 80 + shift, 112))
    path.cubicTo(QPointF(CX - 82 + shift, 160), QPointF(CX - 52 + shift * 1.4, 202), QPointF(CX + shift * 1.8, 214))
    path.cubicTo(QPointF(CX + 52 + shift * 1.4, 202), QPointF(CX + 82 + shift, 160), QPointF(CX + 80 + shift, 112))
    path.cubicTo(QPointF(CX + 78 + shift, 44), QPointF(CX - 78 + shift, 44), QPointF(CX - 80 + shift, 112))
    return path


def _paint_face(painter: QPainter, mascot: Mascot) -> None:
    yaw, pitch = mascot.pose.yaw, mascot.pose.pitch
    gradient = QLinearGradient(QPointF(CX, 70), QPointF(CX, 214))
    gradient.setColorAt(0, QColor(SKIN_SHADE))
    gradient.setColorAt(0.35, QColor(SKIN))
    painter.setPen(_outline(SKIN_LINE, 1.3))
    painter.setBrush(gradient)
    painter.drawPath(_face_path(yaw * 2))

    fx, fy = yaw * 9, pitch * 5  # features sit in front of the face and move most
    for side in (-1, 1):
        blush = QRadialGradient(QPointF(CX + side * 47 + fx, 178 + fy), 16)
        color = QColor(BLUSH)
        color.setAlpha(130 if mascot.happy else 85)
        blush.setColorAt(0, color)
        color.setAlpha(0)
        blush.setColorAt(1, color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(blush)
        painter.drawEllipse(QPointF(CX + side * 47 + fx, 178 + fy), 18, 10)

    look_x, look_y = mascot.look
    for side in (-1, 1):
        center = QPointF(CX + side * 34 + fx, 150 + fy)
        if mascot.happy:
            _paint_happy_eye(painter, center)
        else:
            _paint_eye(painter, center, side, look_x, look_y, mascot.openness)
        brow = QPainterPath(QPointF(center.x() - side * 14, 121 + fy * 0.6))
        brow.quadTo(QPointF(center.x() + side * 2, 115 + fy * 0.6 - (3 if mascot.happy else 0)), QPointF(center.x() + side * 16, 120 + fy * 0.6))
        painter.setPen(QPen(QColor(HAIR_LINE), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(brow)

    painter.setPen(QPen(QColor(SKIN_LINE), 1.4, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(CX + fx * 1.1, 176 + fy), QPointF(CX + fx * 1.1 + 1.5, 179 + fy))
    _paint_mouth(painter, QPointF(CX + fx * 1.05, 194 + fy), mascot)


def _paint_eye(painter: QPainter, center: QPointF, side: int, look_x: float, look_y: float, openness: float) -> None:
    if openness < 0.2:
        closed = QPainterPath(QPointF(center.x() - 17, center.y() + 4))
        closed.quadTo(QPointF(center.x(), center.y() + 13), QPointF(center.x() + 17, center.y() + 4))
        painter.setPen(QPen(QColor(LASH), 3.2, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(closed)
        return
    painter.save()
    painter.translate(center.x(), center.y() - 18)
    painter.scale(1.0, openness)
    painter.translate(-center.x(), -(center.y() - 18))

    white = QPainterPath()
    white.addEllipse(center, 17.5, 21.5)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(white)
    painter.setClipPath(white)

    iris_center = QPointF(center.x() + look_x * 6.5, center.y() + 3 + look_y * 5.5)
    iris = QLinearGradient(QPointF(iris_center.x(), iris_center.y() - 18), QPointF(iris_center.x(), iris_center.y() + 18))
    iris.setColorAt(0, QColor(IRIS_TOP))
    iris.setColorAt(0.5, QColor(IRIS_MID))
    iris.setColorAt(1, QColor(IRIS_LOW))
    painter.setPen(QPen(QColor(IRIS_TOP), 1.4))
    painter.setBrush(iris)
    painter.drawEllipse(iris_center, 13.5, 18)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(PUPIL))
    painter.drawEllipse(QPointF(iris_center.x(), iris_center.y() - 1), 6, 8.5)
    shade = QColor(IRIS_TOP)
    shade.setAlpha(110)
    painter.setBrush(shade)
    painter.drawEllipse(QPointF(center.x(), center.y() - 19), 19, 8)  # shadow of the upper lid
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QPointF(iris_center.x() - 5, iris_center.y() - 8), 5, 6)
    painter.drawEllipse(QPointF(iris_center.x() + 6, iris_center.y() + 8), 2.4, 2.4)
    painter.setClipping(False)

    lash = QPainterPath(QPointF(center.x() - side * 19, center.y() - 2))
    lash.cubicTo(
        QPointF(center.x() - side * 18, center.y() - 26), QPointF(center.x() + side * 16, center.y() - 28),
        QPointF(center.x() + side * 21, center.y() - 8),
    )
    lash.lineTo(QPointF(center.x() + side * 26, center.y() - 12))  # the flick at the outer corner
    painter.setPen(QPen(QColor(LASH), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(lash)
    lower = QPainterPath(QPointF(center.x() - 8, center.y() + 21))
    lower.quadTo(QPointF(center.x() + side * 6, center.y() + 23.5), QPointF(center.x() + side * 13, center.y() + 18))
    painter.setPen(QPen(QColor(LASH), 1.3, Qt.SolidLine, Qt.RoundCap))
    painter.drawPath(lower)
    painter.restore()


def _paint_happy_eye(painter: QPainter, center: QPointF) -> None:
    arc = QPainterPath(QPointF(center.x() - 15, center.y() + 6))
    arc.quadTo(QPointF(center.x(), center.y() - 14), QPointF(center.x() + 15, center.y() + 6))
    painter.setPen(QPen(QColor(LASH), 3.6, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(arc)


def _paint_mouth(painter: QPainter, center: QPointF, mascot: Mascot) -> None:
    opening = 0.0
    if mascot.talking:
        opening = abs(math.sin(mascot.time * 17)) * 0.8 + 0.2
    elif mascot.happy:
        opening = 0.9
    if opening < 0.05:
        smile = QPainterPath(QPointF(center.x() - 7, center.y() - 1))
        smile.quadTo(QPointF(center.x(), center.y() + 4), QPointF(center.x() + 7, center.y() - 1))
        painter.setPen(QPen(QColor("#8c3a4b"), 1.8, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(smile)
        return
    height = 3 + 8 * opening
    mouth = QPainterPath(QPointF(center.x() - 8, center.y() - 2))
    mouth.quadTo(QPointF(center.x(), center.y()), QPointF(center.x() + 8, center.y() - 2))
    mouth.quadTo(QPointF(center.x(), center.y() + height * 1.6), QPointF(center.x() - 8, center.y() - 2))
    painter.setPen(_outline("#6b2234", 1.3))
    painter.setBrush(QColor("#9b3046"))
    painter.drawPath(mouth)
    painter.save()
    painter.setClipPath(mouth)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ff8a9b"))
    painter.drawEllipse(QPointF(center.x(), center.y() + height * 0.9), 6, height * 0.45)
    painter.restore()


def _paint_hair_cap(painter: QPainter, yaw: float) -> None:
    shift = yaw * 3
    cap = QPainterPath(QPointF(CX - 87 + shift, 128))
    cap.cubicTo(QPointF(CX - 98 + shift, 22), QPointF(CX + 98 + shift, 22), QPointF(CX + 87 + shift, 128))
    cap.cubicTo(QPointF(CX + 80 + shift, 96), QPointF(CX + 50 + shift, 76), QPointF(CX + shift, 74))
    cap.cubicTo(QPointF(CX - 50 + shift, 76), QPointF(CX - 80 + shift, 96), QPointF(CX - 87 + shift, 128))
    gradient = QLinearGradient(QPointF(CX, 30), QPointF(CX, 110))
    gradient.setColorAt(0, QColor(HAIR_LIGHT))
    gradient.setColorAt(0.45, QColor(HAIR))
    gradient.setColorAt(1, QColor(HAIR))
    painter.setPen(_outline(HAIR_LINE))
    painter.setBrush(gradient)
    painter.drawPath(cap)
    shine = QColor("#ffffff")
    shine.setAlpha(140)
    painter.save()
    painter.setClipPath(cap)
    painter.setPen(QPen(shine, 4.5, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(CX - 60 + shift * 1.4, 54, 120, 64), 38 * 16, 104 * 16)  # the ring of light on the hair
    painter.restore()


def _paint_bow(painter: QPainter, knot: QPointF, side: int) -> None:
    painter.setPen(_outline(RIBBON_DARK, 1.2))
    painter.setBrush(QColor(RIBBON))
    for direction in (-1, 1):
        loop = QPainterPath(knot)
        loop.cubicTo(
            QPointF(knot.x() + direction * 10, knot.y() - 20), QPointF(knot.x() + direction * 22, knot.y() - 14),
            QPointF(knot.x() + direction * 19, knot.y() + 2),
        )
        loop.cubicTo(QPointF(knot.x() + direction * 16, knot.y() + 10), QPointF(knot.x() + direction * 6, knot.y() + 6), knot)
        painter.drawPath(loop)
    painter.setBrush(QColor(RIBBON_DARK))
    painter.drawEllipse(knot, 5, 5.5)


def _paint_waving_arm(painter: QPainter, elapsed: float) -> None:
    raise_in = min(elapsed / 0.35, 1.0)
    raise_out = min((WAVE_SECONDS - elapsed) / 0.35, 1.0)
    lifted = QEasingCurve(QEasingCurve.OutBack).valueForProgress(min(raise_in, raise_out))
    hidden, raised = QPointF(CX + 104, HEIGHT + 70), QPointF(CX + 104, 206)
    wrist = hidden + (raised - hidden) * lifted
    elbow = QPointF(CX + 96, HEIGHT + 24)
    cuff = wrist + QPointF(0, 16)
    painter.setPen(QPen(QColor("#171b2e"), 34, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(elbow, cuff)
    painter.setPen(QPen(QColor(OUTFIT_LIGHT), 31, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(elbow, cuff)
    painter.setPen(QPen(QColor(COLLAR), 4, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(cuff + QPointF(-13, 2), cuff + QPointF(13, 2))

    painter.save()
    painter.translate(wrist)
    painter.rotate(math.sin(elapsed * 9.0) * 18 * lifted)
    painter.setPen(_outline(SKIN_LINE, 1.2))
    painter.setBrush(QColor(SKIN))
    painter.save()
    painter.rotate(-58)
    painter.drawRoundedRect(QRectF(-5, -30, 10, 22), 5, 5)  # thumb
    painter.restore()
    for angle, length in ((-21, 20), (-7, 25), (7, 25), (21, 21)):
        painter.save()
        painter.rotate(angle)
        painter.drawRoundedRect(QRectF(-4.6, -16 - length, 9.2, length + 8), 4.6, 4.6)
        painter.restore()
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(0, -8), 15.5, 15)  # the palm hides the finger roots
    painter.setPen(_outline(SKIN_LINE, 1.2))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(-15.5, -23, 31, 30), 200 * 16, 140 * 16)
    painter.restore()


class SpeechBubble(QWidget):
    """What she says. Pops in, types the text out, its tail points at her."""

    TAIL = 14
    MAX_WIDTH = 236
    PADDING = 14

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = ""
        self.shown_chars = 0
        self._scale = 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedWidth(self.MAX_WIDTH + self.TAIL)
        self._typing = QTimer(self)
        self._typing.setInterval(32)
        self._typing.timeout.connect(self._type_next)
        self._pop = QVariantAnimation(self)
        self._pop.setDuration(320)
        self._pop.setEasingCurve(QEasingCurve.OutBack)
        self._pop.setStartValue(0.6)
        self._pop.setEndValue(1.0)
        self._pop.valueChanged.connect(self._set_scale)

    @property
    def visible_text(self) -> str:
        return self.text[: self.shown_chars]

    def typing_seconds(self) -> float:
        return len(self.text) * self._typing.interval() / 1000

    def say(self, text: str) -> None:
        self.text = text
        self.shown_chars = 0
        metrics = QFontMetrics(self.font())
        box = metrics.boundingRect(0, 0, self.MAX_WIDTH - 2 * self.PADDING, 1000, Qt.TextWordWrap, text)
        self.setFixedHeight(box.height() + 2 * self.PADDING + 4)
        self._typing.start()
        self._pop.stop()
        self._pop.start()
        self.show()

    def finish(self) -> None:
        self.shown_chars = len(self.text)
        self._typing.stop()
        self.update()

    def _type_next(self) -> None:
        self.shown_chars += 1
        if self.shown_chars >= len(self.text):
            self._typing.stop()
        self.update()

    def _set_scale(self, value: float) -> None:
        self._scale = value
        self.update()

    def hideEvent(self, event) -> None:
        self.finish()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        anchor = QPointF(0, self.height() * 0.62)
        painter.translate(anchor)
        painter.scale(self._scale, self._scale)
        painter.translate(-anchor)

        body = QRectF(self.TAIL, 1, self.width() - self.TAIL - 2, self.height() - 3)
        path = QPainterPath()
        path.addRoundedRect(body, 18, 18)
        tail = QPainterPath(QPointF(self.TAIL + 2, body.bottom() - 26))
        tail.quadTo(QPointF(self.TAIL - 4, body.bottom() - 12), QPointF(0, body.bottom() - 4))
        tail.quadTo(QPointF(self.TAIL + 6, body.bottom() - 8), QPointF(self.TAIL + 14, body.bottom() - 14))
        path = path.united(tail)
        shadow = QColor("#000000")
        shadow.setAlpha(40 if theme.dark else 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawPath(path.translated(0, 2))
        painter.setBrush(QColor(theme.surface))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawPath(path)
        painter.setPen(QColor(theme.text))
        painter.drawText(
            body.adjusted(self.PADDING, self.PADDING - 2, -self.PADDING, -self.PADDING),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            self.visible_text,
        )
        painter.end()


GREETING = "Привет! Сыграем партию?"
WELCOME_BACK = "С возвращением! Ещё партию?"
POKE_LINES = (
    "Эй, щекотно!",
    "Лучше сыграй со мной!",
    "Загляни в пазлы, там есть хитрые.",
    "Я болею за тебя!",
    "Белые начинают и выигрывают!",
)


BUBBLE_OVERLAP = 70


class MascotStage(QWidget):
    """The girl in the middle and her speech bubble to the right of her head."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mascot = Mascot()
        self.bubble = SpeechBubble()
        self._greeted = False
        self._poke_index = 0
        self.mascot.poked.connect(self._answer_poke)

        self.mascot.setParent(self)
        self.bubble.setParent(self)
        self.setMinimumSize(self.minimumSizeHint())
        self.bubble.hide()

    def minimumSizeHint(self) -> QSize:
        return QSize(WIDTH + 2 * (self.bubble.width() - BUBBLE_OVERLAP), HEIGHT)

    def sizeHint(self) -> QSize:
        return self.minimumSizeHint()

    def resizeEvent(self, event) -> None:
        """The girl in the middle; the bubble starts inside her empty right margin."""
        left = (self.width() - WIDTH) // 2
        self.mascot.move(left, 0)
        self.bubble.move(left + WIDTH - BUBBLE_OVERLAP, 58)
        super().resizeEvent(event)

    def greet(self) -> None:
        text = t(WELCOME_BACK if self._greeted else GREETING)
        self._greeted = True
        self._say(text)
        self.mascot.wave()

    def _say(self, text: str) -> None:
        self.bubble.say(text)
        self.mascot.talk(self.bubble.typing_seconds() + 0.2)

    def _answer_poke(self) -> None:
        self._say(t(POKE_LINES[self._poke_index % len(POKE_LINES)]))
        self._poke_index += 1
