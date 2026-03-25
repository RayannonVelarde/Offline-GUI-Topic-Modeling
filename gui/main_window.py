import os
import sys
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from widgets import JobCard, DropZone

# Path to mixbothtask.py (same directory as this file)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIXBOTHTASK_PATH = os.path.join(SCRIPT_DIR, "mixbothtask.py")


def _format_duration(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    if seconds < 0 or not (seconds == seconds):  # NaN check
        return "—"
    total = int(round(seconds))
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _get_audio_duration(path: str) -> str:
    """Return duration of audio file as M:SS or H:MM:SS, or '—' if unknown."""
    try:
        import wave
        ext = os.path.splitext(path)[1].lower()
        if ext == ".wav":
            with wave.open(path, "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                if rate and frames >= 0:
                    return _format_duration(frames / float(rate))
        # Mutagen for mp3, m4a, flac, ogg, etc.
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if f is not None and hasattr(f, "info") and f.info is not None and hasattr(f.info, "length"):
            return _format_duration(f.info.length)
    except Exception:
        pass
    return "—"

# ── Status color map ──────────────────────────────────────────────────────────
STATUS_COLORS = {
    "Pending":    "#94a3b8",
    "Processing": "#3b82f6",
    "Complete":   "#22c55e",
    "Error":      "#ef4444",
}


class StatusColumnDelegate(QStyledItemDelegate):
    """Paints the Status column text in the correct color (e.g. green for Complete)."""

    def paint(self, painter: QPainter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        color_hex = STATUS_COLORS.get(text, "#94a3b8")
        # Draw background for selection state
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(QColor(color_hex))
        painter.drawText(
            option.rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

# ── Sample data ───────────────────────────────────────────────────────────────
SAMPLE_FILES = [
    ("interview_01.mp3",  "12:34",   "Pending"),
    ("meeting_notes.wav", "45:12",   "Processing"),
    ("podcast_ep5.m4a",   "1:23:45", "Complete"),
]

SAMPLE_JOBS = [
    ("interview_01.mp3",  "Transcribing...", 75),
    ("meeting_notes.wav", "Processing...",   45),
    ("podcast_ep5.m4a",   "Complete",       100),
]

NAV_ITEMS = [
    ("🏠  Home",          True),
    ("📄  Files",         False),
    ("⚙  Jobs",          False),
    ("🔍 Topic Modeling", False),
    ("⚙  Settings",      False),
    ("↓  Export",         False),
]


class JobOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Options")

        layout = QVBoxLayout(self)

        self.diarization_checkbox = QCheckBox("Enable speaker diarization")
        self.diarization_checkbox.setChecked(True)

        self.translation_combo = QComboBox()
        self.translation_combo.addItems(["None", "Auto → English"])

        self.timestamps_combo = QComboBox()
        self.timestamps_combo.addItems(
            ["No timestamps", "Per segment", "Per word"]
        )

        layout.addWidget(self.diarization_checkbox)
        layout.addWidget(QLabel("Translation:"))
        layout.addWidget(self.translation_combo)
        layout.addWidget(QLabel("Timestamps:"))
        layout.addWidget(self.timestamps_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Transcription App")
        self._job_process = None
        self._current_job_card = None

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Give side panels a bit more space while keeping center dominant
        root_layout.addWidget(self._build_sidebar(), stretch=1)
        root_layout.addWidget(self._build_center(), stretch=3)
        root_layout.addWidget(self._build_right_panel(), stretch=1)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(4)

        logo = QLabel("Transcription")
        logo.setObjectName("sidebar-logo")
        sub = QLabel("Offline Tool")
        sub.setObjectName("sidebar-sub")
        layout.addWidget(logo)
        layout.addWidget(sub)
        layout.addSpacing(20)

        for label, active in NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("nav-btn-active" if active else "nav-btn")
            btn.setFlat(True)
            layout.addWidget(btn)

        layout.addStretch()
        ver = QLabel("v1.0.0")
        ver.setObjectName("version-label")
        layout.addWidget(ver)

        return sidebar

    # ── Center panel ──────────────────────────────────────────────────────────
    def _build_center(self) -> QFrame:
        center = QFrame()
        center.setObjectName("center-panel")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("Transcription Home")
        title.setObjectName("page-title")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle = QLabel("Upload audio files for transcription and translation")
        subtitle.setObjectName("page-sub")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(DropZone(on_files_dropped=self.add_files_to_table))

        add_btn = QPushButton("＋  Add files")
        add_btn.setObjectName("add-btn")
        add_btn.setFixedWidth(130)
        add_btn.clicked.connect(self.open_files_dialog)
        layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        # Add a bit of vertical breathing room before the table
        layout.addSpacing(12)

        layout.addWidget(self._build_table())

        start_btn = QPushButton("▶  Start Job")
        start_btn.setObjectName("start-btn")
        start_btn.setFixedWidth(130)
        start_btn.clicked.connect(self.open_job_options)
        layout.addWidget(start_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()

        return center

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 3)
        # Columns: 0 = Duration, 1 = Filename (center), 2 = Status
        self.table.setHorizontalHeaderLabels(["Duration", "Filename", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(200)

        hdr = self.table.horizontalHeader()
        # Make all three columns share available width equally
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self.table.setItemDelegateForColumn(2, StatusColumnDelegate(self.table))

        for fname, dur, status in SAMPLE_FILES:
            self._append_table_row(fname, dur, status)

        return self.table

    # ── Right panel ───────────────────────────────────────────────────────────
    def _build_right_panel(self) -> QFrame:
        right = QFrame()
        right.setObjectName("right-panel")
        layout = QVBoxLayout(right)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(12)

        queue_title = QLabel("⚡  PROCESSING QUEUE")
        queue_title.setObjectName("section-title")
        layout.addWidget(queue_title)

        self.jobs_layout = QVBoxLayout()
        layout.addLayout(self.jobs_layout)

        layout.addSpacing(8)

        log_title = QLabel("  LOG OUTPUT")
        log_title.setObjectName("section-title")
        layout.addWidget(log_title)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("log-box")
        self.log_box.setReadOnly(True)
        self.log_box.setPlainText("")
        # Slightly increase log output text size for readability
        font = self.log_box.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() + 2)
            self.log_box.setFont(font)
        layout.addWidget(self.log_box, stretch=1)

        return right

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _append_table_row(self, fname: str, duration: str, status: str, full_path: str | None = None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        # Duration in left column (0)
        dur_item = QTableWidgetItem(duration)
        dur_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 0, dur_item)

        # Filename in center column (1)
        item = QTableWidgetItem(fname)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        if full_path:
            item.setData(Qt.ItemDataRole.UserRole, full_path)
        self.table.setItem(row, 1, item)
        status_item = QTableWidgetItem(status)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        status_item.setForeground(QColor(STATUS_COLORS.get(status, "#94a3b8")))
        self.table.setItem(row, 2, status_item)
        self.table.setRowHeight(row, 48)

    def add_files_to_table(self, files: list[str]):
        for path in files:
            duration = _get_audio_duration(path)
            self._append_table_row(os.path.basename(path), duration, "Pending", full_path=path)
            self.log_box.append(f"[+] Added file: {os.path.basename(path)}\n")

    def open_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select audio files",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg);;All Files (*)",
        )
        if files:
            self.add_files_to_table(files)

    def open_job_options(self):
        # Require at least one row selected before starting a job
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            self.log_box.append("[warn] Select a file in the table before starting a job.\n")
            return

        dialog = JobOptionsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            diarize = dialog.diarization_checkbox.isChecked()
            translation = dialog.translation_combo.currentText()
            timestamps = dialog.timestamps_combo.currentText()

            # Run the job for the first selected row
            selected_row = selected_ranges[0].topRow()
            # Filename is stored in column 1 (center)
            item = self.table.item(selected_row, 1)
            fname = item.text()
            full_path = item.data(Qt.ItemDataRole.UserRole) or fname

            job_card = JobCard(fname, "Processing...", 0)
            self.jobs_layout.addWidget(job_card)

            self.log_box.append(
                f"[job] Starting job for {fname} "
                f"(translation='{translation}', diarization={diarize}, "
                f"timestamps='{timestamps}')\n"
            )

            if self._job_process is not None and self._job_process.state() != QProcess.ProcessState.NotRunning:
                self.log_box.append("[warn] A job is already running. Wait for it to finish.\n")
                return

            python = sys.executable
            self._job_process = QProcess(self)
            self._current_job_card = job_card
            self._current_fname = fname
            self._current_job_row = selected_row

            self._job_process.readyReadStandardOutput.connect(self._on_job_stdout)
            self._job_process.readyReadStandardError.connect(self._on_job_stderr)
            self._job_process.finished.connect(self._on_job_finished)

            self._job_process.setWorkingDirectory(SCRIPT_DIR)
            self._job_process.start(python, [MIXBOTHTASK_PATH, full_path])
            if not self._job_process.waitForStarted(5000):
                self.log_box.append(f"[error] Failed to start job: {self._job_process.errorString()}\n")
                job_card.update_status("Error", 0)
                self._update_table_row_status(selected_row, "Error")
                self._job_process = None
                self._current_job_card = None

    def _on_job_stdout(self):
        if self._job_process:
            data = self._job_process.readAllStandardOutput()
            if data:
                self.log_box.append(data.data().decode("utf-8", errors="replace"))

    def _on_job_stderr(self):
        if self._job_process:
            data = self._job_process.readAllStandardError()
            if data:
                self.log_box.append(data.data().decode("utf-8", errors="replace"))

    def _on_job_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        if self._current_job_card is not None:
            if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                self._current_job_card.update_status("Complete", 100)
                self.log_box.append(f"[job] Completed job for {self._current_fname}\n")
                self._update_table_row_status(self._current_job_row, "Complete")
            else:
                self._current_job_card.update_status("Error", 0)
                self.log_box.append(f"[job] Job failed for {self._current_fname} (exit code {exit_code})\n")
                self._update_table_row_status(self._current_job_row, "Error")
        self._job_process = None
        self._current_job_card = None

    def _update_table_row_status(self, row: int, status: str):
        """Update the Status column for a table row."""
        if 0 <= row < self.table.rowCount():
            status_item = self.table.item(row, 2)
            if status_item is None:
                status_item = QTableWidgetItem(status)
                self.table.setItem(row, 2, status_item)
            else:
                status_item.setText(status)
            status_item.setForeground(QColor(STATUS_COLORS.get(status, "#94a3b8")))
