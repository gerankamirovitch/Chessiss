"""Main window: home screen and navigation between screens."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.clock import PRESETS, UNTIMED, TimeControl
from core.explain import Mark
from core.game import GameSession, GameSetup, Mode
from core.pgn_io import read_first_game
from storage.db import COLORS_BY_NAME, Database
from ui.analysis_screen import AnalysisScreen
from ui.engine_service import EngineService
from ui.game_screen import ACTIVE_GAME_KEY, GameScreen
from ui.history_screen import GameTable, HistoryScreen
from ui.new_game_dialog import NewGameDialog
from ui.puzzle_screens import PuzzleListScreen, PuzzleSolveScreen
from ui.settings_screen import SettingsScreen
from ui.sound import SoundPlayer
from ui.theme import THEMES, apply_theme


class HomeScreen(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        title = QLabel("Chessiss")
        title.setObjectName("appTitle")
        subtitle = QLabel("Шахматы с тренером, который объясняет каждый ход")
        subtitle.setObjectName("muted")

        self.ai_button = self._mode_button("Против AI\nИгра с разбором ходов")
        self.local_button = self._mode_button("Вдвоём\nЗа одним компьютером")
        self.puzzles_button = self._mode_button("Пазлы\nТактика по темам")
        self.analysis_button = self._mode_button("Анализ партии\nЗагрузить PGN и разобрать")

        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self.ai_button, 0, 0)
        grid.addWidget(self.local_button, 0, 1)
        grid.addWidget(self.puzzles_button, 1, 0)
        grid.addWidget(self.analysis_button, 1, 1)

        self.resume_button = QPushButton("Продолжить прерванную партию")
        self.resume_button.setObjectName("primary")
        self.history_button = QPushButton("История партий")
        self.settings_button = QPushButton("Настройки")
        row = QHBoxLayout()
        row.addWidget(self.resume_button)
        row.addStretch(1)
        row.addWidget(self.history_button)
        row.addWidget(self.settings_button)

        self.engine_warning = QLabel()
        self.engine_warning.setWordWrap(True)

        recent = QLabel("Последние партии")
        recent.setObjectName("status")
        self.recent = GameTable()
        self.recent_empty = QLabel("Здесь появятся сыгранные партии.")
        self.recent_empty.setObjectName("muted")

        column = QVBoxLayout()
        column.setSpacing(10)
        column.addWidget(title)
        column.addWidget(subtitle)
        column.addLayout(grid)
        column.addLayout(row)
        column.addWidget(self.engine_warning)
        column.addWidget(recent)
        column.addWidget(self.recent_empty)
        column.addWidget(self.recent, 1)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(860)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(holder)

    def _mode_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("modeButton")
        button.setAutoDefault(False)
        return button


class MainWindow(QMainWindow):
    def __init__(self, db: Database, engine: EngineService, sound: SoundPlayer) -> None:
        super().__init__()
        self.db = db
        self.engine = engine
        self.sound = sound
        self.setWindowTitle("Chessiss")
        self.resize(1200, 800)
        self.setMinimumSize(900, 620)
        theme = THEMES.get(db.get_setting("theme"), THEMES["light"])

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomeScreen()
        self.game_screen = GameScreen(db, engine, sound, theme)
        self.analysis_screen = AnalysisScreen(db, engine, theme)
        self.puzzle_list = PuzzleListScreen(db)
        self.puzzle_solve = PuzzleSolveScreen(db, sound, theme)
        self.history = HistoryScreen(db)
        self.settings = SettingsScreen(db, engine)
        for screen in (
            self.home, self.game_screen, self.analysis_screen, self.puzzle_list,
            self.puzzle_solve, self.history, self.settings,
        ):
            self.stack.addWidget(screen)

        self.home.ai_button.clicked.connect(lambda: self.new_game(Mode.AI))
        self.home.local_button.clicked.connect(lambda: self.new_game(Mode.LOCAL))
        self.home.puzzles_button.clicked.connect(self.show_puzzles)
        self.home.analysis_button.clicked.connect(self.show_analysis)
        self.home.history_button.clicked.connect(self.show_history)
        self.home.settings_button.clicked.connect(lambda: self._show(self.settings))
        self.home.resume_button.clicked.connect(self.resume_game)
        self.home.recent.gameActivated.connect(self.open_saved_game)

        self.game_screen.backRequested.connect(self.show_home)
        self.game_screen.reviewRequested.connect(lambda game_id: self.open_saved_game(game_id, auto_review=True))
        self.game_screen.gameSaved.connect(self.refresh_home)
        self.analysis_screen.backRequested.connect(self.show_home)
        self.analysis_screen.gamesChanged.connect(self.refresh_home)
        self.puzzle_list.backRequested.connect(self.show_home)
        self.puzzle_list.puzzleChosen.connect(self.open_puzzle)
        self.puzzle_solve.backRequested.connect(self.show_puzzles)
        self.history.backRequested.connect(self.show_home)
        self.history.openGame.connect(self.open_saved_game)
        self.settings.backRequested.connect(self.show_home)
        self.settings.themeChanged.connect(self.apply_theme_name)
        self.settings.soundChanged.connect(self._on_sound_changed)
        self.engine.statusChanged.connect(lambda *_: self.refresh_home())

        self.show_home()

    # --- navigation ----------------------------------------------------------

    def _show(self, screen: QWidget) -> None:
        self.stack.setCurrentWidget(screen)

    def show_home(self) -> None:
        self.refresh_home()
        self._show(self.home)

    def refresh_home(self) -> None:
        games = self.db.list_games(limit=8)
        self.home.recent.set_games(games)
        self.home.recent.setVisible(bool(games))
        self.home.recent_empty.setVisible(not games)
        self.home.resume_button.setVisible(self.db.get_json(ACTIVE_GAME_KEY) is not None)
        if self.engine.available:
            self.home.engine_warning.setVisible(False)
        else:
            self.home.engine_warning.setText(self.engine.message)
            self.home.engine_warning.setVisible(True)

    def show_puzzles(self) -> None:
        self.puzzle_list.refresh()
        self._show(self.puzzle_list)

    def open_puzzle(self, puzzle_id: str, queue: list[str]) -> None:
        self.puzzle_solve.open_puzzle(puzzle_id, queue)
        self._show(self.puzzle_solve)

    def show_analysis(self) -> None:
        self._show(self.analysis_screen)
        if self.analysis_screen.game is None:
            self.analysis_screen.choose_file()

    def show_history(self) -> None:
        self.history.refresh()
        self._show(self.history)

    def open_saved_game(self, game_id: int, auto_review: bool = False) -> None:
        self.analysis_screen.show_saved_game(game_id, auto_review)
        self._show(self.analysis_screen)

    # --- games ---------------------------------------------------------------

    def new_game(self, mode: Mode) -> None:
        if mode == Mode.AI and not self.engine.available:
            QMessageBox.warning(self, "Stockfish", self.engine.message)
            return
        dialog = NewGameDialog(
            mode,
            int(self.db.get_setting("ai_level")),
            self.db.get_setting("last_time_control"),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        setup = dialog.setup()
        self.db.set_setting("last_time_control", setup.time_control.storage_key)
        self._show(self.game_screen)
        self.game_screen.start_game(setup, dialog.color_choice)

    def resume_game(self) -> None:
        session_and_comments = self._load_active_game()
        if session_and_comments is None:
            self.db.delete_setting(ACTIVE_GAME_KEY)
            self.refresh_home()
            QMessageBox.information(self, "Партия", "Прерванную партию не удалось восстановить.")
            return
        session, comments, color_choice = session_and_comments
        self._show(self.game_screen)
        self.game_screen.resume_game(session, comments, color_choice)

    def _load_active_game(self):
        state = self.db.get_json(ACTIVE_GAME_KEY)
        if not state:
            return None
        row = self.db.get_game(state.get("game_id", -1))
        parsed = read_first_game(row.pgn) if row is not None else None
        if parsed is None:
            return None
        try:
            control = TimeControl.from_storage_key(state["time_control"])
            mode = Mode(state["mode"])
            setup = GameSetup(
                mode,
                self._preset_for(control),
                COLORS_BY_NAME.get(state.get("player_color")),
                int(state.get("level") or 0),
            )
            session = GameSession.resume(
                setup, parsed.start_fen, parsed.moves, int(state["white_ms"]), int(state["black_ms"]),
                started_at=row.date, game_id=row.id,
            )
        except (KeyError, ValueError):
            return None
        comments: dict[int, tuple[str, Optional[Mark]]] = {}
        for stored in self.db.get_moves(row.id):
            if stored.comment:
                comments[stored.ply] = (stored.comment, Mark(stored.mark) if stored.mark else None)
        return session, comments, state.get("color_choice", "white")

    @staticmethod
    def _preset_for(control: TimeControl) -> TimeControl:
        if control.untimed:
            return UNTIMED
        for preset in PRESETS:
            if preset.storage_key == control.storage_key:
                return preset
        return control

    # --- settings ------------------------------------------------------------

    def apply_theme_name(self, name: str) -> None:
        theme = THEMES.get(name, THEMES["light"])
        apply_theme(QApplication.instance(), theme)
        for screen in (self.game_screen, self.analysis_screen, self.puzzle_solve):
            screen.set_theme(theme)

    def _on_sound_changed(self, enabled: bool) -> None:
        self.sound.enabled = enabled

    # --- closing -------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.game_screen.save_and_leave()
        self.analysis_screen.cancel_review()
        event.accept()
