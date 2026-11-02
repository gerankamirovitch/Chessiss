"""Download the official Stockfish release into ~/Downloads and install it into
engines/stockfish/. The binary is not stored in the repository."""
from __future__ import annotations

import hashlib
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

TAG = "sf_19"
ASSET = "stockfish-windows-x86-64-universal.zip"
SHA256 = "3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7"
URL = f"https://github.com/official-stockfish/Stockfish/releases/download/{TAG}/{ASSET}"
ATTEMPTS = 40

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = ROOT / "engines" / "stockfish"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(path: Path) -> None:
    """Resumes after dropped connections using HTTP range requests."""
    for attempt in range(1, ATTEMPTS + 1):
        done = path.stat().st_size if path.exists() else 0
        request = urllib.request.Request(URL, headers={"Range": f"bytes={done}-"} if done else {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if done and response.status != 206:
                    done = 0  # the server ignored the range, start over
                with path.open("ab" if done else "wb") as out:
                    while chunk := response.read(1 << 16):
                        out.write(chunk)
                        done += len(chunk)
            return
        except urllib.error.HTTPError as error:
            if error.code == 416:  # already complete
                return
            print(f"attempt {attempt}: HTTP {error.code}", flush=True)
        except OSError as error:
            print(f"attempt {attempt}: {error}, have {done} bytes", flush=True)
        time.sleep(3)
    raise SystemExit("download failed")


def main() -> None:
    archive = Path.home() / "Downloads" / ASSET
    if not archive.exists() or sha256_of(archive) != SHA256:
        download(archive)
    actual = sha256_of(archive)
    if actual != SHA256:
        archive.unlink()
        raise SystemExit(f"checksum mismatch: {actual}, the file was removed")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        exe = next(n for n in names if n.lower().endswith(".exe") and "stockfish" in n.lower())
        with bundle.open(exe) as source, (TARGET_DIR / "stockfish.exe").open("wb") as target:
            shutil.copyfileobj(source, target)
        # GPLv3 requires the license text to travel with the binary.
        for name in names:
            if Path(name).name.lower() in ("copying.txt", "copying"):
                with bundle.open(name) as source, (TARGET_DIR / "Copying.txt").open("wb") as target:
                    shutil.copyfileobj(source, target)
    print(f"installed {TARGET_DIR / 'stockfish.exe'} ({TAG})")


if __name__ == "__main__":
    sys.exit(main())
