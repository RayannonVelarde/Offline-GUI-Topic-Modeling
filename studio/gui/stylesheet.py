"""
Theme stylesheets.

- LIGHT is the default (requested).
- DARK preserves the existing visual design.
"""

THEME_LIGHT = "light"
THEME_DARK = "dark"


LIGHT_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #f3f4f6; /* soft off-white */
    color: #1f2937;            /* dark gray (not pure black) */
    font-family: 'Helvetica Neue', 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* ── Sidebar ── */
#sidebar {
    background-color: #eef2f7; /* subtle blue-gray */
    border-right: 1px solid #d7dee8;
    min-width: 288px;
    max-width: 288px;
}

#sidebar-logo {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 24px;
    font-weight: 800;
    letter-spacing: -0.035em;
    word-spacing: -5px;
    color: #0f172a;
    padding: 4px 0px 2px 0px;
    margin: 0px;
    line-height: 1.22;
    background-color: transparent;
    border: none;
    border-radius: 0px;
}

#sidebar-sub {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: -0.035em;
    word-spacing: -1px;
    color: #64748b;
    padding: 0px;
    margin: 0px;
    margin-left: 5px;
    background-color: transparent;
    border: none;
    border-radius: 0px;
}

#nav-btn {
    background: transparent;
    color: #475569;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: 500;
}
#nav-btn:hover {
    background-color: #e6edf7;
    color: #0f172a;
}
#nav-btn-active {
    background-color: #2563eb; /* keep accent language */
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: 600;
}

#version-label {
    color: #94a3b8;
    font-size: 12px;
}

/* ── Theme toggle ── */
#theme-toggle {
    color: #475569;
    spacing: 8px;
    padding: 6px 8px;
    border-radius: 8px;
}
#theme-toggle:hover {
    background-color: #e6edf7;
}
#theme-toggle::indicator {
    width: 16px;
    height: 16px;
}

/* ── Job Options dialog (per-run) ── */
QDialog#job-options-dialog {
    background-color: #f3f4f6;
}
QCheckBox#job-options-checkbox {
    color: #334155;
    spacing: 8px;
    font-size: 13px;
    font-weight: 500;
}
QCheckBox#job-options-checkbox::indicator {
    width: 16px;
    height: 16px;
}
QLabel#settings-dropdown-value {
    color: #0f172a;
    font-size: 13px;
    font-weight: 500;
}
QFrame#job-options-dropdown-field {
    background-color: transparent;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 30px;
}

/* ── Settings ── */
#settings-page QWidget {
    background-color: transparent;
}

#settings-card {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 12px;
}
#settings-label {
    color: #475569;
    font-size: 13px;
    font-weight: 500;
}
#settings-input {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 10px;
    color: #0f172a;
    min-height: 30px;
}
#settings-input:focus {
    border: 1px solid #2563eb;
}
QComboBox#settings-input::drop-down {
    border: none;
    width: 24px;
}
QComboBox#settings-input QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d7dee8;
    selection-background-color: #e8f0ff;
    selection-color: #0f172a;
}

QMenu#settings-translation-menu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 4px;
}
QMenu#settings-translation-menu::item {
    padding: 8px 12px;
    border-radius: 6px;
}
QMenu#settings-translation-menu::item:selected {
    background-color: #e8f0ff;
    color: #0f172a;
}

QToolButton#settings-chevron-btn {
    border: none;
    background: transparent;
    padding: 0px;
}
QToolButton#settings-chevron-btn:hover {
    background: transparent;
}
QToolButton#settings-chevron-btn:pressed {
    background: transparent;
}

QSpinBox#settings-input {
    padding: 7px 10px;
}
QSpinBox#settings-input::up-button, QSpinBox#settings-input::down-button {
    width: 18px;
}

#settings-hint {
    color: #64748b;
    font-size: 12px;
    font-weight: 400;
    margin-top: 2px;
}

