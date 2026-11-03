"""Generated sounds, played through winsound. No audio files in the repository: each sound
is synthesized once into the data folder and reused.

Move sounds come in styles the player picks in Settings:
  wood    - a wooden piece set down on a board: a low thump of the board, the click of
            the piece's edge and a short burst of contact noise
  classic - the plain tone of the first versions
  bubble  - a rising "bloop", like a bubble popping
  retro   - an 8-bit square-wave blip
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable

from core.paths import data_dir

try:
    import winsound
except ImportError:  # not Windows: stay silent
    winsound = None

_RATE = 44100
SOUND_VERSION = 2  # bump when a sound changes, so the cached files are made again
MOVE_STYLES = ("wood", "classic", "bubble", "retro")
DEFAULT_STYLE = "wood"

Samples = list[float]


def _mix(*parts: tuple[float, Samples]) -> Samples:
    """Adds sounds that start at the given offsets in seconds."""
    length = max(int(offset * _RATE) + len(samples) for offset, samples in parts)
    out = [0.0] * length
    for offset, samples in parts:
        start = int(offset * _RATE)
        for index, value in enumerate(samples):
            out[start + index] += value
    return out


def _concat(*parts: Samples) -> Samples:
    out: Samples = []
    for part in parts:
        out.extend(part)
    return out


def _tone(frequency: float, seconds: float, volume: float = 0.3) -> Samples:
    """The original sound: a sine with a soft start and a fading end."""
    count = int(_RATE * seconds)
    return [
        volume * min(1.0, (count - i) / (count * 0.6)) * min(1.0, i / 120) * math.sin(2 * math.pi * frequency * i / _RATE)
        for i in range(count)
    ]


def _knock(strength: float = 1.0, pitch: float = 1.0, seed: int = 1) -> Samples:
    """A piece set down on a wooden board. Modal synthesis: a few damped resonances of
    the board and the piece, excited by a very short burst of noise."""
    rng = random.Random(seed)
    count = int(_RATE * 0.16)
    # (frequency in Hz, decay time in s, loudness): the board's thump, then the hard
    # clicks of the piece's edge, each a little out of tune with the others.
    modes = (
        (165 * pitch, 0.045, 0.9),
        (310 * pitch, 0.030, 0.55),
        (980 * pitch, 0.012, 0.35),
        (1630 * pitch, 0.009, 0.30),
        (2470 * pitch, 0.006, 0.22),
        (3720 * pitch, 0.004, 0.15),
    )
    phases = [rng.uniform(0, math.tau) for _ in modes]
    out = []
    smooth = 0.0
    for i in range(count):
        time = i / _RATE
        attack = min(1.0, i / 22)  # half a millisecond: no click from a sudden start
        value = 0.0
        for (frequency, decay, loudness), phase in zip(modes, phases):
            value += loudness * math.exp(-time / decay) * math.sin(math.tau * frequency * time + phase)
        noise = rng.uniform(-1, 1) * math.exp(-time / 0.0025)
        smooth += (noise - smooth) * 0.35  # a one-pole low-pass takes the hiss off the contact noise
        out.append(strength * attack * (0.42 * value + 0.55 * smooth))
    return out


def _bloop(start: float, end: float, seconds: float, volume: float = 0.45) -> Samples:
    """A sine whose pitch glides up fast: a bubble popping on the surface."""
    count = int(_RATE * seconds)
    out = []
    phase = 0.0
    for i in range(count):
        share = i / count
        frequency = start * (end / start) ** (share ** 0.6)
        phase += math.tau * frequency / _RATE
        envelope = min(1.0, i / 60) * (1 - share) ** 1.6
        out.append(volume * envelope * (math.sin(phase) + 0.18 * math.sin(2 * phase)))
    return out


def _square(frequency: float, seconds: float, volume: float = 0.18, duty: float = 0.25) -> Samples:
    """A square wave with a short fade: the sound of old game consoles."""
    count = int(_RATE * seconds)
    period = _RATE / frequency
    return [
        volume * (1.0 if (i % period) < period * duty else -1.0)
        * min(1.0, (count - i) / (count * 0.3)) * min(1.0, i / 40)
        for i in range(count)
    ]


_BUILDERS: dict[str, Callable[[], Samples]] = {
    "wood_move": lambda: _knock(1.0, 1.0, seed=3),
    "wood_capture": lambda: _mix((0.0, _knock(0.55, 1.12, seed=5)), (0.055, _knock(1.0, 0.94, seed=8))),
    "classic_move": lambda: _tone(520, 0.045),
    "classic_capture": lambda: _tone(320, 0.07),
    "bubble_move": lambda: _bloop(260, 980, 0.085),
    "bubble_capture": lambda: _mix((0.0, _bloop(220, 760, 0.07)), (0.06, _bloop(300, 1250, 0.09))),
    "retro_move": lambda: _concat(_square(660, 0.035), _square(990, 0.05)),
    "retro_capture": lambda: _concat(_square(990, 0.03), _square(740, 0.03), _square(494, 0.06)),
    "check": lambda: _concat(_tone(700, 0.06), _tone(880, 0.07)),
    "end": lambda: _concat(_tone(520, 0.09), _tone(390, 0.09), _tone(290, 0.16)),
    "correct": lambda: _concat(_tone(620, 0.07), _tone(830, 0.1)),
    "wrong": lambda: _tone(210, 0.14),
}
SOUND_NAMES = tuple(_BUILDERS)


def render(name: str) -> Samples:
    return _BUILDERS[name]()


def _write_wave(path: Path, samples: Samples) -> None:
    peak = max((abs(value) for value in samples), default=0.0)
    gain = 0.8 / peak if peak > 0.8 else 1.0  # never clips
    frames = bytearray()
    for value in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value * gain)) * 32767))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        out.writeframes(bytes(frames))


class SoundPlayer:
    def __init__(self, enabled: bool = True, style: str = DEFAULT_STYLE) -> None:
        self.enabled = enabled
        self.style = style if style in MOVE_STYLES else DEFAULT_STYLE
        self._paths: dict[str, Path] = {}
        self._folder = data_dir() / f"sounds{SOUND_VERSION}"

    def set_style(self, style: str) -> None:
        self.style = style if style in MOVE_STYLES else DEFAULT_STYLE

    def file_name(self, name: str) -> str:
        """The sound that plays for an event: moves and captures in the chosen style."""
        return f"{self.style}_{name}" if name in ("move", "capture") else name

    def path_for(self, name: str) -> Path | None:
        """The file of a sound, made on first use, so a start does not wait for all of them."""
        path = self._paths.get(name)
        if path is not None:
            return path
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            path = self._folder / f"{name}.wav"
            if not path.exists():
                _write_wave(path, render(name))
        except OSError:
            return None
        self._paths[name] = path
        return path

    def play(self, name: str) -> None:
        if not self.enabled or winsound is None:
            return
        path = self.path_for(self.file_name(name))
        if path is None:
            return
        try:
            winsound.PlaySound(
                str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except RuntimeError:
            pass
