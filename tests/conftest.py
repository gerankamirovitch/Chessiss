import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESSISS_DATA_DIR", str(tmp_path / "data"))


def _stockfish() -> Path | None:
    bundled = sorted((ROOT / "engines" / "stockfish").glob("stockfish*.exe"))
    if bundled:
        return bundled[0]
    found = shutil.which("stockfish")
    return Path(found) if found else None


@pytest.fixture(scope="session")
def stockfish_path() -> Path:
    path = _stockfish()
    if path is None:
        pytest.skip("Stockfish binary is missing, run scripts/fetch_stockfish.py")
    return path


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()