#settings-page #settings-card #section-title {
    padding-bottom: 0px;
}

/* ── Review ── */
#review-page QWidget {
    background-color: transparent;
}

#review-page QToolButton#review-open-folder-btn,
#review-page QToolButton#review-open-transcript-btn,
#review-page QToolButton#review-open-translation-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#review-page QToolButton#review-open-folder-btn:hover,
#review-page QToolButton#review-open-transcript-btn:hover,
#review-page QToolButton#review-open-translation-btn:hover {
    background-color: rgba(15, 23, 42, 0.06);
    border-radius: 4px;
}

/* ── Review previews ── */
#review-preview {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    padding: 8px 10px;
    color: #0f172a;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 14px;
    selection-background-color: #bfdbfe;
    selection-color: #0f172a;
}

/* ── Review audio player ── */
#review-volume {
    max-height: 18px;
}
#review-volume::groove:horizontal {
    height: 4px;
    background: #e2e8f0;
    border-radius: 2px;
}
#review-volume::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}
#review-volume::handle:horizontal {
    width: 10px;
    margin: -4px 0;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
}

/* ── Center ── */
#center-panel {
    background-color: #f3f4f6;
}

#page-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.035em;
    color: #0f172a;
}

#page-sub {
    font-size: 13px;
    color: #64748b;
}

#drop-zone {
    background-color: transparent;
    border: 1.5px dashed #cbd5e1;
    border-radius: 12px;
    color: #64748b;
    font-size: 13px;
}
#drop-zone:hover {
    border-color: #3b82f6;
    background-color: transparent;
}

#drop-icon {
    font-size: 32px;
    background-color: #e8f0ff;
    color: #2563eb;
    border-radius: 24px;
    padding: 12px;
    min-width: 54px;
    max-width: 54px;
    min-height: 54px;
    max-height: 54px;
}
#drop-text {
    color: #475569;
    font-size: 15px;
    font-weight: 500;
}

#add-btn {
    background-color: transparent;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    color: #334155;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
}
#add-btn:hover {
    border-color: #2563eb;
    color: #2563eb;
    background-color: #f8fafc;
}

/* Review play button: same hierarchy as add-btn */
QToolButton#review-play-btn {
    background-color: transparent;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    color: #334155;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
}
QToolButton#review-play-btn:hover {
    border-color: #2563eb;
    color: #2563eb;
    background-color: #f8fafc;
}

#home-warning {
    background-color: #fef3c7;
    border: 1px solid #facc15;
    border-radius: 8px;
    color: #92400e;
    font-size: 12px;
    padding: 6px 10px;
}

/* ── Table ── */
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    gridline-color: #d7dee8;
    color: #334155;
    font-size: 13px;
    selection-background-color: #e8f0ff;
}
QTableWidget::item {
    padding: 10px 14px;
    border-bottom: 1px solid #edf2f7;
}
QTableWidget::item:selected {
    background-color: #e8f0ff;
    /* Avoid palette highlightedText (often white); status column still uses delegate colors */
    color: #0f172a;
}
QHeaderView::section {
    background-color: #f3f4f6;
    color: #64748b;
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid #d7dee8;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Home file table: slightly clearer selection + tighter headers */
#home-file-table {
    selection-background-color: #d4e2f7;
}
#home-file-table::item:selected {
    background-color: #d4e2f7;
    color: #0f172a;
}
#home-file-table QHeaderView::section {
    padding: 9px 12px;
    letter-spacing: 0.35px;
}
#home-file-table QWidget#home-filename-cell[homeRowSelected=true],
#home-file-table QWidget#home-status-cell[homeRowSelected=true],
#home-file-table QWidget#home-folder-cell[homeRowSelected=true] {
    background-color: #d4e2f7;
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-open-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-open-btn:hover {
    background-color: rgba(15, 23, 42, 0.06);
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-log-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-log-btn:hover {
    background-color: rgba(15, 23, 42, 0.06);
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-remove-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-remove-btn:hover {
    background-color: rgba(15, 23, 42, 0.06);
    border-radius: 4px;
}

#jobs-table QToolButton#jobs-row-open-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#jobs-table QToolButton#jobs-row-open-btn:hover {
    background-color: rgba(15, 23, 42, 0.06);
    border-radius: 4px;
}

/* Jobs card: "Recent jobs" label + table header row sit flat on card (no inner gray bar) */
#jobs-recent-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 13px;
    font-weight: 800;
    color: #64748b;
    letter-spacing: 0.4px;
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
}

