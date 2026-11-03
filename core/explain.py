"""Turns Stockfish numbers into plain language. No LLM and no network: every
sentence comes from a move comparison and tactical pattern checks on the board."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

import chess

from core.engine import EVAL_CLAMP, Line, Score
from core.game import outcome_of
from core.i18n import is_english, t
from core.pgn_io import display_san

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

DECISIVE_CP = 500

_TERM_RE = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")


def render_terms(raw: str, seen: set[str]) -> str:
    """Expands [[shown text|term]]. Adds the definition on first use and records the term.
    [[~shown|term]] is a sentence of its own that appears only that first time."""

    def replace(match: re.Match) -> str:
        shown, term = match.group(1), match.group(2)
        once = shown.startswith("~")
        if once:
            shown = shown[1:]
        if term in seen:
            return "" if once else shown
        seen.add(term)
        definition = t(TERMS[term])
        return f"{shown} ({definition}). " if once else f"{shown} ({definition})"

    return _TERM_RE.sub(replace, raw)


class Mark(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"

    @property
    def label(self) -> str:
        return t(_MARK_LABELS[self])

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
    Mark.INACCURACY: "[[~Неточность|неточность]]",
    Mark.MISTAKE: "[[~Ошибка|ошибка]]",
    Mark.BLUNDER: "[[~Зевок|зевок]]",
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
    tenths = (abs(cp) + 5) // 10
    point = "." if is_english() else ","
    return f"{tenths // 10}{point}{tenths % 10}"


def centipawns_text(cp: int) -> str:
    cp = abs(cp)
    if is_english():
        return f"{cp} [[centipawn{'' if cp == 1 else 's'}|сантипешка]]"
    tail2, tail1 = cp % 100, cp % 10
    if 11 <= tail2 <= 14 or tail1 == 0 or tail1 >= 5:
        word = "сантипешек"
    elif tail1 == 1:
        word = "сантипешка"
    else:
        word = "сантипешки"
    return f"{cp} [[{word}|сантипешка]]"


def _moves_text(count: int) -> str:
    if is_english():
        return f"{count} move" if count == 1 else f"{count} moves"
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


def _nom(piece_type: int) -> str:
    return t(_NOMINATIVE[piece_type])


def _acc(piece_type: int) -> str:
    return t(_ACCUSATIVE[piece_type])


def _piece_at(board: chess.Board, square: int) -> str:
    return t("{piece} на {square}", piece=_nom(board.piece_type_at(square)), square=chess.square_name(square))


def _piece_at_acc(board: chess.Board, square: int) -> str:
    return t("{piece} на {square}", piece=_acc(board.piece_type_at(square)), square=chess.square_name(square))


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
    names = [_acc(board.piece_type_at(s)) for s in squares]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + t(" и ") + names[-1]


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


def _landing_is_safe(after: chess.Board, move: chess.Move, color: bool) -> bool:
    """The moved piece cannot be won. SEE only looks at the square itself, so a pawn
    that just stepped two squares also has to survive en passant."""
    if see(after, move.to_square, not color) > 0:
        return False
    double_step = abs(chess.square_rank(move.to_square) - chess.square_rank(move.from_square)) == 2
    return not (after.piece_type_at(move.to_square) == chess.PAWN and double_step and after.has_legal_en_passant())


def _fork_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    to = move.to_square
    if not _landing_is_safe(after, move, color):
        return None
    targets = _targets_of_piece(after, to, color)
    if len(targets) < 2:
        return None
    previously = before.attacks(move.from_square)
    if all(chess.BB_SQUARES[t] & int(previously) for t in targets):
        return None
    moved = after.piece_type_at(to)
    names = _list_targets(after, targets)
    subject = _nom(moved)
    if moved in (chess.KNIGHT, chess.PAWN):
        return Motif("fork", t("это [[вилка|вилка]]: {subject} нападает сразу на {names}", subject=subject, names=names))
    return Motif(
        "double_attack",
        t("это [[двойной удар|двойной удар]]: {subject} нападает сразу на {names}", subject=subject, names=names),
    )


def _discovered_motif(before: chess.Board, after: chess.Board, move: chess.Move, color: bool) -> Optional[Motif]:
    """A moved piece and a piece it uncovered each start a separate real threat."""
    to = move.to_square
    if not _landing_is_safe(after, move, color):
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
        t(
            "это [[двойной удар|двойной удар]]: {subject} нападает на {names}, и этим же ходом "
            "открыта линия для фигуры на {square}: под ударом {target}",
            subject=_nom(after.piece_type_at(to)),
            names=_list_targets(after, fresh_moved),
            square=chess.square_name(opener_square),
            target=_nom(after.piece_type_at(opened_target)),
        ),
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
        behind_type = after.piece_type_at(behind)
        if PIECE_VALUES[behind_type] <= PIECE_VALUES[victim_type]:
            continue
        # If the piece behind is defended and worth less than the pinner, taking it loses
        # material, so the front piece is free to move and there is no pin.
        if (
            behind_type != chess.KING
            and PIECE_VALUES[behind_type] <= PIECE_VALUES[piece]
            and after.attackers(not color, behind)
        ):
            continue
        pronoun = "ней" if _is_feminine(victim_type) else "ним"
        return Motif(
            "pin",
            t(
                "это [[связка|связка]]: {piece} держит {victim}, потому что за {pronoun} стоит {behind}",
                piece=_nom(piece),
                victim=_piece_at_acc(after, victim),
                pronoun=pronoun,
                behind=_nom(after.piece_type_at(behind)),
            ),
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
    after = before.copy(stack=False)
    after.push(move)
    if after.attackers(not color, move.to_square):
        return Motif("wins_hanging", t("забирает {victim}: взять в ответ сопернику невыгодно", victim=_acc(victim)))
    pronoun = "неё" if _is_feminine(victim) else "него"
    return Motif("wins_hanging", t("забирает {victim}: защиты у {pronoun} не было", victim=_acc(victim), pronoun=pronoun))


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
        name = _acc(before.piece_type_at(move.from_square))
        return Motif("saves", t("уводит из-под удара {piece} с {square}", piece=name, square=chess.square_name(move.from_square)))
    for square in sorted(threatened, key=threatened.get, reverse=True):
        if square == move.from_square or square in still:
            continue
        if after.piece_at(square) == before.piece_at(square):
            was, pronoun = ("была", "её") if _is_feminine(before.piece_type_at(square)) else ("был", "его")
            return Motif(
                "saves",
                t("{piece} {was} под ударом, и этот ход {pronoun} спасает", piece=_piece_at(before, square), was=was, pronoun=pronoun),
            )
    return None


def _hanging_motif(after: chess.Board, color: bool) -> Optional[Motif]:
    threatened = _threatened_pieces(after, color)
    if not threatened:
        return None
    square = max(threatened, key=lambda s: threatened[s])
    if not after.attackers(color, square):
        text = "{piece} остаётся под ударом, защиты нет"
    elif _is_feminine(after.piece_type_at(square)):
        text = "{piece} остаётся под ударом, защищена недостаточно"
    else:
        text = "{piece} остаётся под ударом, защищён недостаточно"
    return Motif("hanging", t(text, piece=_piece_at(after, square)), positive=False)


def motifs_of_move(board: chess.Board, move: chess.Move) -> list[Motif]:
    """Tactical patterns a move creates, most forcing first. `board` is before the move."""
    color = board.turn
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return [Motif("mate", t("ставит мат"))]
    motifs: list[Motif] = []
    if _mate_threat(board, after):
        motifs.append(Motif("mate_threat", t("создаёт [[матовую угрозу|матовая угроза]]")))
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


def _names(piece_types: Sequence[int]) -> str:
    """["ферзя"], ["коня и пешку"], ["две пешки"]: pieces in the accusative, biggest first."""
    pieces = [p for p in sorted(set(piece_types), key=lambda p: -PIECE_VALUES[p]) if p != chess.PAWN]
    parts = [_one_piece(p) if piece_types.count(p) == 1 else _plural_pieces(p, piece_types.count(p)) for p in pieces]
    pawns = piece_types.count(chess.PAWN)
    if pawns:
        parts.append(_plural_pieces(chess.PAWN, pawns) if pawns > 1 else _one_piece(chess.PAWN))
    return t(" и ").join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + t(" и ") + parts[-1]


_PLURALS = {
    chess.PAWN: "пешки",
    chess.KNIGHT: "коня",
    chess.BISHOP: "слона",
    chess.ROOK: "ладьи",
    chess.QUEEN: "ферзя",
}
_COUNT_WORDS = {2: ("два", "две"), 3: ("три", "три"), 4: ("четыре", "четыре")}
_ENGLISH_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
}
_ENGLISH_COUNTS = {2: "two", 3: "three", 4: "four"}


def _one_piece(piece_type: int) -> str:
    """What is won or lost: "ферзя", "a queen"."""
    return f"a {_ENGLISH_NAMES[piece_type]}" if is_english() else _ACCUSATIVE[piece_type]


def _plural_pieces(piece_type: int, count: int) -> str:
    if is_english():
        if count > 4:
            return f"{count} pawns" if piece_type == chess.PAWN else f"{count} pieces"
        return f"{_ENGLISH_COUNTS[count]} {_ENGLISH_NAMES[piece_type]}s"
    if count > 4:
        return f"{count} " + ("пешек" if piece_type == chess.PAWN else "фигур")
    masculine, feminine = _COUNT_WORDS[count]
    return f"{feminine if _is_feminine(piece_type) else masculine} {_PLURALS[piece_type]}"


@dataclass(frozen=True)
class MaterialResult:
    net: int
    won: tuple[int, ...] = ()  # piece types taken from the opponent, even trades cancelled
    lost: tuple[int, ...] = ()
    wins_exchange: bool = False
    exact: bool = True  # False when the pieces above do not tell the whole story

    @property
    def phrase(self) -> Optional[str]:
        """What is won, in the accusative: "ход выигрывает ___"."""
        if self.net <= 0:
            return None
        if self.wins_exchange:
            return t("[[качество|качество]]")
        if self.exact and self.won:
            if self.lost:
                return t("{won} за {lost}", won=_names(self.won), lost=_names(self.lost))
            return _names(self.won)
        if self.net >= 9:
            return _one_piece(chess.QUEEN)
        if self.net >= 5:
            return _one_piece(chess.ROOK)
        if self.net >= 3:
            return t("фигуру")
        return t("две пешки") if self.net == 2 else _one_piece(chess.PAWN)


def material_along(board: chess.Board, moves: Iterable[chess.Move], color: bool, max_plies: int = 4) -> MaterialResult:
    """Material change for `color` after a short line from `board`. Four plies cover a
    tactic and its recapture. Beyond that an engine line stops being forced."""
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

    won: list[int] = []
    lost: list[int] = []
    promoted = False
    for piece in mine:
        taken = theirs[piece] - theirs_after[piece]
        given = mine[piece] - mine_after[piece]
        promoted = promoted or given < 0 or taken < 0
        balance = taken - given
        won.extend([piece] * max(0, balance))
        lost.extend([piece] * max(0, -balance))
    exact = not promoted and pending == 0
    exchange = (
        exact and len(won) == 1 and won[0] == chess.ROOK
        and len(lost) == 1 and lost[0] in (chess.KNIGHT, chess.BISHOP)
    )
    return MaterialResult(net, tuple(won), tuple(lost), exchange, exact)


def _confirmed(board: chess.Board, score: Score, color: bool, material: MaterialResult) -> bool:
    """An engine line is only its best guess. Claim a material win only if the evaluation,
    counted from the material balance before the line, shows most of that win."""
    balance = _value(_material(board, color)) - _value(_material(board, not color))
    return score.for_color(color) - balance * 100 >= material.net * 60


# --- explanation --------------------------------------------------------------


def score_after(board_after: chess.Board, line: Optional[Line]) -> Score:
    """Evaluation of a position, which may be final and so has no engine line. A line
    wins over a claimable draw: an imported game can play on past a threefold repetition."""
    if line is not None and board_after.outcome() is None:
        return line.score
    outcome = outcome_of(board_after)
    if outcome is None:
        raise ValueError("a position that is not final needs an engine line")
    if outcome.winner is None:
        return Score(0)
    return Score(EVAL_CLAMP if outcome.winner == chess.WHITE else -EVAL_CLAMP, 0)


def position_text(score: Score) -> str:
    if score.mate:
        side = t("белые ставят") if score.mate > 0 else t("чёрные ставят")
        return t("Оценка: {side} мат в {moves}.", side=side, moves=_moves_text(abs(score.mate)))
    if abs(score.cp) < 30:
        return t("Оценка: позиция примерно равна.")
    side = t("белых") if score.cp > 0 else t("чёрных")
    return t("Оценка: у {side} перевес {pawns} пешки.", side=side, pawns=pawns_text(score.cp))


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


def _reason_for(board: chess.Board, line: Line) -> tuple[str, bool]:
    """Short clause on why the first move of an engine line is good, and whether
    that clause is only general advice with no concrete tactic behind it."""
    move = line.move
    color = board.turn
    mate = line.score.mate_for(color)
    motifs = motifs_of_move(board, move)
    if motifs and motifs[0].kind == "mate":
        return t("ставит мат"), False
    if mate is not None and mate > 0:
        return t("ведёт к мату в {moves}", moves=_moves_text(mate)), False
    material = material_along(board, line.pv, color)
    wins = material.phrase if material.phrase and _confirmed(board, line.score, color, material) else None
    tactical = [m for m in motifs if m.kind != "saves" and m.positive]
    if tactical:
        reason = tactical[0].clause
        if wins and tactical[0].kind in ("fork", "double_attack", "pin"):
            reason = t("{reason}, и в итоге выигрывает {wins}", reason=reason, wins=wins)
        return reason, False
    if wins and not _is_recapture(board, move):
        return t("выигрывает {wins}", wins=wins), False
    saves = [m for m in motifs if m.kind == "saves"]
    if saves:
        return saves[0].clause, False
    if _stops_mate(board, move):
        return t("защищает от мата следующим ходом"), False
    return _generic_reason(board, move), True


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


_CENTER = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])
_DATIVE = {chess.BISHOP: "слону", chess.ROOK: "ладье", chess.QUEEN: "ферзю"}


def _generic_reason(board: chess.Board, move: chess.Move) -> str:
    color = board.turn
    piece = board.piece_type_at(move.from_square)
    if board.is_castling(move):
        return t("уводит короля в безопасное место и вводит в игру ладью")
    if board.gives_check(move):
        return t("ставит шах и заставляет соперника отвечать")
    if _is_recapture(board, move):
        return t("отыгрывает только что взятый материал")
    if board.is_capture(move):
        return t("упрощает позицию разменом")
    after = board.copy(stack=False)
    after.push(move)
    if _landing_is_safe(after, move, color):
        for target in after.attacks(move.to_square) & after.occupied_co[not color]:
            target_type = after.piece_type_at(target)
            if target_type != chess.KING and PIECE_VALUES[target_type] > PIECE_VALUES[piece]:
                return t("нападает на {piece}", piece=_acc(target_type))
    home_rank = 0 if color == chess.WHITE else 7
    if piece in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank:
        return t("вводит в игру {piece}", piece=_acc(piece))
    if piece == chess.PAWN:
        if move.to_square in _CENTER:
            return t("пешка занимает центр")
        if after.attacks(move.to_square) & _CENTER:
            return t("пешка борется за центр")
    for slider in (chess.BISHOP, chess.QUEEN, chess.ROOK):
        for square in after.pieces(slider, color):
            if square != move.to_square and len(after.attacks(square)) > len(board.attacks(square)):
                return t("открывает дорогу {piece}", piece=t(_DATIVE[slider]))
    if move.to_square in _CENTER:
        return t("ставит {piece} в центр", piece=_acc(piece))
    return t("по расчёту движка он сильнее других")


def _still_decided(before: Score, after: Score, color: bool) -> bool:
    """The same side was clearly winning before and after the move. The result did not
    change, and big swings up there are mostly the engine finding a mate at another depth,
    so such a move is at worst an inaccuracy. The text still names the better move."""
    was, now = before.for_color(color), after.for_color(color)
    return (was >= DECISIVE_CP and now >= DECISIVE_CP) or (was <= -DECISIVE_CP and now <= -DECISIVE_CP)


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
    cp_loss = 0 if is_best else max(0, best.score.comparable_for(color) - score.comparable_for(color, 1))
    mark = classify(min(cp_loss, 99) if _still_decided(best.score, score, color) else cp_loss)
    motifs = motifs_of_move(board, move)

    lines: list[str] = []
    outcome = outcome_of(after)
    if outcome is not None and outcome.winner is not None:
        lines.append(t("Мат, партия окончена."))
        return MoveExplanation(san, color, score, 0, Mark.EXCELLENT, True, None, None, ["mate"], lines)

    verdict = _verdict(board, move, best, score, is_best, cp_loss, mark, after_line, color)
    lines.append(verdict)
    if cp_loss < 100:
        shown = 0
        for motif in motifs:
            if not motif.positive or shown == 2:
                continue
            if motif.kind == "saves" and board.is_capture(move):
                continue  # taking the attacker is explained by the capture itself
            if motif.kind == "wins_hanging" and t("Ход выигрывает") in verdict:
                continue
            lines.append(_sentence(motif.clause) + ".")
            shown += 1

    refuted = False
    if cp_loss >= 50:
        hanging = _hanging_motif(after, color)
        if hanging is not None:
            lines.append(_sentence(hanging.clause) + ".")
        if after_line is not None:
            refutation = _refutation(after, after_line, color, cp_loss)
            lines.extend(refutation)
            refuted = bool(refutation)

    if not is_best and cp_loss > 10:
        reason, is_general = _reason_for(board, best)
        if is_general and cp_loss >= 100 and refuted:
            reason = t("он не даёт сопернику такой возможности")
        best_san = display_san(board.san(best.move))
        # With a mate on either side the centipawn gap is only the clamp, not a measurement.
        if best.score.mate is None and score.mate is None:
            lines.append(t("Лучше был ход {move} (сильнее на {gap}): {reason}.", move=best_san, gap=centipawns_text(cp_loss), reason=reason))
        else:
            lines.append(t("Лучше был ход {move}: {reason}.", move=best_san, reason=reason))
    lines.append(position_text(score))

    best_san_final = None if is_best else board.san(best.move)
    return MoveExplanation(
        san, color, score, cp_loss, mark, is_best, best_san_final,
        None if is_best else best.move, [m.kind for m in motifs], lines,
    )


def _verdict(
    board: chess.Board, move: chess.Move, best: Line, score: Score,
    is_best: bool, cp_loss: int, mark: Mark, after_line: Optional[Line], color: bool,
) -> str:
    prefix = t(_MARK_TERMS[mark]) if mark in _MARK_TERMS else ""
    mate = score.mate_for(color)
    missed = best.score.mate_for(color)
    if cp_loss > 10 and mate is not None and mate < 0:
        if missed is not None and missed < 0:
            return prefix + t("Мат был неизбежен, но этот ход его ускоряет: теперь мат в {moves}.", moves=_moves_text(-mate))
        return prefix + t("Ход допускает мат в {moves}.", moves=_moves_text(-mate))
    if cp_loss > 10 and missed is not None and missed > 0:
        return prefix + t("Ход упускает мат в {moves}.", moves=_moves_text(missed))
    if cp_loss > 10:
        return prefix + t("Ход ослабил позицию на {pawns} пешки, это {gap}.", pawns=pawns_text(cp_loss), gap=centipawns_text(cp_loss))
    if after_line is not None:
        material = material_along(board, (move, *after_line.pv), color)
        if material.phrase and _is_recapture(board, move):
            return prefix + t("Ход отыгрывает взятый материал.")
        if material.phrase and _confirmed(board, score, color, material):
            return prefix + t("Ход выигрывает {what}.", what=material.phrase)
    if mate is not None and mate > 0:
        return prefix + t("Ход ведёт к мату в {moves}.", moves=_moves_text(mate))
    if is_best:
        return prefix + t("Лучший ход по мнению движка.")
    return prefix + t("Ход ничего не меняет в оценке позиции.")


def _refutation(after: chess.Board, line: Line, color: bool, cp_loss: int) -> list[str]:
    """What the opponent does next, stated as a consequence."""
    reply = line.move
    if reply not in after.legal_moves:
        return []
    reply_san = display_san(after.san(reply))
    opponent = not color
    mate = line.score.mate_for(opponent)
    if mate is not None and mate > 0:
        if mate == 1:
            return [t("Соперник отвечает {move} и ставит мат.", move=reply_san.rstrip("#"))]
        return [t("Соперник отвечает {move} и ставит мат в {moves}.", move=reply_san, moves=_moves_text(mate))]
    material = material_along(after, line.pv, opponent)
    if material.phrase and _confirmed(after, line.score, opponent, material):
        return [t("Соперник отвечает {move} и выигрывает {what}.", move=reply_san, what=material.phrase)]
    if cp_loss >= 100:
        return [t("Сильный ответ соперника: {move}.", move=reply_san)]
    return []


# --- hints --------------------------------------------------------------------


@dataclass(frozen=True)
class Hint:
    move: chess.Move
    san: str
    score: Score
    reason: str

    def render(self, seen: set[str]) -> str:
        """Final text. `seen` tracks explained terms and is updated in place."""
        return f"{display_san(self.san)}: {render_terms(self.reason, seen)}."


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
