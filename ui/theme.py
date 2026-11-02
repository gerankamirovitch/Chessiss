"""Light and dark palettes, applied through QPalette and one stylesheet."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from core.explain import Mark


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


LIGHT = Theme(
    name="light",
    window="#f3f1ec",
    surface="#ffffff",
    surface_alt="#eae7df",
    border="#d4d0c6",
    text="#23211d",
    text_muted="#6b675e",
    accent="#3f6d4e",
    accent_text="#ffffff",
    clock_active="#3f6d4e",
    clock_active_text="#ffffff",
    clock_low="#b3362b",
    board_light="#ecdfc4",
    board_dark="#a97f5b",
    last_move="#d9c33c80",
    selected="#7fa65080",
    target="#2a2a2a55",
    check="#d8362a",
    arrow="#2f7d4fcc",
    graph_white="#ffffff",
    graph_black="#4a4640",
    graph_line="#3f6d4e",
)

DARK = Theme(
    name="dark",
    window="#1f2023",
    surface="#2a2b2f",
    surface_alt="#35363b",
    border="#44454b",
    text="#e8e6e1",
    text_muted="#a3a19b",
    accent="#6aa67d",
    accent_text="#10150f",
    clock_active="#6aa67d",
    clock_active_text="#10150f",
    clock_low="#e0584c",
    board_light="#c9b896",
    board_dark="#7c5f45",
    last_move="#d9c33c70",
    selected="#7fa65080",
    target="#10101066",
    check="#e0483c",
    arrow="#5cc489cc",
    graph_white="#d9d7d2",
    graph_black="#3a3b40",
    graph_line="#6aa67d",
)

THEMES = {"light": LIGHT, "dark": DARK}

MARK_COLORS = {
    Mark.EXCELLENT: "#2e9e5b",
    Mark.GOOD: "#7a9a4a",
    Mark.INACCURACY: "#d39b1d",
    Mark.MISTAKE: "#e0701f",
    Mark.BLUNDER: "#d6332a",
}


def apply_theme(app: QApplication, theme: Theme) -> None:
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


def _stylesheet(t: Theme) -> str:
    return f"""
    QWidget {{ font-family: "Segoe UI"; font-size: 10pt; }}
    QLabel#screenTitle {{ font-size: 16pt; font-weight: 600; }}
    QLabel#appTitle {{ font-size: 30pt; font-weight: 700; }}
    QLabel#muted {{ color: {t.text_muted}; }}
    QLabel#status {{ font-size: 11pt; font-weight: 600; }}
    QLabel#clock {{
        font-size: 22pt; font-weight: 600; padding: 4px 12px; border-radius: 6px;
        background: {t.surface_alt}; color: {t.text_muted};
    }}
    QLabel#clock[active="true"] {{ background: {t.clock_active}; color: {t.clock_active_text}; }}
    QLabel#clock[low="true"] {{ background: {t.clock_low}; color: #ffffff; }}
    QPushButton {{
        padding: 6px 12px; border: 1px solid {t.border}; border-radius: 6px;
        background: {t.surface_alt};
    }}
    QPushButton:hover:enabled {{ border-color: {t.accent}; }}
    QPushButton:focus {{ border: 2px solid {t.accent}; padding: 5px 11px; }}
    QPushButton:disabled {{ color: {t.text_muted}; background: {t.window}; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
    QPushButton#modeButton {{
        padding: 16px; font-size: 13pt; font-weight: 600; text-align: left;
        background: {t.surface}; border-radius: 10px;
    }}
    QTextBrowser, QTableWidget, QLineEdit, QComboBox, QSpinBox {{
        background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px;
    }}
    QTableWidget {{ gridline-color: transparent; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QHeaderView::section {{ background: {t.surface_alt}; border: none; padding: 4px 6px; }}
    QProgressBar {{ border: 1px solid {t.border}; border-radius: 6px; text-align: center; background: {t.surface}; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 5px; }}
    """
