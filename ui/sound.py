"""Short generated sounds, played through winsound. No audio files in the repository."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from core.paths import data_dir

try:
    import winsound
except ImportError:  # not Windows: stay silent
    winsound = None

_RATE = 22050
_SOUNDS = {
    "move": [(520, 0.045)],
    "capture": [(320, 0.07)],
    "check": [(700, 0.06), (880, 0.07)],
    "end": [(520, 0.09), (390, 0.09), (290, 0.16)],
    "correct": [(620, 0.07), (830, 0.1)],
    "wrong": [(210, 0.14)],
}


def _write_wave(path: Path, tones: list[tuple[int, float]]) -> None:
    frames = bytearray()
    for frequency, seconds in tones:
        count = int(_RATE * seconds)
        for index in range(count):
            envelope = min(1.0, (count - index) / (count * 0.6)) * min(1.0, index / 60)
            sample = int(9000 * envelope * math.sin(2 * math.pi * frequency * index / _RATE))
            frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        out.writeframes(bytes(frames))


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._paths: dict[str, Path] = {}
        if winsound is None:
            return
        try:
            folder = data_dir() / "sounds"
            folder.mkdir(exist_ok=True)
            for name, tones in _SOUNDS.items():
                path = folder / f"{name}.wav"
                if not path.exists():
                    _write_wave(path, tones)
                self._paths[name] = path
        except OSError:
            self._paths = {}

    def play(self, name: str) -> None:
        if not self.enabled or winsound is None:
            return
        path = self._paths.get(name)
        if path is None:
            return
        try:
            winsound.PlaySound(
                str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except RuntimeError:
            pass
