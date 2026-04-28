#custom widgets 

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
        layout.setSpacing(8)

        # Top row: filename + percentage
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("job-name")
        self.name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.pct_lbl = QLabel(f"{pct}%")
        self.pct_lbl.setObjectName("job-pct")
        self.pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pct_lbl.setMinimumWidth(44)
        top.addWidget(self.name_lbl)
        top.addStretch()
        top.addWidget(self.pct_lbl, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setMaximum(100)
        self.bar.setValue(pct)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        # Status label
        self.status_lbl = QLabel(status)
        self.status_lbl.setObjectName("job-status")
        layout.addWidget(self.status_lbl)

        self._apply_visual_state(status=status, pct=pct)

    def _apply_visual_state(self, *, status: str, pct: int):
        # Percent text color
        if status.strip().lower().startswith("error") and pct == 0:
            self.pct_lbl.setStyleSheet("color: #ef4444;")
        elif pct >= 100:
            self.pct_lbl.setStyleSheet("color: #22c55e;")
        else:
            # Clear per-state override so theme stylesheet applies (blue in light, blue in dark)
            self.pct_lbl.setStyleSheet("")

        # Progress bar chunk color: blue by default, green when complete
        if pct >= 100:
            self.bar.setObjectName("complete")
        else:
            self.bar.setObjectName("")
        # Force stylesheet re-application so objectName change takes effect immediately
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.bar.update()

    def update_status(self, status: str, pct: int | None = None):
        self.status_lbl.setText(status)
        if pct is not None:
            self.bar.setValue(pct)
            self.pct_lbl.setText(f"{pct}%")
            self._apply_visual_state(status=status, pct=pct)
        else:
            # If status changed without a pct update, keep current pct but refresh colors.
            self._apply_visual_state(status=status, pct=int(self.bar.value()))

# Handles drag & drop and click‑to‑open dialog.
class DropZone(QLabel):
    def __init__(self, on_files_dropped=None, parent=None):
        super().__init__(parent)
        self.on_files_dropped = on_files_dropped
        self.setObjectName("drop-zone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(188)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName("drop-icon")
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)

        text = QLabel("Drag & drop audio files here")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setObjectName("drop-text")
        layout.addWidget(text)

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
