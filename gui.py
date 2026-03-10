import sys
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView, QProgressBar, QScrollArea,
    QSizePolicy, QSpacerItem, QStackedWidget,
)


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


def status_color(status: str) -> str:
    return {"Pending": "#94a3b8", "Processing": "#3b82f6", "Complete": "#22c55e"}.get(status, "#94a3b8")


class JobCard(QFrame):
    def __init__(self, name: str, status: str, pct: int, parent=None):
        super().__init__(parent)
        self.setObjectName("job-card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setObjectName("job-name")
        pct_lbl = QLabel(f"{pct}%")
        pct_lbl.setObjectName("job-pct")
        top.addWidget(name_lbl)
        top.addStretch()
        top.addWidget(pct_lbl)
        layout.addLayout(top)

        bar = QProgressBar()
        bar.setMaximum(100)
        bar.setValue(pct)
        bar.setFixedHeight(4)
        bar.setTextVisible(False)
        if pct == 100:
            bar.setObjectName("complete")
        layout.addWidget(bar)

        status_lbl = QLabel(status)
        status_lbl.setObjectName("job-status")
        layout.addWidget(status_lbl)


class DropZone(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drop-zone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(160)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("""
            font-size: 28px;
            background-color: #1e2d4a;
            color: #3b82f6;
            border-radius: 24px;
            padding: 10px;
            min-width: 48px;
            max-width: 48px;
            min-height: 48px;
            max-height: 48px;
        """)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)

        text = QLabel("Drag & drop audio files here")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet("color: #94a3b8; font-size: 14px; font-weight: 500;")
        layout.addWidget(text)

        or_lbl = QLabel("or")
        or_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_lbl.setStyleSheet("color: #475569; font-size: 12px;")
        layout.addWidget(or_lbl)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Transcription App")
        self.setStyleSheet(APP_STYLESHEET)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(16, 24, 16, 16)
        sb_layout.setSpacing(4)

        logo = QLabel("Transcription")
        logo.setObjectName("sidebar-logo")
        sub = QLabel("Offline Tool")
        sub.setObjectName("sidebar-sub")
        sb_layout.addWidget(logo)
        sb_layout.addWidget(sub)
        sb_layout.addSpacing(20)

        nav_items = [("🏠  Home", True), ("📄  Files", False), ("⚙  Jobs", False),
                     ("🔍 Topic Modeling", False), ("⚙  Settings", False), ("↓  Export", False)]
        for label, active in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("nav-btn-active" if active else "nav-btn")
            btn.setFlat(True)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        ver = QLabel("v1.0.0")
        ver.setObjectName("version-label")
        sb_layout.addWidget(ver)

        # ── Center Panel ─────────────────────────────────────────
        center = QFrame()
        center.setObjectName("center-panel")
        c_layout = QVBoxLayout(center)
        c_layout.setContentsMargins(32, 28, 32, 28)
        c_layout.setSpacing(16)

        title = QLabel("Transcription Home")
        title.setObjectName("page-title")
        subtitle = QLabel("Upload audio files for transcription and translation")
        subtitle.setObjectName("page-sub")
        c_layout.addWidget(title)
        c_layout.addWidget(subtitle)

        drop = DropZone()
        c_layout.addWidget(drop)

        add_btn = QPushButton("＋  Add files")
        add_btn.setObjectName("add-btn")
        add_btn.setFixedWidth(130)
        c_layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Table
        table = QTableWidget(3, 3)
        table.setHorizontalHeaderLabels(["Filename", "Duration", "Status"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        rows = [
            ("interview_01.mp3", "12:34", "Pending"),
            ("meeting_notes.wav", "45:12", "Processing"),
            ("podcast_ep5.m4a", "1:23:45", "Complete"),
        ]
        for r, (fname, dur, status) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(fname))
            table.setItem(r, 1, QTableWidgetItem(dur))

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(status_color(status)))
            table.setItem(r, 2, status_item)
            table.setRowHeight(r, 48)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.setMinimumHeight(200)

        c_layout.addWidget(table)

        start_btn = QPushButton("▶  Start Job")
        start_btn.setObjectName("start-btn")
        start_btn.setFixedWidth(130)
        c_layout.addWidget(start_btn, alignment=Qt.AlignmentFlag.AlignRight)
        c_layout.addStretch()

        # ── Right Panel ───────────────────────────────────────────
        right = QFrame()
        right.setObjectName("right-panel")
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(16, 24, 16, 16)
        r_layout.setSpacing(12)

        queue_title = QLabel("⚡  JOB QUEUE")
        queue_title.setObjectName("section-title")
        r_layout.addWidget(queue_title)

        jobs = [
            ("interview_01.mp3", "Transcribing...", 75),
            ("meeting_notes.wav", "Processing...", 45),
            ("podcast_ep5.m4a", "Complete", 100),
        ]
        for name, status, pct in jobs:
            card = JobCard(name, status, pct)
            r_layout.addWidget(card)

        r_layout.addSpacing(8)

        log_title = QLabel("  LOG OUTPUT")
        log_title.setObjectName("section-title")
        r_layout.addWidget(log_title)

        log_box = QTextEdit()
        log_box.setObjectName("log-box")
        log_box.setReadOnly(True)
        log_box.setPlainText(
            "[14:32:01] Started processing interview_01.mp3\n"
            "[14:32:05] Detected language: English (US)\n"
            "[14:32:12] Transcription progress: 75%\n"
            "[14:31:45] meeting_notes.wav added to queue\n"
            "[14:30:22] podcast_ep5.m4a completed successfully\n"
            "[14:30:20] Diarization enabled — 3 speakers detected"
        )
        r_layout.addWidget(log_box, stretch=1)

        # ── Assemble ──────────────────────────────────────────────
        root_layout.addWidget(sidebar)
        root_layout.addWidget(center, stretch=1)
        root_layout.addWidget(right)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())