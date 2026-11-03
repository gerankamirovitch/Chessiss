"""Settings. Every change is written to the database at once."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.engine import MAX_LEVEL, MIN_LEVEL
from core.i18n import LANGUAGES, t
from storage.db import Database
from ui.engine_service import EngineService
from ui.widgets import header_bar


class SettingsScreen(QWidget):
    backRequested = Signal()
    themeChanged = Signal(str)
    soundChanged = Signal(bool)
    languageChanged = Signal(str)

    def __init__(self, db: Database, engine: EngineService, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.engine = engine
        header, _ = header_bar(t("Настройки"), self.backRequested.emit)

        self.theme_box = QComboBox()
        self.theme_box.addItem(t("Светлая"), "light")
        self.theme_box.addItem(t("Тёмная"), "dark")
        self.sound_box = QCheckBox(t("Звук ходов"))
        self.language_box = QComboBox()
        for code, name in LANGUAGES.items():
            self.language_box.addItem(name, code)
        self.level_box = QSpinBox()
        self.level_box.setRange(MIN_LEVEL, MAX_LEVEL)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(t("Встроенный Stockfish"))
        browse = QPushButton(t("Выбрать…"))
        browse.clicked.connect(self._browse)
        reset = QPushButton(t("Встроенный"))
        reset.clicked.connect(self._use_bundled)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(reset)

        self.engine_status = QLabel()
        self.engine_status.setWordWrap(True)

        form = QFormLayout()
        form.addRow(t("Тема"), self.theme_box)
        form.addRow("", self.sound_box)
        form.addRow(t("Язык"), self.language_box)
        form.addRow(t("Уровень AI по умолчанию"), self.level_box)
        form.addRow(t("Путь к Stockfish"), path_row)
        form.addRow(t("Состояние движка"), self.engine_status)

        form_widget = QWidget()
        form_widget.setLayout(form)
        form_widget.setMaximumWidth(720)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.addWidget(header)
        root.addWidget(form_widget, 0, Qt.AlignTop)
        root.addStretch(1)

        self.load()
        self.theme_box.currentIndexChanged.connect(self._on_theme)
        self.sound_box.toggled.connect(self._on_sound)
        self.language_box.currentIndexChanged.connect(self._on_language)
        self.level_box.valueChanged.connect(lambda v: self.db.set_setting("ai_level", str(v)))
        self.path_edit.editingFinished.connect(self._on_path_edited)
        self.engine.statusChanged.connect(self._on_engine_status)  # a bound method: disconnects with this screen

    def load(self) -> None:
        self.theme_box.setCurrentIndex(self.theme_box.findData(self.db.get_setting("theme")))
        self.sound_box.setChecked(self.db.get_setting("sound") == "1")
        self.language_box.setCurrentIndex(self.language_box.findData(self.db.get_setting("language")))
        self.level_box.setValue(int(self.db.get_setting("ai_level")))
        self.path_edit.setText(self.db.get_setting("stockfish_path") or "")
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self.engine.available:
            self.engine_status.setText(t("Stockfish работает."))
        else:
            self.engine_status.setText(self.engine.message)

    def _on_engine_status(self, _available: bool, _message: str) -> None:
        self._refresh_status()

    def _on_language(self) -> None:
        value = self.language_box.currentData()
        self.db.set_setting("language", value)
        self.languageChanged.emit(value)

    def _on_theme(self) -> None:
        value = self.theme_box.currentData()
        self.db.set_setting("theme", value)
        self.themeChanged.emit(value)

    def _on_sound(self, enabled: bool) -> None:
        self.db.set_setting("sound", "1" if enabled else "0")
        self.soundChanged.emit(enabled)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Stockfish", "", t("Программы (*.exe);;Все файлы (*)"))
        if path:
            self.path_edit.setText(path)
            self._apply_path(path)

    def _use_bundled(self) -> None:
        self.path_edit.setText("")
        self._apply_path("")

    def _on_path_edited(self) -> None:
        path = self.path_edit.text().strip()
        if path != (self.db.get_setting("stockfish_path") or "") or not self.engine.available:
            self._apply_path(path)

    def _apply_path(self, path: str) -> None:
        self.db.set_setting("stockfish_path", path)
        self.engine.set_custom_path(path)
        self.engine_status.setText(t("Проверяю движок…"))