#jobs-table QHeaderView::section {
    background-color: #ffffff;
    color: #64748b;
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid #d7dee8;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* QPushButton: native style can ignore generic #id backgrounds until hover; be explicit. */
QPushButton#start-btn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#start-btn:hover {
    background-color: #1d4ed8;
}
QPushButton#start-btn:pressed {
    background-color: #1d4ed8;
}
QPushButton#start-btn:disabled {
    background-color: #e2e8f0;
    color: #94a3b8;
    border: 1px solid #cbd5e1;
}

#section-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 13px;
    font-weight: 800;
    color: #64748b;
    letter-spacing: 0.4px;
}

#job-card {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    padding: 4px;
}

#job-name {
    font-size: 12px;
    font-weight: 600;
    color: #0f172a;
}

#job-status {
    font-size: 11px;
    color: #64748b;
}

#job-pct {
    font-size: 12px;
    font-weight: 700;
    color: #2563eb;
}

QProgressBar {
    background-color: #e2e8f0;
    border-radius: 3px;
    height: 4px;
    color: transparent;
    border: none;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 3px;
}
QProgressBar#complete::chunk {
    background-color: #22c55e;
}
QProgressBar#error::chunk {
    background-color: #ef4444;
}

#home-file-log {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 8px;
    color: #000000;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

#log-box {
    background-color: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 10px;
    color: #000000;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: 'Helvetica Neue', 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* ── Sidebar ── */
#sidebar {
    background-color: #0a0d13;
    border-right: 1px solid #1e2433;
    min-width: 288px;
    max-width: 288px;
}

#sidebar-logo {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 24px;
    font-weight: 800;
    letter-spacing: -0.035em;
    word-spacing: -5px;
    color: #f1f5f9;
    padding: 4px 0px 2px 0px;
    margin: 0px;
    line-height: 1.22;
    background-color: transparent;
    border: none;
    border-radius: 0px;
}

#sidebar-sub {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: -0.035em;
    word-spacing: -1px;
    color: #475569;
    padding: 0px;
    margin: 0px;
    margin-left: 5px;
    background-color: transparent;
    border: none;
    border-radius: 0px;
}

#nav-btn {
    background: transparent;
    color: #94a3b8;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: 500;
}
#nav-btn:hover {
    background-color: #1e2433;
    color: #e2e8f0;
}
#nav-btn-active {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: 600;
}

#version-label {
    color: #334155;
    font-size: 12px;
}

/* ── Theme toggle ── */
#theme-toggle {
    color: #94a3b8;
    spacing: 8px;
    padding: 6px 8px;
    border-radius: 8px;
}
#theme-toggle:hover {
    background-color: #1e2433;
    color: #e2e8f0;
}
#theme-toggle::indicator {
    width: 16px;
    height: 16px;
}

/* ── Job Options dialog (per-run) ── */
QDialog#job-options-dialog {
    background-color: #0f1117;
}
QCheckBox#job-options-checkbox {
    color: #e2e8f0;
    spacing: 8px;
    font-size: 13px;
    font-weight: 500;
}
QCheckBox#job-options-checkbox::indicator {
    width: 16px;
    height: 16px;
}
QLabel#settings-dropdown-value {
    color: #e2e8f0;
    font-size: 13px;
    font-weight: 500;
}
QFrame#job-options-dropdown-field {
    background-color: transparent;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 30px;
}

