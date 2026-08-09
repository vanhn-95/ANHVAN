"""Bảng màu và stylesheet tối cho SubAI Studio."""

ACCENT = "#4f8cff"
BG = "#14161c"
SURFACE = "#1c1f27"
SURFACE_ALT = "#232733"
BORDER = "#2e3441"
TEXT = "#e6e9f0"
MUTED = "#8b93a7"
OK = "#3ecf8e"
WARN = "#f5b544"
DANGER = "#ff5f6b"

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Noto Sans", "Ubuntu", sans-serif;
    font-size: 13px;
}}
QLabel, QCheckBox {{
    background: transparent;
}}
QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 9px;
    min-height: 20px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
/* Cố tình KHÔNG style QComboBox::drop-down / ::down-arrow.
   Đặt bất kỳ luật nào lên hai phần tử này sẽ tắt cách vẽ của style Fusion và
   mũi tên biến mất, khiến combo trông y hệt ô text — người dùng không biết là
   bấm được để xổ danh sách. Để Fusion tự vẽ mũi tên gốc. */
QComboBox QAbstractItemView {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    outline: none;
}}
QPushButton {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px 16px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton#primary {{
    background-color: {ACCENT};
    border: none;
    color: #ffffff;
    font-weight: 600;
    padding: 10px 22px;
}}
QPushButton#primary:hover {{ background-color: #6ba0ff; }}
QPushButton#primary:disabled {{ background-color: #34405c; color: {MUTED}; }}
QPushButton#danger {{ border-color: {DANGER}; color: {DANGER}; }}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 9px 18px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-bottom-color: {SURFACE};
}}
QProgressBar {{
    background-color: {SURFACE_ALT};
    border: none;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 7px;
}}
QPlainTextEdit#log {{
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    background-color: #0f1116;
}}
QCheckBox {{
    padding: 4px 0;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QLabel#title {{ font-size: 19px; font-weight: 700; }}
QLabel#subtitle {{ color: {MUTED}; }}
QLabel#stage {{ font-weight: 600; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
