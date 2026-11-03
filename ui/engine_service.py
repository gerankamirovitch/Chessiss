"""Runs engine work off the UI thread and returns results to it.

Two processes: one plays at the chosen level, one analyses at full strength, so a
weakened opponent never lowers the quality of the explanations. Each has its own
single worker thread. A crashed engine is restarted once before the error is reported.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Sequence

import chess
from PySide6.QtCore import QObject, Signal, Slot

from core.analysis import Analyzer, review_game
from core.engine import Engine, EngineFailure, find_stockfish
from core.i18n import t

NOT_FOUND_MESSAGE = (
    "Stockfish не найден. Укажите путь к stockfish.exe в настройках. "
    "Игра вдвоём, пазлы и просмотр партий работают и без него."
)


class Ticket:
    """Handle of a queued request. After cancel() the callbacks never run."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class EngineService(QObject):
    statusChanged = Signal(bool, str)  # available, message
    _deliver = Signal(object)

    def __init__(self, custom_path: str = "", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._custom_path = custom_path
        self._play_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-play")
        self._analysis_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-analysis")
        self._play: Optional[Engine] = None
        self._analysis: Optional[Engine] = None
        self._analyzer: Optional[Analyzer] = None
        self._available = True
        self._message = ""
        self._closed = False
        self._deliver.connect(self._run_delivered)

    @Slot(object)
    def _run_delivered(self, callback: Callable[[], None]) -> None:
        if not self._closed:
            callback()

    # --- state ---------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    @property
    def message(self) -> str:
        return self._message

    def warm_up(self) -> None:
        """Starts the analysis process in the background so the app opens at once."""
        self._analysis_pool.submit(self._warm_up_job)

    def set_custom_path(self, path: str) -> None:
        self._custom_path = path
        self._play_pool.submit(self._drop_play)
        self._analysis_pool.submit(self._drop_analysis)
        self.warm_up()

    def shutdown(self) -> None:
        self._closed = True
        self._play_pool.submit(self._drop_play)
        self._analysis_pool.submit(self._drop_analysis)
        self._play_pool.shutdown(wait=True, cancel_futures=False)
        self._analysis_pool.shutdown(wait=True, cancel_futures=False)

    # --- requests ------------------------------------------------------------

    def request_move(
        self,
        board: chess.Board,
        level: int,
        remaining_ms: Optional[int],
        increment_ms: int,
        on_done: Callable[[chess.Move], None],
        on_error: Callable[[str], None],
    ) -> Ticket:
        position = board.copy()
        return self._submit(
            self._play_pool,
            self._play_engine,
            lambda engine: engine.best_move(position, level, remaining_ms, increment_ms),
            on_done,
            on_error,
        )

    def request_explanation(self, board: chess.Board, move: chess.Move, on_done, on_error) -> Ticket:
        position = board.copy()
        return self._submit_analysis(lambda analyzer: analyzer.explain(position, move), on_done, on_error)

    def request_hints(self, board: chess.Board, count: int, on_done, on_error) -> Ticket:
        position = board.copy()
        return self._submit_analysis(lambda analyzer: analyzer.hints(position, count), on_done, on_error)

    def request_draw_decision(self, board: chess.Board, ai_color: bool, on_done, on_error) -> Ticket:
        position = board.copy()
        return self._submit_analysis(lambda analyzer: analyzer.accepts_draw(position, ai_color), on_done, on_error)

    def request_review(
        self,
        start_fen: str,
        moves: Sequence[chess.Move],
        on_progress: Callable[[int, int], None],
        on_done,
        on_error,
    ) -> Ticket:
        moves = list(moves)
        ticket = Ticket()

        def progress(done: int, total: int) -> None:
            self._deliver.emit(lambda: None if ticket.cancelled else on_progress(done, total))

        def work(engine: Engine):
            return review_game(engine, start_fen, moves, progress, lambda: ticket.cancelled)

        return self._submit(self._analysis_pool, self._analysis_engine, work, on_done, on_error, ticket)

    # --- plumbing ------------------------------------------------------------

    def _submit_analysis(self, work, on_done, on_error) -> Ticket:
        def run(engine: Engine):
            if self._analyzer is None or self._analyzer.engine is not engine:
                self._analyzer = Analyzer(engine)
            return work(self._analyzer)

        return self._submit(self._analysis_pool, self._analysis_engine, run, on_done, on_error)

    def _submit(self, pool, get_engine, work, on_done, on_error, ticket: Optional[Ticket] = None) -> Ticket:
        ticket = ticket or Ticket()

        def job() -> None:
            if ticket.cancelled or self._closed:
                return
            try:
                engine = get_engine()
                try:
                    result = work(engine)
                except EngineFailure:
                    if ticket.cancelled or self._closed:
                        return
                    engine.restart()
                    result = work(engine)
            except EngineFailure as error:
                message = str(error)
                self._set_status(False, message)
                self._deliver.emit(lambda: None if ticket.cancelled else on_error(message))
                return
            except Exception as error:  # a bad position or a python-chess error must not kill the worker
                message = t("Ошибка анализа: {error}", error=error)
                self._deliver.emit(lambda: None if ticket.cancelled else on_error(message))
                return
            self._set_status(True, "")
            self._deliver.emit(lambda: None if ticket.cancelled else on_done(result))

        pool.submit(job)
        return ticket

    def _set_status(self, available: bool, message: str, force: bool = False) -> None:
        if not force and (available, message) == (self._available, self._message):
            return
        self._available, self._message = available, message

        def notify() -> None:
            self.statusChanged.emit(available, message)

        self._deliver.emit(notify)

    def _make_engine(self, threads: int, hash_mb: int) -> Engine:
        path = find_stockfish(self._custom_path or None)
        if path is None:
            raise EngineFailure(t(NOT_FOUND_MESSAGE))
        engine = Engine(path, threads=threads, hash_mb=hash_mb)
        engine.start()
        return engine

    def _play_engine(self) -> Engine:
        if self._play is None or not self._play.is_running:
            self._play = self._make_engine(threads=1, hash_mb=32)
        return self._play

    def _analysis_engine(self) -> Engine:
        if self._analysis is None or not self._analysis.is_running:
            self._analysis = self._make_engine(threads=2, hash_mb=128)
        return self._analysis

    def _warm_up_job(self) -> None:
        try:
            self._analysis_engine()
        except EngineFailure as error:
            self._set_status(False, str(error), force=True)
        else:
            self._set_status(True, "", force=True)

    def _drop_play(self) -> None:
        engine, self._play = self._play, None
        if engine is not None:
            engine.stop()

    def _drop_analysis(self) -> None:
        engine, self._analysis = self._analysis, None
        self._analyzer = None
        if engine is not None:
            engine.stop()