/* ── Settings ── */
#settings-page QWidget {
    background-color: transparent;
}

#settings-card {
    background-color: #141720;
    border: 1px solid #1e2433;
    border-radius: 12px;
}
#settings-label {
    color: #94a3b8;
    font-size: 13px;
    font-weight: 500;
}
#settings-input {
    background-color: #0f1117;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 10px;
    color: #e2e8f0;
    min-height: 30px;
}
#settings-input:focus {
    border: 1px solid #3b82f6;
}
QComboBox#settings-input::drop-down {
    border: none;
    width: 24px;
}
QComboBox#settings-input QAbstractItemView {
    background: #0f1117;
    border: 1px solid #1e2433;
    selection-background-color: #1e2d4a;
    selection-color: #e2e8f0;
}

QMenu#settings-translation-menu {
    background-color: #0f1117;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px 4px;
}
QMenu#settings-translation-menu::item {
    padding: 8px 12px;
    border-radius: 6px;
}
QMenu#settings-translation-menu::item:selected {
    background-color: #1e2d4a;
    color: #e2e8f0;
}

QSpinBox#settings-input {
    padding: 7px 10px;
}
QSpinBox#settings-input::up-button, QSpinBox#settings-input::down-button {
    width: 18px;
}

#settings-hint {
    color: #64748b;
    font-size: 12px;
    font-weight: 400;
    margin-top: 2px;
}

#settings-page #settings-card #section-title {
    padding-bottom: 0px;
}

/* ── Review ── */
#review-page QWidget {
    background-color: transparent;
}

#review-page QToolButton#review-open-folder-btn,
#review-page QToolButton#review-open-transcript-btn,
#review-page QToolButton#review-open-translation-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#review-page QToolButton#review-open-folder-btn:hover,
#review-page QToolButton#review-open-transcript-btn:hover,
#review-page QToolButton#review-open-translation-btn:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 4px;
}

/* ── Review previews ── */
#review-preview {
    background-color: #0f1117;
    border: 1px solid #1e2433;
    border-radius: 10px;
    padding: 8px 10px;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 14px;
    selection-background-color: #1e3a5f;
    selection-color: #f1f5f9;
}

/* ── Review audio player ── */
#review-volume {
    max-height: 18px;
}
#review-volume::groove:horizontal {
    height: 4px;
    background: #1e2433;
    border-radius: 2px;
}
#review-volume::sub-page:horizontal {
    background: #3b82f6;
    border-radius: 2px;
}
#review-volume::handle:horizontal {
    width: 10px;
    margin: -4px 0;
    background: #0f1117;
    border: 1px solid #334155;
    border-radius: 6px;
}

/* ── Center ── */
#center-panel {
    background-color: #0f1117;
}

#page-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.035em;
    color: #f1f5f9;
}

#page-sub {
    font-size: 13px;
    color: #64748b;
}

#drop-zone {
    background-color: transparent;
    border: 1.5px dashed #2d3748;
    border-radius: 12px;
    color: #64748b;
    font-size: 13px;
}
#drop-zone:hover {
    border-color: #3b82f6;
    background-color: transparent;
}

#drop-icon {
    font-size: 32px;
    background-color: #1e2d4a;
    color: #3b82f6;
    border-radius: 24px;
    padding: 12px;
    min-width: 54px;
    max-width: 54px;
    min-height: 54px;
    max-height: 54px;
}
#drop-text {
    color: #94a3b8;
    font-size: 15px;
    font-weight: 500;
}

#add-btn {
    background-color: transparent;
    border: 1.5px solid #334155;
    border-radius: 8px;
    color: #cbd5e1;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
}
#add-btn:hover {
    border-color: #3b82f6;
    color: #3b82f6;
    background-color: #161c2e;
}

