"""
QC Launcher — 统一样式模块
所有按钮、输入框、列表等控件的共享样式表。
"""

# ============================================================
#  颜色常量
# ============================================================
C_GREEN = "#22c55e"
C_RED = "#ef4444"
C_GRAY = "#6b7280"
C_BORDER = "#e2e8f0"
C_BG = "#f8fafc"
C_ORANGE = "#f59e0b"
C_BLUE = "#3b82f6"

# ============================================================
#  Launcher light-flat design tokens
# ============================================================

LAUNCHER_BG = "#eef2f6"
LAUNCHER_SURFACE = "#ffffff"
LAUNCHER_SURFACE_SOFT = "#f6f8fb"
LAUNCHER_TEXT = "#17324d"
LAUNCHER_TEXT_SECONDARY = "#61758a"
LAUNCHER_MUTED = "#8b9aaa"
LAUNCHER_BORDER = "#d9e1e8"
LAUNCHER_BLUE = "#3d6f9f"
LAUNCHER_GREEN = "#2f9461"
LAUNCHER_ORANGE = "#d49324"
LAUNCHER_RED = "#cf5252"
LAUNCHER_LOG = "#263746"

LAUNCHER_CARD = f"""
    QFrame#flatCard {{
        background: {LAUNCHER_SURFACE};
        border: 1px solid {LAUNCHER_BORDER};
        border-radius: 8px;
    }}
"""

LAUNCHER_INPUT = f"""
    QLineEdit {{
        min-height: 30px;
        border: 1px solid {LAUNCHER_BORDER};
        border-radius: 6px;
        padding: 2px 10px;
        background: {LAUNCHER_SURFACE_SOFT};
        color: {LAUNCHER_TEXT};
        selection-background-color: #cfe0ef;
    }}
    QLineEdit:focus {{
        border-color: {LAUNCHER_BLUE};
        background: {LAUNCHER_SURFACE};
    }}
    QLineEdit:disabled {{
        border-color: #e0e6ec;
        background: #edf1f4;
        color: {LAUNCHER_MUTED};
    }}
"""

LAUNCHER_SEGMENT = f"""
    QRadioButton {{
        min-height: 30px;
        padding: 0 18px;
        color: {LAUNCHER_TEXT_SECONDARY};
        background: {LAUNCHER_SURFACE_SOFT};
        border: 1px solid {LAUNCHER_BORDER};
        border-radius: 6px;
        spacing: 0;
    }}
    QRadioButton::indicator {{
        width: 0;
        height: 0;
        border: none;
        background: transparent;
        image: none;
    }}
    QRadioButton:hover {{ background: #edf3f8; color: {LAUNCHER_TEXT}; }}
    QRadioButton:checked {{
        background: #e3f1e9;
        border-color: #a8d2b9;
        color: #24764d;
        font-weight: bold;
    }}
"""

LAUNCHER_SWITCH = f"""
    QCheckBox {{ color: {LAUNCHER_TEXT_SECONDARY}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 32px;
        height: 18px;
        border-radius: 9px;
        border: 1px solid #cbd5df;
        background: #dfe5eb;
    }}
    QCheckBox::indicator:checked {{
        border-color: {LAUNCHER_GREEN};
        background: {LAUNCHER_GREEN};
    }}
"""

LAUNCHER_PRIMARY_GREEN = f"""
    QPushButton {{
        min-height: 38px;
        border: none;
        border-radius: 35px;
        padding: 0 18px;
        background: {LAUNCHER_GREEN};
        color: white;
        font-weight: bold;
    }}
    QPushButton:hover {{ background: #278354; }}
    QPushButton:pressed {{ background: #206e47; }}
    QPushButton:disabled {{ background: #aab6c1; color: #eef2f6; }}
"""

LAUNCHER_PRIMARY_RED = LAUNCHER_PRIMARY_GREEN.replace(
    LAUNCHER_GREEN, LAUNCHER_RED
).replace("#278354", "#bb4747").replace("#206e47", "#a33d3d")

LAUNCHER_SECONDARY_BUTTON = f"""
    QPushButton {{
        min-height: 24px;
        border: 1px solid {LAUNCHER_BORDER};
        border-radius: 6px;
        padding: 0 12px;
        background: {LAUNCHER_SURFACE};
        color: {LAUNCHER_TEXT};
        font-weight: 600;
    }}
    QPushButton:hover {{ border-color: #b9c8d5; background: #f1f5f8; }}
    QPushButton:pressed {{ background: #e6edf3; }}
    QPushButton:disabled {{ color: {LAUNCHER_MUTED}; background: #edf1f4; }}
"""

