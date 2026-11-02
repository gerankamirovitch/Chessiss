"""Explanation generator on known positions. The engine lines here are written by
hand, so these tests check the pattern recognition and wording, not Stockfish."""
import chess
import pytest

from core.engine import EVAL_CLAMP, Line, Score
from core.explain import (
    Mark,
    ai_accepts_draw,
    build_hints,
    centipawns_text,
    classify,
    explain_move,
    material_along,
    motifs_of_move,
    position_text,
    render_terms,
    see,
)


def kinds(fen, uci):
    return [m.kind for m in motifs_of_move(chess.Board(fen), chess.Move.from_uci(uci))]


def line(cp, *ucis, mate=None):
    return Line(Score(cp, mate), tuple(chess.Move.from_uci(u) for u in ucis))


# --- SEE ---

def test_see_undefended_piece_is_won_outright():
    board = chess.Board("4k3/8/8/4n3/8/8/4R3/4K3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 3


def test_see_defended_piece_with_worse_attacker_is_not_won():
    board = chess.Board("4k3/8/3p4/4n3/8/8/4Q3/4K3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 0, "queen takes defended knight loses the queen"


def test_see_pawn_takes_defended_knight_still_wins():
    board = chess.Board("4k3/8/3p4/4n3/3P4/8/8/4K3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 2


def test_see_counts_xray_batteries():
    even = chess.Board("4k3/4r3/4r3/4n3/8/4R3/4R3/4K3 w - - 0 1")
    assert see(even, chess.E5, chess.WHITE) == 0
    outnumbered = chess.Board("4k3/8/4r3/4n3/8/4R3/4R3/4K3 w - - 0 1")
    assert see(outnumbered, chess.E5, chess.WHITE) == 3


def test_see_pinned_defender_does_not_count():
    # The d6 pawn is pinned to the king on the d-file, so it cannot recapture on e5.
    board = chess.Board("3k4/8/3p4/4n3/8/8/4R3/3RK3 w - - 0 1")
    assert see(board, chess.E5, chess.WHITE) == 3


def test_see_empty_or_own_square_is_zero():
    board = chess.Board()
    assert see(board, chess.E4, chess.WHITE) == 0
    assert see(board, chess.E2, chess.WHITE) == 0


# --- tactical motifs ---

def test_knight_fork_on_king_and_rook():
    motifs = motifs_of_move(chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"), chess.Move.from_uci("b5c7"))
    assert motifs[0].kind == "fork"
    assert "конь" in motifs[0].clause and "короля" in motifs[0].clause and "ладью" in motifs[0].clause


def test_knight_fork_on_queen_and_rook():
    assert "fork" in kinds("6k1/8/1q3r2/8/4N3/8/8/K7 w - - 0 1", "e4d5")


def test_pawn_fork():
    assert "fork" in kinds("4k3/8/2n1n3/8/3P4/8/8/4K3 w - - 0 1", "d4d5")


def test_pawn_taken_by_one_of_its_targets_is_no_fork():
    assert "fork" not in kinds("4k3/8/2n1b3/8/3P4/8/8/4K3 w - - 0 1", "d4d5")


def test_fork_needs_a_safe_square():
    # The c7 rook simply takes the knight landing on its square's neighbour.
    assert "fork" not in kinds("r3k3/2r5/8/1N6/8/8/8/4K3 w - - 0 1", "b5d6")


def test_attack_on_defended_pawns_is_no_fork():
    assert "fork" not in kinds("4k3/8/2p1p3/3p4/8/4N3/8/4K3 w - - 0 1", "e3c4")


def test_queen_double_attack_is_named_double_attack_not_fork():
    found = kinds("4k3/8/8/n7/8/8/8/3QK3 w - - 0 1", "d1a4")
    assert "double_attack" in found, "check on e8 plus the loose knight on a5"
    assert "fork" not in found


def test_queen_attacked_back_by_its_target_is_no_double_attack():
    assert "double_attack" not in kinds("4k3/8/8/8/7r/8/8/3QK3 w - - 0 1", "d1a4")


def test_discovered_attack_is_a_double_attack():
    # The bishop leaves the e-file and hits the loose a6 knight, the rook behind it hits the queen.
    motifs = motifs_of_move(chess.Board("4q1k1/8/n7/8/8/8/4B3/4RK2 w - - 0 1"), chess.Move.from_uci("e2d3"))
    motif = next(m for m in motifs if m.kind == "double_attack")
    assert "слон нападает на коня" in motif.clause
    assert "под ударом ферзь" in motif.clause


def test_absolute_pin_to_king():
    motifs = motifs_of_move(chess.Board("4k3/8/2n5/8/8/8/8/4KB2 w - - 0 1"), chess.Move.from_uci("f1b5"))
    pin = next(m for m in motifs if m.kind == "pin")
    assert "коня на c6" in pin.clause and "король" in pin.clause


def test_relative_pin_to_queen():
    assert "pin" in kinds("3qk3/8/8/3n4/8/8/8/4KR2 w - - 0 1", "f1d1")


def test_no_pin_when_piece_behind_is_cheaper():
    assert "pin" not in kinds("3nk3/8/8/3q4/8/8/8/4KR2 w - - 0 1", "f1d1")


def test_no_pin_when_pinner_just_gets_taken():
    assert "pin" not in kinds("4k3/3p4/2n5/1p6/8/8/8/4KB2 w - - 0 1", "f1b5")


def test_mate_detected():
    assert kinds("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "h5f7") == ["mate"]


def test_mate_threat_detected():
    assert "mate_threat" in kinds("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3", "d1h5")


def test_quiet_move_is_no_mate_threat():
    assert "mate_threat" not in kinds(chess.STARTING_FEN, "e2e4")


def test_old_mate_threat_is_not_reported_again():
    # White already had Qxf7 mate available. A pawn move on the other wing creates nothing.
    assert "mate_threat" not in kinds("r1bqkb1r/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 4", "a2a3")


def test_taking_an_undefended_piece():
    assert "wins_hanging" in kinds("4k3/8/8/4n3/8/8/4R3/4K3 w - - 0 1", "e2e5")


def test_taking_a_defended_piece_is_not_winning_a_hanging_piece():
    assert "wins_hanging" not in kinds("4k3/8/3p4/4n3/8/8/4R3/4K3 w - - 0 1", "e2e5")


def test_moving_an_attacked_piece_away():
    motifs = motifs_of_move(chess.Board("4k3/8/8/4r3/8/8/4N3/6K1 w - - 0 1"), chess.Move.from_uci("e2c3"))
    saves = next(m for m in motifs if m.kind == "saves")
    assert "уводит коня на e2" in saves.clause


def test_defending_an_attacked_piece():
    motifs = motifs_of_move(chess.Board("4k3/8/8/4r3/8/8/4N3/R5K1 w - - 0 1"), chess.Move.from_uci("a1e1"))
    saves = next(m for m in motifs if m.kind == "saves")
    assert saves.clause == "конь на e2 был под ударом, и этот ход его защищает"


# --- material ---

def test_material_winning_a_queen():
    board = chess.Board("4k3/8/8/4q3/8/8/4R3/4K3 w - - 0 1")
    result = material_along(board, [chess.Move.from_uci("e2e5")], chess.WHITE)
    assert result.net == 9 and result.phrase == "ферзя"


def test_material_even_trade_is_nothing():
    board = chess.Board("4k3/8/3p4/4n3/8/5N2/8/4K3 w - - 0 1")
    moves = [chess.Move.from_uci(u) for u in ("f3e5", "d6e5")]
    result = material_along(board, moves, chess.WHITE)
    assert result.net == 0 and result.phrase is None


def test_material_detects_winning_the_exchange():
    board = chess.Board("4k3/8/4p3/3r4/8/2N5/8/4K3 w - - 0 1")
    moves = [chess.Move.from_uci(u) for u in ("c3d5", "e6d5")]
    result = material_along(board, moves, chess.WHITE)
    assert result.wins_exchange
    assert "качество" in result.phrase


def test_material_ignores_final_capture_that_gets_recaptured():
    board = chess.Board("4k3/8/3p4/4p3/8/8/4Q3/4K3 w - - 0 1")
    result = material_along(board, [chess.Move.from_uci("e2e5")], chess.WHITE)
    assert result.net <= 0


# --- explain_move wording ---

def test_best_move_wording():
    board = chess.Board()
    explanation = explain_move(board, chess.Move.from_uci("e2e4"), line(30, "e2e4", "e7e5"), line(25, "e7e5"))
    assert explanation.is_best and explanation.cp_loss == 0 and explanation.mark == Mark.EXCELLENT
    assert "Лучший ход" in explanation.render(set())


def test_equal_alternative_says_nothing_changes():
    board = chess.Board()
    explanation = explain_move(board, chess.Move.from_uci("d2d4"), line(30, "e2e4"), line(25, "d7d5"))
    assert explanation.cp_loss == 5
    assert "ничего не меняет" in explanation.render(set())


def test_loss_is_stated_in_pawns_centipawns_and_with_better_move():
    board = chess.Board("4k3/8/8/4r3/8/8/4N3/6K1 w - - 0 1")
    explanation = explain_move(board, chess.Move.from_uci("g1h1"), line(-200, "e2c3", "e5e6"), line(-500, "e5e2"))
    text = explanation.render(set())
    assert explanation.cp_loss == 300 and explanation.mark == Mark.BLUNDER
    assert "ослабил позицию на 3,0 пешки" in text
    assert "300 сантипешек" in text
    assert "Лучше был ход Кc3" in text
    assert "из-под удара" in text, "the reason for the better move"
    assert "Конь на e2 остаётся под ударом, защиты нет." in text
    assert "Соперник отвечает Лxe2 и выигрывает фигуру." in text
    assert explanation.best_san == "Nc3"


def test_feminine_pieces_agree_in_gender():
    board = chess.Board("4k3/8/8/4q3/8/2R5/8/R5K1 w - - 0 1")
    saves = next(
        m for m in motifs_of_move(board, chess.Move.from_uci("a1a3")) if m.kind == "saves"
    )
    assert saves.clause == "ладья на c3 была под ударом, и этот ход её защищает"
    hanging = explain_move(board, chess.Move.from_uci("g1h1"), line(-100, "c3c5"), line(-400, "e5c3"))
    assert "Ладья на c3 остаётся под ударом" in hanging.render(set())


def test_black_move_loss_uses_blacks_point_of_view():
    board = chess.Board("4k3/8/8/8/8/8/4P3/4K3 b - - 0 1")
    explanation = explain_move(board, chess.Move.from_uci("e8e7"), line(100, "e8d7"), line(350, "e2e4"))
    assert explanation.cp_loss == 250
    assert explanation.mark == Mark.MISTAKE


def test_improvement_above_engine_estimate_is_not_a_negative_loss():
    board = chess.Board()
    explanation = explain_move(board, chess.Move.from_uci("d2d4"), line(10, "e2e4"), line(40, "d7d5"))
    assert explanation.cp_loss == 0


def test_checkmating_move():
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    explanation = explain_move(board, chess.Move.from_uci("h5f7"), line(EVAL_CLAMP, "h5f7", mate=1), None)
    assert explanation.score.cp == EVAL_CLAMP
    assert "мат" in explanation.render(set())


def test_stalemate_blunder_evaluated_as_zero():
    board = chess.Board("7k/5Q2/8/6K1/8/8/8/8 w - - 0 1")
    explanation = explain_move(board, chess.Move.from_uci("g5g6"), line(EVAL_CLAMP, "f7f8", mate=1), None)
    assert explanation.score.cp == 0
    assert explanation.mark == Mark.BLUNDER


def test_blunder_allowing_mate_names_the_mating_reply():
    board = chess.Board("6k1/p4ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1")
    explanation = explain_move(
        board, chess.Move.from_uci("a7a6"), line(0, "g7g6"), line(EVAL_CLAMP, "d1d8", mate=1),
    )
    assert explanation.mark == Mark.BLUNDER
    text = explanation.render(set())
    assert "Соперник отвечает Лd8 и ставит мат." in text
    assert "Ход допускает мат в 1 ход." in text
    assert "защищает от мата" in text, "why g6 was better"


def test_move_winning_material_says_so():
    board = chess.Board("4k3/8/8/4n3/8/8/4R3/4K3 w - - 0 1")
    explanation = explain_move(board, chess.Move.from_uci("e2e5"), line(600, "e2e5"), line(600, "e8d7"))
    assert "выигрывает фигуру" in explanation.render(set())


def test_recapture_is_not_called_winning_a_piece():
    board = chess.Board("4k3/8/2b5/3n4/8/4N3/8/4K3 w - - 0 1")
    board.push_uci("e3d5")
    explanation = explain_move(board, chess.Move.from_uci("c6d5"), line(0, "c6d5"), line(0, "e1e2"))
    text = explanation.render(set())
    assert "отыгрывает" in text
    assert "выигрывает" not in text


def test_position_text():
    assert "равна" in position_text(Score(10))
    assert "у белых перевес 1,5 пешки" in position_text(Score(150))
    assert "у чёрных перевес 0,5 пешки" in position_text(Score(-50))
    assert "белые ставят мат в 3 хода" in position_text(Score(EVAL_CLAMP, 3))
    assert "чёрные ставят мат в 5 ходов" in position_text(Score(-EVAL_CLAMP, -5))


@pytest.mark.parametrize(
    "cp,word",
    [(1, "сантипешка"), (2, "сантипешки"), (5, "сантипешек"), (11, "сантипешек"),
     (21, "сантипешка"), (100, "сантипешек"), (101, "сантипешка"), (150, "сантипешек"), (112, "сантипешек")],
)
def test_centipawn_plural(cp, word):
    assert f"{cp} [[{word}|" in centipawns_text(cp)


@pytest.mark.parametrize(
    "loss,mark",
    [(0, Mark.EXCELLENT), (10, Mark.EXCELLENT), (11, Mark.GOOD), (49, Mark.GOOD), (50, Mark.INACCURACY),
     (99, Mark.INACCURACY), (100, Mark.MISTAKE), (299, Mark.MISTAKE), (300, Mark.BLUNDER), (2000, Mark.BLUNDER)],
)
def test_classify_thresholds(loss, mark):
    assert classify(loss) == mark


def test_terms_are_defined_once():
    seen = set()
    first = render_terms("это [[вилка|вилка]]: ...", seen)
    second = render_terms("это [[вилка|вилка]]: ...", seen)
    assert "нападает сразу на две" in first
    assert second == "это вилка: ..."
    assert seen == {"вилка"}


def test_no_raw_markers_leak_into_text():
    board = chess.Board("4k3/8/8/4r3/8/8/4N3/6K1 w - - 0 1")
    explanation = explain_move(board, chess.Move.from_uci("g1h1"), line(-200, "e2c3"), line(-500, "e5e2"))
    text = explanation.render(set())
    assert "[[" not in text and "]]" not in text


# --- hints ---

def test_hints_give_reasons_and_drop_bad_candidates():
    board = chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    hints = build_hints(
        board,
        [line(500, "b5c7"), line(450, "b5d6"), line(-200, "b5a7")],
    )
    assert [h.san.rstrip("+") for h in hints] == ["Nc7", "Nd6"]
    assert "вилка" in hints[0].reason
    assert hints[0].text.startswith("Кc7")


def test_hints_handle_empty_lines():
    assert build_hints(chess.Board(), []) == []


# --- draw offers ---

@pytest.mark.parametrize(
    "cp,ai,fullmove,accepted",
    [
        (-200, chess.WHITE, 5, True),      # AI (white) is worse
        (200, chess.BLACK, 5, True),       # AI (black) is worse
        (200, chess.WHITE, 40, False),     # AI is winning
        (10, chess.WHITE, 5, False),       # equal, but too early
        (10, chess.WHITE, 25, True),       # equal and late
        (-40, chess.WHITE, 25, False),     # slightly worse, not equal, keeps playing
    ],
)
def test_ai_draw_decision(cp, ai, fullmove, accepted):
    assert ai_accepts_draw(Score(cp), ai, fullmove) is accepted