/* Review play button: same hierarchy as add-btn */
QToolButton#review-play-btn {
    background-color: transparent;
    border: 1.5px solid #334155;
    border-radius: 8px;
    color: #cbd5e1;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
}
QToolButton#review-play-btn:hover {
    border-color: #3b82f6;
    color: #3b82f6;
    background-color: #161c2e;
}

#home-warning {
    background-color: #451a03;
    border: 1px solid #a16207;
    border-radius: 8px;
    color: #fed7aa;
    font-size: 12px;
    padding: 6px 10px;
}

/* ── Table ── */
QTableWidget {
    background-color: #141720;
    border: 1px solid #1e2433;
    border-radius: 10px;
    gridline-color: #1e2433;
    color: #cbd5e1;
    font-size: 13px;
    selection-background-color: #1e2d4a;
}
QTableWidget::item {
    padding: 10px 14px;
    border-bottom: 1px solid #1a1f2e;
}
QTableWidget::item:selected {
    background-color: #1e2d4a;
    color: #e2e8f0;
}
QHeaderView::section {
    background-color: #0f1117;
    color: #475569;
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid #1e2433;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

#home-file-table QHeaderView::section {
    padding: 9px 12px;
    letter-spacing: 0.35px;
}
#home-file-table QWidget#home-filename-cell[homeRowSelected=true],
#home-file-table QWidget#home-status-cell[homeRowSelected=true],
#home-file-table QWidget#home-folder-cell[homeRowSelected=true] {
    background-color: #1e2d4a;
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-open-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-open-btn:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-log-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-log-btn:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 4px;
}
#home-file-table QToolButton#home-row-remove-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#home-file-table QToolButton#home-row-remove-btn:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 4px;
}

#jobs-table QToolButton#jobs-row-open-btn {
    background: transparent;
    border: none;
    padding: 0px;
}
#jobs-table QToolButton#jobs-row-open-btn:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 4px;
}

#jobs-recent-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 13px;
    font-weight: 800;
    color: #94a3b8;
    letter-spacing: 0.4px;
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
}

#jobs-table QHeaderView::section {
    background-color: #141720;
    color: #475569;
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid #1e2433;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QPushButton#start-btn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#start-btn:hover {
    background-color: #1d4ed8;
}
QPushButton#start-btn:pressed {
    background-color: #1d4ed8;
}
QPushButton#start-btn:disabled {
    background-color: #334155;
    color: #64748b;
    border: none;
}

#section-title {
    font-family: 'SF Pro Rounded', 'Nunito', 'Sniglet', 'Chalkboard SE', 'Segoe UI Variable', 'Segoe UI',
        sans-serif;
    font-size: 13px;
    font-weight: 800;
    color: #94a3b8;
    letter-spacing: 0.4px;
}

#job-card {
    background-color: #141720;
    border: 1px solid #1e2433;
    border-radius: 10px;
    padding: 4px;
}

#job-name {
    font-size: 12px;
    font-weight: 600;
    color: #e2e8f0;
}

#job-status {
    font-size: 11px;
    color: #64748b;
}

#job-pct {
    font-size: 12px;
    font-weight: 700;
    color: #3b82f6;
}

QProgressBar {
    background-color: #1e2433;
    border-radius: 3px;
    height: 4px;
    color: transparent;
    border: none;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 3px;
}
QProgressBar#complete::chunk {
    background-color: #22c55e;
}
QProgressBar#error::chunk {
    background-color: #ef4444;
}

#home-file-log {
    background-color: #080b10;
    border: 1px solid #1e2433;
    border-radius: 8px;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

#log-box {
    background-color: #080b10;
    border: 1px solid #1e2433;
    border-radius: 10px;
    color: #ffffff;
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
}
QScrollBar::handle:vertical {
    background: #2d3748;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def get_stylesheet(theme: str) -> str:
    if theme == THEME_DARK:
        return DARK_STYLESHEET
    return LIGHT_STYLESHEET
