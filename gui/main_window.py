import os
import sys
import time
import keyring
from PySide6.QtCore import Qt, QProcess, QSettings, QUrl, QSize, QTimer, QProcessEnvironment
from PySide6.QtGui import QColor, QPainter, QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidgetSelectionRange,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from widgets import JobCard, DropZone
from stylesheet import THEME_DARK, THEME_LIGHT, get_stylesheet
from nav_icons import make_nav_icon

# Path to mixbothtask.py (same directory as this file)
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIXBOTHTASK_PATH = os.path.join(SCRIPT_DIR, "mixbothtask.py")

SETTINGS_ORG = "OfflineGUI"
SETTINGS_APP = "TopicModelingTranscription"

KEYRING_SERVICE = "OfflineGUI"
KEYRING_HF_USER = "huggingface_token"

KEY_THEME = "ui/theme"
KEY_OUTPUT_FOLDER = "jobs/output_folder"
KEY_DEFAULT_DIARIZATION = "jobs/default_diarization"
KEY_DEFAULT_NUM_SPEAKERS = "jobs/default_num_speakers"
KEY_DEFAULT_TIMESTAMPS = "jobs/default_timestamps"
KEY_DEFAULT_TRANSLATION = "jobs/default_translation"
KEY_AUTO_OPEN_OUTPUT = "jobs/auto_open_output_folder"

OUTPUT_SPANISH_BASENAME = "transcription_spanish.txt"
OUTPUT_ENGLISH_BASENAME = "transcription_english.txt"


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
    "Pending":    "#eab308",  # slightly lighter muted yellow (readable in light & dark)
    "Processing": "#3b82f6",
    "Complete":   "#22c55e",
    "Error":      "#ef4444",
}


