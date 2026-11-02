"""Chess clock logic. Free of Qt: the time source is injected so tests control it."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import chess


@dataclass(frozen=True)
class TimeControl:
    """Minutes per game plus Fischer increment. minutes == 0 means no timer."""

    minutes: int
    increment: int = 0
    category: str = "Своё"

    @property
    def untimed(self) -> bool:
        return self.minutes <= 0

    @property
    def initial_ms(self) -> int:
        return self.minutes * 60_000

    @property
    def label(self) -> str:
        if self.untimed:
            return "без таймера"
        return f"{self.minutes}+{self.increment}"

    @property
    def pgn_tag(self) -> str:
        if self.untimed:
            return "-"
        return f"{self.minutes * 60}+{self.increment}"

    @property
    def storage_key(self) -> str:
        return f"{self.minutes}+{self.increment}"

    @classmethod
    def from_storage_key(cls, key: str) -> "TimeControl":
        minutes, increment = key.split("+")
        return cls(int(minutes), int(increment))


UNTIMED = TimeControl(0, 0, "Тренировка")

PRESETS: tuple[TimeControl, ...] = (
    TimeControl(1, 0, "Bullet"),
    TimeControl(2, 1, "Bullet"),
    TimeControl(3, 0, "Blitz"),
    TimeControl(5, 0, "Blitz"),
    TimeControl(10, 0, "Rapid"),
    TimeControl(15, 10, "Rapid"),
    TimeControl(30, 0, "Classical"),
)


class ChessClock:
    """Two countdowns, one running at a time."""

    def __init__(
        self,
        control: TimeControl,
        now: Callable[[], float] = time.monotonic,
        white_ms: Optional[int] = None,
        black_ms: Optional[int] = None,
    ) -> None:
        self.control = control
        self._now = now
        self._ms = {
            chess.WHITE: control.initial_ms if white_ms is None else white_ms,
            chess.BLACK: control.initial_ms if black_ms is None else black_ms,
        }
        self._running: Optional[bool] = None
        self._since = 0.0

    @property
    def running_color(self) -> Optional[bool]:
        return self._running

    @property
    def is_running(self) -> bool:
        return self._running is not None

    def start(self, color: bool) -> None:
        self._settle()
        self._running = color
        self._since = self._now()

    def stop(self) -> None:
        self._settle()
        self._running = None

    def press(self, color: bool) -> None:
        """Player `color` finished a move: credit the increment, run the other clock."""
        self._settle()
        if not self.control.untimed:
            self._ms[color] += self.control.increment * 1000
        self._running = not color
        self._since = self._now()

    def remaining_ms(self, color: bool) -> int:
        ms = self._ms[color]
        if self._running == color:
            ms -= int((self._now() - self._since) * 1000)
        return max(0, ms)

    def flagged(self) -> Optional[bool]:
        """Color whose time ran out, if any."""
        if self.control.untimed:
            return None
        for color in (chess.WHITE, chess.BLACK):
            if self.remaining_ms(color) <= 0:
                return color
        return None

    def snapshot(self) -> tuple[int, int]:
        return self.remaining_ms(chess.WHITE), self.remaining_ms(chess.BLACK)

    def restore(self, snapshot: tuple[int, int], running: Optional[bool]) -> None:
        self._ms[chess.WHITE], self._ms[chess.BLACK] = snapshot
        self._running = running
        self._since = self._now()

    def _settle(self) -> None:
        if self._running is None:
            return
        elapsed = int((self._now() - self._since) * 1000)
        self._ms[self._running] = max(0, self._ms[self._running] - elapsed)
        self._since = self._now()


def format_clock(ms: int) -> str:
    """"1:05:09", "12:04", tenths below 20 seconds: "0:07.3"."""
    if ms >= 3_600_000:
        total = ms // 1000
        return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
    if ms >= 20_000:
        # Rounded up so a fresh 5+0 clock reads 5:00 and 0:00 only ever means flagged.
        total = (ms + 999) // 1000
        return f"{total // 60}:{total % 60:02d}"
    return f"0:{ms // 1000:02d}.{ms % 1000 // 100}"
