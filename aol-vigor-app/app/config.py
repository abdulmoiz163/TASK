APP_NAME = "AOL Crop Vigor Analyzer"
APP_VERSION = "2.0"

DEFAULT_TILE_SIZE_M = 3.5
DEFAULT_OVERLAP_PCT = 0.0

BAND_CONFIG = {
    "nir_index": 4,
    "red_index": 1,
    "green_index": 2,
}

NODATA_DEM = -9999
NODATA_INDEX = -9999

C_BG = "#f5f5f5"
C_SURFACE = "#ffffff"
C_PANEL = "#fafafa"
C_BORDER = "#d0d0d0"
C_TEXT = "#1a1a1a"
C_TEXT_SECONDARY = "#666666"
C_MUTED = "#999999"
C_ACCENT = "#2563eb"
C_ACCENT_HOVER = "#1d4ed8"
C_ACCENT_LIGHT = "#dbeafe"
C_SUCCESS = "#16a34a"
C_WARN = "#d97706"
C_ERR = "#dc2626"

C_TILE_LINE = "#2563eb"
C_TILE_FILL = "#2563eb18"
C_AOI_LINE = "#16a34a"
C_AOI_FILL = "#16a34a20"
C_VIGOR_HIGH = "#166534"
C_VIGOR_MEDIUM = "#f59e0b"
C_VIGOR_LOW = "#b91c1c"
C_VIGOR_VERY_HIGH = "#052e16"

STYLE = f"""
QMainWindow, QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    font-size: 12px;
    color: {C_TEXT};
    background: {C_SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {C_ACCENT};
}}
QPushButton {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 6px 16px;
    color: {C_TEXT};
    font-size: 12px;
}}
QPushButton:hover {{
    background: {C_ACCENT_LIGHT};
    border-color: {C_ACCENT};
    color: {C_ACCENT};
}}
QPushButton:pressed {{
    background: {C_ACCENT};
    color: white;
}}
QPushButton:disabled {{
    color: {C_MUTED};
    border-color: {C_BORDER};
    background: {C_PANEL};
}}
QPushButton#primary {{
    background: {C_ACCENT};
    color: white;
    border: none;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {C_ACCENT_HOVER};
}}
QPushButton#danger {{
    background: {C_ERR};
    color: white;
    border: none;
}}
QPushButton#success {{
    background: {C_SUCCESS};
    color: white;
    border: none;
}}
QPushButton:checked {{
    background: {C_ACCENT};
    color: white;
    border-color: {C_ACCENT};
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    color: {C_TEXT};
    font-size: 12px;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    selection-background-color: {C_ACCENT_LIGHT};
    selection-color: {C_ACCENT};
}}
QProgressBar {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    height: 16px;
    text-align: center;
    color: {C_TEXT};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 3px; }}
QTabWidget::pane {{
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    background: {C_SURFACE};
}}
QTabBar::tab {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 6px 16px;
    color: {C_TEXT_SECONDARY};
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {C_SURFACE};
    color: {C_ACCENT};
    border-bottom: 2px solid {C_ACCENT};
}}
QTextEdit {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    color: {C_TEXT};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: {C_PANEL};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_MUTED};
}}
QCheckBox {{ color: {C_TEXT}; spacing: 6px; font-size: 12px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    background: {C_SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {C_ACCENT};
    border-color: {C_ACCENT};
}}
QRadioButton {{ color: {C_TEXT}; spacing: 6px; font-size: 12px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C_BORDER};
    border-radius: 7px;
    background: {C_SURFACE};
}}
QRadioButton::indicator:checked {{
    background: {C_ACCENT};
    border-color: {C_ACCENT};
}}
QSplitter::handle {{ background: {C_BORDER}; }}
QLabel#section {{ color: {C_ACCENT}; font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; }}
QLabel#coord {{ font-family: 'Consolas', monospace; color: {C_TEXT_SECONDARY}; font-size: 11px; }}
QLabel#title {{ font-size: 18px; font-weight: 700; color: {C_TEXT}; }}
QLabel#subtitle {{ font-size: 11px; color: {C_TEXT_SECONDARY}; }}
QLabel#step {{ font-size: 11px; font-weight: 600; color: {C_ACCENT}; }}
"""

VIGOR_COLORS = {
    0: "#b91c1c",
    1: "#f59e0b",
    2: "#16a34a",
    3: "#052e16",
}

VIGOR_LABELS = {
    0: "Low Vigor",
    1: "Medium Vigor",
    2: "High Vigor",
    3: "Very High Vigor",
}
