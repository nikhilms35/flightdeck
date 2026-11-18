from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

ASSETS = Path(__file__).resolve().parent / "assets"

T = dict(
    bg="#0B0F14",
    surface="#11161D",
    surface2="#161C25",
    raised="#1C2430",
    border="#242D3A",
    border_hi="#32404F",
    text="#E6EDF3",
    muted="#8B98A6",
    faint="#5C6876",
    accent="#3D8BFD",
    accent_hi="#5C9FFF",
    accent_soft="#16263D",
    ok="#2FBF71",
    ok_soft="#10291D",
    warn="#E8A93A",
    warn_soft="#2E2512",
    danger="#F05A52",
    danger_soft="#33161A",
)

UI_FONT = "Inter"
MONO_FONT = "JetBrains Mono"


def load_fonts():
    global UI_FONT, MONO_FONT
    fams = {}
    for f in (ASSETS / "fonts").glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(f))
        for fam in QFontDatabase.applicationFontFamilies(fid):
            fams[fam.lower()] = fam
    UI_FONT = next((v for k, v in fams.items() if k.startswith("inter")), "Sans Serif")
    MONO_FONT = next((v for k, v in fams.items() if "jetbrains" in k), "Monospace")
    f = QFont(UI_FONT, 10)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def mono(size=10, bold=False):
    f = QFont(MONO_FONT, size)
    f.setBold(bold)
    return f


def stylesheet():
    t = T
    return f"""
* {{ font-family: "{UI_FONT}"; color: {t['text']}; }}
QMainWindow, QWidget#Root {{ background: {t['bg']}; }}
QWidget {{ background: transparent; font-size: 10pt; }}
QToolTip {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['border_hi']};
            padding: 6px 8px; border-radius: 6px; }}

/* ---------- chrome ---------- */
QFrame#TopBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
QFrame#SideBar {{ background: {t['surface']}; border-right: 1px solid {t['border']}; }}
QLabel#Wordmark {{ font-size: 13pt; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#WordmarkAccent {{ font-size: 13pt; font-weight: 700; color: {t['accent']}; }}
QToolButton#Nav {{ border: none; border-radius: 10px; padding: 10px 6px; color: {t['muted']};
                   font-size: 9pt; font-weight: 600; }}
QToolButton#Nav:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QToolButton#Nav:checked {{ background: {t['accent_soft']}; color: {t['accent_hi']}; }}
QFrame#StatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
QLabel#StatusText {{ color: {t['muted']}; font-size: 9pt; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QLabel#CardTitle {{ color: {t['muted']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#H1 {{ font-size: 17pt; font-weight: 700; }}
QLabel#H2 {{ font-size: 12.5pt; font-weight: 650; }}
QLabel#Muted {{ color: {t['muted']}; }}
QLabel#Faint {{ color: {t['faint']}; font-size: 9pt; }}
QFrame#Tile {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QLabel#TileLabel {{ color: {t['muted']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#TileUnit {{ color: {t['faint']}; font-size: 9pt; }}
QLabel#Callout {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px;
                  padding: 12px 14px; color: {t['text']}; }}
QLabel#Callout[kind="warn"] {{ background: {t['warn_soft']}; border-color: #5A4418; }}
QLabel#Callout[kind="danger"] {{ background: {t['danger_soft']}; border-color: #5E2328; }}
QLabel#Callout[kind="ok"] {{ background: {t['ok_soft']}; border-color: #1C4A31; }}
QLabel#BigPrompt {{ font-size: 20pt; font-weight: 700; color: {t['accent_hi']}; }}

/* ---------- pills ---------- */
QLabel#Pill {{ border-radius: 11px; padding: 3px 10px; font-size: 8.5pt; font-weight: 700;
               background: {t['surface2']}; color: {t['muted']}; border: 1px solid {t['border']}; }}
QLabel#Pill[kind="ok"] {{ background: {t['ok_soft']}; color: {t['ok']}; border-color: #1C4A31; }}
QLabel#Pill[kind="warn"] {{ background: {t['warn_soft']}; color: {t['warn']}; border-color: #5A4418; }}
QLabel#Pill[kind="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; border-color: #5E2328; }}
QLabel#Pill[kind="accent"] {{ background: {t['accent_soft']}; color: {t['accent_hi']}; border-color: #23426B; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {t['raised']}; border: 1px solid {t['border_hi']}; border-radius: 8px;
               padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: #243042; border-color: #3D4C5E; }}
QPushButton:pressed {{ background: #1A2230; }}
QPushButton:disabled {{ color: {t['faint']}; background: {t['surface2']}; border-color: {t['border']}; }}
QPushButton[kind="primary"] {{ background: {t['accent']}; border-color: {t['accent']}; color: white; }}
QPushButton[kind="primary"]:hover {{ background: {t['accent_hi']}; border-color: {t['accent_hi']}; }}
QPushButton[kind="primary"]:disabled {{ background: #22344F; border-color: #22344F; color: #7D8FA8; }}
QPushButton[kind="danger"] {{ background: {t['danger_soft']}; border-color: #6B272C; color: {t['danger']}; }}
QPushButton[kind="danger"]:hover {{ background: #46191E; }}
QPushButton[kind="ok"] {{ background: {t['ok_soft']}; border-color: #1F5236; color: {t['ok']}; }}
QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {t['muted']}; }}
QPushButton[kind="ghost"]:hover {{ background: {t['surface2']}; color: {t['text']}; }}

/* ---------- inputs ---------- */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {t['surface2']}; border: 1px solid {t['border_hi']}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {t['accent']}; min-height: 18px; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #415064; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t['raised']}; border: 1px solid {t['border_hi']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; outline: none; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {t['border_hi']};
                        background: {t['surface2']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

/* ---------- tables / lists ---------- */
QTableView, QTableWidget, QListWidget, QPlainTextEdit, QTextEdit {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
    gridline-color: {t['border']}; selection-background-color: {t['accent_soft']};
    selection-color: {t['text']}; alternate-background-color: {t['surface2']}; outline: none; }}
QTableView::item, QTableWidget::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 8px; font-size: 8.5pt; font-weight: 700; }}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}
QListWidget#SubNav {{ background: transparent; border: none; }}
QListWidget#SubNav::item {{ padding: 10px 12px; border-radius: 8px; color: {t['muted']}; margin: 1px 0; }}
QListWidget#SubNav::item:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QListWidget#SubNav::item:selected {{ background: {t['accent_soft']}; color: {t['accent_hi']}; }}

QProgressBar {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 6px;
                height: 12px; text-align: center; font-size: 8pt; color: {t['muted']}; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border_hi']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #46566A; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_hi']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QSplitter::handle {{ background: {t['border']}; }}
QScrollArea {{ border: none; }}
"""