LAUNCHER_LOG_STYLE = f"""
    QTextEdit {{
        border: none;
        border-radius: 6px;
        background: {LAUNCHER_LOG};
        color: #e5edf3;
        padding: 10px 12px;
        selection-background-color: #48677f;
    }}
"""

# ============================================================
#  按钮样式模板
# ============================================================

BTN_PRIMARY_TPL = """
    QPushButton {{ border: none; border-radius: 5px; padding: 6px 24px;
        background: {bg}; color: white; font-weight: bold; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:disabled {{ background: #94a3b8; }}
"""

BTN_SMALL_TPL = """
    QPushButton {{ border: none; border-radius: 5px; padding: 5px 14px;
        background: {bg}; color: {fg}; font-weight: bold; }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:disabled {{ background: #94a3b8; }}
"""

# ── 主要按钮（实色背景） ──
BTN_GREEN  = BTN_PRIMARY_TPL.format(bg=C_GREEN, hover="#16a34a")
BTN_RED    = BTN_PRIMARY_TPL.format(bg=C_RED, hover="#dc2626")
BTN_ORANGE = BTN_PRIMARY_TPL.format(bg=C_ORANGE, hover="#d97706")
BTN_BLUE   = BTN_PRIMARY_TPL.format(bg=C_BLUE, hover="#2563eb")

# ── 次要按钮（灰色背景） ──
BTN_SECONDARY = BTN_SMALL_TPL.format(bg="#e2e8f0", fg="#475569", hover="#cbd5e1")

# ============================================================
#  QLineEdit 样式
# ============================================================
INPUT_STYLE = """
    QLineEdit { border: 1px solid #e2e8f0; border-radius: 4px;
        padding: 4px 8px; background: white; }
    QLineEdit:focus { border-color: #3b82f6; }
"""

INPUT_READONLY = """
    QLineEdit { border: 1px solid #e2e8f0; border-radius: 4px;
        padding: 3px 6px; background: #f1f5f9; color: #64748b; }
"""

# ============================================================
#  QComboBox 样式
# ============================================================
COMBO_STYLE = """
    QComboBox { border: 1px solid #e2e8f0; border-radius: 4px;
        padding: 4px 6px; background: white; color: #1e293b; }
"""

# ============================================================
#  QListWidget 样式
# ============================================================
LIST_STYLE = """
    QListWidget { border: 1px solid #e2e8f0; border-radius: 6px;
        background: white; outline: none; }
    QListWidget::item { padding: 6px 8px; border-radius: 4px; }
    QListWidget::item:selected { background: #dbeafe; color: #1e293b; }
    QListWidget::item:hover { background: #f1f5f9; }
"""

# ============================================================
#  QProgressBar 样式
# ============================================================
PROGRESS_BAR = """
    QProgressBar { border: 1px solid #e2e8f0; border-radius: 4px;
        text-align: center; }
    QProgressBar::chunk { background: #22c55e; border-radius: 3px; }
"""

PROGRESS_BAR_TALL = """
    QProgressBar { border: 1px solid #e2e8f0; border-radius: 4px;
        text-align: center; height: 20px; }
    QProgressBar::chunk { background: #22c55e; border-radius: 3px; }
"""

# ============================================================
#  QTextEdit 日志面板样式
# ============================================================
LOG_AREA = """
    QTextEdit { border: 1px solid #e2e8f0; border-radius: 6px;
        background: #0f172a; color: #e2e8f0; padding: 6px; }
"""

# ============================================================
#  QGroupBox 卡片样式
# ============================================================
CARD_STYLE = """
    QGroupBox {{
        border: 1px solid {border};
        border-radius: 8px;
        margin-top: 12px;
        padding: 16px 12px 12px 12px;
        background: {bg};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: #1e293b;
    }}
"""

# ============================================================
#  小工具按钮（加 / 删）
# ============================================================
BTN_ADD_SMALL = """
    QPushButton { border: none; border-radius: 4px; background: transparent;
        color: #22c55e; font-weight: bold; }
    QPushButton:hover { background: #dcfce7; }
"""

BTN_DEL_SMALL = """
    QPushButton { border: none; border-radius: 4px; background: transparent;
        color: #ef4444; font-weight: bold; }
    QPushButton:hover { background: #fee2e2; }
"""

# ============================================================
#  警告条
# ============================================================
WARN_BAR = """
    color: #dc2626; background: #fef2f2;
    border: 1px solid #fecaca; border-radius: 4px;
    padding: 6px 10px;
"""
