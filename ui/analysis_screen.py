"""Game review: load a PGN or a saved game, run Stockfish over it, step through moves."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import chess
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.analysis import GameReview
from core.clock import storage_key_from_pgn_tag
from core.explain import Mark
from core.game import Mode
from core.pgn_io import ParsedGame, read_first_game, read_games, ru_san
from storage.db import Database
from ui.board_widget import BoardWidget
from ui.engine_service import EngineService, Ticket
from ui.theme import MARK_COLORS, Theme
from ui.widgets import (
    EvalGraph,
    ExplanationBlock,
    ExplanationPanel,
    FenBar,
    MoveList,
    NavBar,
    header_bar,
    navigation_shortcuts,
)


def load_pgn_file(parent: QWidget, path: str) -> Optional[ParsedGame]:
    """Reads a PGN file, asks which game when it holds several. None if nothing usable."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = Path(path).read_text(encoding="cp1251", errors="replace")
    except OSError as error:
        QMessageBox.warning(parent, "PGN", f"Не удалось прочитать файл: {error}")
        return None
    games = read_games(text)
    if not games:
        QMessageBox.warning(parent, "PGN", "В файле нет ни одной партии.")
        return None
    game = games[0]
    if len(games) > 1:
        titles = [f"{index + 1}. {g.title}" for index, g in enumerate(games[:500])]
        choice, accepted = QInputDialog.getItem(parent, "Выбор партии", f"Партий в файле: {len(games)}", titles, 0, False)
        if not accepted:
            return None
        game = games[titles.index(choice)]
    if game.errors:
        QMessageBox.warning(
            parent, "PGN",
            f"Запись повреждена, загружено ходов: {len(game.moves)}.\n{game.errors[0]}",
        )
    return game


def store_imported(db: Database, game: ParsedGame) -> int:
    existing = db.find_game_by_pgn(game.pgn)
    if existing is not None:
        return existing
    control = storage_key_from_pgn_tag(game.headers.get("TimeControl", "-"))
    return db.create_game(datetime.now(), Mode.IMPORT.value, None, control, game.result, game.pgn)


