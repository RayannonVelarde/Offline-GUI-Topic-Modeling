#custom widgets 

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QFileDialog,
)


class JobCard(QFrame):
    def __init__(self, name: str, status: str, pct: int, parent=None):
        super().__init__(parent)
        self.setObjectName("job-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Top row: filename + percentage
        top = QHBoxLayout()
        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("job-name")
        self.pct_lbl = QLabel(f"{pct}%")
        self.pct_lbl.setObjectName("job-pct")
        top.addWidget(self.name_lbl)
        top.addStretch()
        top.addWidget(self.pct_lbl)
        layout.addLayout(top)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setMaximum(100)
        self.bar.setValue(pct)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        if pct == 100:
            self.bar.setObjectName("complete")
        layout.addWidget(self.bar)

        # Status label
        self.status_lbl = QLabel(status)
        self.status_lbl.setObjectName("job-status")
        layout.addWidget(self.status_lbl)

    def update_status(self, status: str, pct: int | None = None):
        self.status_lbl.setText(status)
        if pct is not None:
            self.bar.setValue(pct)
            self.pct_lbl.setText(f"{pct}%")
            if pct == 100:
                self.bar.setObjectName("complete")

# Handles drag & drop and click‑to‑open dialog.
class DropZone(QLabel):
    def __init__(self, on_files_dropped=None, parent=None):
        super().__init__(parent)
        self.on_files_dropped = on_files_dropped
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
        if paths and self.on_files_dropped:
            self.on_files_dropped(paths)
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.on_files_dropped:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Select audio files",
                "",
                "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg);;All Files (*)",
            )
            if files:
                self.on_files_dropped(files)
        else:
            super().mousePressEvent(event)
