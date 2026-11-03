"""Application startup."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox

from core.i18n import set_language, t
from core.paths import data_dir, database_path, puzzle_seed_path
from storage.db import Database
from ui.engine_service import EngineService
from ui.fx import install_press_animation
from ui.main_window import MainWindow
from ui.sound import SoundPlayer
from ui.theme import apply_theme, theme_by_name


def _log_exception(kind, value, trace) -> None:
    """A bug in a slot gets logged and shown; the app keeps running and data stays saved."""
    text = "".join(traceback.format_exception(kind, value, trace))
    try:
        with (data_dir() / "error.log").open("a", encoding="utf-8") as log:
            log.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}\n")
    except OSError:
        pass
    if sys.stderr is not None:
        sys.stderr.write(text)
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None, "Chessiss",
            t("Внутренняя ошибка: {error}\nПодробности записаны в {path}.", error=value, path=data_dir() / "error.log"),
        )


def create_window(app: QApplication) -> tuple[MainWindow, Database, EngineService]:
    db = Database(database_path())
    seed = puzzle_seed_path()
    if seed.exists():
        db.seed_puzzles_from_file(seed)
    set_language(db.get_setting("language"))
    apply_theme(app, theme_by_name(db.get_setting("theme")))
    install_press_animation(app)
    engine = EngineService(db.get_setting("stockfish_path") or "")
    sound = SoundPlayer(db.get_setting("sound") == "1", db.get_setting("move_sound"))
    window = MainWindow(db, engine, sound)
    return window, db, engine


def run() -> int:
    sys.excepthook = _log_exception
    app = QApplication(sys.argv)
    app.setApplicationName("Chessiss")
    window, db, engine = create_window(app)
    window.show()
    engine.warm_up()
    code = app.exec()
    engine.shutdown()
    db.close()
    return code
