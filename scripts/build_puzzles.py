"""Builds data/puzzles.json from the Lichess puzzle database (CC0).

Reads the compressed CSV as a stream and stops once every theme is full, so the
multi-hundred-megabyte file is not downloaded whole. Run once by the developer;
the app itself never touches the network.

In the database, FEN is the position before the opponent's move, and the first
move of the list is that opponent's move. Here that move is already applied:
the stored position is what the solver sees.

Selection:
- ratings 1400-2800 in four equal bands per theme, so every theme has easy and hard ones;
- the solver makes at least two moves (except mate in one);
- one puzzle per source game, and no position that is nearly the same as one already
  picked for the theme (same pieces on the same squares, give or take a few).
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
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "puzzles.json"
sys.path.insert(0, str(ROOT))

from core.puzzles import THEMES  # noqa: E402

PER_THEME = 160
RATING_BUCKETS = ((1400, 1750), (1750, 2050), (2050, 2350), (2350, 2800))
MIN_POPULARITY = 80
MIN_PLAYS = 250
MAX_RATING_DEVIATION = 90
MIN_SOLVER_MOVES = 2
SIMILAR = 0.8  # share of shared piece-squares above which two positions count as repeats
MAX_ROWS = 5_000_000

# Lichess tag for each of our themes, tried from the rarest to the most common, so that
# a puzzle with several tags fills the theme that needs it most.
TAGS = (
    ("double_check", "doubleCheck"),
    ("zugzwang", "zugzwang"),
    ("back_rank", "backRankMate"),
    ("skewer", "skewer"),
    ("discovered", "discoveredAttack"),
    ("attraction", "attraction"),
    ("deflection", "deflection"),
    ("quiet", "quietMove"),
    ("promotion", "promotion"),
    ("endgame", "endgame"),
    ("sacrifice", "sacrifice"),
    ("pin", "pin"),
    ("fork", "fork"),
)
MATES = {"mateIn1": ("mate1", 1), "mateIn2": ("mate2", 2), "mateIn3": ("mate3", 3), "mateIn4": ("mate4", 4)}
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def material(board: chess.Board, color: bool) -> int:
    return sum(len(board.pieces(piece, color)) * value for piece, value in VALUES.items())


def balance(board: chess.Board, color: bool) -> int:
    return material(board, color) - material(board, not color)


def candidate_themes(row: dict[str, str], board: chess.Board, before: int, solver: bool, solver_moves: int) -> list[str]:
    """Our themes this puzzle may go to, best fit first."""
    tags = set(row["Themes"].split())
    mated = board.is_checkmate()
    themes = []
    for tag, (theme, moves) in MATES.items():
        if tag in tags and mated and solver_moves == moves:
            themes.append(theme)
    if solver_moves < MIN_SOLVER_MOVES:
        return themes  # mate in one is the only short puzzle we keep
    gained = balance(board, solver) - before
    for theme, tag in TAGS:
        if tag in tags and (mated or gained >= 2 or theme in ("zugzwang", "quiet", "promotion", "endgame")):
            if theme == "back_rank":
                themes.insert(0, theme)  # a back-rank mate is a better label than "mate in N"
            else:
                themes.append(theme)
    if not mated and ("crushing" in tags or "advantage" in tags) and gained >= 3:
        themes.append("material")
    return themes


def parse(row: dict[str, str]) -> tuple[dict, list[str]] | None:
    """Replays the line with python-chess. Returns the stored form and the themes it fits."""
    moves = row["Moves"].split()
    if len(moves) < 2 or len(moves) % 2 != 0:
        return None
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
    themes = candidate_themes(row, board, before, solver, len(moves) // 2)
    if not themes:
        return None
    return {
        "id": row["PuzzleId"],
        "fen": start,
        "solution": moves[1:],
        "rating": int(row["Rating"]),
    }, themes


def bucket_of(rating: int) -> int | None:
    for index, (low, high) in enumerate(RATING_BUCKETS):
        if low <= rating < high:
            return index
    return None


def squares(fen: str) -> frozenset[tuple[int, str]]:
    board = chess.Board(fen)
    return frozenset((square, piece.symbol()) for square, piece in board.piece_map().items())


def too_similar(placement: frozenset, picked: list[frozenset]) -> bool:
    for other in picked:
        shared = len(placement & other)
        if shared / max(len(placement | other), 1) >= SIMILAR:
            return True
    return False


def main() -> None:
    per_bucket = PER_THEME // len(RATING_BUCKETS)
    picked: dict[tuple[str, int], list[dict]] = defaultdict(list)
    placements: dict[str, list[frozenset]] = defaultdict(list)
    games: set[str] = set()
    wanted = len(THEMES) * len(RATING_BUCKETS)
    skipped_repeats = 0

    request = urllib.request.Request(URL, headers={"User-Agent": "Chessiss puzzle builder"})
    seen = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        stream = zstandard.ZstdDecompressor().stream_reader(response)
        for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8")):
            seen += 1
            if seen > MAX_ROWS:
                break
            if (
                int(row["Popularity"]) < MIN_POPULARITY
                or int(row["NbPlays"]) < MIN_PLAYS
                or int(row["RatingDeviation"]) > MAX_RATING_DEVIATION
            ):
                continue
            bucket = bucket_of(int(row["Rating"]))
            if bucket is None:
                continue
            game = row["GameUrl"].split("#")[0]
            if game in games:
                continue
            parsed = parse(row)
            if parsed is None:
                continue
            puzzle, themes = parsed
            for theme in themes:
                slot = picked[(theme, bucket)]
                if len(slot) >= per_bucket:
                    continue
                placement = squares(puzzle["fen"])
                if too_similar(placement, placements[theme]):
                    skipped_repeats += 1
                    break
                slot.append({**puzzle, "theme": theme})
                placements[theme].append(placement)
                games.add(game)
                full = sum(len(s) >= per_bucket for s in picked.values())
                total = sum(len(s) for s in picked.values())
                if total % 100 == 0:
                    print(f"read {seen}, picked {total}, full slots {full}/{wanted}", flush=True)
                break
            if sum(len(s) >= per_bucket for s in picked.values()) == wanted:
                break

    puzzles = sorted(
        (p for slot in picked.values() for p in slot), key=lambda p: (p["theme"], p["rating"], p["id"])
    )
    counts = {theme: sum(p["theme"] == theme for p in puzzles) for theme in THEMES}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as out:
        out.write('{\n"source": "Lichess puzzle database (CC0), https://database.lichess.org/",\n"puzzles": [\n')
        out.write(",\n".join(json.dumps(p, separators=(",", ":")) for p in puzzles))
        out.write("\n]\n}\n")
    print(f"wrote {len(puzzles)} puzzles from {seen} rows to {OUTPUT}; skipped {skipped_repeats} near repeats")
    print(counts)


if __name__ == "__main__":
    main()
