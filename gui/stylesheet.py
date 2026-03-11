APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: 'SF Pro Display', 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* ── Sidebar ── */
#sidebar {
    background-color: #0a0d13;
    border-right: 1px solid #1e2433;
    min-width: 180px;
    max-width: 180px;
}

#sidebar-logo {
    font-size: 15px;
    font-weight: 700;
    color: #f1f5f9;
    padding: 4px 0px;
}

#sidebar-sub {
    font-size: 11px;
    color: #475569;
    padding: 0px;
}

#nav-btn {
    background: transparent;
    color: #94a3b8;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    text-align: left;
    font-size: 13px;
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
    padding: 9px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}

#version-label {
    color: #334155;
    font-size: 11px;
}

/* ── Center ── */
#center-panel {
    background-color: #0f1117;
}

#page-title {
    font-size: 24px;
    font-weight: 700;
    color: #f1f5f9;
}

#page-sub {
    font-size: 13px;
    color: #64748b;
}

#drop-zone {
    background-color: #141720;
    border: 1.5px dashed #2d3748;
    border-radius: 12px;
    color: #64748b;
    font-size: 13px;
}
#drop-zone:hover {
    border-color: #3b82f6;
    background-color: #161c2e;
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

#start-btn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}
#start-btn:hover {
    background-color: #1d4ed8;
}

/* ── Right Panel ── */
#right-panel {
    background-color: #0a0d13;
    border-left: 1px solid #1e2433;
    min-width: 260px;
    max-width: 300px;
}

#section-title {
    font-size: 13px;
    font-weight: 700;
    color: #94a3b8;
    letter-spacing: 0.8px;
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
    text-visible: false;
    border: none;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 3px;
}
QProgressBar#complete::chunk {
    background-color: #22c55e;
}

#log-box {
    background-color: #080b10;
    border: 1px solid #1e2433;
    border-radius: 10px;
    color: #22c55e;
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
