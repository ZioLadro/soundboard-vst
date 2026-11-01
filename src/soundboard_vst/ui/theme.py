"""Tema scuro dell'applicazione."""

BG = "#15171c"
PANEL = "#1e2128"
PANEL_2 = "#262a33"
BORDER = "#323743"
TEXT = "#e6e8ee"
MUTED = "#8b92a3"
ACCENT = "#f2a93b"      # suono in riproduzione, pulsanti principali
ACCENT_2 = "#3ec7b2"    # fader / meter
DANGER = "#e5534b"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 10pt;
}}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

QFrame#panel, QWidget#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#sectionTitle {{
    background: transparent;
    color: {MUTED};
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#stripTitle {{ background: transparent; font-weight: 600; }}
QLabel#dbLabel {{ background: transparent; color: {MUTED}; font-family: Consolas, monospace; font-size: 9pt; }}
QLabel {{ background: transparent; }}

QPushButton, QToolButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 10px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {MUTED}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; color: #1b1406; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #f6bb5e; }}
QPushButton#danger {{ color: {DANGER}; }}
QPushButton#mute {{ padding: 4px 0; font-weight: 700; }}
QPushButton#mute:checked {{ background: {DANGER}; color: white; border: none; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#small {{ padding: 2px 6px; min-width: 18px; }}

QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {ACCENT};
    selection-color: #1b1406;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {BORDER}; }}

QListWidget {{
    background: {PANEL};
    border: none;
    outline: none;
}}
QListWidget#inserts {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QListWidget#inserts::item {{ padding: 4px 6px; border-bottom: 1px solid {PANEL_2}; }}
QListWidget#inserts::item:selected {{ background: {PANEL_2}; color: {TEXT}; }}


QSlider::groove:vertical {{ background: {BG}; width: 6px; border-radius: 3px; }}
QSlider::sub-page:vertical {{ background: {BG}; border-radius: 3px; }}
QSlider::add-page:vertical {{ background: {ACCENT_2}; border-radius: 3px; }}
QSlider::handle:vertical {{
    background: {TEXT}; height: 14px; margin: 0 -8px; border-radius: 4px;
}}
QSlider::groove:horizontal {{ background: {BG}; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_2}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; margin: -5px 0; border-radius: 4px; }}

QCheckBox {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {MUTED}; border-radius: 3px; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT_2}; border-color: {ACCENT_2}; }}

QSplitter::handle {{ background: {BG}; height: 8px; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: {MUTED}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {BORDER}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QDialog {{ background: {BG}; }}

QTabWidget#mainTabs::pane {{ border: none; }}
QTabWidget#mainTabs > QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 8px 18px; margin-right: 4px;
    border: none; border-bottom: 2px solid transparent; font-size: 11pt; font-weight: 600;
}}
QTabWidget#mainTabs > QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabWidget#mainTabs > QTabBar::tab:hover {{ color: {TEXT}; }}

QTabBar#pages::tab {{
    background: {BG}; color: {MUTED}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 4px 12px; margin-right: 4px;
}}
QTabBar#pages::tab:selected {{ background: {PANEL_2}; color: {TEXT}; border-color: {ACCENT}; }}

QListWidget#library {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; }}
QListWidget#library::item {{ padding: 5px 8px; border-radius: 4px; }}
QListWidget#library::item:selected {{ background: {PANEL_2}; color: {TEXT}; }}
QListWidget#library::item:hover {{ background: {PANEL_2}; }}
"""