class AnalysisScreen(QWidget):
    backRequested = Signal()
    gamesChanged = Signal()

    def __init__(self, db: Database, engine: EngineService, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.engine = engine
        self.game: Optional[ParsedGame] = None
        self.game_id: Optional[int] = None
        self._ply = 0
        self._comments: dict[int, str] = {}
        self._marks: dict[int, Mark] = {}
        self._evals: dict[int, int] = {}
        self._ticket: Optional[Ticket] = None

        header, self.title = header_bar("Анализ партии", self._on_back)
        self.board = BoardWidget(theme)
        self.fen_bar = FenBar()
        self.moves = MoveList()
        self.moves.plySelected.connect(self.go_to)
        self.graph = EvalGraph(theme)
        self.graph.plySelected.connect(self.go_to)
        self.coach = ExplanationPanel()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.nav = NavBar(
            lambda: self.go_to(0),
            lambda: self.go_to(self._ply - 1),
            lambda: self.go_to(self._ply + 1),
            lambda: self.go_to(self._last_ply()),
        )
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.open_button = QPushButton("Открыть PGN")
        self.open_button.clicked.connect(self.choose_file)
        self.analyze_button = QPushButton("Запустить анализ")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.clicked.connect(self.start_review)
        self.cancel_button = QPushButton("Стоп")
        self.cancel_button.clicked.connect(self.cancel_review)
        self.cancel_button.setVisible(False)
        self.flip_button = QPushButton("Повернуть")
        self.flip_button.clicked.connect(lambda: self.board.set_flipped(not self.board.flipped))
        self.export_button = QPushButton("Сохранить PGN")
        self.export_button.clicked.connect(self.export_pgn)
        for button in (self.open_button, self.analyze_button, self.cancel_button, self.flip_button, self.export_button):
            button.setAutoDefault(False)

        actions = QHBoxLayout()
        for button in (self.open_button, self.analyze_button, self.cancel_button, self.flip_button, self.export_button):
            actions.addWidget(button)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.graph)
        side.addWidget(self.summary)
        side.addWidget(self.moves, 3)
        side.addWidget(self.nav)
        side.addWidget(self.coach, 3)
        side.addWidget(self.progress)
        side.addLayout(actions)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(440)

        left = QVBoxLayout()
        left.addWidget(self.board, 1)
        left.addWidget(self.fen_bar)
        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(side_widget)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(header)
        root.addLayout(body, 1)

        navigation_shortcuts(
            self,
            lambda: self.go_to(0),
            lambda: self.go_to(self._ply - 1),
            lambda: self.go_to(self._ply + 1),
            lambda: self.go_to(self._last_ply()),
        )

        self._show_empty()

    def set_theme(self, theme: Theme) -> None:
        self.board.set_theme(theme)
        self.graph.set_theme(theme)

    # --- loading -------------------------------------------------------------

    def _show_empty(self) -> None:
        self.game = None
        self.game_id = None
        self.board.set_position(chess.Board())
        self.fen_bar.set_fen(chess.STARTING_FEN)
        self.moves.clear_moves()
        self.graph.set_data([], [])
        self.summary.setText("")
        self.coach.show_text("Откройте файл PGN или выберите партию в истории.")
        self.analyze_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть PGN", "", "PGN (*.pgn);;Все файлы (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> bool:
        game = load_pgn_file(self, path)
        if game is None:
            return False
        game_id = store_imported(self.db, game)
        self.gamesChanged.emit()
        self.show_saved_game(game_id, auto_review=False)
        return True

    def show_saved_game(self, game_id: int, auto_review: bool = False) -> None:
        self.cancel_review()
        row = self.db.get_game(game_id)
        game = read_first_game(row.pgn) if row is not None else None
        if game is None:
            QMessageBox.warning(self, "Партия", "Не удалось прочитать запись партии.")
            return
        self.game = game
        self.game_id = game_id
        self._comments, self._marks, self._evals = {}, {}, {}
        self.moves.set_start(chess.Board(game.start_fen))
        self.moves.set_moves(game.sans)
        for stored in self.db.get_moves(game_id):
            if stored.ply > len(game.moves):
                continue
            if stored.comment:
                self._comments[stored.ply] = stored.comment
            if stored.eval_cp is not None:
                self._evals[stored.ply] = stored.eval_cp
            if stored.mark:
                self._marks[stored.ply] = Mark(stored.mark)
                self.moves.set_mark(stored.ply, self._marks[stored.ply])
        self.board.set_flipped(row.player_color == chess.BLACK)
        self.title.setText(game.title)
        self.analyze_button.setEnabled(bool(game.moves))
        self.export_button.setEnabled(True)
        self._refresh_graph()
        self._refresh_summary()
        self._ply = -1
        self.go_to(0)
        if auto_review and game.moves:
            self.start_review()

    # --- navigation ----------------------------------------------------------

    def _last_ply(self) -> int:
        return len(self.game.moves) if self.game else 0

    def go_to(self, ply: int) -> None:
        if self.game is None:
            return
        ply = max(0, min(ply, self._last_ply()))
        if ply == self._ply:
            return
        step_forward = ply == self._ply + 1
        self._ply = ply
        board = self.game.board_at(ply)
        last = self.game.moves[ply - 1] if ply > 0 else None
        self.board.set_position(board, last, animate=step_forward)
        self.fen_bar.set_fen(board.fen())
        self.moves.set_current_ply(ply)
        self.graph.set_current_ply(ply)
        self._refresh_coach()

    def _refresh_coach(self) -> None:
        if self.game is None:
            return
        if self._ply == 0:
            text = "Начальная позиция."
            if not self._comments:
                text += " Нажмите «Запустить анализ», чтобы получить оценку и разбор каждого хода."
            self.coach.show_text(text)
            return
        san = self.game.sans[self._ply - 1]
        board = self.game.board_at(self._ply - 1)
        side = "Белые" if board.turn == chess.WHITE else "Чёрные"
        comment = self._comments.get(self._ply)
        if comment is None:
            self.coach.show_blocks([ExplanationBlock(f"{side}: {ru_san(san)}", "Ход ещё не разобран.")])
        else:
            self.coach.show_blocks([ExplanationBlock(f"{side}: {ru_san(san)}", comment, self._marks.get(self._ply))])

    def _refresh_graph(self) -> None:
        count = self._last_ply()
        evals = [self._evals.get(ply) for ply in range(1, count + 1)]
        marks = [self._marks.get(ply) for ply in range(1, count + 1)]
        self.graph.set_data(evals, marks)

    def _refresh_summary(self) -> None:
        if not self._marks:
            self.summary.setText("")
            return
        start_white = chess.Board(self.game.start_fen).turn == chess.WHITE
        rows = []
        for color, name in ((chess.WHITE, "Белые"), (chess.BLACK, "Чёрные")):
            counts = {mark: 0 for mark in Mark}
            for ply, mark in self._marks.items():
                is_white = (ply % 2 == 1) == start_white
                if is_white == (color == chess.WHITE):
                    counts[mark] += 1
            cells = " · ".join(
                f"<span style='color:{MARK_COLORS[mark]}'>{mark.label.lower()} {count}</span>"
                for mark, count in counts.items() if count
            )
            rows.append(f"<b>{name}:</b> {cells or 'нет разобранных ходов'}")
        self.summary.setText("<br>".join(rows))

    # --- review --------------------------------------------------------------

    def start_review(self) -> None:
        if self.game is None or not self.game.moves or self._ticket is not None:
            return
        self.progress.setRange(0, len(self.game.moves))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress.setFormat("%v из %m")
        self.analyze_button.setVisible(False)
        self.cancel_button.setVisible(True)
        self._ticket = self.engine.request_review(
            self.game.start_fen, self.game.moves, self._on_progress, self._on_review_done, self._on_review_error
        )

    def cancel_review(self) -> None:
        if self._ticket is not None:
            self._ticket.cancel()
            self._ticket = None
        self._review_finished()

    def _review_finished(self) -> None:
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.analyze_button.setVisible(True)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)

    def _on_review_error(self, message: str) -> None:
        self._ticket = None
        self._review_finished()
        QMessageBox.warning(self, "Анализ", message)

    def _on_review_done(self, review: GameReview) -> None:
        self._ticket = None
        self._review_finished()
        seen = self.db.seen_terms()
        rows = []
        for index, item in enumerate(review.explanations):
            ply = index + 1
            text = item.render(seen)
            self._comments[ply] = text
            self._marks[ply] = item.mark
            self._evals[ply] = item.score.cp
            self.moves.set_mark(ply, item.mark)
            rows.append((ply, item.san, item.score.cp, text, item.mark.value))
        self.db.save_seen_terms(seen)
        if self.game_id is not None:
            self.db.save_review(self.game_id, rows)
        self._refresh_graph()
        self._refresh_summary()
        self._refresh_coach()

    # --- export --------------------------------------------------------------

    def export_pgn(self) -> None:
        if self.game is None:
            return
        export_game_pgn(self, self.game.pgn)

    def _on_back(self) -> None:
        self.cancel_review()
        self.backRequested.emit()


def export_game_pgn(parent: QWidget, pgn: str) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "Сохранить PGN", "game.pgn", "PGN (*.pgn)")
    if not path:
        return
    try:
        Path(path).write_text(pgn + "\n", encoding="utf-8")
    except OSError as error:
        QMessageBox.warning(parent, "PGN", f"Не удалось сохранить файл: {error}")
