"""English localization: the catalog covers the code, and nothing Russian reaches the screen."""
import ast
import re
from pathlib import Path

import chess
import pytest

from core.clock import UNTIMED
from core.engine import Line, Score
from core.explain import explain_move, motifs_of_move, position_text
from core.game import GameOutcome, GameSetup, Mode, Termination
from core.i18n import EN, set_language, t, written_in_current_language
from core.pgn_io import display_player, display_san

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [*sorted((ROOT / "core").glob("*.py")), *sorted((ROOT / "ui").glob("*.py"))]
CYRILLIC = re.compile("[Ѐ-ӿ]")

# Words of the Russian grammar. English has its own branches for them.
RUSSIAN_ONLY = {
    "core/i18n.py": None,  # the catalog itself
    "core/pgn_io.py": {"К", "С", "Л", "Ф", "Кр", r"^Stockfish, (?:уровень|level) (\d+)$"},
    "core/clock.py": {"Своё", "Тренировка"},  # never shown, the dialog and tables use their own texts
    "core/explain.py": {
        "|сантипешка]]", "сантипешка", "сантипешки", "сантипешек", "вилка", "двойной удар", "связка", "качество",
        "матовая угроза", "неточность", "ошибка", "зевок", "ход", "ходов", "хода",
        "пешки", "ладьи", "пешек", "фигур", "два", "две", "три", "четыре",
        "ней", "ним", "неё", "него", "была", "её", "был", "его",
    },
}


def _constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and ast.get_docstring(node) is not None:
            docstrings.add(id(node.body[0].value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.fixture
def english():
    set_language("en")
    yield
    set_language("ru")


@pytest.mark.parametrize("path", SOURCES, ids=_relative)
def test_every_russian_text_in_the_code_has_an_english_form(path):
    allowed = RUSSIAN_ONLY.get(_relative(path), set())
    if allowed is None:
        return
    for text in _constants(path):
        if CYRILLIC.search(text) and text not in allowed:
            assert text in EN or text.strip(" .,:") in allowed, f"{path.name}: {text!r}"


def test_catalog_has_no_dead_entries():
    used = {text for path in SOURCES if path.name != "i18n.py" for text in _constants(path)}
    assert sorted(key for key in EN if key not in used) == []


def test_english_forms_are_english_and_keep_their_placeholders():
    fields = re.compile(r"\{(\w+)\}")
    pronouns = {"pronoun", "was"}  # Russian grammar, English sentences do not need them
    for ru, en in EN.items():
        assert not CYRILLIC.search(re.sub(r"\|[^\]]*\]\]", "", en)), en
        assert set(fields.findall(ru)) - pronouns == set(fields.findall(en)), ru


def test_russian_stays_the_default_and_unknown_codes_fall_back_to_it():
    assert t("Настройки") == "Настройки"
    set_language("de")
    assert t("Настройки") == "Настройки"


def test_saved_text_is_checked_against_the_current_language(english):
    assert written_in_current_language("This move wins a pawn.")
    assert not written_in_current_language("Ход выигрывает пешку.")
    set_language("ru")
    assert written_in_current_language("Ход выигрывает пешку.")
    assert not written_in_current_language("This move wins a pawn.")


# --- explanations in English --------------------------------------------------

def line(cp, *ucis, mate=None):
    return Line(Score(cp, mate), tuple(chess.Move.from_uci(u) for u in ucis))


def explained(fen, uci, best, after):
    board = chess.Board(fen)
    return explain_move(board, chess.Move.from_uci(uci), best, after).render(set())


def test_english_fork_explanation(english):
    text = explained(
        "r3k3/ppp2ppp/8/1N6/8/8/PPP2PPP/4K2R w - - 0 1", "b5c7", line(800, "b5c7"), line(800, "e8d7", "c7a8"),
    )
    assert "This move wins a rook and a pawn." in text
    assert "This is a fork (a knight or pawn attacks two pieces at once" in text
    assert "the knight attacks the rook and the king at once" in text
    assert "Evaluation: White is ahead by 8.0 pawns." in text
    assert not CYRILLIC.search(text)


def test_english_blunder_uses_standard_notation_and_defines_the_terms(english):
    text = explained(
        "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3", "g8f6",
        line(-50, "g7g6"), line(9999, "h5f7", mate=1),
    )
    assert text.startswith("Blunder (a move more than 3 pawns worse")
    assert "This move allows mate in 1 move." in text
    assert "The opponent replies Qxf7 and mates." in text
    assert "g6 was better:" in text
    assert not CYRILLIC.search(text)


@pytest.mark.parametrize("fen, uci", [
    ("r3k3/ppp2ppp/8/1N6/8/8/PPP2PPP/4K2R w - - 0 1", "b5c7"),  # fork
    ("3qk3/8/8/8/3n4/8/3R4/4K2Q w - - 0 1", "d2d4"),  # capture
    ("4k3/8/8/3r4/8/8/8/3QK3 w - - 0 1", "d1d5"),  # free rook
    ("6k1/5ppp/8/8/8/8/5PPP/3QR1K1 w - - 0 1", "d1d8"),  # back rank mate
    ("3k4/3r4/8/8/8/8/8/3RK2B w - - 0 1", "h1g2"),  # quiet
])
def test_motifs_have_no_russian_left(english, fen, uci):
    for motif in motifs_of_move(chess.Board(fen), chess.Move.from_uci(uci)):
        assert not CYRILLIC.search(re.sub(r"\|[^\]]*\]\]", "", motif.clause)), motif.clause


def test_english_evaluation_and_game_texts(english):
    assert position_text(Score(150)) == "Evaluation: White is ahead by 1.5 pawns."
    assert position_text(Score(0)) == "Evaluation: the position is about equal."
    assert position_text(Score(-1000, -3)) == "Evaluation: Black mates in 3 moves."
    assert GameOutcome("1-0", Termination.CHECKMATE).text == "White won: checkmate."
    assert GameOutcome("1/2-1/2", Termination.STALEMATE).text == "Draw: stalemate."


def test_notation_and_saved_names_follow_the_language(english):
    assert display_san("Nf3") == "Nf3"
    assert display_player("Белые") == "White"
    assert display_player("Stockfish, уровень 7") == "Stockfish, level 7"
    assert display_player("Magnus") == "Magnus"
    set_language("ru")
    assert display_san("Nf3") == "Кf3"
    assert display_player("Black") == "Чёрные"
    assert display_player("Stockfish, level 7") == "Stockfish, уровень 7"


def test_game_setup_is_unaffected_by_language(english):
    assert GameSetup(Mode.LOCAL, UNTIMED).time_control.storage_key == "0+0"