class StatusColumnDelegate(QStyledItemDelegate):
    """Paints the Status column text in the correct color (e.g. green for Complete)."""

    def paint(self, painter: QPainter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        color_hex = STATUS_COLORS.get(text, "#94a3b8")
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        # Keep status hue when selected (do not use highlightedText — it forces white)
        painter.setPen(QColor(color_hex))
        painter.drawText(
            option.rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_FILES = [
    #("interview_01.mp3",  "12:34",   "Pending"),
    #("meeting_notes.wav", "45:12",   "Processing"),
    #("podcast_ep5.m4a",   "1:23:45", "Complete"),
]

SAMPLE_JOBS = [
    #("interview_01.mp3",  "Transcribing...", 75),
    #("meeting_notes.wav", "Processing...",   45),
    #("podcast_ep5.m4a",   "Complete",       100),
]

# (page_id, label) — icons from nav_icons (SVG, consistent stroke style)
NAV_DEF: list[tuple[str, str]] = [
    ("home", "Home"),
    ("jobs", "Jobs"),
    ("review", "Review"),
    ("settings", "Settings"),
]


class JobOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Options")

        layout = QVBoxLayout(self)

        self.diarization_checkbox = QCheckBox("Enable speaker diarization")
        self.diarization_checkbox.setChecked(True)

        spk_row = QHBoxLayout()
        spk_lbl = QLabel("Number of speakers:")
        self.speaker_count_spin = QSpinBox()
        self.speaker_count_spin.setRange(1, 32)
        self.speaker_count_spin.setValue(2)
        self.speaker_count_spin.setFixedWidth(72)
        spk_row.addWidget(spk_lbl)
        spk_row.addStretch()
        spk_row.addWidget(self.speaker_count_spin)

        self.diarization_checkbox.toggled.connect(self._sync_speaker_spin_enabled)
        self._sync_speaker_spin_enabled()

        self.translation_combo = QComboBox()
        self.translation_combo.addItems(["None", "Auto → English"])

        self.timestamps_combo = QComboBox()
        self.timestamps_combo.addItems(
            ["No timestamps", "Per segment", "Per word"]
        )

        layout.addWidget(self.diarization_checkbox)
        layout.addLayout(spk_row)
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

    def _sync_speaker_spin_enabled(self):
        self.speaker_count_spin.setEnabled(self.diarization_checkbox.isChecked())


class ReviewComparisonPage(QFrame):
    """Clean comparison-mode Review page (selector + side-by-side outputs)."""

    def __init__(self, stack_threshold_px: int = 900, parent=None):
        super().__init__(parent)
        self.stack_threshold_px = stack_threshold_px
        self._is_stacked = False
        self.compare_splitter: QSplitter | None = None

    def _apply_layout_mode(self):
        if self.compare_splitter is None:
            return
        should_stack = self.width() < self.stack_threshold_px
        if should_stack == self._is_stacked:
            return
        self._is_stacked = should_stack
        self.compare_splitter.setOrientation(
            Qt.Orientation.Vertical if should_stack else Qt.Orientation.Horizontal
        )
        self.compare_splitter.setSizes([1, 1])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_layout_mode()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Transcription App")
        self._job_process = None
        self._current_job_card = None
        self._current_full_path = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._current_page = "home"
        self._theme = THEME_LIGHT
        self._jobs: list[dict] = []
        self._review_items: list[dict] = []
        self._queue_open = False
        self._queue_panel_width = 280
        self._queue_splitter_block_signal = False

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar(), stretch=0)

        # Center + queue share one horizontal splitter so opening the queue resizes
        # content predictably (no overlay, no extra root column fighting min-width).
        self._queue_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._queue_splitter.setObjectName("queue-splitter")
        self._queue_splitter.setChildrenCollapsible(False)
        self._queue_splitter.setCollapsible(0, False)
        self._queue_splitter.setCollapsible(1, True)
        self._queue_splitter.setHandleWidth(5)
        self._queue_splitter.setStretchFactor(0, 1)
        self._queue_splitter.setStretchFactor(1, 0)

        center = self._build_center()
        self._right_panel = self._build_right_panel()
        self._right_panel.setMinimumWidth(0)
        self._right_panel.setMaximumWidth(self._queue_panel_width)

        self._queue_splitter.addWidget(center)
        self._queue_splitter.addWidget(self._right_panel)
        self._queue_splitter.splitterMoved.connect(self._on_queue_splitter_moved)

        root_layout.addWidget(self._queue_splitter, stretch=1)

        QTimer.singleShot(0, self._sync_queue_splitter_sizes)

        # Apply persisted theme (LIGHT by default)
        self.apply_theme(self._settings().value(KEY_THEME, THEME_LIGHT))

    def _settings(self) -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def apply_theme(self, theme: str):
        theme = THEME_DARK if theme == THEME_DARK else THEME_LIGHT
        self._theme = theme
        self._settings().setValue(KEY_THEME, theme)
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.setStyleSheet(get_stylesheet(theme))
        self._refresh_nav_icons()

    def _refresh_nav_icons(self):
        if not self._nav_buttons:
            return
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        active = "#ffffff"
        icon_sz = 18
        for pid, btn in self._nav_buttons.items():
            color = active if pid == self._current_page else inactive
            btn.setIcon(make_nav_icon(pid, size=icon_sz, color_hex=color))
            btn.setIconSize(QSize(icon_sz, icon_sz))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._queue_open:
            self._sync_queue_splitter_sizes()

    def _sync_queue_splitter_sizes(self):
        """Keep queue width stable when open; collapse to 0 when closed."""
        if not hasattr(self, "_queue_splitter"):
            return
        sp = self._queue_splitter
        total = sp.width()
        if total < 2:
            return
        self._queue_splitter_block_signal = True
        try:
            if self._queue_open:
                min_center = 280
                rw = self._queue_panel_width
                if total - rw < min_center:
                    rw = max(0, total - min_center)
                if rw < 48:
                    self._queue_open = False
                    if hasattr(self, "_queue_btn"):
                        self._queue_btn.setChecked(False)
                    sp.setSizes([total, 0])
                    return
                lw = total - rw
                sp.setSizes([lw, rw])
                self._right_panel.setMaximumWidth(self._queue_panel_width)
            else:
                sp.setSizes([total, 0])
        finally:
            self._queue_splitter_block_signal = False

    def _on_queue_splitter_moved(self, _pos: int, index: int):
        """Keep Queue toggle in sync when the user drags the splitter closed/open."""
        _ = index
        if self._queue_splitter_block_signal:
            return
        sp = self._queue_splitter
        sizes = sp.sizes()
        if len(sizes) < 2:
            return
        if sizes[1] < 20:
            self._queue_open = False
            self._queue_btn.setChecked(False)
        else:
            self._queue_open = True
            self._queue_btn.setChecked(True)

    def _get_output_folder(self) -> str:
        """Return output folder; create a sensible default if unset."""
        saved = self._settings().value(KEY_OUTPUT_FOLDER, "")
        if isinstance(saved, str) and saved.strip():
            path = saved.strip()
        else:
            path = os.path.join(SCRIPT_DIR, "outputs")
            self._settings().setValue(KEY_OUTPUT_FOLDER, path)
        os.makedirs(path, exist_ok=True)
        return path

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(4)

        logo = QLabel("Speech to Text Studio")
        logo.setObjectName("sidebar-logo")
        logo.setWordWrap(True)
        sub = QLabel("Offline Tool")
        sub.setObjectName("sidebar-sub")
        layout.addWidget(logo)
        layout.addWidget(sub)
        layout.addSpacing(20)

        for page_id, label in NAV_DEF:
            btn = QPushButton(label)
            btn.setObjectName("nav-btn-active" if page_id == "home" else "nav-btn")
            btn.setFlat(True)
            self._nav_buttons[page_id] = btn
            btn.clicked.connect(lambda _=False, p=page_id: self._on_nav_clicked(p))
            layout.addWidget(btn)

        layout.addStretch()

        # Keep sidebar clean; the real theme toggle lives in Settings page.
        ver = QLabel("v1.0.0")
        ver.setObjectName("version-label")
        layout.addWidget(ver)

        return sidebar

    def _on_nav_clicked(self, page_id: str):
        if page_id in ("home", "jobs", "review", "settings"):
            self._show_page(page_id)

    def _set_active_nav(self, page_id: str):
        for pid, btn in self._nav_buttons.items():
            is_active = pid == page_id
            new_name = "nav-btn-active" if is_active else "nav-btn"
            if btn.objectName() != new_name:
                btn.setObjectName(new_name)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
        self._refresh_nav_icons()

    def _show_page(self, page: str):
        page = page if page in ("home", "jobs", "review", "settings") else "home"
        self._current_page = page

        # Queue panel is only for Home; close when navigating away.
        if page != "home" and getattr(self, "_queue_open", False):
            self._queue_open = False
            if hasattr(self, "_queue_btn"):
                self._queue_btn.setChecked(False)
            if hasattr(self, "_queue_splitter"):
                self._sync_queue_splitter_sizes()

        if page == "settings":
            self._set_active_nav("settings")
            self._pages.setCurrentWidget(self._settings_page)
        elif page == "review":
            self._set_active_nav("review")
            self._pages.setCurrentWidget(self._review_page)
            self._refresh_review_items()
        elif page == "jobs":
            self._set_active_nav("jobs")
            self._pages.setCurrentWidget(self._jobs_page)
        else:
            self._set_active_nav("home")
            self._pages.setCurrentWidget(self._home_page)

    # ── Center panel ──────────────────────────────────────────────────────────
    def _build_center(self) -> QFrame:
        center = QFrame()
        center.setObjectName("center-panel")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)

        self._pages = QStackedWidget()
        self._home_page = self._build_home_page()
        self._jobs_page = self._build_jobs_page()
        self._review_page = self._build_review_page()
        self._settings_page = self._build_settings_page()
        self._pages.addWidget(self._home_page)
        self._pages.addWidget(self._jobs_page)
        self._pages.addWidget(self._review_page)
        self._pages.addWidget(self._settings_page)
        layout.addWidget(self._pages)

        self._show_page("home")

        return center

    def _build_home_page(self) -> QFrame:
        home = QFrame()
        home.setObjectName("home-page")
        layout = QVBoxLayout(home)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        # AlignTop only: AlignHCenter was shrinking rows to minimum width and centering
        # them, so the header/Queue row did not track the real center width when the
        # queue panel toggled (maximized vs narrow).
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Top header row (title block + queue toggle button) ──
        header_row = QHBoxLayout()

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Transcription Home")
        title.setObjectName("page-title")
        subtitle = QLabel("Upload audio files for transcription and translation")
        subtitle.setObjectName("page-sub")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        self._queue_btn = QPushButton("⊞  Queue")
        self._queue_btn.setObjectName("add-btn")
        self._queue_btn.setFixedWidth(100)
        self._queue_btn.setCheckable(True)
        self._queue_btn.clicked.connect(self._toggle_right_panel)

        header_row.addLayout(title_col)
        header_row.addStretch()
        header_row.addWidget(self._queue_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        layout.addWidget(DropZone(on_files_dropped=self.add_files_to_table))

        add_btn = QPushButton("＋  Add files")
        add_btn.setObjectName("add-btn")
        add_btn.setFixedWidth(130)
        add_btn.clicked.connect(self.open_files_dialog)
        layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(12)

        # Inline warning banner shown when Start Job is clicked without a selection.
        self._home_warning = QLabel("Select a file from the table to start a job.")
        self._home_warning.setObjectName("home-warning")
        self._home_warning.setWordWrap(True)
        self._home_warning.hide()
        layout.addWidget(self._home_warning)

        layout.addWidget(self._build_table())

        start_btn = QPushButton("▶  Start Job")
        start_btn.setObjectName("start-btn")
        start_btn.setFixedWidth(130)
        start_btn.clicked.connect(self.open_job_options)
        layout.addWidget(start_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()

        return home

    def _build_jobs_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("jobs-page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Jobs")
        title.setObjectName("page-title")
        subtitle = QLabel("Monitor queued, running, and completed jobs")
        subtitle.setObjectName("page-sub")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        card = QFrame()
        card.setObjectName("settings-card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        section = QLabel("Recent jobs")
        section.setObjectName("section-title")
        card_layout.addWidget(section)

        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setObjectName("jobs-table")
        self.jobs_table.setHorizontalHeaderLabels(["Filename", "Status", "Output folder", "Opened"])
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setShowGrid(False)
        self.jobs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setMinimumHeight(200)
        hdr = self.jobs_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.jobs_table.setItemDelegateForColumn(1, StatusColumnDelegate(self.jobs_table))
        card_layout.addWidget(self.jobs_table)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _build_review_page(self) -> QFrame:
        page = ReviewComparisonPage()
        page.setObjectName("review-page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Review")
        title.setObjectName("page-title")
        subtitle = QLabel("Check transcription and translation outputs side-by-side for verification")
        subtitle.setObjectName("page-sub")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        # Single compact card: selector + folder path
        info = QFrame()
        info.setObjectName("settings-card")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(10)
        selector_label = QLabel("Selected file:")
        selector_label.setObjectName("settings-label")
        self.review_selector = QComboBox()
        self.review_selector.setObjectName("settings-input")
        self.review_selector.setMinimumWidth(220)
        self.review_selector.currentIndexChanged.connect(self._on_review_selection_changed)
        selector_row.addWidget(selector_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        selector_row.addWidget(self.review_selector, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
        info_layout.addLayout(selector_row)

        self.review_info_path = QLabel("")
        self.review_info_path.setObjectName("settings-label")
        self.review_info_path.setWordWrap(True)
        self.review_info_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.review_info_path)

        layout.addWidget(info)

        # Main comparison area
        compare = QSplitter(Qt.Orientation.Horizontal)
        compare.setChildrenCollapsible(False)
        compare.setHandleWidth(8)
        page.compare_splitter = compare

        left = QFrame()
        left.setObjectName("settings-card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 14, 16, 14)
        left_layout.setSpacing(10)
        left_title = QLabel("Transcription output")
        left_title.setObjectName("section-title")
        left_layout.addWidget(left_title)
        self.spanish_preview = QTextEdit()
        self.spanish_preview.setObjectName("review-preview")
        self.spanish_preview.setReadOnly(True)
        left_layout.addWidget(self.spanish_preview, stretch=1)

        right = QFrame()
        right.setObjectName("settings-card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)
        right_title = QLabel("Translation output")
        right_title.setObjectName("section-title")
        right_layout.addWidget(right_title)
        self.english_preview = QTextEdit()
        self.english_preview.setObjectName("review-preview")
        self.english_preview.setReadOnly(True)
        right_layout.addWidget(self.english_preview, stretch=1)

        compare.addWidget(left)
        compare.addWidget(right)
        compare.setStretchFactor(0, 1)
        compare.setStretchFactor(1, 1)
        compare.setSizes([1, 1])

        page._apply_layout_mode()
        layout.addWidget(compare, stretch=1)

        # Bottom action row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.open_spanish_btn = QPushButton("Open transcription file")
        self.open_spanish_btn.setObjectName("add-btn")
        self.open_spanish_btn.clicked.connect(lambda: self._open_review_file(which="spanish"))
        self.open_english_btn = QPushButton("Open translation file")
        self.open_english_btn.setObjectName("add-btn")
        self.open_english_btn.clicked.connect(lambda: self._open_review_file(which="english"))
        self.open_folder_btn = QPushButton("Open containing folder")
        self.open_folder_btn.setObjectName("add-btn")
        self.open_folder_btn.clicked.connect(self._open_review_folder)
        btn_row.addWidget(self.open_spanish_btn)
        btn_row.addWidget(self.open_english_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.open_folder_btn)
        layout.addLayout(btn_row)
        return page

    def _build_settings_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("settings-page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Settings")
        title.setObjectName("page-title")
        subtitle = QLabel("App preferences for transcription jobs")
        subtitle.setObjectName("page-sub")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        card = QFrame()
        card.setObjectName("settings-card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        # Appearance
        section1 = QLabel("Appearance")
        section1.setObjectName("section-title")
        card_layout.addWidget(section1)

        self.dark_mode_checkbox = QCheckBox("Enable dark mode")
        self.dark_mode_checkbox.setObjectName("theme-toggle")
        theme = self._settings().value(KEY_THEME, THEME_LIGHT)
        self.dark_mode_checkbox.setChecked(theme == THEME_DARK)
        self.dark_mode_checkbox.toggled.connect(self._on_dark_mode_toggled)
        card_layout.addWidget(self.dark_mode_checkbox)

        # Defaults
        section2 = QLabel("Job defaults")
        section2.setObjectName("section-title")
        card_layout.addWidget(section2)

        self.default_diarization_checkbox = QCheckBox("Enable speaker diarization by default")
        self.default_diarization_checkbox.setChecked(bool(self._settings().value(KEY_DEFAULT_DIARIZATION, True, type=bool)))
        self.default_diarization_checkbox.toggled.connect(self._on_default_diarization_toggled)
        card_layout.addWidget(self.default_diarization_checkbox)

        def_spk_row = QHBoxLayout()
        def_spk_label = QLabel("Default number of speakers:")
        def_spk_label.setObjectName("settings-label")
        self.default_speaker_spin = QSpinBox()
        self.default_speaker_spin.setRange(1, 32)
        self.default_speaker_spin.setValue(
            max(1, min(32, int(self._settings().value(KEY_DEFAULT_NUM_SPEAKERS, 2, type=int))))
        )
        self.default_speaker_spin.setFixedWidth(72)
        self.default_speaker_spin.valueChanged.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_NUM_SPEAKERS, int(v))
        )
        def_spk_row.addWidget(def_spk_label)
        def_spk_row.addStretch()
        def_spk_row.addWidget(self.default_speaker_spin)
        card_layout.addLayout(def_spk_row)
        self.default_speaker_spin.setEnabled(self.default_diarization_checkbox.isChecked())

        self.default_timestamps_checkbox = QCheckBox("Show timestamps by default (per segment)")
        self.default_timestamps_checkbox.setChecked(bool(self._settings().value(KEY_DEFAULT_TIMESTAMPS, True, type=bool)))
        self.default_timestamps_checkbox.toggled.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_TIMESTAMPS, bool(v))
        )
        card_layout.addWidget(self.default_timestamps_checkbox)

        # Translation mode (fixed to current backend behavior).
        tr_row = QHBoxLayout()
        tr_label = QLabel("Translation mode:")
        tr_label.setObjectName("settings-label")
        tr_value = QLabel("Spanish → English")
        tr_value.setObjectName("settings-label")
        tr_row.addWidget(tr_label)
        tr_row.addStretch()
        tr_row.addWidget(tr_value)
        card_layout.addLayout(tr_row)

        # Output behavior
        section3 = QLabel("Output")
        section3.setObjectName("section-title")
        card_layout.addWidget(section3)

        out_row = QHBoxLayout()
        out_label = QLabel("Default output folder:")
        out_label.setObjectName("settings-label")
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setObjectName("settings-input")
        self.output_folder_edit.setPlaceholderText("Choose a folder…")
        self.output_folder_edit.setText(self._settings().value(KEY_OUTPUT_FOLDER, ""))
        self.output_folder_edit.textChanged.connect(
            lambda t: self._settings().setValue(KEY_OUTPUT_FOLDER, t.strip())
        )
        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("add-btn")
        browse_btn.clicked.connect(self._browse_output_folder)
        out_row.addWidget(out_label)
        out_row.addWidget(self.output_folder_edit, stretch=1)
        out_row.addWidget(browse_btn)
        card_layout.addLayout(out_row)

        self.auto_open_output_checkbox = QCheckBox("Auto-open output folder when a job completes")
        self.auto_open_output_checkbox.setChecked(bool(self._settings().value(KEY_AUTO_OPEN_OUTPUT, False, type=bool)))
        self.auto_open_output_checkbox.toggled.connect(
            lambda v: self._settings().setValue(KEY_AUTO_OPEN_OUTPUT, bool(v))
        )
        card_layout.addWidget(self.auto_open_output_checkbox)

        # Hugging Face token
        section4 = QLabel("Integration")
        section4.setObjectName("section-title")
        card_layout.addWidget(section4)

        hf_row = QHBoxLayout()
        hf_label = QLabel("Hugging Face token:")
        hf_label.setObjectName("settings-label")
        self.hf_token_edit = QLineEdit()
        self.hf_token_edit.setObjectName("settings-input")
        self.hf_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._load_hf_token_into_field()
        hf_save_btn = QPushButton("Save")
        hf_save_btn.setObjectName("add-btn")
        hf_save_btn.setFixedWidth(72)
        hf_save_btn.clicked.connect(self._save_hf_token_from_field)
        hf_clear_btn = QPushButton("Clear")
        hf_clear_btn.setObjectName("add-btn")
        hf_clear_btn.setFixedWidth(72)
        hf_clear_btn.clicked.connect(self._clear_hf_token)
        hf_row.addWidget(hf_label)
        hf_row.addWidget(self.hf_token_edit, stretch=1)
        hf_row.addWidget(hf_save_btn)
        hf_row.addWidget(hf_clear_btn)
        card_layout.addLayout(hf_row)

        hf_note = QLabel("Stored securely in your OS keychain.")
        hf_note.setObjectName("settings-label")
        card_layout.addWidget(hf_note)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _on_default_diarization_toggled(self, checked: bool):
        self._settings().setValue(KEY_DEFAULT_DIARIZATION, bool(checked))
        self.default_speaker_spin.setEnabled(checked)

    def _on_dark_mode_toggled(self, checked: bool):
        self.apply_theme(THEME_DARK if checked else THEME_LIGHT)

    def _browse_output_folder(self):
        start_dir = self.output_folder_edit.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Select output folder", start_dir)
        if folder:
            self.output_folder_edit.setText(folder)

    def _load_hf_token_into_field(self):
        if not hasattr(self, "hf_token_edit"):
            return
        token = self._get_hf_token()
        self.hf_token_edit.setText(token)

    def _get_hf_token(self) -> str:
        try:
            token = keyring.get_password(KEYRING_SERVICE, KEYRING_HF_USER)
        except Exception:
            return ""
        return (token or "").strip()

    def _save_hf_token_from_field(self):
        if not hasattr(self, "hf_token_edit"):
            return
        token = (self.hf_token_edit.text() or "").strip()
        if not token:
            self._clear_hf_token()
            return
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_HF_USER, token)
        except Exception:
            # Silent failure; user can retry.
            return

    def _clear_hf_token(self):
        if hasattr(self, "hf_token_edit"):
            self.hf_token_edit.clear()
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_HF_USER)
        except Exception:
            # Deleting may fail if nothing was stored; ignore.
            return

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Duration", "Filename", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(150)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self.table.setItemDelegateForColumn(2, StatusColumnDelegate(self.table))

        # Hide home warning once the user makes a valid selection.
        self.table.itemSelectionChanged.connect(self._on_home_selection_changed)

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

        queue_title = QLabel("PROCESSING QUEUE")
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
        font = self.log_box.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() + 2)
            self.log_box.setFont(font)
        layout.addWidget(self.log_box, stretch=1)

        return right

    def _append_log(self, text: str):
        if not hasattr(self, "log_box") or self.log_box is None:
            return

        line = text.rstrip("\n")
        lower = line.lower()
        if "[job] completed job" in lower:
            color = "#16a34a"
        elif "[job] job failed" in lower or lower.startswith("[error]"):
            color = "#ef4444"
        else:
            color = "#ffffff" if self._theme == THEME_DARK else "#000000"

        cur = self.log_box.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(line + "\n", fmt)
        self.log_box.setTextCursor(cur)
        self.log_box.ensureCursorVisible()

    # ── Toggle right panel ────────────────────────────────────────────────────
    def _toggle_right_panel(self):
        self._queue_open = not self._queue_open
        self._queue_btn.setChecked(self._queue_open)
        self._sync_queue_splitter_sizes()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _append_table_row(self, fname: str, duration: str, status: str, full_path: str | None = None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        dur_item = QTableWidgetItem(duration)
        dur_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 0, dur_item)

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
            self._append_log(f"[+] Added file: {os.path.basename(path)}")

    def open_files_dialog(self):
        start_dir = self._settings().value(KEY_OUTPUT_FOLDER, "")
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select audio files",
            start_dir if isinstance(start_dir, str) else "",
            "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg);;All Files (*)",
        )
        if files:
            self.add_files_to_table(files)

    def _show_home_warning(self, visible: bool):
        if not hasattr(self, "_home_warning"):
            return
        self._home_warning.setVisible(visible)

    def _on_home_selection_changed(self):
        # Any real selection should clear the warning banner.
        if self.table.selectedRanges():
            self._show_home_warning(False)

    def open_job_options(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            self._append_log("[warn] Select a file in the table before starting a job.")
            self._show_home_warning(True)
            return

        dialog = JobOptionsDialog(self)
        # Apply saved defaults to the dialog.
        dialog.diarization_checkbox.setChecked(bool(self._settings().value(KEY_DEFAULT_DIARIZATION, True, type=bool)))
        dialog.speaker_count_spin.setValue(
            max(1, min(32, int(self._settings().value(KEY_DEFAULT_NUM_SPEAKERS, 2, type=int))))
        )
        dialog._sync_speaker_spin_enabled()
        dialog.translation_combo.setCurrentText(self._settings().value(KEY_DEFAULT_TRANSLATION, "None"))
        if bool(self._settings().value(KEY_DEFAULT_TIMESTAMPS, True, type=bool)):
            dialog.timestamps_combo.setCurrentText("Per segment")
        else:
            dialog.timestamps_combo.setCurrentText("No timestamps")

        if dialog.exec() == QDialog.DialogCode.Accepted:
            diarize = dialog.diarization_checkbox.isChecked()
            num_speakers = dialog.speaker_count_spin.value()
            translation = dialog.translation_combo.currentText()
            timestamps = dialog.timestamps_combo.currentText()

            # Require a Hugging Face token for jobs that need it.
            token = self._get_hf_token()
            if not token:
                self._append_log("[warn] Hugging Face token is missing. Add it in Settings before starting this job.")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Token required",
                    "A valid Hugging Face token is required.\n\n"
                    "Open the Settings page and add your token in the Hugging Face token field.",
                )
                return

            # Only allow one active job process at a time.
            if self._job_process is not None and self._job_process.state() != QProcess.ProcessState.NotRunning:
                self._append_log("[warn] A job is already running. Wait for it to finish.")
                return

            selected_row = selected_ranges[0].topRow()
            item = self.table.item(selected_row, 1)
            fname = item.text()
            full_path = item.data(Qt.ItemDataRole.UserRole) or fname
            self._current_full_path = full_path

            job_card = JobCard(fname, "Processing...", 0)
            self.jobs_layout.addWidget(job_card)
            self._add_job_record(fname=fname, full_path=full_path, status="Processing")

            self._append_log(
                f"[job] Starting job for {fname} "
                f"(translation='{translation}', diarization={diarize}, "
                f"num_speakers={num_speakers}, timestamps='{timestamps}')"
            )

            python = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
            self._job_process = QProcess(self)
            self._current_job_card = job_card
            self._current_fname = fname
            self._current_job_row = selected_row

            self._job_process.readyReadStandardOutput.connect(self._on_job_stdout)
            self._job_process.readyReadStandardError.connect(self._on_job_stderr)
            self._job_process.finished.connect(self._on_job_finished)

            self._job_process.setWorkingDirectory(SCRIPT_DIR)

            # Pass Hugging Face token via environment only; never log or write it to disk.
            env = QProcessEnvironment.systemEnvironment()
            env.insert("HUGGINGFACE_TOKEN", token)
            self._job_process.setProcessEnvironment(env)

            self._job_process.start(python, [MIXBOTHTASK_PATH, full_path, str(num_speakers)])
            if not self._job_process.waitForStarted(5000):
                self._append_log(f"[error] Failed to start job: {self._job_process.errorString()}")
                job_card.update_status("Error", 0)
                self._update_table_row_status(selected_row, "Error")
                self._job_process = None
                self._current_job_card = None
            else:
                # Reflect real state in the Home table immediately.
                self._update_table_row_status(selected_row, "Processing")

    def _on_job_stdout(self):
        if self._job_process:
            data = self._job_process.readAllStandardOutput()
            if data:
                for ln in data.data().decode("utf-8", errors="replace").splitlines():
                    if ln.strip():
                        self._append_log(ln)

    def _on_job_stderr(self):
        if self._job_process:
            data = self._job_process.readAllStandardError()
            if data:
                for ln in data.data().decode("utf-8", errors="replace").splitlines():
                    if ln.strip():
                        self._append_log(ln)

    def _on_job_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        if self._current_job_card is not None:
            if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                self._current_job_card.update_status("Complete", 100)
                self._append_log(f"[job] Completed job for {self._current_fname}")
                self._update_table_row_status(self._current_job_row, "Complete")
                out = self._archive_latest_outputs_for_job(self._current_full_path or self._current_fname)
                self._update_job_record(fname=self._current_fname, status="Complete", outputs=out)
                if bool(self._settings().value(KEY_AUTO_OPEN_OUTPUT, False, type=bool)):
                    folder = out.get("folder") if out else self._get_output_folder()
                    if isinstance(folder, str) and folder.strip():
                        QDesktopServices.openUrl(QUrl.fromLocalFile(folder.strip()))
            else:
                self._current_job_card.update_status("Error", 0)
                self._append_log(f"[job] Job failed for {self._current_fname} (exit code {exit_code}).")
                self._update_table_row_status(self._current_job_row, "Error")
                self._update_job_record(fname=self._current_fname, status="Error", outputs=None)
        self._job_process = None
        self._current_job_card = None
        self._current_full_path = None

    def _add_job_record(self, fname: str, full_path: str, status: str):
        rec = {
            "fname": fname,
            "full_path": full_path,
            "status": status,
            "output_folder": "",
            "opened": "",
            "spanish_path": "",
            "english_path": "",
        }
        self._jobs.insert(0, rec)
        self._refresh_jobs_table()

    def _update_job_record(self, fname: str, status: str, outputs: dict | None):
        for rec in self._jobs:
            if rec.get("fname") == fname and rec.get("status") == "Processing":
                rec["status"] = status
                if outputs:
                    rec["output_folder"] = outputs.get("folder", "")
                    rec["spanish_path"] = outputs.get("spanish_path", "")
                    rec["english_path"] = outputs.get("english_path", "")
                    rec["opened"] = time.strftime("%H:%M:%S")
                self._refresh_jobs_table()
                return
        # Fallback: update latest matching
        for rec in self._jobs:
            if rec.get("fname") == fname:
                rec["status"] = status
                if outputs:
                    rec["output_folder"] = outputs.get("folder", "")
                    rec["spanish_path"] = outputs.get("spanish_path", "")
                    rec["english_path"] = outputs.get("english_path", "")
                    rec["opened"] = time.strftime("%H:%M:%S")
                self._refresh_jobs_table()
                return

    def _refresh_jobs_table(self):
        if not hasattr(self, "jobs_table"):
            return
        self.jobs_table.setRowCount(0)
        for rec in self._jobs[:50]:
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            fname_item = QTableWidgetItem(rec.get("fname", ""))
            fname_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.jobs_table.setItem(row, 0, fname_item)

            status_text = rec.get("status", "")
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            status_item.setForeground(QColor(STATUS_COLORS.get(status_text, "#94a3b8")))
            self.jobs_table.setItem(row, 1, status_item)
            self.jobs_table.setItem(row, 2, QTableWidgetItem(rec.get("output_folder", "")))
            self.jobs_table.setItem(row, 3, QTableWidgetItem(rec.get("opened", "")))
            self.jobs_table.setRowHeight(row, 42)

    def _safe_read_text(self, path: str, limit_chars: int = 20000) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(limit_chars + 1)
            if len(data) > limit_chars:
                return data[:limit_chars] + "\n\n… (preview truncated) …"
            return data
        except Exception as e:
            return f"[error] Could not read file:\n{path}\n\n{e}"

    def _archive_latest_outputs_for_job(self, full_path: str) -> dict:
        """
        mixbothtask.py writes fixed filenames in SCRIPT_DIR.
        After each successful run, move them into the output folder with unique names.
        """
        out_dir = self._get_output_folder()
        base = os.path.splitext(os.path.basename(full_path))[0]
        stamp = time.strftime("%Y%m%d_%H%M%S")

        src_spanish = os.path.join(SCRIPT_DIR, OUTPUT_SPANISH_BASENAME)
        src_english = os.path.join(SCRIPT_DIR, OUTPUT_ENGLISH_BASENAME)

        dst_spanish = os.path.join(out_dir, f"{base}_{stamp}_transcription_spanish.txt")
        dst_english = os.path.join(out_dir, f"{base}_{stamp}_translation_english.txt")

        moved_any = False
        if os.path.exists(src_spanish):
            os.replace(src_spanish, dst_spanish)
            moved_any = True
        else:
            dst_spanish = ""
        if os.path.exists(src_english):
            os.replace(src_english, dst_english)
            moved_any = True
        else:
            dst_english = ""

        return {
            "folder": out_dir,
            "spanish_path": dst_spanish,
            "english_path": dst_english,
            "moved_any": moved_any,
        }

    def _refresh_review_items(self):
        out_dir = self._get_output_folder()
        items: list[dict] = []

        # Prefer recently completed jobs we already know about.
        for rec in self._jobs:
            if rec.get("status") == "Complete" and (rec.get("spanish_path") or rec.get("english_path")):
                items.append(
                    {
                        "label": rec.get("fname", ""),
                        "folder": rec.get("output_folder", out_dir),
                        "spanish_path": rec.get("spanish_path", ""),
                        "english_path": rec.get("english_path", ""),
                    }
                )

        # If none yet, do a simple scan of the output folder for our naming scheme.
        if not items and os.path.isdir(out_dir):
            files = sorted(os.listdir(out_dir), reverse=True)
            groups: dict[str, dict] = {}
            for fn in files:
                if not fn.lower().endswith(".txt"):
                    continue
                full = os.path.join(out_dir, fn)
                key = fn
                # Group by base + timestamp prefix (everything before last suffix)
                if fn.endswith("_transcription_spanish.txt"):
                    key = fn[: -len("_transcription_spanish.txt")]
                    groups.setdefault(key, {})["spanish_path"] = full
                elif fn.endswith("_translation_english.txt"):
                    key = fn[: -len("_translation_english.txt")]
                    groups.setdefault(key, {})["english_path"] = full
                groups.setdefault(key, {})["label"] = key
                groups.setdefault(key, {})["folder"] = out_dir
            for key, g in groups.items():
                if g.get("spanish_path") or g.get("english_path"):
                    items.append(
                        {
                            "label": g.get("label", key),
                            "folder": g.get("folder", out_dir),
                            "spanish_path": g.get("spanish_path", ""),
                            "english_path": g.get("english_path", ""),
                        }
                    )

        self._review_items = items[:200]
        if not hasattr(self, "review_selector"):
            return

        prev_idx = self.review_selector.currentIndex()
        prev_label = self.review_selector.currentText()

        self.review_selector.blockSignals(True)
        self.review_selector.clear()
        for it in self._review_items:
            label = it.get("label", "")
            self.review_selector.addItem(label)
        self.review_selector.blockSignals(False)

        # Restore selection if possible.
        if prev_label:
            idx = self.review_selector.findText(prev_label)
            if idx >= 0:
                self.review_selector.setCurrentIndex(idx)
            elif self._review_items:
                self.review_selector.setCurrentIndex(0)
        else:
            if 0 <= prev_idx < self.review_selector.count():
                self.review_selector.setCurrentIndex(prev_idx)
            elif self._review_items:
                self.review_selector.setCurrentIndex(0)

        if not self._review_items:
            self.review_info_path.setText("Run a job to generate .txt files, then come back to Review.")
            self.spanish_preview.setPlainText("")
            self.english_preview.setPlainText("")
        else:
            self._on_review_selection_changed()

    def _selected_review_item(self) -> dict | None:
        if not hasattr(self, "review_selector"):
            return None
        idx = self.review_selector.currentIndex()
        if 0 <= idx < len(self._review_items):
            return self._review_items[idx]
        return None

    def _on_review_selection_changed(self):
        it = self._selected_review_item()
        if not it:
            if hasattr(self, "review_info_path"):
                self.review_info_path.setText("")
            if hasattr(self, "spanish_preview"):
                self.spanish_preview.setPlainText("")
            if hasattr(self, "english_preview"):
                self.english_preview.setPlainText("")
            return

        folder = it.get("folder", "")
        sp = it.get("spanish_path", "")
        en = it.get("english_path", "")

        self.review_info_path.setText(f"Folder: {folder}")

        self.spanish_preview.setPlainText(self._safe_read_text(sp) if sp else "No transcription file found.")
        self.english_preview.setPlainText(self._safe_read_text(en) if en else "No translation file found.")

    def _open_review_folder(self):
        it = self._selected_review_item()
        if not it:
            return
        folder = it.get("folder", "")
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_review_file(self, which: str):
        it = self._selected_review_item()
        if not it:
            return
        path = it.get("spanish_path", "") if which == "spanish" else it.get("english_path", "")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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