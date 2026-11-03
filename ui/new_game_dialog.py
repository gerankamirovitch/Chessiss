"""New game settings: color, AI level, time control."""
from __future__ import annotations

import random
from typing import Optional

import chess
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.clock import PRESETS, UNTIMED, TimeControl
from core.engine import MAX_LEVEL, MIN_LEVEL
from core.game import GameSetup, Mode
from core.i18n import t

_CUSTOM = "custom"


def resolve_color(choice: str) -> bool:
    if choice == "white":
        return chess.WHITE
    if choice == "black":
        return chess.BLACK
    return random.choice((chess.WHITE, chess.BLACK))


class NewGameDialog(QDialog):
    def __init__(
        self,
        mode: Mode,
        default_level: int = 5,
        last_control: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle(t("Новая партия"))
        self.setMinimumWidth(380)

        form = QFormLayout()
        self.color_box = QComboBox()
        self.color_box.addItem(t("Белые"), "white")
        self.color_box.addItem(t("Чёрные"), "black")
        self.color_box.addItem(t("Случайно"), "random")

        level_row = QHBoxLayout()
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(MIN_LEVEL, MAX_LEVEL)
        self.level_slider.setValue(default_level)
        self.level_label = QLabel()
        self.level_label.setMinimumWidth(24)
        self.level_slider.valueChanged.connect(lambda v: self.level_label.setText(str(v)))
        self.level_label.setText(str(default_level))
        level_row.addWidget(self.level_slider, 1)
        level_row.addWidget(self.level_label)

        if mode == Mode.AI:
            form.addRow(t("Ваш цвет"), self.color_box)
            form.addRow(t("Уровень AI (1–20)"), level_row)

        self.control_box = QComboBox()
        for control in PRESETS:
            self.control_box.addItem(f"{control.category} {control.label}", control.storage_key)
        self.control_box.addItem(t("Своя настройка"), _CUSTOM)
        self.control_box.addItem(t("Тренировка без таймера"), UNTIMED.storage_key)
        form.addRow(t("Контроль времени"), self.control_box)

        self.minutes = QSpinBox()
        self.minutes.setRange(1, 300)
        self.minutes.setValue(10)
        self.minutes.setSuffix(t(" мин"))
        self.increment = QSpinBox()
        self.increment.setRange(0, 180)
        self.increment.setSuffix(t(" сек"))
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.minutes)
        custom_row.addWidget(QLabel("+"))
        custom_row.addWidget(self.increment)
        self.custom_row_label = QLabel(t("Минуты + инкремент"))
        form.addRow(self.custom_row_label, custom_row)

        self.control_box.currentIndexChanged.connect(self._sync_custom)
        self._select_control(last_control)
        self._sync_custom()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("Начать"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("Отмена"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _select_control(self, key: Optional[str]) -> None:
        index = self.control_box.findData(key) if key else -1
        if index >= 0:
            self.control_box.setCurrentIndex(index)
            return
        if key:
            try:
                control = TimeControl.from_storage_key(key)
            except ValueError:
                return
            self.minutes.setValue(max(1, control.minutes))
            self.increment.setValue(control.increment)
            self.control_box.setCurrentIndex(self.control_box.findData(_CUSTOM))
        else:
            self.control_box.setCurrentIndex(self.control_box.findData("5+0"))

    def _sync_custom(self) -> None:
        custom = self.control_box.currentData() == _CUSTOM
        for widget in (self.minutes, self.increment, self.custom_row_label):
            widget.setEnabled(custom)

    def time_control(self) -> TimeControl:
        data = self.control_box.currentData()
        if data == _CUSTOM:
            return TimeControl(self.minutes.value(), self.increment.value())
        for preset in (*PRESETS, UNTIMED):
            if preset.storage_key == data:
                return preset
        return TimeControl.from_storage_key(data)

    @property
    def color_choice(self) -> str:
        return self.color_box.currentData()

    def setup(self) -> GameSetup:
        if self.mode == Mode.AI:
            return GameSetup(Mode.AI, self.time_control(), resolve_color(self.color_choice), self.level_slider.value())
        return GameSetup(self.mode, self.time_control(), None, 0)
