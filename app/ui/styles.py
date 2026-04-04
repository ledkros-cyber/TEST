"""Application stylesheet and color constants."""

BG = "#1a1b2e"
SURFACE = "#252640"
SURFACE2 = "#2f3050"
ACCENT = "#6c63ff"
ACCENT_HOVER = "#8b84ff"
ACCENT_DANGER = "#e05260"
TEXT = "#e8e8f0"
TEXT_DIM = "#9090aa"
INPUT_BG = "#1e1f35"
BORDER = "#3a3b55"
SUCCESS = "#4caf81"
WARNING = "#f0a030"

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG};
}}

/* --- Tab Bar --- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {SURFACE};
    border-radius: 6px;
}}
QTabBar::tab {{
    background-color: {BG};
    color: {TEXT_DIM};
    padding: 10px 22px;
    border: none;
    border-bottom: 3px solid transparent;
    font-weight: bold;
    font-size: 13px;
    min-width: 100px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 3px solid {ACCENT};
    background-color: {SURFACE};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
    background-color: {SURFACE2};
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton:pressed {{
    background-color: #5a53cc;
}}
QPushButton:disabled {{
    background-color: {SURFACE2};
    color: {TEXT_DIM};
}}
QPushButton#danger {{
    background-color: {ACCENT_DANGER};
}}
QPushButton#danger:hover {{
    background-color: #f07080;
}}
QPushButton#secondary {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QPushButton#secondary:hover {{
    background-color: {BORDER};
}}

/* --- LineEdit / TextEdit --- */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {INPUT_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}

/* --- ComboBox --- */
QComboBox {{
    background-color: {INPUT_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    min-height: 28px;
}}
QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

/* --- SpinBox / DoubleSpinBox --- */
QSpinBox, QDoubleSpinBox {{
    background-color: {INPUT_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    min-height: 28px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}

/* --- Slider --- */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background: {SURFACE2};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: none;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}

/* --- GroupBox --- */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 8px;
    font-weight: bold;
    color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {ACCENT};
}}

/* --- Table --- */
QTableWidget {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT};
}}
QTableWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    background-color: {SURFACE2};
    color: {TEXT_DIM};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: bold;
    font-size: 12px;
}}

/* --- ScrollBar --- */
QScrollBar:vertical {{
    background: {SURFACE};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* --- ProgressBar --- */
QProgressBar {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

/* --- Label --- */
QLabel#title {{
    font-size: 18px;
    font-weight: bold;
    color: {ACCENT};
}}
QLabel#subtitle {{
    font-size: 13px;
    color: {TEXT_DIM};
}}
QLabel#status_ok {{
    color: {SUCCESS};
    font-weight: bold;
}}
QLabel#status_err {{
    color: {ACCENT_DANGER};
    font-weight: bold;
}}

/* --- CheckBox --- */
QCheckBox {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {BORDER};
    border-radius: 4px;
    background: {INPUT_BG};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* --- Splitter --- */
QSplitter::handle {{
    background: {BORDER};
}}

/* --- ScrollArea --- */
QScrollArea {{
    border: none;
}}
"""
