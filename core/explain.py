"""Turns Stockfish numbers into plain Russian. No LLM and no network: every
sentence comes from a move comparison and tactical pattern checks on the board."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

import chess

from core.engine import EVAL_CLAMP, Line, Score
from core.game import outcome_of
from core.pgn_io import ru_san

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}
_NOMINATIVE = {
    chess.PAWN: "пешка",
    chess.KNIGHT: "конь",
    chess.BISHOP: "слон",
    chess.ROOK: "ладья",
    chess.QUEEN: "ферзь",
    chess.KING: "король",
}
_ACCUSATIVE = {
    chess.PAWN: "пешку",
    chess.KNIGHT: "коня",
    chess.BISHOP: "слона",
    chess.ROOK: "ладью",
    chess.QUEEN: "ферзя",
    chess.KING: "короля",
}

# Each term is explained once, the first time the interface uses it.
TERMS = {
    "сантипешка": "единица оценки движка, 100 сантипешек равны одной пешке",
    "вилка": "конь или пешка нападает сразу на две фигуры, и спасти обе нельзя",
    "двойной удар": "один ход создаёт сразу две угрозы, а ответить можно только на одну",
    "связка": "фигура не может уйти с линии, потому что за ней стоит более ценная фигура",
    "качество": "разница между ладьёй и конём или слоном, примерно две пешки",
    "матовая угроза": "если не ответить, следующим ходом будет мат",
    "неточность": "ход хуже лучшего на 0,5–1 пешку",
    "ошибка": "ход хуже лучшего на 1–3 пешки",
    "зевок": "ход хуже лучшего больше чем на 3 пешки, обычно потеря фигуры или мат",
}

_TERM_RE = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")


def render_terms(raw: str, seen: set[str]) -> str:
    """Expands [[shown text|term]]. Adds the definition on first use and records the term."""

    def replace(match: re.Match) -> str:
        shown, term = match.group(1), match.group(2)
        if term in seen:
            return shown
        seen.add(term)
        return f"{shown} ({TERMS[term]})"

    return _TERM_RE.sub(replace, raw)


class Mark(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"

    @property
    def label(self) -> str:
        return _MARK_LABELS[self]

    @property
    def glyph(self) -> str:
        return _MARK_GLYPHS[self]


_MARK_LABELS = {
    Mark.EXCELLENT: "Отличный",
    Mark.GOOD: "Хороший",
    Mark.INACCURACY: "Неточность",
    Mark.MISTAKE: "Ошибка",
    Mark.BLUNDER: "Зевок",
}
_MARK_GLYPHS = {
    Mark.EXCELLENT: "",
    Mark.GOOD: "",
    Mark.INACCURACY: "?!",
    Mark.MISTAKE: "?",
    Mark.BLUNDER: "??",
}
_MARK_TERMS = {
    Mark.INACCURACY: "[[Неточность|неточность]]",
    Mark.MISTAKE: "[[Ошибка|ошибка]]",
    Mark.BLUNDER: "[[Зевок|зевок]]",
}


def classify(cp_loss: int) -> Mark:
    """Common centipawn thresholds: inaccuracy 50, mistake 100, blunder 300."""
    if cp_loss <= 10:
        return Mark.EXCELLENT
    if cp_loss < 50:
        return Mark.GOOD
    if cp_loss < 100:
        return Mark.INACCURACY
    if cp_loss < 300:
        return Mark.MISTAKE
    return Mark.BLUNDER


def pawns_text(cp: int) -> str:
    return f"{abs(cp) / 100:.1f}".replace(".", ",")


def centipawns_text(cp: int) -> str:
    cp = abs(cp)
    tail2, tail1 = cp % 100, cp % 10
    if 11 <= tail2 <= 14 or tail1 == 0 or tail1 >= 5:
        word = "сантипешек"
    elif tail1 == 1:
        word = "сантипешка"
    else:
        word = "сантипешки"
    return f"{cp} [[{word}|сантипешка]]"


def _moves_text(count: int) -> str:
    tail2, tail1 = count % 100, count % 10
    if 11 <= tail2 <= 14 or tail1 == 0 or tail1 >= 5:
        return f"{count} ходов"
    if tail1 == 1:
        return f"{count} ход"
    return f"{count} хода"


def _sentence(clause: str) -> str:
    """Capitalizes the first visible letter, skipping an opening [[ of a term."""
    for index, char in enumerate(clause):
        if char.isalpha():
            return clause[:index] + char.upper() + clause[index + 1:]
    return clause


def _is_feminine(piece_type: int) -> bool:
    return piece_type in (chess.PAWN, chess.ROOK)


def _piece_at(board: chess.Board, square: int) -> str:
    return f"{_NOMINATIVE[board.piece_type_at(square)]} на {chess.square_name(square)}"


def _piece_at_acc(board: chess.Board, square: int) -> str:
    return f"{_ACCUSATIVE[board.piece_type_at(square)]} на {chess.square_name(square)}"


# --- static exchange ----------------------------------------------------------


def see(board: chess.Board, square: int, by_color: bool) -> int:
    """Material in pawns `by_color` nets by opening captures on `square`, best play
    from both sides, stopping whenever going on loses. 0 means capturing does not pay."""
    target = board.piece_at(square)
    if target is None or target.color == by_color:
        return 0
    position = board.copy(stack=False)

    def exchange(color: bool, on_square_value: int) -> int:
        attacker = _least_valuable_attacker(position, color, square)
        if attacker is None:
            return 0
        attacker_piece = position.piece_at(attacker)
        occupant = position.piece_at(square)
        position.remove_piece_at(attacker)
        position.set_piece_at(square, attacker_piece)
        gain = on_square_value - exchange(not color, PIECE_VALUES[attacker_piece.piece_type])
        position.set_piece_at(square, occupant)
        position.set_piece_at(attacker, attacker_piece)
        return max(0, gain)

    return exchange(by_color, PIECE_VALUES[target.piece_type])


def _least_valuable_attacker(board: chess.Board, color: bool, square: int) -> Optional[int]:
    best, best_value = None, 10 ** 6
    for attacker in board.attackers(color, square):
        if board.is_pinned(color, attacker) and square not in board.pin(color, attacker):
            continue
        value = PIECE_VALUES[board.piece_type_at(attacker)]
        if value < best_value:
            best, best_value = attacker, value
    return best


# --- motifs -------------------------------------------------------------------


@dataclass(frozen=True)
class Motif:
    kind: str  # "mate", "mate_threat", "fork", "double_attack", "pin", "exchange",
    #            "wins_hanging", "saves", "hanging"
    clause: str  # lower case, may hold [[term]] markers
    positive: bool = True


def _list_targets(board: chess.Board, squares: Sequence[int]) -> str:
    names = [_ACCUSATIVE[board.piece_type_at(s)] for s in squares]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " и " + names[-1]


def _mate_in_one_exists(board: chess.Board) -> bool:
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def _mate_threat(before: chess.Board, after: chess.Board) -> bool:
    if after.is_check() or after.is_game_over():
        return False
    passed = after.copy(stack=False)
    passed.push(chess.Move.null())
    if passed.is_check() or not _mate_in_one_exists(passed):
        return False
    return before.is_check() or not _mate_in_one_exists(before.copy(stack=False))


def _targets_of_piece(after: chess.Board, square: int, color: bool) -> list[int]:
    """Enemy non-pawns the piece on `square` attacks and could actually win:
    the king, anything worth more than the attacker, or anything poorly defended."""
    my_value = PIECE_VALUES[after.piece_type_at(square)]
    targets = []
    for target in after.attacks(square) & after.occupied_co[not color]:
        target_type = after.piece_type_at(target)
        if target_type == chess.PAWN:
            continue
        if target_type == chess.KING or PIECE_VALUES[target_type] > my_value or see(after, target, color) > 0:
            targets.append(target)
    return targets


def _fork_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    to = move.to_square
    if see(after, to, not color) > 0:
        return None
    targets = _targets_of_piece(after, to, color)
    if len(targets) < 2:
        return None
    previously = before.attacks(move.from_square)
    if all(chess.BB_SQUARES[t] & int(previously) for t in targets):
        return None
    moved = after.piece_type_at(to)
    names = _list_targets(after, targets)
    subject = _NOMINATIVE[moved]
    if moved in (chess.KNIGHT, chess.PAWN):
        return Motif("fork", f"это [[вилка|вилка]]: {subject} нападает сразу на {names}")
    return Motif("double_attack", f"это [[двойной удар|двойной удар]]: {subject} нападает сразу на {names}")


def _discovered_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    """A moved piece and a piece it uncovered each start a separate real threat."""
    to = move.to_square
    if see(after, to, not color) > 0:
        return None
    moved_targets = _targets_of_piece(after, to, color)
    uncovered = []
    sliders = after.pieces(chess.BISHOP, color) | after.pieces(chess.ROOK, color) | after.pieces(chess.QUEEN, color)
    for square in sliders:
        if square == to:
            continue
        # Only the vacated square can open a new line for a piece that did not move.
        new_attacks = chess.SquareSet(int(after.attacks(square)) & ~int(before.attacks(square)))
        slider_value = PIECE_VALUES[after.piece_type_at(square)]
        for target in new_attacks & after.occupied_co[not color]:
            target_type = after.piece_type_at(target)
            if target_type == chess.PAWN:
                continue
            if target_type == chess.KING or PIECE_VALUES[target_type] > slider_value or see(after, target, color) > 0:
                uncovered.append((square, target))
    fresh_moved = [t for t in moved_targets if t not in {t2 for _, t2 in uncovered}]
    if not uncovered or not fresh_moved:
        return None
    opener_square, opened_target = uncovered[0]
    return Motif(
        "double_attack",
        f"это [[двойной удар|двойной удар]]: {_NOMINATIVE[after.piece_type_at(to)]} нападает на "
        f"{_list_targets(after, fresh_moved)}, и этим же ходом открыта линия для фигуры на "
        f"{chess.square_name(opener_square)}: под ударом {_NOMINATIVE[after.piece_type_at(opened_target)]}",
    )


def _pin_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    to = move.to_square
    piece = after.piece_type_at(to)
    if piece not in (chess.BISHOP, chess.ROOK, chess.QUEEN) or see(after, to, not color) > 0:
        return None
    previously = int(before.attacks(move.from_square))
    enemy = after.occupied_co[not color]
    for victim in after.attacks(to) & enemy:
        victim_type = after.piece_type_at(victim)
        if victim_type in (chess.PAWN, chess.KING) or chess.BB_SQUARES[victim] & previously:
            continue
        behind = _first_piece_behind(after, to, victim)
        if behind is None or after.color_at(behind) == color:
            continue
        if PIECE_VALUES[after.piece_type_at(behind)] <= PIECE_VALUES[victim_type]:
            continue
        pronoun = "ней" if _is_feminine(victim_type) else "ним"
        return Motif(
            "pin",
            f"это [[связка|связка]]: {_NOMINATIVE[piece]} держит {_piece_at_acc(after, victim)}, "
            f"потому что за {pronoun} стоит {_NOMINATIVE[after.piece_type_at(behind)]}",
        )
    return None


def _first_piece_behind(board: chess.Board, origin: int, through: int) -> Optional[int]:
    """First occupied square past `through` on the line from `origin`."""
    file_step = chess.square_file(through) - chess.square_file(origin)
    rank_step = chess.square_rank(through) - chess.square_rank(origin)
    file_step = (file_step > 0) - (file_step < 0)
    rank_step = (rank_step > 0) - (rank_step < 0)
    file, rank = chess.square_file(through) + file_step, chess.square_rank(through) + rank_step
    while 0 <= file < 8 and 0 <= rank < 8:
        square = chess.square(file, rank)
        if board.piece_at(square):
            return square
        file += file_step
        rank += rank_step
    return None


def _is_recapture(board: chess.Board, move: chess.Move) -> bool:
    if not board.move_stack or not board.is_capture(move):
        return False
    last = board.peek()
    if last.to_square != move.to_square:
        return False
    previous = board.copy()
    previous.pop()
    return previous.is_capture(last)


def _wins_hanging_motif(before: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    if not before.is_capture(move) or before.is_en_passant(move) or _is_recapture(before, move):
        return None
    victim = before.piece_type_at(move.to_square)
    if victim is None or see(before, move.to_square, color) < PIECE_VALUES[victim]:
        return None
    pronoun = "неё" if _is_feminine(victim) else "него"
    return Motif("wins_hanging", f"забирает {_ACCUSATIVE[victim]}: защиты у {pronoun} не было")


def _threatened_pieces(board: chess.Board, color: bool) -> dict[int, int]:
    """Own pieces (not pawns) the opponent could win now, with the gain in pawns."""
    found = {}
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type in (chess.PAWN, chess.KING):
            continue
        gain = see(board, square, not color)
        if gain > 0:
            found[square] = gain
    return found


def _saves_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    threatened = _threatened_pieces(before, color)
    if not threatened:
        return None
    still = _threatened_pieces(after, color)
    if move.from_square in threatened and not still:
        return Motif("saves", f"уводит {_piece_at_acc(before, move.from_square)} из-под удара")
    for square in sorted(threatened, key=threatened.get, reverse=True):
        if square == move.from_square or square in still:
            continue
        if after.piece_at(square) == before.piece_at(square):
            was, pronoun = ("была", "её") if _is_feminine(before.piece_type_at(square)) else ("был", "его")
            return Motif("saves", f"{_piece_at(before, square)} {was} под ударом, и этот ход {pronoun} защищает")
    return None


def _hanging_motif(after: chess.Board, color: bool) -> Optional[Motif]:
    threatened = _threatened_pieces(after, color)
    if not threatened:
        return None
    square = max(threatened, key=lambda s: threatened[s])
    defended = bool(after.attackers(color, square))
    guarded = "защищена" if _is_feminine(after.piece_type_at(square)) else "защищён"
    tail = f"{guarded} недостаточно" if defended else "защиты нет"
    return Motif("hanging", f"{_piece_at(after, square)} остаётся под ударом, {tail}", positive=False)


def motifs_of_move(board: chess.Board, move: chess.Move) -> list[Motif]:
    """Tactical patterns a move creates, most forcing first. `board` is before the move."""
    color = board.turn
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return [Motif("mate", "ставит мат")]
    motifs: list[Motif] = []
    if _mate_threat(board, after):
        motifs.append(Motif("mate_threat", "создаёт [[матовую угрозу|матовая угроза]]"))
    for detector in (_fork_motif, _discovered_motif, _pin_motif):
        motif = detector(board, after, move, color)
        if motif is not None:
            motifs.append(motif)
    motif = _wins_hanging_motif(board, move, color)
    if motif is not None:
        motifs.append(motif)
    motif = _saves_motif(board, after, move, color)
    if motif is not None:
        motifs.append(motif)
    return motifs


# --- material along an engine line --------------------------------------------


def _material(board: chess.Board, color: bool) -> dict[int, int]:
    return {
        piece: len(board.pieces(piece, color))
        for piece in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    }


def _value(counts: dict[int, int]) -> int:
    return sum(PIECE_VALUES[piece] * count for piece, count in counts.items())


@dataclass(frozen=True)
class MaterialResult:
    net: int
    wins_exchange: bool = False

    @property
    def phrase(self) -> Optional[str]:
        """What is won, in the accusative: "ходом выигрывает ___"."""
        if self.wins_exchange:
            return "[[качество|качество]]"
        if self.net >= 9:
            return "ферзя"
        if self.net >= 5:
            return "ладью"
        if self.net >= 3:
            return "фигуру"
        if self.net == 2:
            return "две пешки"
        if self.net == 1:
            return "пешку"
        return None


def material_along(board: chess.Board, moves: Iterable[chess.Move], color: bool, max_plies: int = 6) -> MaterialResult:
    """Material change for `color` after playing a forcing line from `board`."""
    position = board.copy(stack=False)
    mine = _material(position, color)
    theirs = _material(position, not color)
    for index, move in enumerate(moves):
        if index >= max_plies or move not in position.legal_moves:
            break
        position.push(move)
    # Do not count a capture at the very end of the line that simply gets recaptured.
    pending = 0
    if position.turn != color:
        pending = max(_threatened_pieces(position, color).values(), default=0)
    mine_after, theirs_after = _material(position, color), _material(position, not color)
    net = (_value(mine_after) - _value(mine)) - (_value(theirs_after) - _value(theirs)) - pending
    lost_minor = (mine[chess.KNIGHT] + mine[chess.BISHOP]) - (mine_after[chess.KNIGHT] + mine_after[chess.BISHOP])
    won_rook = theirs[chess.ROOK] - theirs_after[chess.ROOK]
    exchange = won_rook == 1 and lost_minor == 1 and net in (1, 2, 3) and (
        theirs[chess.QUEEN] == theirs_after[chess.QUEEN] and mine[chess.QUEEN] == mine_after[chess.QUEEN]
        and mine[chess.ROOK] == mine_after[chess.ROOK]
    )
    return MaterialResult(net, exchange)


# --- explanation --------------------------------------------------------------


def score_after(board_after: chess.Board, line: Optional[Line]) -> Score:
    """Evaluation of a position, which may be final and so has no engine line."""
    outcome = outcome_of(board_after)
    if outcome is None:
        if line is None:
            raise ValueError("a position that is not final needs an engine line")
        return line.score
    if outcome.winner is None:
        return Score(0)
    return Score(EVAL_CLAMP if outcome.winner == chess.WHITE else -EVAL_CLAMP, 0)


def position_text(score: Score) -> str:
    if score.mate:
        side = "белые ставят" if score.mate > 0 else "чёрные ставят"
        return f"Оценка: {side} мат в {_moves_text(abs(score.mate))}."
    if abs(score.cp) < 30:
        return "Оценка: позиция примерно равна."
    side = "белых" if score.cp > 0 else "чёрных"
    return f"Оценка: у {side} перевес {pawns_text(score.cp)} пешки."


@dataclass
class MoveExplanation:
    san: str
    color: bool
    score: Score  # after the move, white's point of view
    cp_loss: int
    mark: Mark
    is_best: bool
    best_san: Optional[str]
    best_move: Optional[chess.Move]
    motif_kinds: list[str] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

    def render(self, seen: set[str]) -> str:
        """Final text. `seen` tracks explained terms and is updated in place."""
        return "\n".join(render_terms(line, seen) for line in self.raw_lines)


def _reason_for(board: chess.Board, line: Line) -> tuple[str, list[str]]:
    """Short clause on why the first move of an engine line is good."""
    move = line.move
    color = board.turn
    mate = line.score.mate_for(color)
    motifs = motifs_of_move(board, move)
    kinds = [m.kind for m in motifs]
    if motifs and motifs[0].kind == "mate":
        return "ставит мат", kinds
    if mate is not None and mate > 0:
        return f"ведёт к мату в {_moves_text(mate)}", kinds
    material = material_along(board, line.pv, color)
    tactical = [m for m in motifs if m.kind != "saves" and m.positive]
    if tactical:
        reason = tactical[0].clause
        if material.phrase and material.net > 0 and tactical[0].kind in ("fork", "double_attack", "pin"):
            reason += f", и в итоге выигрывает {material.phrase}"
        return reason, kinds
    if material.phrase and material.net > 0 and not _is_recapture(board, move):
        return f"выигрывает {material.phrase}", kinds
    saves = [m for m in motifs if m.kind == "saves"]
    if saves:
        return saves[0].clause, kinds
    if _stops_mate(board, move):
        return "защищает от мата следующим ходом", kinds
    return _generic_reason(board, move), kinds


def _stops_mate(board: chess.Board, move: chess.Move) -> bool:
    """The opponent had mate in one if this side passed, and this move removes it."""
    if board.is_check():
        return False
    passed = board.copy(stack=False)
    passed.push(chess.Move.null())
    if not _mate_in_one_exists(passed):
        return False
    after = board.copy(stack=False)
    after.push(move)
    return not _mate_in_one_exists(after)


_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}


def _generic_reason(board: chess.Board, move: chess.Move) -> str:
    color = board.turn
    piece = board.piece_type_at(move.from_square)
    if board.is_castling(move):
        return "уводит короля в безопасное место и вводит в игру ладью"
    if board.gives_check(move):
        return "ставит шах и заставляет соперника отвечать"
    if _is_recapture(board, move):
        return "отыгрывает только что взятый материал"
    if board.is_capture(move):
        return "упрощает позицию разменом"
    home_rank = 0 if color == chess.WHITE else 7
    if piece in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank:
        return f"вводит в игру {_ACCUSATIVE[piece]}"
    if piece == chess.PAWN and move.to_square in _CENTER:
        return "пешка занимает центр"
    if move.to_square in _CENTER:
        return f"ставит {_ACCUSATIVE[piece]} в центр"
    return "движок считает его самым полезным в этой позиции"


def explain_move(
    board: chess.Board, move: chess.Move, best: Line, after_line: Optional[Line]
) -> MoveExplanation:
    """`board` is the position before the move, `best` the engine's top line for it,
    `after_line` the top line for the position after (None if the game just ended)."""
    color = board.turn
    san = board.san(move)
    after = board.copy()
    after.push(move)
    score = score_after(after, after_line)
    is_best = move == best.move
    cp_loss = 0 if is_best else max(0, best.score.for_color(color) - score.for_color(color))
    mark = classify(cp_loss)
    motifs = motifs_of_move(board, move)

    lines: list[str] = []
    outcome = outcome_of(after)
    if outcome is not None and outcome.winner is not None:
        lines.append(f"{ru_san(san)}: мат, партия окончена.")
        return MoveExplanation(san, color, score, 0, Mark.EXCELLENT, True, None, None, ["mate"], lines)

    lines.append(_verdict(board, move, san, best, score, is_best, cp_loss, mark, after_line, color))
    if cp_loss < 100:
        for motif in motifs[:2]:
            if motif.positive and motif.kind != "wins_hanging":
                lines.append(_sentence(motif.clause) + ".")

    if cp_loss >= 50:
        hanging = _hanging_motif(after, color)
        if hanging is not None:
            lines.append(_sentence(hanging.clause) + ".")
        if after_line is not None:
            lines.extend(_refutation(after, after_line, color))

    if not is_best and cp_loss > 10:
        reason, _ = _reason_for(board, best)
        best_san = board.san(best.move)
        lines.append(
            f"Лучше был ход {ru_san(best_san)} (сильнее на {centipawns_text(cp_loss)}): {reason}."
        )
    lines.append(position_text(score))

    best_san_final = None if is_best else board.san(best.move)
    return MoveExplanation(
        san, color, score, cp_loss, mark, is_best, best_san_final,
        None if is_best else best.move, [m.kind for m in motifs], lines,
    )


def _verdict(
    board: chess.Board, move: chess.Move, san: str, best: Line, score: Score,
    is_best: bool, cp_loss: int, mark: Mark, after_line: Optional[Line], color: bool,
) -> str:
    shown = ru_san(san)
    prefix = f"{shown}: {_MARK_TERMS[mark]}. " if mark in _MARK_TERMS else f"{shown}: "
    mate = score.mate_for(color)
    if cp_loss > 10 and mate is not None and mate < 0:
        return f"{prefix}Ход допускает мат в {_moves_text(-mate)}."
    if cp_loss > 10:
        return f"{prefix}Ход ослабил позицию на {pawns_text(cp_loss)} пешки ({centipawns_text(cp_loss)})."
    if after_line is not None:
        material = material_along(board, (move, *after_line.pv), color)
        if material.phrase and material.net > 0:
            if _is_recapture(board, move):
                return f"{prefix}Ход отыгрывает взятый материал."
            return f"{prefix}Ход выигрывает {material.phrase}."
    if mate is not None and mate > 0:
        return f"{prefix}Ход ведёт к мату в {_moves_text(mate)}."
    if is_best:
        return f"{prefix}Лучший ход по мнению движка."
    return f"{prefix}Ход ничего не меняет в оценке позиции."


def _refutation(after: chess.Board, line: Line, color: bool) -> list[str]:
    """What the opponent does next, stated as a consequence."""
    reply = line.move
    if reply not in after.legal_moves:
        return []
    reply_san = ru_san(after.san(reply))
    opponent = not color
    mate = line.score.mate_for(opponent)
    if mate is not None and mate > 0:
        if mate == 1:
            return [f"Соперник отвечает {reply_san.rstrip('#')} и ставит мат."]
        return [f"Соперник отвечает {reply_san} и ставит мат в {_moves_text(mate)}."]
    material = material_along(after, line.pv, opponent)
    if material.phrase and material.net > 0:
        return [f"Соперник отвечает {reply_san} и выигрывает {material.phrase}."]
    return [f"Сильный ответ соперника: {reply_san}."]


# --- hints --------------------------------------------------------------------


@dataclass(frozen=True)
class Hint:
    move: chess.Move
    san: str
    score: Score
    reason: str

    @property
    def text(self) -> str:
        return f"{ru_san(self.san)}: {self.reason}."


def build_hints(board: chess.Board, lines: Sequence[Line], limit: int = 3, margin_cp: int = 150) -> list[Hint]:
    """Up to `limit` candidates, dropping moves far worse than the best one."""
    if not lines:
        return []
    color = board.turn
    top = lines[0].score.for_color(color)
    hints = []
    for line in lines[:limit]:
        if line.score.for_color(color) < top - margin_cp:
            break
        reason, _ = _reason_for(board, line)
        hints.append(Hint(line.move, board.san(line.move), line.score, reason))
    return hints


# --- draw offers --------------------------------------------------------------


def ai_accepts_draw(score: Score, ai_color: bool, fullmove: int) -> bool:
    """The AI takes a draw when it stands worse, or in a dead-equal position once the
    opening is over. Anything better for the AI is declined."""
    cp = score.for_color(ai_color)
    if cp <= -50:
        return True
    return abs(cp) <= 25 and fullmove >= 20
