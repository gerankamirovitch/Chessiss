"""Light, dark and liquid glass palettes, applied through QPalette and one stylesheet."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPalette, QPen
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
    dark: bool = False
    glass: bool = False  # see-through surfaces over the painted backdrop


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
    dark=False,
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
    dark=True,
)

# Liquid glass: one theme that follows the system's light or dark mode. Surfaces are
# #AARRGGBB, partly transparent, so the backdrop shows through them.
GLASS_DARK = Theme(
    name="glass",
    window="#0b0d17",
    surface="#a61a1c2a",
    surface_alt="#26ffffff",
    border="#30ffffff",
    text="#f5f5f7",
    text_muted="#a8acbb",
    accent="#0a84ff",
    accent_text="#ffffff",
    clock_active="#0a84ff",
    clock_active_text="#ffffff",
    clock_low="#ff453a",
    board_light=DARK.board_light,
    board_dark=DARK.board_dark,
    last_move=DARK.last_move,
    selected=DARK.selected,
    target=DARK.target,
    check=DARK.check,
    arrow=DARK.arrow,
    graph_white=DARK.graph_white,
    graph_black=DARK.graph_black,
    graph_line="#0a84ff",
    win=DARK.win,
    draw=DARK.draw,
    loss=DARK.loss,
    dark=True,
    glass=True,
)

GLASS_LIGHT = Theme(
    name="glass",
    window="#e9eef8",
    surface="#b8ffffff",
    surface_alt="#8cffffff",
    border="#26000000",
    text="#1d1d1f",
    text_muted="#585c6b",
    accent="#007aff",
    accent_text="#ffffff",
    clock_active="#007aff",
    clock_active_text="#ffffff",
    clock_low="#d70015",
    board_light=LIGHT.board_light,
    board_dark=LIGHT.board_dark,
    last_move=LIGHT.last_move,
    selected=LIGHT.selected,
    target=LIGHT.target,
    check=LIGHT.check,
    arrow=LIGHT.arrow,
    graph_white=LIGHT.graph_white,
    graph_black=LIGHT.graph_black,
    graph_line="#007aff",
    win=LIGHT.win,
    draw=LIGHT.draw,
    loss=LIGHT.loss,
    dark=False,
    glass=True,
)

THEMES = {"light": LIGHT, "dark": DARK}
THEME_NAMES = ("light", "dark", "glass")


def theme_by_name(name: str | None) -> Theme:
    """The saved setting to a palette. Glass picks its light or dark version from Windows."""
    if name == "glass":
        scheme = QGuiApplication.styleHints().colorScheme() if QGuiApplication.instance() else Qt.ColorScheme.Dark
        return GLASS_LIGHT if scheme == Qt.ColorScheme.Light else GLASS_DARK
    return THEMES.get(name or "", LIGHT)

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


def _hex(color: QColor) -> str:
    return color.name(QColor.HexArgb) if color.alpha() < 255 else color.name()


def _shade(value: str, factor: int) -> str:
    """Lighter (factor > 100) or darker (< 100), keeping the transparency."""
    color = QColor(value)
    alpha = color.alpha()
    color = color.lighter(factor) if factor >= 100 else color.darker(round(10000 / factor))
    color.setAlpha(alpha)
    return _hex(color)


def _raised(top: str, bottom: str) -> str:
    """A soft vertical gradient: the light falls from above, so a button looks raised."""
    return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom})"


def _stylesheet(t: Theme) -> str:
    dark = t.dark
    hover = _shade(t.surface_alt, 115 if dark else 97)
    pressed = _shade(t.surface_alt, 135 if dark else 90)
    accent_hover = _shade(t.accent, 112)
    accent_pressed = _shade(t.accent, 85)
    button = _raised(_shade(t.surface_alt, 118 if dark else 104), _shade(t.surface_alt, 96 if dark else 97))
    button_hover = _raised(_shade(hover, 118 if dark else 104), hover)
    primary = _raised(_shade(t.accent, 116), _shade(t.accent, 92))
    primary_hover = _raised(_shade(accent_hover, 112), accent_hover)
    mode = _raised(_shade(t.surface, 122 if dark else 100), _shade(t.surface, 100 if dark else 98))
    mode_hover = _shade(t.surface, 130 if dark else 98)
    highlight = "#38ffffff" if dark else "#f2ffffff"  # the lit top edge
    shadow = "#66000000" if dark else "#2e000000"  # the shaded bottom edge
    edges = f"border-top-color: {highlight}; border-bottom-color: {shadow};"
    disabled = t.surface_alt if t.glass else t.window
    chat = t.surface if dark else t.surface_alt
    card_edge = f"border: 1px solid {t.border}; border-top-color: {highlight};" if t.glass else "border: none;"
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
    QFrame#card {{ background: {t.surface}; border-radius: 18px; {card_edge} }}
    QPushButton {{
        padding: 9px 12px; min-height: 20px; border: 2px solid transparent; {edges} border-radius: 12px;
        background: {button}; font-size: 10.5pt; font-weight: 500;
    }}
    QPushButton:hover:enabled {{ background: {button_hover}; }}
    QPushButton:pressed {{ background: {pressed}; border-top-color: {shadow}; border-bottom-color: {highlight}; }}
    QPushButton[keyboardFocus="true"] {{ border-color: {t.accent}; }}
    QPushButton:disabled {{ color: {t.text_muted}; background: {disabled}; border-color: transparent; }}
    QPushButton#primary {{ background: {primary}; color: {t.accent_text}; font-weight: 600; }}
    QPushButton#primary:hover:enabled {{ background: {primary_hover}; }}
    QPushButton#primary:pressed {{ background: {accent_pressed}; }}
    QPushButton#primary[keyboardFocus="true"] {{ border-color: {t.text}; }}
    QPushButton#primary:disabled {{ background: {t.surface_alt}; color: {t.text_muted}; }}
    QPushButton#modeButton {{
        padding: 20px 22px; min-height: 60px; font-size: 13.5pt; font-weight: 600; text-align: left;
        background: {mode}; border-radius: 18px;
    }}
    QPushButton#modeButton:hover:enabled {{ background: {mode_hover}; }}
    QPushButton#modeButton:pressed {{ background: {hover}; }}
    QPushButton#linkButton {{ background: transparent; border-color: transparent; color: {t.accent}; padding: 6px 10px; }}
    QPushButton#linkButton:hover:enabled {{ background: {t.surface_alt}; }}
    QPushButton#iconButton {{ padding: 0; min-height: 0; background: transparent; border-color: transparent; border-radius: 14px; }}
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
    QComboBox QAbstractItemView {{
        background: {t.surface if not t.glass else ("#f21c1e2b" if dark else "#f5ffffff")}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 10px; padding: 4px;
        outline: none; selection-background-color: {t.accent}; selection-color: {t.accent_text};
    }}
    QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 7px; color: {t.text}; background: transparent; }}
    QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
        background: {t.accent}; color: {t.accent_text};
    }}
    QTableWidget {{ gridline-color: transparent; outline: none; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {t.surface_alt}; border: none; padding: 4px 6px; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}
    QTableWidget#gameTable {{ border: none; border-radius: 14px; }}
    QTableWidget#gameTable::item {{ padding: 0 11px; border-bottom: 1px solid {t.surface_alt}; }}
    QTableWidget#gameTable QHeaderView::section {{
        background: transparent; color: {t.text_muted}; font-weight: 600; padding: 9px 14px;
        border-bottom: 1px solid {t.border};
    }}
    QProgressBar {{ border: none; border-radius: 8px; text-align: center; background: {t.surface_alt}; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 8px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollArea#chat {{ background: {chat}; border: 1px solid {t.border}; border-radius: 12px; }}
    QWidget#chatContent {{ background: transparent; }}
    QFrame#playerCard {{ background: {t.surface}; border: 2px solid transparent; border-radius: 14px; }}
    QFrame#playerCard[toMove="true"] {{ border-color: {t.accent}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 28px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent; width: 0; height: 0;
    }}
    QToolTip {{ background: {t.surface if not t.glass else ("#1c1e2b" if dark else "#ffffff")}; color: {t.text}; border: 1px solid {t.border}; }}
    """
