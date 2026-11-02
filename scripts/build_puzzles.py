"""Builds data/puzzles.json from the Lichess puzzle database (CC0).

Reads the compressed CSV as a stream and stops once every theme is full, so the
multi-hundred-megabyte file is not downloaded whole. Run once by the developer;
the app itself never touches the network.

In the database, FEN is the position before the opponent's move, and the first
move of the list is that opponent's move. Here that move is already applied:
the stored position is what the solver sees.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import chess
import zstandard

URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "puzzles.json"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.puzzles import THEMES  # noqa: E402

PER_THEME = 100
RATING_BUCKETS = ((600, 1000), (1000, 1400), (1400, 1800), (1800, 2300))
MIN_POPULARITY = 80
MIN_PLAYS = 300
MAX_RATING_DEVIATION = 100
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def material(board: chess.Board, color: bool) -> int:
    return sum(len(board.pieces(piece, color)) * value for piece, value in VALUES.items())


def balance(board: chess.Board, color: bool) -> int:
    return material(board, color) - material(board, not color)


def parse(row: dict[str, str]) -> dict | None:
    """Replays the line with python-chess and returns the stored form, or None if
    the puzzle is not usable or does not fit one of the app's themes."""
    themes = set(row["Themes"].split())
    moves = row["Moves"].split()
    board = chess.Board(row["FEN"])
    try:
        board.push_uci(moves[0])
        start = board.fen()
        solver = board.turn
        before = balance(board, solver)
        for uci in moves[1:]:
            board.push_uci(uci)
    except ValueError:
        return None
    if len(moves) < 2 or len(moves) % 2 != 0:
        return None

    if "mateIn1" in themes and len(moves) == 2 and board.is_checkmate():
        theme = "mate1"
    elif "mateIn2" in themes and len(moves) == 4 and board.is_checkmate():
        theme = "mate2"
    elif "mateIn3" in themes and len(moves) == 6 and board.is_checkmate():
        theme = "mate3"
    elif board.is_checkmate() or "mate" in themes:
        return None
    elif "fork" in themes and balance(board, solver) - before >= 2:
        theme = "fork"
    elif "pin" in themes and balance(board, solver) - before >= 2:
        theme = "pin"
    elif ("crushing" in themes or "advantage" in themes) and balance(board, solver) - before >= 3:
        theme = "material"
    else:
        return None
    return {
        "id": row["PuzzleId"],
        "fen": start,
        "solution": moves[1:],
        "theme": theme,
        "rating": int(row["Rating"]),
    }


def bucket_of(rating: int) -> int | None:
    for index, (low, high) in enumerate(RATING_BUCKETS):
        if low <= rating < high:
            return index
    return None


def main() -> None:
    per_bucket = PER_THEME // len(RATING_BUCKETS)
    picked: dict[tuple[str, int], list[dict]] = defaultdict(list)
    wanted = len(THEMES) * len(RATING_BUCKETS)

    request = urllib.request.Request(URL, headers={"User-Agent": "Chessiss puzzle builder"})
    seen = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        stream = zstandard.ZstdDecompressor().stream_reader(response)
        for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8")):
            seen += 1
            if (
                int(row["Popularity"]) < MIN_POPULARITY
                or int(row["NbPlays"]) < MIN_PLAYS
                or int(row["RatingDeviation"]) > MAX_RATING_DEVIATION
            ):
                continue
            bucket = bucket_of(int(row["Rating"]))
            if bucket is None:
                continue
            puzzle = parse(row)
            if puzzle is None:
                continue
            slot = picked[(puzzle["theme"], bucket)]
            if len(slot) < per_bucket:
                slot.append(puzzle)
                full = sum(len(s) >= per_bucket for s in picked.values())
                total = sum(len(s) for s in picked.values())
                if total % 50 == 0:
                    print(f"read {seen}, picked {total}, full slots {full}/{wanted}", flush=True)
                if full == wanted:
                    break

    puzzles = sorted(
        (p for slot in picked.values() for p in slot), key=lambda p: (p["theme"], p["rating"], p["id"])
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as out:
        out.write('{\n"source": "Lichess puzzle database (CC0), https://database.lichess.org/",\n"puzzles": [\n')
        out.write(",\n".join(json.dumps(p, separators=(",", ":")) for p in puzzles))
        out.write("\n]\n}\n")
    print(f"wrote {len(puzzles)} puzzles from {seen} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
