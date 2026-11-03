"""Light and dark palettes, applied through QPalette and one stylesheet."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication

from core.explain import Mark
from core.paths import data_dir


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    clock_active: str
    clock_active_text: str
    clock_low: str
    board_light: str
    board_dark: str
    last_move: str
    selected: str
    target: str
    check: str
    arrow: str
    graph_white: str
    graph_black: str
    graph_line: str
    win: str
    draw: str
    loss: str


LIGHT = Theme(
    name="light",
    window="#f5f5f7",
    surface="#ffffff",
    surface_alt="#e8e8ed",
    border="#d8d8dd",
    text="#1d1d1f",
    text_muted="#6e6e73",
    accent="#007aff",
    accent_text="#ffffff",
    clock_active="#007aff",
    clock_active_text="#ffffff",
    clock_low="#d70015",
    board_light="#ecdfc4",
    board_dark="#a97f5b",
    last_move="#d9c33c80",
    selected="#7fa65080",
    target="#2a2a2a55",
    check="#d8362a",
    arrow="#2f7d4fcc",
    graph_white="#ffffff",
    graph_black="#4a4640",
    graph_line="#007aff",
    win="#248a3d",
    draw="#8e8e93",
    loss="#d70015",
)

DARK = Theme(
    name="dark",
    window="#111113",
    surface="#1c1c1e",
    surface_alt="#2c2c2e",
    border="#38383a",
    text="#f5f5f7",
    text_muted="#98989d",
    accent="#0a84ff",
    accent_text="#ffffff",
    clock_active="#0a84ff",
    clock_active_text="#ffffff",
    clock_low="#ff453a",
    board_light="#c9b896",
    board_dark="#7c5f45",
    last_move="#d9c33c70",
    selected="#7fa65080",
    target="#10101066",
    check="#e0483c",
    arrow="#5cc489cc",
    graph_white="#d9d7d2",
    graph_black="#3a3b40",
    graph_line="#0a84ff",
    win="#30d158",
    draw="#98989d",
    loss="#ff453a",
)

THEMES = {"light": LIGHT, "dark": DARK}

MARK_COLORS = {
    Mark.EXCELLENT: "#2e9e5b",
    Mark.GOOD: "#7a9a4a",
    Mark.INACCURACY: "#d39b1d",
    Mark.MISTAKE: "#e0701f",
    Mark.BLUNDER: "#d6332a",
}


_current = DARK


def current_theme() -> Theme:
    return _current


def apply_theme(app: QApplication, theme: Theme) -> None:
    global _current
    _current = theme
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.Window: theme.window,
        QPalette.WindowText: theme.text,
        QPalette.Base: theme.surface,
        QPalette.AlternateBase: theme.surface_alt,
        QPalette.Text: theme.text,
        QPalette.Button: theme.surface_alt,
        QPalette.ButtonText: theme.text,
        QPalette.ToolTipBase: theme.surface,
        QPalette.ToolTipText: theme.text,
        QPalette.Highlight: theme.accent,
        QPalette.HighlightedText: theme.accent_text,
        QPalette.PlaceholderText: theme.text_muted,
        QPalette.Link: theme.accent,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(theme.text_muted))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(theme))


def _chevron(color: str, up: bool) -> str:
    """Path of a small arrow picture: a stylesheet can only take arrows from a file."""
    path: Path = data_dir() / f"chevron_{'up' if up else 'down'}_{color.lstrip('#')}.png"
    if not path.exists():
        size = 32
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        top, bottom = (22.0, 11.0) if up else (11.0, 22.0)
        painter.drawPolyline([QPointF(6, top), QPointF(16, bottom), QPointF(26, top)])
        painter.end()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(path))
    return path.as_posix()


def _stylesheet(t: Theme) -> str:
    hover = QColor(t.surface_alt).lighter(115 if t.name == "dark" else 97).name()
    pressed = QColor(t.surface_alt).lighter(135 if t.name == "dark" else 90).name()
    accent_hover = QColor(t.accent).lighter(112).name()
    accent_pressed = QColor(t.accent).darker(118).name()
    return f"""
    QWidget {{ font-family: "SF Pro Text", "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; }}
    QLabel#screenTitle {{ font-size: 17pt; font-weight: 600; }}
    QLabel#appTitle {{ font-size: 32pt; font-weight: 700; }}
    QLabel#muted {{ color: {t.text_muted}; }}
    QLabel#status {{ font-size: 11pt; font-weight: 600; }}
    QLabel#clock {{
        font-size: 22pt; font-weight: 600; padding: 4px 14px; border-radius: 12px;
        background: {t.surface_alt}; color: {t.text_muted};
    }}
    QLabel#clock[active="true"] {{ background: {t.clock_active}; color: {t.clock_active_text}; }}
    QLabel#clock[low="true"] {{ background: {t.clock_low}; color: #ffffff; }}
    QFrame#card {{ background: {t.surface}; border-radius: 18px; }}
    QPushButton {{
        padding: 9px 12px; min-height: 20px; border: 2px solid transparent; border-radius: 12px;
        background: {t.surface_alt}; font-size: 10.5pt; font-weight: 500;
    }}
    QPushButton:hover:enabled {{ background: {hover}; }}
    QPushButton:pressed {{ background: {pressed}; }}
    QPushButton[keyboardFocus="true"] {{ border-color: {t.accent}; }}
    QPushButton:disabled {{ color: {t.text_muted}; background: {t.window}; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.accent_text}; font-weight: 600; }}
    QPushButton#primary:hover:enabled {{ background: {accent_hover}; }}
    QPushButton#primary:pressed {{ background: {accent_pressed}; }}
    QPushButton#primary[keyboardFocus="true"] {{ border-color: {t.text}; }}
    QPushButton#primary:disabled {{ background: {t.surface_alt}; color: {t.text_muted}; }}
    QPushButton#modeButton {{
        padding: 18px; font-size: 12.5pt; font-weight: 600; text-align: left;
        background: {t.surface}; border-radius: 18px;
    }}
    QPushButton#modeButton:hover:enabled {{ background: {QColor(t.surface).lighter(125 if t.name == "dark" else 98).name()}; }}
    QPushButton#modeButton:pressed {{ background: {hover}; }}
    QPushButton#linkButton {{ background: transparent; color: {t.accent}; padding: 6px 10px; }}
    QPushButton#linkButton:hover:enabled {{ background: {t.surface_alt}; }}
    QPushButton#iconButton {{ padding: 0; min-height: 0; background: transparent; border-radius: 14px; }}
    QPushButton#iconButton:hover:enabled {{ background: {t.surface_alt}; }}
    QPushButton#iconButton:pressed {{ background: {pressed}; }}
    QTextBrowser, QTableWidget, QLineEdit {{
        background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px;
    }}
    QLineEdit {{ padding: 6px 10px; }}
    QComboBox, QSpinBox {{
        padding: 6px 10px; border: 1px solid {t.border}; border-radius: 10px; background: {t.surface};
    }}
    QComboBox::drop-down {{ background: transparent; border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url({_chevron(t.text_muted, False)}); width: 12px; height: 12px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: 24px; }}
    QSpinBox::up-arrow {{ image: url({_chevron(t.text_muted, True)}); width: 11px; height: 11px; }}
    QSpinBox::down-arrow {{ image: url({_chevron(t.text_muted, False)}); width: 11px; height: 11px; }}
    QSpinBox QLineEdit {{ background: transparent; border: none; padding: 0 0 0 8px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border-radius: 10px; selection-background-color: {t.accent}; }}
    QTableWidget {{ gridline-color: transparent; outline: none; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {t.surface_alt}; border: none; padding: 4px 6px; }}
    QTableWidget#gameTable {{ border: none; border-radius: 14px; }}
    QTableWidget#gameTable::item {{ padding: 0 11px; border-bottom: 1px solid {t.surface_alt}; }}
    QTableWidget#gameTable QHeaderView::section {{
        background: {t.surface}; color: {t.text_muted}; font-weight: 600; padding: 9px 14px;
        border-bottom: 1px solid {t.border};
    }}
    QProgressBar {{ border: none; border-radius: 8px; text-align: center; background: {t.surface_alt}; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 8px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 28px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent; width: 0; height: 0;
    }}
    """
