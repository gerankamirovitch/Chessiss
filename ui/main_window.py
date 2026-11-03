"""Main window: home screen and navigation between screens."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.clock import PRESETS, UNTIMED, TimeControl
from core.explain import Mark
from core.game import GameSession, GameSetup, Mode
from core.i18n import set_language, t, written_in_current_language
from core.pgn_io import read_first_game
from storage.db import COLORS_BY_NAME, Database, GameRow
from ui.analysis_screen import AnalysisScreen
from ui.engine_service import EngineService
from ui.fx import cross_fade
from ui.game_screen import ACTIVE_GAME_KEY, GameScreen
from ui.history_screen import GameTable, HistoryScreen
from ui.home_widgets import ExpandingIconButton, StatsCard
from ui.new_game_dialog import NewGameDialog
from ui.puzzle_screens import PuzzleListScreen, PuzzleSolveScreen
from ui.settings_screen import SettingsScreen
from ui.sound import SoundPlayer
from ui.theme import THEMES, apply_theme

COLLAPSED_GAMES = 3
EXPAND_MS = 260


class HomeScreen(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        title = QLabel("Chessiss")
        title.setObjectName("appTitle")
        subtitle = QLabel(t("Шахматы с тренером, который объясняет каждый ход"))
        subtitle.setObjectName("muted")

        self.ai_button = self._mode_button(t("Против AI\nИгра с разбором ходов"))
        self.local_button = self._mode_button(t("Вдвоём\nЗа одним компьютером"))
        self.puzzles_button = self._mode_button(t("Пазлы\nТактика по темам"))
        self.analysis_button = self._mode_button(t("Анализ партии\nЗагрузить PGN и разобрать"))

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self.ai_button, 0, 0)
        grid.addWidget(self.local_button, 0, 1)
        grid.addWidget(self.puzzles_button, 1, 0)
        grid.addWidget(self.analysis_button, 1, 1)

        self.stats = StatsCard()
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addLayout(grid, 2)
        top.addWidget(self.stats, 1)

        self.resume_button = QPushButton(t("Продолжить прерванную партию"))
        self.resume_button.setObjectName("primary")

        self.history_button = ExpandingIconButton("history", t("История"))
        self.settings_button = ExpandingIconButton("settings", t("Настройки"))
        corner = QHBoxLayout()
        corner.setContentsMargins(16, 12, 16, 0)
        corner.setSpacing(6)
        corner.addStretch(1)
        corner.addWidget(self.history_button)
        corner.addWidget(self.settings_button)

        self.engine_warning = QLabel()
        self.engine_warning.setWordWrap(True)

        recent = QLabel(t("Последние партии"))
        recent.setObjectName("status")
        self.expand_button = QPushButton(t("Показать все"))
        self.expand_button.setObjectName("linkButton")
        self.expand_button.setAutoDefault(False)
        self.expand_button.clicked.connect(self._toggle_expanded)
        recent_row = QHBoxLayout()
        recent_row.addWidget(recent)
        recent_row.addStretch(1)
        recent_row.addWidget(self.expand_button)

        self.recent = GameTable()
        self.recent.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_empty = QLabel(t("Здесь появятся сыгранные партии."))
        self.recent_empty.setObjectName("muted")
        self._expanded = False
        self._height_animation = QVariantAnimation(self)
        self._height_animation.setDuration(EXPAND_MS)
        self._height_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._height_animation.valueChanged.connect(self.recent.setFixedHeight)
        self._height_animation.finished.connect(self._hide_collapsed_rows)

        column = QVBoxLayout()
        column.setSpacing(12)
        column.addWidget(title)
        column.addWidget(subtitle)
        column.addSpacing(6)
        column.addLayout(top)
        column.addWidget(self.resume_button)
        column.addWidget(self.engine_warning)
        column.addSpacing(6)
        column.addLayout(recent_row)
        column.addWidget(self.recent_empty)
        column.addWidget(self.recent)
        column.addStretch(1)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(1040)
        page = QWidget()
        centered = QHBoxLayout(page)
        centered.setContentsMargins(16, 0, 16, 24)
        centered.addWidget(holder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(corner)
        outer.addWidget(scroll, 1)

    def _mode_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("modeButton")
        button.setAutoDefault(False)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)  # as tall as the statistics card
        return button

    def set_games(self, games: list[GameRow]) -> None:
        self.recent.set_games(games)
        self.recent.setVisible(bool(games))
        self.recent_empty.setVisible(not games)
        self.expand_button.setVisible(len(games) > COLLAPSED_GAMES)
        if len(games) <= COLLAPSED_GAMES:
            self._expanded = False
        self._height_animation.stop()
        self.expand_button.setText(t("Свернуть") if self._expanded else t("Показать все"))
        self.recent.setFixedHeight(self.recent.height_for_rows(self._visible_rows()))
        self._hide_collapsed_rows()

    def _visible_rows(self) -> int:
        count = self.recent.rowCount()
        return count if self._expanded else min(count, COLLAPSED_GAMES)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.expand_button.setText(t("Свернуть") if self._expanded else t("Показать все"))
        for row in range(self.recent.rowCount()):  # stay visible while the table slides shut
            self.recent.setRowHidden(row, False)
        self._height_animation.stop()
        self._height_animation.setStartValue(self.recent.height())
        self._height_animation.setEndValue(self.recent.height_for_rows(self._visible_rows()))
        self._height_animation.start()

    def _hide_collapsed_rows(self) -> None:
        for row in range(self.recent.rowCount()):
            self.recent.setRowHidden(row, not self._expanded and row >= COLLAPSED_GAMES)


class MainWindow(QMainWindow):
    def __init__(self, db: Database, engine: EngineService, sound: SoundPlayer) -> None:
        super().__init__()
        self.db = db
        self.engine = engine
        self.sound = sound
        self.setWindowTitle("Chessiss")
        self.resize(1200, 800)
        self.setMinimumSize(900, 620)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_screens()
        self.engine.statusChanged.connect(lambda *_: self.refresh_home())

        self.show_home()

    def _build_screens(self) -> None:
        """Texts are set when a screen is built, so a new language means new screens."""
        theme = THEMES.get(self.db.get_setting("theme"), THEMES["light"])
        db, engine, sound = self.db, self.engine, self.sound
        self.home = HomeScreen()
        self.game_screen = GameScreen(db, engine, sound, theme)
        self.analysis_screen = AnalysisScreen(db, engine, theme)
        self.puzzle_list = PuzzleListScreen(db)
        self.puzzle_solve = PuzzleSolveScreen(db, sound, theme)
        self.history = HistoryScreen(db)
        self.settings = SettingsScreen(db, engine)
        for screen in self._screens():
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
        self.settings.languageChanged.connect(self.apply_language)

    def _screens(self) -> tuple[QWidget, ...]:
        return (
            self.home, self.game_screen, self.analysis_screen, self.puzzle_list,
            self.puzzle_solve, self.history, self.settings,
        )

    # --- navigation ----------------------------------------------------------

    def _show(self, screen: QWidget) -> None:
        if screen is not self.stack.currentWidget():
            cross_fade(self.stack, lambda: self.stack.setCurrentWidget(screen))

    def show_home(self) -> None:
        self.refresh_home()
        self._show(self.home)
        self.home.stats.chart.play()

    def refresh_home(self) -> None:
        self.home.set_games(self.db.list_games())
        self.home.stats.set_stats(self.db.player_stats())
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
            self.engine.warm_up()  # the binary may be back: the next attempt can succeed
            QMessageBox.warning(self, "Stockfish", self.engine.message)
            return
        if self.db.get_json(ACTIVE_GAME_KEY) is not None:
            answer = QMessageBox.question(
                self, t("Новая партия"),
                t(
                    "Есть прерванная партия. Если начать новую, продолжить её будет нельзя: "
                    "она останется в истории как незавершённая. Начать новую?"
                ),
            )
            if answer != QMessageBox.Yes:
                return
            self.db.delete_setting(ACTIVE_GAME_KEY)
            self.refresh_home()
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
            QMessageBox.information(self, t("Партия"), t("Прерванную партию не удалось восстановить."))
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
            if stored.comment and written_in_current_language(stored.comment):  # others get explained anew
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
        self.refresh_home()  # the table colors its scores from the theme

    def apply_language(self, code: str) -> None:
        set_language(code)

        def rebuild() -> None:
            self.game_screen.save_and_leave()
            self.analysis_screen.cancel_review()
            old_screens = self._screens()
            self._build_screens()
            self.stack.setCurrentWidget(self.settings)
            for screen in old_screens:
                self.stack.removeWidget(screen)
                screen.deleteLater()
            self.refresh_home()

        cross_fade(self.stack, rebuild)
        if not self.engine.available:
            self.engine.warm_up()  # writes its message again, in the new language

    def _on_sound_changed(self, enabled: bool) -> None:
        self.sound.enabled = enabled

    # --- closing -------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.game_screen.save_and_leave()
        self.analysis_screen.cancel_review()
        event.accept()
