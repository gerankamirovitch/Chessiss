"""The game screen: board, clocks, notation, coach panel, game buttons."""
from __future__ import annotations

from typing import Optional

import chess
from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.clock import format_clock
from core.explain import Hint, Mark, MoveExplanation
from core.game import GameSession, GameSetup, Mode, PlayedMove
from core.pgn_io import ru_san, session_to_pgn
from storage.db import COLOR_NAMES, Database
from ui.board_widget import BoardWidget
from ui.engine_service import EngineService, Ticket
from ui.new_game_dialog import resolve_color
from ui.sound import SoundPlayer
from ui.theme import Theme
from ui.widgets import ExplanationBlock, ExplanationPanel, FenBar, MoveList, NavBar, header_bar, navigation_shortcuts

TICK_MS = 100
LOW_TIME_MS = 20_000
MIN_AI_REPLY_MS = 250
ACTIVE_GAME_KEY = "active_game"


def _set_active(label: QLabel, active: bool, low: bool) -> None:
    if label.property("active") != active or label.property("low") != low:
        label.setProperty("active", active)
        label.setProperty("low", low)
        label.style().unpolish(label)
        label.style().polish(label)


class GameScreen(QWidget):
    backRequested = Signal()
    reviewRequested = Signal(int)
    gameSaved = Signal()

    def __init__(self, db: Database, engine: EngineService, sound: SoundPlayer, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.engine = engine
        self.sound = sound
        self.session: Optional[GameSession] = None
        self._color_choice = "white"
        self._view_ply = 0
        self._comments: dict[int, tuple[str, Optional[Mark]]] = {}
        self._tickets: list[Ticket] = []
        self._ai_ticket: Optional[Ticket] = None
        self._hint_ticket: Optional[Ticket] = None
        self._hint_text = ""
        self._draw_offered_at = -1
        self._paused = False
        self._ai_error = False
        self._seen_terms: set[str] = db.seen_terms()
        self._ai_clock = QElapsedTimer()

        header, self.title = header_bar("Партия", self._on_back)
        self.board = BoardWidget(theme)
        self.board.moveAttempted.connect(self._on_board_move)

        self.top_name, self.bottom_name = QLabel(), QLabel()
        self.top_clock, self.bottom_clock = QLabel("0:00"), QLabel("0:00")
        for clock in (self.top_clock, self.bottom_clock):
            clock.setObjectName("clock")
            clock.setAlignment(Qt.AlignCenter)
            clock.setMinimumWidth(130)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)

        self.moves = MoveList()
        self.moves.plySelected.connect(self._go_to_ply)
        self.coach = ExplanationPanel()
        self.nav = NavBar(
            lambda: self._go_to_ply(0),
            lambda: self._go_to_ply(self._view_ply - 1),
            lambda: self._go_to_ply(self._view_ply + 1),
            self._go_to_latest,
        )
        self.fen_bar = FenBar()

        self.hint_button = self._button("Подсказка", self._on_hint)
        self.flip_button = self._button("Повернуть", self._on_flip)
        self.undo_button = self._button("Отменить ход", self._on_undo)
        self.draw_button = self._button("Ничья", self._on_draw)
        self.resign_button = self._button("Сдаться", self._on_resign)
        self.pause_button = self._button("Пауза", self._on_pause)
        self.rematch_button = self._button("Реванш", self._on_rematch)
        self.review_button = self._button("Разбор партии", self._on_review)
        self.review_button.setObjectName("primary")
        self.retry_button = self._button("Повторить ход AI", self._on_retry_ai)

        buttons = QGridLayout()
        buttons.setSpacing(6)
        for index, button in enumerate((
            self.hint_button, self.flip_button, self.undo_button,
            self.draw_button, self.resign_button, self.pause_button,
        )):
            buttons.addWidget(button, index // 3, index % 3)
        end_row = QHBoxLayout()
        end_row.addWidget(self.review_button)
        end_row.addWidget(self.rematch_button)
        end_row.addWidget(self.retry_button)

        top_row = QHBoxLayout()
        top_row.addWidget(self.top_name, 1)
        top_row.addWidget(self.top_clock)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.bottom_name, 1)
        bottom_row.addWidget(self.bottom_clock)

        side = QVBoxLayout()
        side.setSpacing(6)
        side.addLayout(top_row)
        side.addWidget(self.moves, 3)
        side.addWidget(self.nav)
        side.addWidget(self.coach, 3)
        side.addWidget(self.status)
        side.addLayout(end_row)
        side.addLayout(buttons)
        side.addLayout(bottom_row)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(400)
        side.setContentsMargins(0, 0, 0, 0)

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

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        navigation_shortcuts(
            self,
            lambda: self._go_to_ply(0),
            lambda: self._go_to_ply(self._view_ply - 1),
            lambda: self._go_to_ply(self._view_ply + 1),
            self._go_to_latest,
        )

    def _button(self, text: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(handler)
        return button

    def set_theme(self, theme: Theme) -> None:
        self.board.set_theme(theme)

    # --- starting a game -----------------------------------------------------

    def start_game(self, setup: GameSetup, color_choice: str = "white") -> None:
        self._color_choice = color_choice
        self._begin(GameSession(setup))

    def resume_game(
        self, session: GameSession, comments: dict[int, tuple[str, Optional[Mark]]], color_choice: str = "white"
    ) -> None:
        self._color_choice = color_choice
        self._begin(session)
        self._comments = comments
        for ply, (_, mark) in comments.items():
            self.moves.set_mark(ply, mark)
        self._refresh_all(animate=False)

    def _begin(self, session: GameSession) -> None:
        self._timer.stop()
        self._cancel_all()
        self.session = session
        self._comments = {}
        self._hint_text = ""
        self._draw_offered_at = -1
        self._paused = False
        self._ai_error = False
        self._seen_terms = self.db.seen_terms()
        self._view_ply = session.ply_count
        self.board.set_controller(session)
        self.board.set_arrows([])
        self.board.set_flipped(session.setup.player_color == chess.BLACK)
        self.moves.set_start(chess.Board(session.start_fen))
        self.moves.set_moves(session.sans)
        self.moves.set_current_ply(self._view_ply)
        if session.mode == Mode.AI:
            self.title.setText(f"Партия против Stockfish, уровень {session.setup.level}")
        else:
            self.title.setText("Партия вдвоём")
        session.start()
        if session.setup.time_control.untimed:
            for clock in (self.top_clock, self.bottom_clock):
                clock.setText("∞")
                _set_active(clock, False, False)
        else:
            self._timer.start()
        self._refresh_all(animate=False)
        self._warn_if_no_engine()
        if session.is_ai_turn:
            self._request_ai_move()

    def _warn_if_no_engine(self) -> None:
        if not self.engine.available and self.engine.message and self.session.mode != Mode.AI:
            self.coach.show_text(self.engine.message + "\nОбъяснения ходов выключены.")

    # --- moves ---------------------------------------------------------------

    def _on_board_move(self, from_square: int, to_square: int, promotion: int) -> None:
        session = self.session
        if session is None or session.is_over or self._view_ply != session.ply_count:
            return
        move = session.build_move(from_square, to_square, promotion or None)
        if move is not None:
            self._apply_move(move)

    def _apply_move(self, move: chess.Move) -> None:
        session = self.session
        played = session.play(move)
        if played is None:
            self._on_game_over()
            return
        self._hint_text = ""
        self.board.set_arrows([])
        self.moves.append_move(played.san)
        self._view_ply = session.ply_count
        self._persist_move(played)
        self._play_sound(played)
        self._refresh_all(animate=True)
        self._request_explanation(played)
        if session.is_over:
            self._on_game_over()
        elif session.is_ai_turn:
            self._request_ai_move()

    def _play_sound(self, played: PlayedMove) -> None:
        if self.session.is_over:
            return
        self.sound.play("check" if played.is_check else "capture" if played.is_capture else "move")

    # --- AI ------------------------------------------------------------------

    def _request_ai_move(self) -> None:
        session = self.session
        color = session.board.turn
        remaining = None if session.setup.time_control.untimed else session.clock.remaining_ms(color)
        increment = session.setup.time_control.increment * 1000
        self._ai_clock.start()
        self._ai_error = False
        self._ai_ticket = self.engine.request_move(
            session.board, session.setup.level, remaining, increment, self._on_ai_move, self._on_ai_error
        )
        self._refresh_controls()

    def _on_ai_move(self, move: chess.Move) -> None:
        session = self.session
        if session is None or session.is_over or not session.is_ai_turn:
            return
        # Lets the player see their own move land before the reply. The clock keeps
        # running, so skip this when time is short.
        wait = MIN_AI_REPLY_MS - self._ai_clock.elapsed()
        low_time = (
            not session.setup.time_control.untimed
            and session.clock.remaining_ms(session.board.turn) < 10_000
        )
        if wait > 0 and not low_time:
            ticket = self._ai_ticket
            QTimer.singleShot(int(wait), lambda: self._apply_ai_move(move, ticket))
        else:
            self._apply_ai_move(move, self._ai_ticket)

    def _apply_ai_move(self, move: chess.Move, ticket: Optional[Ticket]) -> None:
        session = self.session
        if ticket is None or ticket is not self._ai_ticket or ticket.cancelled:
            return
        if session is None or session.is_over or not session.is_ai_turn:
            return
        self._ai_ticket = None
        if move in session.board.legal_moves:
            self._apply_move(move)

    def _on_ai_error(self, message: str) -> None:
        session = self.session
        if session is None or session.is_over:
            return
        self._ai_ticket = None
        self._ai_error = True
        session.clock.stop()  # the player should not win on time because the engine died
        self.status.setText("Stockfish не отвечает. Партия на паузе.")
        self.coach.show_text(message)
        self._refresh_controls()

    def _on_retry_ai(self) -> None:
        session = self.session
        if session is None or session.is_over or not self._ai_error:
            return
        session.clock.start(session.board.turn)
        self._request_ai_move()
        self._refresh_all(animate=False)

    # --- explanations --------------------------------------------------------

    def _request_explanation(self, played: PlayedMove) -> None:
        session = self.session

        def done(explanation: MoveExplanation) -> None:
            self._on_explanation(session, played, explanation)

        def failed(message: str) -> None:
            if self._still_played(session, played):
                self._comments[played.ply] = (f"Объяснение недоступно: {message}", None)
                self._refresh_coach()

        self._tickets.append(self.engine.request_explanation(played.board_before, played.move, done, failed))
        self._refresh_coach()

    def _still_played(self, session: GameSession, played: PlayedMove) -> bool:
        """False once the move was undone, even if the same ply number holds another move now."""
        return (
            self.session is session
            and session.ply_count >= played.ply
            and session.board.move_stack[played.ply - 1] == played.move
            and session.board_at(played.ply - 1).fen() == played.board_before.fen()
        )

    def _on_explanation(self, session: GameSession, played: PlayedMove, explanation: MoveExplanation) -> None:
        if not self._still_played(session, played):
            return
        before = len(self._seen_terms)
        text = explanation.render(self._seen_terms)
        if len(self._seen_terms) != before:
            self.db.save_seen_terms(self._seen_terms)
        self._comments[played.ply] = (text, explanation.mark)
        self.moves.set_mark(played.ply, explanation.mark)
        if session.game_id is not None:
            self.db.annotate_move(session.game_id, played.ply, explanation.score.cp, text, explanation.mark.value)
        self._refresh_coach()

    def _refresh_coach(self) -> None:
        session = self.session
        if session is None:
            return
        at_latest = self._view_ply == session.ply_count
        plies = [self._view_ply]
        if at_latest and session.mode == Mode.AI and self._view_ply >= 2:
            plies = [self._view_ply - 1, self._view_ply]
        blocks = []
        for ply in plies:
            if ply <= 0:
                continue
            san = session.sans[ply - 1]
            color = chess.WHITE if (ply % 2 == 1) == (chess.Board(session.start_fen).turn == chess.WHITE) else chess.BLACK
            who = self._mover_name(color)
            title = f"{who}: {ru_san(san)}"
            comment = self._comments.get(ply)
            if comment is None:
                blocks.append(ExplanationBlock(title, "", pending=self.engine.available))
                if not self.engine.available:
                    blocks[-1].text = "Объяснений нет: Stockfish недоступен."
            else:
                blocks.append(ExplanationBlock(title, comment[0], comment[1]))
        if self._hint_text and at_latest:
            blocks.append(ExplanationBlock("Подсказка", self._hint_text))
        if not blocks:
            self.coach.show_text(
                "Здесь после каждого хода появится разбор: что он изменил в оценке, "
                "какой ход был лучше и почему."
            )
            return
        self.coach.show_blocks(blocks)

    def _mover_name(self, color: bool) -> str:
        session = self.session
        side = "Белые" if color == chess.WHITE else "Чёрные"
        if session.mode != Mode.AI:
            return side
        return "Ваш ход" if color == session.setup.player_color else "Ход AI"

    # --- persistence ---------------------------------------------------------

    def _ensure_game_row(self) -> int:
        session = self.session
        if session.game_id is None:
            session.game_id = self.db.create_game(
                session.started_at,
                session.mode.value,
                session.setup.player_color,
                session.setup.time_control.storage_key,
                session.outcome.result if session.outcome else "*",
                session_to_pgn(session),
            )
        return session.game_id

    def _persist_move(self, played: PlayedMove) -> None:
        session = self.session
        game_id = self._ensure_game_row()
        self.db.add_move(game_id, played.ply, played.san)
        self.db.update_game(game_id, session.outcome.result if session.outcome else "*", session_to_pgn(session))
        self._save_active_state()

    def _save_active_state(self) -> None:
        session = self.session
        if session is None or session.is_over or session.game_id is None:
            return
        white_ms, black_ms = session.clock.snapshot()
        self.db.set_json(ACTIVE_GAME_KEY, {
            "game_id": session.game_id,
            "mode": session.mode.value,
            "player_color": COLOR_NAMES[session.setup.player_color] if session.setup.player_color is not None else None,
            "level": session.setup.level,
            "time_control": session.setup.time_control.storage_key,
            "white_ms": white_ms,
            "black_ms": black_ms,
            "start_fen": session.start_fen,
            "color_choice": self._color_choice,
        })

    def save_and_leave(self) -> None:
        """Called when leaving the screen or closing the window mid-game."""
        if self.session is not None and not self.session.is_over:
            self._save_active_state()
        self._timer.stop()
        self._cancel_all()
        if self.session is not None:
            self.session.clock.stop()

    # --- game end ------------------------------------------------------------

    def _on_game_over(self) -> None:
        session = self.session
        self._timer.stop()
        self._cancel_ai()
        game_id = self._ensure_game_row()
        self.db.update_game(game_id, session.outcome.result, session_to_pgn(session))
        self.db.delete_setting(ACTIVE_GAME_KEY)
        self.sound.play("end")
        self._view_ply = session.ply_count
        self._refresh_all(animate=False)
        self.gameSaved.emit()

    def _on_resign(self) -> None:
        session = self.session
        if session is None or session.is_over:
            return
        color = session.setup.player_color if session.mode == Mode.AI else session.board.turn
        side = "Белые сдаются" if color == chess.WHITE else "Чёрные сдаются"
        if QMessageBox.question(self, "Сдаться", f"{side}. Точно?") != QMessageBox.Yes:
            return
        if self.session is session and not session.is_over:
            session.resign(color)
            self._on_game_over()

    def _on_draw(self) -> None:
        session = self.session
        if session is None or session.is_over:
            return
        if session.mode == Mode.LOCAL:
            answer = QMessageBox.question(self, "Ничья", "Оба игрока согласны на ничью?")
            if answer == QMessageBox.Yes and self.session is session and not session.is_over:
                session.agree_draw()
                self._on_game_over()
            return
        self._draw_offered_at = session.ply_count
        self.draw_button.setEnabled(False)
        ai_color = not session.setup.player_color
        position = session.board.copy()

        def done(accepted: bool) -> None:
            if self.session is not session or session.is_over:
                return
            if accepted and session.board.fen() == position.fen():
                session.agree_draw()
                self._on_game_over()
            elif accepted:
                self.status.setText("Позиция изменилась, предложите ничью ещё раз.")
                self._draw_offered_at = -1
                self._refresh_controls()
            else:
                self.status.setText("AI отказался от ничьей: по его оценке, можно играть дальше.")

        def failed(message: str) -> None:
            if self.session is session and not session.is_over:
                self.status.setText(message)
                self._draw_offered_at = -1
                self._refresh_controls()

        self._tickets.append(self.engine.request_draw_decision(position, ai_color, done, failed))

    def _on_undo(self) -> None:
        session = self.session
        if session is None:
            return
        size = session.undo_size()
        if not size or self._paused:
            return
        self._cancel_ai()
        removed_from = session.ply_count - size + 1
        session.undo()
        self.moves.pop_moves(size)
        for ply in range(removed_from, removed_from + size):
            self._comments.pop(ply, None)
        self._hint_text = ""
        self.board.set_arrows([])
        self._view_ply = session.ply_count
        if session.game_id is not None:
            self.db.delete_moves_from(session.game_id, removed_from)
            self.db.update_game(session.game_id, "*", session_to_pgn(session))
            self._save_active_state()
        self._refresh_all(animate=False)
        if session.is_ai_turn:
            self._request_ai_move()

    def _on_rematch(self) -> None:
        session = self.session
        if session is None:
            return
        setup = session.setup
        if setup.mode == Mode.AI:
            setup = GameSetup(Mode.AI, setup.time_control, resolve_color(self._color_choice), setup.level)
        self.start_game(setup, self._color_choice)

    def _on_review(self) -> None:
        session = self.session
        if session is not None and session.game_id is not None:
            self.reviewRequested.emit(session.game_id)

    def _on_hint(self) -> None:
        session = self.session
        if session is None or session.is_over or session.is_ai_turn or self._view_ply != session.ply_count:
            return
        self.hint_button.setEnabled(False)
        self._hint_text = "Считаю…"
        self._refresh_coach()
        ply = session.ply_count

        def done(hints: list[Hint]) -> None:
            if self.session is not session or session.ply_count != ply:
                return
            self._hint_text = "\n".join(h.text for h in hints) or "Вариантов нет."
            self.board.set_arrows(
                (h.move.from_square, h.move.to_square, 1.0 - index * 0.3) for index, h in enumerate(hints)
            )
            self._refresh_coach()
            self._refresh_controls()

        def failed(message: str) -> None:
            if self.session is session:
                self._hint_text = message
                self._refresh_coach()
                self._refresh_controls()

        self._hint_ticket = self.engine.request_hints(session.board, 3, done, failed)
        self._tickets.append(self._hint_ticket)

    def _on_flip(self) -> None:
        self.board.set_flipped(not self.board.flipped)
        self._refresh_players()

    def _on_pause(self) -> None:
        session = self.session
        if session is None or not session.can_pause:
            return
        self._paused = not self._paused
        if self._paused:
            session.clock.stop()
        else:
            session.clock.start(session.board.turn)
        self._refresh_all(animate=False)

    def _on_back(self) -> None:
        self.save_and_leave()
        self.backRequested.emit()

    # --- ticks and refresh ---------------------------------------------------

    def _tick(self) -> None:
        session = self.session
        if session is None:
            return
        if not session.is_over and session.clock.is_running and session.poll_flag() is not None:
            self._on_game_over()
            return
        self._refresh_clocks()

    def _refresh_all(self, animate: bool) -> None:
        self._refresh_board(animate)
        self._refresh_players()
        self._refresh_coach()
        self._refresh_status()
        self._refresh_controls()

    def _refresh_board(self, animate: bool) -> None:
        session = self.session
        at_latest = self._view_ply == session.ply_count
        board = session.board if at_latest else session.board_at(self._view_ply)
        last = session.moves[self._view_ply - 1] if self._view_ply > 0 else None
        self.board.set_position(board, last, animate and at_latest)
        self.fen_bar.set_fen(board.fen())
        self.moves.set_current_ply(self._view_ply)
        self.board.set_interactive(self._interactive_colors(at_latest))

    def _interactive_colors(self, at_latest: bool) -> set[bool]:
        session = self.session
        if not at_latest or session.is_over or self._paused or self._ai_error:
            return set()
        if session.mode == Mode.AI:
            return set() if session.is_ai_turn else {session.setup.player_color}
        return {session.board.turn}

    def _refresh_players(self) -> None:
        session = self.session
        if session is None:
            return
        bottom = chess.BLACK if self.board.flipped else chess.WHITE
        self.bottom_name.setText(self._player_name(bottom))
        self.top_name.setText(self._player_name(not bottom))
        self._refresh_clocks()

    def _player_name(self, color: bool) -> str:
        session = self.session
        side = "Белые" if color == chess.WHITE else "Чёрные"
        if session.mode != Mode.AI:
            return side
        who = "Вы" if color == session.setup.player_color else f"Stockfish, уровень {session.setup.level}"
        return f"{who} ({side.lower()})"

    def _refresh_clocks(self) -> None:
        session = self.session
        if session is None or session.setup.time_control.untimed:
            return
        bottom = chess.BLACK if self.board.flipped else chess.WHITE
        for color, label in ((bottom, self.bottom_clock), (not bottom, self.top_clock)):
            remaining = session.clock.remaining_ms(color)
            text = format_clock(remaining)
            if label.text() != text:
                label.setText(text)
            active = session.clock.running_color == color
            _set_active(label, active, active and remaining < LOW_TIME_MS)

    def _refresh_status(self) -> None:
        session = self.session
        if session.outcome is not None:
            self.status.setText(session.outcome.text)
        elif self._paused:
            self.status.setText("Пауза")
        elif self._ai_error:
            pass
        elif session.is_ai_turn:
            self.status.setText("AI думает…")
        elif session.board.is_check():
            self.status.setText("Шах!")
        elif session.mode == Mode.AI:
            self.status.setText("Ваш ход")
        else:
            self.status.setText("Ход белых" if session.board.turn == chess.WHITE else "Ход чёрных")

    def _refresh_controls(self) -> None:
        session = self.session
        if session is None:
            return
        running = not session.is_over
        at_latest = self._view_ply == session.ply_count
        human_turn = running and not session.is_ai_turn and not self._paused
        self.hint_button.setEnabled(human_turn and at_latest and self.engine.available and not self._ai_error)
        self.undo_button.setEnabled(session.undo_size() > 0 and not self._paused)
        self.draw_button.setEnabled(running and not self._paused and self._draw_offered_at != session.ply_count)
        self.resign_button.setEnabled(running and not self._paused)
        self.pause_button.setVisible(session.mode == Mode.LOCAL)
        self.pause_button.setEnabled(session.can_pause)
        self.pause_button.setText("Продолжить" if self._paused else "Пауза")
        self.rematch_button.setVisible(not running)
        self.review_button.setVisible(not running)
        self.review_button.setEnabled(session.ply_count > 0)
        self.retry_button.setVisible(self._ai_error and running)

    def _go_to_ply(self, ply: int) -> None:
        session = self.session
        if session is None:
            return
        ply = max(0, min(ply, session.ply_count))
        if ply == self._view_ply:
            return
        self._view_ply = ply
        self._refresh_board(animate=False)
        self._refresh_coach()
        self._refresh_controls()

    def _go_to_latest(self) -> None:
        if self.session is not None:
            self._go_to_ply(self.session.ply_count)

    # --- cancellation --------------------------------------------------------

    def _cancel_ai(self) -> None:
        if self._ai_ticket is not None:
            self._ai_ticket.cancel()
            self._ai_ticket = None

    def _cancel_all(self) -> None:
        self._cancel_ai()
        for ticket in self._tickets:
            ticket.cancel()
        self._tickets = []
