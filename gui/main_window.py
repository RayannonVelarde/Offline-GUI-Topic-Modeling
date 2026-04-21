import json
import os
import time
import keyring
from PySide6.QtCore import QPoint, Qt, QProcess, QSettings, QUrl, QSize, QProcessEnvironment, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QTextCharFormat, QTextCursor, QPainter, QPen
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
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QFormLayout,
    QSlider,
    QMenu,
)

from widgets import DropZone
from stylesheet import THEME_DARK, THEME_LIGHT, get_stylesheet
from nav_icons import (
    make_disclosure_chevron_icon,
    make_folder_open_icon,
    make_log_output_icon,
    make_nav_icon,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # QtMultimedia may be unavailable in some PySide6 builds
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]

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
# Sidecar next to archived transcripts: <stem>_transcription_meta.json
TRANSCRIPTION_META_SUFFIX = "_transcription_meta.json"

# Home file table viewport: medium default, grow with real row/widget heights, cap then scroll.
HOME_TABLE_MIN_H = 260
HOME_TABLE_ABSOLUTE_MAX_PX = 720  # hard cap (rare); usual cap is available space below table top
HOME_TABLE_ROW_MIN_H = 52
# Home table: action column (folder + log toolbuttons + padding).
HOME_TABLE_FOLDER_COL_W = 108


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


class WaveSeekBar(QSlider):
    """Compact timeline with click/drag seek + subtle waveform bars."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMouseTracking(True)
        self.setRange(0, 0)
        self.setSingleStep(1000)
        self.setPageStep(5000)
        self.setFixedHeight(22)
        self._dragging = False

    def isDragging(self) -> bool:
        return bool(self._dragging)

    def _value_from_x(self, x: int) -> int:
        w = max(1, self.width() - 2)
        r = self.maximum() - self.minimum()
        if r <= 0:
            return self.minimum()
        frac = max(0.0, min(1.0, (x - 1) / float(w)))
        return int(self.minimum() + frac * r)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setValue(self._value_from_x(int(event.position().x())))
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.setValue(self._value_from_x(int(event.position().x())))
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 6, -1, -6)

        theme = getattr(self.window(), "_theme", THEME_LIGHT)
        if theme == THEME_DARK:
            track = QColor("#1e2433")
            fill = QColor("#3b82f6")
            bars = QColor(255, 255, 255, 60)
        else:
            track = QColor("#e2e8f0")
            fill = QColor("#2563eb")
            bars = QColor(15, 23, 42, 40)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(rect, 6, 6)

        rng = self.maximum() - self.minimum()
        frac = 0.0 if rng <= 0 else (self.value() - self.minimum()) / float(rng)
        w = int(rect.width() * max(0.0, min(1.0, frac)))
        if w > 0:
            fill_rect = rect.adjusted(0, 0, -(rect.width() - w), 0)
            p.setBrush(fill)
            p.drawRoundedRect(fill_rect, 6, 6)

        p.setBrush(bars)
        p.setPen(Qt.PenStyle.NoPen)
        x0 = rect.x() + 6
        x1 = rect.right() - 6
        mid = rect.center().y()
        step = 7
        i = 0
        for x in range(x0, x1, step):
            h = 3 + ((i * 7) % 9)
            p.drawRoundedRect(x, int(mid - h / 2), 2, h, 1, 1)
            i += 1

        if w > 0:
            px = rect.x() + w
            p.setPen(
                QPen(
                    QColor(255, 255, 255, 160) if theme == THEME_DARK else QColor(15, 23, 42, 120),
                    1,
                )
            )
            p.drawLine(px, rect.y() + 2, px, rect.bottom() - 2)

        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Transcription App")
        self._job_process = None
        self._job_log_path: str | None = None
        self._current_full_path = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._current_page = "home"
        self._theme = THEME_LIGHT
        self._jobs: list[dict] = []
        self._review_items: list[dict] = []
        self._current_job_row: int | None = None
        self._current_fname: str | None = None
        self._estimated_progress_pct: float = 0.0
        self._estimated_progress_row: int | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(110)
        self._progress_timer.timeout.connect(self._on_estimated_progress_tick)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar(), stretch=0)
        root_layout.addWidget(self._build_center(), stretch=1)

        # Apply persisted theme (LIGHT by default)
        self.apply_theme(self._settings().value(KEY_THEME, THEME_LIGHT))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_current_page", "") == "home" and hasattr(self, "table"):
            QTimer.singleShot(0, self._sync_home_table_height)

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
        self._refresh_home_folder_row_icons()
        self._refresh_jobs_folder_row_icons()
        self._refresh_home_log_disclosure_icons()
        self._refresh_settings_disclosure_icons()
        QTimer.singleShot(0, self._sync_home_row_selection_styles)

    def _refresh_settings_disclosure_icons(self) -> None:
        """Update Settings chevron icons when theme changes."""
        btn = getattr(self, "default_translation_chevron_btn", None)
        if btn is None:
            return
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 14
        btn.setIcon(make_disclosure_chevron_icon(expanded=True, size=icon_sz, color_hex=col))
        btn.setIconSize(QSize(icon_sz, icon_sz))

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

    def _refresh_home_folder_row_icons(self) -> None:
        """Match Home table folder action icons to sidebar stroke style / inactive nav color."""
        if not hasattr(self, "table"):
            return
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 14
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "home-row-open-btn":
                    btn.setIcon(make_folder_open_icon(size=icon_sz, color_hex=inactive))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

    def _refresh_jobs_folder_row_icons(self) -> None:
        """Match Jobs table folder buttons to Home stroke folder icon / theme color."""
        if not hasattr(self, "jobs_table"):
            return
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 14
        for r in range(self.jobs_table.rowCount()):
            w = self.jobs_table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "jobs-row-open-btn":
                    btn.setIcon(make_folder_open_icon(size=icon_sz, color_hex=inactive))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

    def _refresh_home_log_disclosure_icons(self) -> None:
        """Update Home action-column log/document icons when theme changes (stroke color)."""
        if not hasattr(self, "table"):
            return
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 14
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "home-row-log-btn":
                    btn.setIcon(make_log_output_icon(size=icon_sz, color_hex=col))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

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
        logo.setAutoFillBackground(False)
        logo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sub = QLabel("Offline Tool")
        sub.setObjectName("sidebar-sub")
        sub.setAutoFillBackground(False)
        sub.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        self._home_page = home
        home.setObjectName("home-page")
        layout = QVBoxLayout(home)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Transcription Home")
        title.setObjectName("page-title")
        subtitle = QLabel("Upload audio files for transcription and translation")
        subtitle.setObjectName("page-sub")
        layout.addWidget(title)
        layout.addWidget(subtitle)

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
        self._home_start_btn = start_btn
        start_btn.setObjectName("start-btn")
        start_btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        section.setObjectName("jobs-recent-title")
        section.setAutoFillBackground(False)
        section.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card_layout.addWidget(section)

        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setObjectName("jobs-table")
        self.jobs_table.setHorizontalHeaderLabels(
            ["Duration", "Filename", "Status", "Output folder"]
        )
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setShowGrid(False)
        self.jobs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setMinimumHeight(200)
        hdr = self.jobs_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
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

        # Audio player bar (under selector row)
        player = QFrame()
        player.setObjectName("settings-card")
        player_layout = QHBoxLayout(player)
        player_layout.setContentsMargins(14, 10, 14, 10)
        player_layout.setSpacing(10)

        self._review_audio_path: str = ""
        self._review_player = None
        self._review_audio_out = None

        self.review_play_btn = QToolButton()
        self.review_play_btn.setObjectName("review-play-btn")
        self.review_play_btn.setToolTip("Play / pause")
        # Always show an explicit label so it never reads as an empty box.
        self.review_play_btn.setText("Play")
        self.review_play_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.review_play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.review_play_btn.setIconSize(QSize(16, 16))
        self.review_play_btn.setFixedHeight(32)
        self.review_play_btn.setMinimumWidth(88)
        self.review_play_btn.setEnabled(False)
        self.review_play_btn.clicked.connect(self._on_review_play_pause_clicked)

        self.review_seek = WaveSeekBar()
        self.review_seek.setObjectName("review-seek")
        self.review_seek.setEnabled(False)
        self.review_seek.sliderMoved.connect(self._on_review_seek_preview)
        self.review_seek.sliderReleased.connect(self._on_review_seek_commit)

        self.review_time_lbl = QLabel("0:00 / 0:00")
        self.review_time_lbl.setObjectName("settings-label")
        self.review_time_lbl.setMinimumWidth(96)
        self.review_time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.review_vol = QSlider(Qt.Orientation.Horizontal)
        self.review_vol.setObjectName("review-volume")
        self.review_vol.setRange(0, 100)
        self.review_vol.setValue(80)
        self.review_vol.setFixedWidth(92)

        # Only enable audio playback if QtMultimedia is available.
        if QMediaPlayer is not None and QAudioOutput is not None:
            self._review_audio_out = QAudioOutput(self)
            self._review_audio_out.setVolume(0.8)
            self._review_player = QMediaPlayer(self)
            self._review_player.setAudioOutput(self._review_audio_out)
            self.review_vol.valueChanged.connect(
                lambda v: self._review_audio_out.setVolume(max(0.0, min(1.0, v / 100.0)))
            )
            self._review_player.durationChanged.connect(self._on_review_media_duration)
            self._review_player.positionChanged.connect(self._on_review_media_position)
            self._review_player.playbackStateChanged.connect(self._on_review_playback_state_changed)
        else:
            self.review_vol.setEnabled(False)
            self.review_vol.setToolTip("Audio playback unavailable (QtMultimedia not installed).")
            self.review_play_btn.setToolTip("Audio playback unavailable (QtMultimedia not installed).")

        player_layout.addWidget(self.review_play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_seek, 1, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_time_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_vol, 0, Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(player)

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

    @staticmethod
    def _format_ms(ms: int) -> str:
        ms = max(0, int(ms))
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _set_review_audio_source(self, audio_path: str) -> None:
        ap = (audio_path or "").strip()
        if ap == self._review_audio_path:
            return
        self._review_audio_path = ap

        self.review_seek.setRange(0, 0)
        self.review_seek.setValue(0)
        self.review_seek.setEnabled(False)
        self.review_play_btn.setEnabled(False)
        self.review_time_lbl.setText("0:00 / 0:00")
        self.review_play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.review_play_btn.setText("Play")

        if self._review_player is None:
            return

        self._review_player.stop()
        if not ap or not os.path.isfile(ap):
            self._review_player.setSource(QUrl())
            return

        self._review_player.setSource(QUrl.fromLocalFile(ap))
        self.review_seek.setEnabled(True)
        self.review_play_btn.setEnabled(True)

    def _on_review_play_pause_clicked(self):
        if self._review_player is None:
            return
        if self._review_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._review_player.pause()
        else:
            self._review_player.play()

    def _on_review_playback_state_changed(self, state):
        icon = (
            QStyle.StandardPixmap.SP_MediaPause
            if state == QMediaPlayer.PlaybackState.PlayingState
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.review_play_btn.setIcon(self.style().standardIcon(icon))
        self.review_play_btn.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")

    def _on_review_media_duration(self, dur_ms: int):
        self.review_seek.setRange(0, max(0, int(dur_ms)))
        pos = 0 if self._review_player is None else int(self._review_player.position())
        self.review_time_lbl.setText(f"{self._format_ms(pos)} / {self._format_ms(dur_ms)}")

    def _on_review_media_position(self, pos_ms: int):
        if not self.review_seek.isDragging():
            self.review_seek.setValue(max(0, int(pos_ms)))
        dur = 0 if self._review_player is None else int(self._review_player.duration())
        self.review_time_lbl.setText(f"{self._format_ms(pos_ms)} / {self._format_ms(dur)}")

    def _on_review_seek_preview(self, pos_ms: int):
        dur = 0 if self._review_player is None else int(self._review_player.duration())
        self.review_time_lbl.setText(f"{self._format_ms(pos_ms)} / {self._format_ms(dur)}")

    def _on_review_seek_commit(self):
        if self._review_player is None:
            return
        self._review_player.setPosition(int(self.review_seek.value()))

    def _build_settings_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("settings-page")

        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Centered column so settings are not stretched edge-to-edge on wide windows.
        _SETTINGS_CONTENT_MAX_W = 720
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)

        content_host = QWidget()
        content_host.setObjectName("settings-content-host")
        content_host.setMaximumWidth(_SETTINGS_CONTENT_MAX_W)
        content_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(content_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Shared grid: one label width + one field column width across all sections.
        _SETTINGS_LABEL_W = 236
        _SETTINGS_FIELD_MIN_W = 220

        title = QLabel("Settings")
        title.setObjectName("page-title")
        subtitle = QLabel("App preferences for transcription jobs")
        subtitle.setObjectName("page-sub")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(2)

        def _make_label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setObjectName("settings-label")
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            lab.setFixedWidth(_SETTINGS_LABEL_W)
            return lab

        def _make_card(title_text: str) -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName("settings-card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 12)
            card_layout.setSpacing(6)
            section = QLabel(title_text)
            section.setObjectName("section-title")
            card_layout.addWidget(section)
            return card, card_layout

        def _make_form(parent: QWidget) -> QFormLayout:
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(6)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            parent.setLayout(form)
            return form

        def _field_row(*widgets: QWidget, stretch_first: bool = True) -> QWidget:
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            for i, ww in enumerate(widgets):
                if i == 0 and stretch_first:
                    row.addWidget(ww, 1, Qt.AlignmentFlag.AlignVCenter)
                else:
                    row.addWidget(ww, 0, Qt.AlignmentFlag.AlignVCenter)
            return w

        def _persist_settings_from_ui() -> None:
            s = self._settings()
            if hasattr(self, "default_diarization_checkbox"):
                s.setValue(KEY_DEFAULT_DIARIZATION, bool(self.default_diarization_checkbox.isChecked()))
            if hasattr(self, "default_speaker_spin"):
                s.setValue(KEY_DEFAULT_NUM_SPEAKERS, int(self.default_speaker_spin.value()))
            if hasattr(self, "default_timestamps_checkbox"):
                s.setValue(KEY_DEFAULT_TIMESTAMPS, bool(self.default_timestamps_checkbox.isChecked()))
            if hasattr(self, "default_translation_combo"):
                s.setValue(KEY_DEFAULT_TRANSLATION, str(self.default_translation_combo.currentText()))
            if hasattr(self, "output_folder_edit"):
                s.setValue(KEY_OUTPUT_FOLDER, str(self.output_folder_edit.text()).strip())
            if hasattr(self, "auto_open_output_checkbox"):
                s.setValue(KEY_AUTO_OPEN_OUTPUT, bool(self.auto_open_output_checkbox.isChecked()))

        # ── Appearance card ──────────────────────────────────────────────────
        appearance_card, appearance_layout = _make_card("Appearance")
        appearance_body = QWidget()
        appearance_form = _make_form(appearance_body)

        self.dark_mode_checkbox = QCheckBox("Enable dark mode")
        self.dark_mode_checkbox.setObjectName("theme-toggle")
        theme = self._settings().value(KEY_THEME, THEME_LIGHT)
        self.dark_mode_checkbox.setChecked(theme == THEME_DARK)
        self.dark_mode_checkbox.toggled.connect(self._on_dark_mode_toggled)
        appearance_form.addRow(self.dark_mode_checkbox)

        appearance_layout.addWidget(appearance_body)
        layout.addWidget(appearance_card)

        # ── Job defaults card ───────────────────────────────────────────────
        defaults_card, defaults_layout = _make_card("Job defaults")
        defaults_body = QWidget()
        defaults_form = _make_form(defaults_body)
        defaults_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.default_diarization_checkbox = QCheckBox("Enable speaker diarization by default")
        self.default_diarization_checkbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.default_diarization_checkbox.setChecked(
            bool(self._settings().value(KEY_DEFAULT_DIARIZATION, True, type=bool))
        )
        self.default_diarization_checkbox.toggled.connect(self._on_default_diarization_toggled)
        dia_row = QWidget()
        dia_lay = QHBoxLayout(dia_row)
        dia_lay.setContentsMargins(0, 0, 0, 4)
        dia_lay.setSpacing(0)
        dia_lay.addWidget(self.default_diarization_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        dia_lay.addStretch(1)
        defaults_form.addRow(_make_label(""), dia_row)

        self.default_speaker_spin = QSpinBox()
        self.default_speaker_spin.setObjectName("settings-input")
        self.default_speaker_spin.setRange(1, 32)
        self.default_speaker_spin.setValue(
            max(1, min(32, int(self._settings().value(KEY_DEFAULT_NUM_SPEAKERS, 2, type=int))))
        )
        self.default_speaker_spin.setMinimumWidth(_SETTINGS_FIELD_MIN_W)
        self.default_speaker_spin.valueChanged.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_NUM_SPEAKERS, int(v))
        )
        self.default_speaker_spin.setEnabled(self.default_diarization_checkbox.isChecked())
        defaults_form.addRow(_make_label("Default number of speakers:"), self.default_speaker_spin)

        # Translation mode dropdown (aesthetic): opens ONLY via chevron click.
        self.default_translation_options = [
            "Auto → English",
            "Auto → Spanish",
            "Auto → French",
            "Auto → German",
            "Auto → Portuguese",
            "Auto → Italian",
            "None",
        ]
        current_translation = str(
            self._settings().value(KEY_DEFAULT_TRANSLATION, "Auto → English")
        )
        if current_translation not in self.default_translation_options:
            current_translation = "Auto → English"

        translation_field = QFrame()
        translation_field.setObjectName("settings-input")
        translation_field.setFixedWidth(_SETTINGS_FIELD_MIN_W)
        translation_field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        translation_lay = QHBoxLayout(translation_field)
        translation_lay.setContentsMargins(0, 0, 0, 0)
        translation_lay.setSpacing(8)

        self.default_translation_value = QLabel(current_translation)
        self.default_translation_value.setObjectName("settings-dropdown-value")
        self.default_translation_value.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.default_translation_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        self.default_translation_value.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        self.default_translation_chevron_btn = QToolButton()
        self.default_translation_chevron_btn.setObjectName("settings-chevron-btn")
        self.default_translation_chevron_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.default_translation_chevron_btn.setAutoRaise(True)
        self.default_translation_chevron_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.default_translation_chevron_btn.setFixedSize(24, 24)

        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 14
        self.default_translation_chevron_btn.setIcon(
            make_disclosure_chevron_icon(expanded=True, size=icon_sz, color_hex=col)
        )
        self.default_translation_chevron_btn.setIconSize(QSize(icon_sz, icon_sz))

        self.default_translation_menu = QMenu(self)
        for opt in self.default_translation_options:
            act = self.default_translation_menu.addAction(opt)
            act.setData(opt)

        def _set_translation_mode(text: str) -> None:
            self.default_translation_value.setText(text)
            self._settings().setValue(KEY_DEFAULT_TRANSLATION, str(text))

        def _open_translation_menu() -> None:
            gp = self.default_translation_chevron_btn.mapToGlobal(
                QPoint(0, self.default_translation_chevron_btn.height())
            )
            self.default_translation_menu.popup(gp)

        self.default_translation_menu.triggered.connect(
            lambda a: _set_translation_mode(str(a.data()))
        )
        self.default_translation_chevron_btn.clicked.connect(_open_translation_menu)

        translation_lay.addWidget(self.default_translation_value, 1)
        translation_lay.addWidget(
            self.default_translation_chevron_btn, 0, Qt.AlignmentFlag.AlignRight
        )

        defaults_form.addRow(_make_label("Translation mode:"), translation_field)

        # Label in the form column + bare checkbox avoids long caption clipping in QCheckBox.
        self.default_timestamps_checkbox = QCheckBox()
        self.default_timestamps_checkbox.setAccessibleName("Timestamps")
        self.default_timestamps_checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.default_timestamps_checkbox.setToolTip(
            "When enabled, new jobs use per-segment timestamps by default."
        )
        self.default_timestamps_checkbox.setChecked(
            bool(self._settings().value(KEY_DEFAULT_TIMESTAMPS, True, type=bool))
        )
        self.default_timestamps_checkbox.toggled.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_TIMESTAMPS, bool(v))
        )
        ts_label = _make_label("Timestamps")
        ts_label.setBuddy(self.default_timestamps_checkbox)
        defaults_form.addRow(ts_label, self.default_timestamps_checkbox)

        defaults_layout.addWidget(defaults_body)
        layout.addWidget(defaults_card)

        # ── Output card ─────────────────────────────────────────────────────
        output_card, output_layout = _make_card("Output")
        output_body = QWidget()
        output_form = _make_form(output_body)

        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setObjectName("settings-input")
        self.output_folder_edit.setPlaceholderText("Choose a folder…")
        self.output_folder_edit.setText(self._settings().value(KEY_OUTPUT_FOLDER, ""))
        self.output_folder_edit.textChanged.connect(
            lambda t: self._settings().setValue(KEY_OUTPUT_FOLDER, t.strip())
        )
        self.output_folder_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.output_folder_edit.setMinimumWidth(max(280, _SETTINGS_FIELD_MIN_W))

        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("add-btn")
        # Minimum width policy: fixed 88px was narrower than add-btn padding + label (text clipped).
        browse_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        browse_btn.clicked.connect(self._browse_output_folder)

        folder_field = _field_row(self.output_folder_edit, browse_btn, stretch_first=True)
        folder_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        output_form.addRow(_make_label("Default output folder:"), folder_field)

        self.auto_open_output_checkbox = QCheckBox("Auto-open output folder when a job completes")
        self.auto_open_output_checkbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.auto_open_output_checkbox.setChecked(
            bool(self._settings().value(KEY_AUTO_OPEN_OUTPUT, False, type=bool))
        )
        self.auto_open_output_checkbox.toggled.connect(
            lambda v: self._settings().setValue(KEY_AUTO_OPEN_OUTPUT, bool(v))
        )
        auto_open_row = QWidget()
        auto_open_lay = QHBoxLayout(auto_open_row)
        auto_open_lay.setContentsMargins(0, 2, 0, 0)
        auto_open_lay.setSpacing(0)
        auto_open_lay.addWidget(self.auto_open_output_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        auto_open_lay.addStretch(1)
        output_form.addRow(_make_label(""), auto_open_row)

        output_layout.addWidget(output_body)
        layout.addWidget(output_card)

        # ── Integration card ────────────────────────────────────────────────
        integration_card, integration_layout = _make_card("Integration")
        integration_body = QWidget()
        integration_form = _make_form(integration_body)

        self.hf_token_edit = QLineEdit()
        self.hf_token_edit.setObjectName("settings-input")
        self.hf_token_edit.setMinimumWidth(_SETTINGS_FIELD_MIN_W)
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

        integration_form.addRow(
            _make_label("Hugging Face token:"),
            _field_row(self.hf_token_edit, hf_save_btn, hf_clear_btn, stretch_first=True),
        )

        hf_note = QLabel("Stored securely in your OS keychain.")
        hf_note.setObjectName("settings-hint")
        integration_form.addRow(_make_label(""), hf_note)

        integration_layout.addWidget(integration_body)
        layout.addWidget(integration_card)

        # ── Bottom actions ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        save_btn = QPushButton("Save settings")
        save_btn.setObjectName("start-btn")
        save_btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        save_btn.setFixedWidth(140)
        save_btn.clicked.connect(_persist_settings_from_ui)
        btn_row.addWidget(save_btn, 0, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(btn_row)
        layout.addStretch()

        center_row.addWidget(content_host, 0, Qt.AlignmentFlag.AlignTop)
        center_row.addStretch(1)
        outer.addLayout(center_row, 1)
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
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("home-file-table")
        self.table.setHorizontalHeaderLabels(["Duration", "Filename", "Status", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table.setColumnWidth(3, HOME_TABLE_FOLDER_COL_W)

        # Hide home warning once the user makes a valid selection.
        self.table.itemSelectionChanged.connect(self._on_home_selection_changed)
        self.table.itemSelectionChanged.connect(self._sync_home_row_selection_styles)

        QTimer.singleShot(0, self._sync_home_table_height)
        return self.table

    def _effective_home_table_max_height(self) -> int:
        """Max table height: fill space down to Start Job when possible, then absolute cap."""
        t = getattr(self, "table", None)
        hp = getattr(self, "_home_page", None)
        if hp is None and t is not None:
            hp = t.parentWidget()
        if hp is None or t is None:
            return HOME_TABLE_ABSOLUTE_MAX_PX
        layout = hp.layout()
        sp = layout.spacing() if layout else 16
        hp.updateGeometry()
        t.updateGeometry()
        pos = t.mapTo(hp, QPoint(0, 0))
        start_h = 48
        sb = getattr(self, "_home_start_btn", None)
        if sb is not None:
            sb.adjustSize()
            start_h = max(sb.sizeHint().height(), sb.height(), 40)
        # Room for table if bottom stretch goes to 0: hp height = table_top + table_h + sp + start + stretch
        avail = hp.height() - pos.y() - sp - start_h
        avail = max(int(avail), HOME_TABLE_MIN_H)
        return min(HOME_TABLE_ABSOLUTE_MAX_PX, avail)

    def _sync_home_table_height(self) -> None:
        """Size the Home table from actual header + row heights (after resizeRowToContents), clamp, then scroll."""
        if not hasattr(self, "table"):
            return
        t = self.table
        for r in range(t.rowCount()):
            t.resizeRowToContents(r)
            if t.rowHeight(r) < HOME_TABLE_ROW_MIN_H:
                t.setRowHeight(r, HOME_TABLE_ROW_MIN_H)
        t.updateGeometry()
        hdr = t.horizontalHeader()
        h_hdr = hdr.height() if hdr.height() > 0 else 34
        body = sum(t.rowHeight(r) for r in range(t.rowCount()))
        desired = h_hdr + body + 6
        eff_max = self._effective_home_table_max_height()
        h = min(max(desired, HOME_TABLE_MIN_H), eff_max)
        t.setFixedHeight(h)

    def _row_for_col1_widget(self, col1: QWidget) -> int:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 1) is col1:
                return r
        return -1

    def _path_for_row(self, row: int) -> str:
        w = self.table.cellWidget(row, 1)
        if w is None:
            return ""
        return getattr(w, "_path_key", "") or ""

    def _filename_for_row(self, row: int) -> str:
        w = self.table.cellWidget(row, 1)
        if w is None:
            return ""
        return getattr(w, "_fname", "") or ""

    def _find_log_edit_for_path(self, path_key: str) -> QTextEdit | None:
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 1)
            if w is not None and getattr(w, "_path_key", "") == path_key:
                return getattr(w, "_log_edit", None)
        return None

    @staticmethod
    def _canonical_file_path(p: str) -> str:
        if not (p or "").strip():
            return ""
        try:
            return os.path.normcase(os.path.normpath(os.path.abspath(p.strip())))
        except Exception:
            return ""

    def _jobs_table_row_for_current_job(self) -> int | None:
        """Jobs table row index for _current_fname / _current_full_path (same order as _jobs[:50])."""
        if self._current_fname is None:
            return None
        if not hasattr(self, "jobs_table"):
            return None
        tgt = self._canonical_file_path(self._current_full_path or "")
        for i, rec in enumerate(self._jobs[:50]):
            if rec.get("fname") != self._current_fname:
                continue
            rfp = self._canonical_file_path((rec.get("full_path") or "").strip())
            if tgt and rfp:
                if rfp == tgt:
                    return i
            elif not tgt and not rfp:
                return i
            elif tgt and not rfp:
                return i
            elif not tgt and rfp:
                return i
        return None

    def _sync_jobs_status_cell_for_current_job(self, status: str, pct: int) -> None:
        """Mirror Home status + progress on the Jobs table for the active job."""
        row = self._jobs_table_row_for_current_job()
        if row is None:
            return
        w = self.jobs_table.cellWidget(row, 2)
        if w is None:
            return
        self._apply_home_status_bar_style(w, status, pct)

    def _reset_home_row_for_new_job(self, row: int) -> None:
        """Clear stale Complete/Error UI and log before launching a new run for this row."""
        self._stop_estimated_progress()
        w = self.table.cellWidget(row, 1)
        if w is not None:
            edit = getattr(w, "_log_edit", None)
            if edit is not None:
                edit.clear()
        self._update_table_row_status(row, "Processing", pct=0)

    def _remove_existing_job_records_for_file(self, full_path: str) -> None:
        """Drop prior Jobs-page entries for the same file so reruns don't duplicate or confuse updates."""
        tgt = self._canonical_file_path(full_path)
        if not tgt:
            return
        kept: list[dict] = []
        for r in self._jobs:
            rfp = (r.get("full_path") or "").strip()
            if rfp and self._canonical_file_path(rfp) == tgt:
                continue
            kept.append(r)
        self._jobs = kept

    def _toggle_log_visibility(self, col1_widget: QWidget, expanded: bool):
        log_edit = getattr(col1_widget, "_log_edit", None)
        expand_btn = getattr(col1_widget, "_expand_btn", None)
        if log_edit is None:
            return
        log_edit.setVisible(expanded)
        if expand_btn is not None:
            col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
            expand_btn.setIcon(make_log_output_icon(size=14, color_hex=col))
            expand_btn.setIconSize(QSize(14, 14))
        self._sync_home_table_height()
        QTimer.singleShot(0, self._sync_home_table_height)

    def _per_job_output_folder_for_path(self, path_key: str) -> str:
        """Folder from job record for this file if recorded and the directory exists."""
        if not (path_key or "").strip():
            return ""
        tgt = self._canonical_file_path(path_key)
        fname = os.path.basename(path_key.strip())
        for rec in self._jobs:
            if rec.get("fname") != fname:
                continue
            rfp = self._canonical_file_path((rec.get("full_path") or "").strip())
            if tgt and rfp and rfp != tgt:
                continue
            folder = (rec.get("output_folder") or "").strip()
            if folder and os.path.isdir(folder):
                return folder
        return ""

    def _open_home_row_output_folder(self, path_key: str) -> None:
        """Open per-job output folder if set; else general output folder if it exists."""
        per = self._per_job_output_folder_for_path(path_key)
        if per:
            QDesktopServices.openUrl(QUrl.fromLocalFile(per))
            return
        saved = self._settings().value(KEY_OUTPUT_FOLDER, "")
        if isinstance(saved, str) and saved.strip():
            p = os.path.abspath(saved.strip())
            if os.path.isdir(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
                return
        default_path = os.path.join(SCRIPT_DIR, "outputs")
        if os.path.isdir(default_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(default_path)))
            return
        QMessageBox.information(
            self,
            "Output folder",
            "No output folder is available yet.\n\n"
            "Complete a job or choose an output folder in Settings.",
        )

    def _sync_home_row_selection_styles(self) -> None:
        """Subtle tint on filename/status cell widgets so selection reads clearly."""
        if not hasattr(self, "table"):
            return
        t = self.table
        selected_rows: set[int] = set(ix.row() for ix in t.selectedIndexes())
        for r in range(t.rowCount()):
            sel = r in selected_rows
            for col in (1, 2, 3):
                w = t.cellWidget(r, col)
                if w is not None:
                    w.setProperty("homeRowSelected", sel)
                    w.style().unpolish(w)
                    w.style().polish(w)
                    w.update()

    def _apply_home_status_bar_style(self, col2: QWidget, status: str, pct: int):
        st_lbl = getattr(col2, "_status_lbl", None)
        bar = getattr(col2, "_progress_bar", None)
        if st_lbl is not None:
            st_lbl.setText(status)
            st_lbl.setStyleSheet(f"color: {STATUS_COLORS.get(status, '#94a3b8')};")
        if bar is None:
            return
        bar.setValue(max(0, min(100, pct)))
        if status == "Complete" and pct >= 100:
            bar.setObjectName("complete")
        elif status == "Error":
            bar.setObjectName("error")
        else:
            bar.setObjectName("")
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.update()

    def _build_home_filename_cell(self, fname: str, path_key: str) -> QWidget:
        outer = QWidget()
        outer.setObjectName("home-filename-cell")
        # Ensure the cell container itself is visually transparent so the
        # table row background is the only background that shows through.
        outer.setAutoFillBackground(False)
        outer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        outer.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        outer._path_key = path_key  # type: ignore[attr-defined]
        outer._fname = fname  # type: ignore[attr-defined]
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(4)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        fn_lab = QLabel(fname)
        fn_lab.setWordWrap(False)
        fn_lab.setStyleSheet("font-weight: 600;")
        name_inner = QHBoxLayout()
        name_inner.setSpacing(6)
        name_inner.setContentsMargins(0, 0, 0, 0)
        name_inner.addWidget(fn_lab, alignment=Qt.AlignmentFlag.AlignVCenter)
        name_block = QWidget()
        name_block.setLayout(name_inner)
        name_block.setAutoFillBackground(False)
        name_block.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        name_block.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addStretch(1)
        name_row.addWidget(name_block, alignment=Qt.AlignmentFlag.AlignCenter)
        name_row.addStretch(1)

        log_edit = QTextEdit()
        log_edit.setObjectName("home-file-log")
        log_edit.setReadOnly(True)
        log_edit.hide()
        log_edit.setMinimumHeight(120)
        log_edit.setMaximumHeight(200)
        font = log_edit.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() + 1)
        log_edit.setFont(font)

        outer._log_edit = log_edit  # type: ignore[attr-defined]

        outer_layout.addLayout(name_row)
        outer_layout.addWidget(log_edit)
        # Absorb extra row height below the log so the name + log block stays top-anchored.
        outer_layout.addStretch(1)
        return outer

    def _build_jobs_filename_cell(self, fname: str) -> QWidget:
        """Filename column for Jobs: same bold label as Home, without expand/log."""
        w = QWidget()
        # Keep this cell visually flat so only the Jobs table/card background shows.
        w.setAutoFillBackground(False)
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        w.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        lab = QLabel(fname)
        lab.setWordWrap(False)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setStyleSheet("font-weight: 600;")
        lay.addWidget(lab, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _build_jobs_output_folder_cell(self, folder_display: str, path_key: str) -> QWidget:
        """Output path + compact folder button on the right (same open logic as Home)."""
        w = QWidget()
        # Flat, transparent container so the table/card background remains the only fill.
        w.setAutoFillBackground(False)
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        w.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)
        path_lbl = QLabel((folder_display or "").strip() or "—")
        path_lbl.setWordWrap(False)
        path_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        path_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(path_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        btn = QToolButton()
        btn.setObjectName("jobs-row-open-btn")
        btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        _folder_muted = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        btn.setIcon(make_folder_open_icon(size=14, color_hex=_folder_muted))
        btn.setIconSize(QSize(14, 14))
        btn.setFixedSize(22, 22)
        btn.setToolTip("Open output folder")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setAutoRaise(True)
        pk = path_key.strip() if path_key else ""
        btn.clicked.connect(lambda _=False, p=pk: self._open_home_row_output_folder(p))
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return w

    def _build_home_folder_cell(self, path_key: str, filename_cell: QWidget) -> QWidget:
        """Far-right actions: open folder (left), then log/details toggle (right)."""
        wrap = QWidget()
        wrap.setObjectName("home-folder-cell")
        wrap.setAutoFillBackground(False)
        wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        wrap.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(4, 4, 8, 4)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        _muted = "#94a3b8" if self._theme == THEME_DARK else "#475569"

        btn = QToolButton()
        btn.setObjectName("home-row-open-btn")
        btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setIcon(make_folder_open_icon(size=14, color_hex=_muted))
        btn.setIconSize(QSize(14, 14))
        btn.setFixedSize(22, 22)
        btn.setToolTip("Open output folder")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setAutoRaise(True)
        pk = path_key.strip() if path_key else ""
        btn.clicked.connect(lambda _=False, p=pk: self._open_home_row_output_folder(p))

        log_btn = QToolButton()
        log_btn.setObjectName("home-row-log-btn")
        log_btn.setCheckable(True)
        log_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        log_btn.setText("")
        log_btn.setIcon(make_log_output_icon(size=14, color_hex=_muted))
        log_btn.setIconSize(QSize(14, 14))
        log_btn.setFixedSize(22, 22)
        log_btn.setToolTip("Show or hide log for this file")
        log_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_btn.setAutoRaise(True)
        filename_cell._expand_btn = log_btn  # type: ignore[attr-defined]
        log_btn.toggled.connect(lambda on, o=filename_cell: self._toggle_log_visibility(o, on))

        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(log_btn, 0, Qt.AlignmentFlag.AlignTop)
        return wrap

    def _build_home_status_cell(self, status: str) -> QWidget:
        sw = QWidget()
        sw.setObjectName("home-status-cell")
        sw.setAutoFillBackground(False)
        sw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        sw.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        sw.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        vl = QVBoxLayout(sw)
        vl.setContentsMargins(6, 4, 6, 4)
        vl.setSpacing(6)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)
        st_lbl = QLabel(status)
        st_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        vl.addWidget(st_lbl)
        vl.addWidget(bar)
        vl.addStretch(1)
        sw._status_lbl = st_lbl  # type: ignore[attr-defined]
        sw._progress_bar = bar  # type: ignore[attr-defined]
        pct = 100 if status == "Complete" else 0
        self._apply_home_status_bar_style(sw, status, pct)
        return sw

    def _append_colored_line_to_edit(self, edit: QTextEdit, text: str):
        line = text.rstrip("\n")
        lower = line.lower()
        if "[job] completed job" in lower:
            color = "#16a34a"
        elif "[job] job failed" in lower or lower.startswith("[error]"):
            color = "#ef4444"
        else:
            color = "#ffffff" if self._theme == THEME_DARK else "#000000"

        cur = edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(line + "\n", fmt)
        edit.setTextCursor(cur)
        edit.ensureCursorVisible()

    def _append_log(self, text: str, target_path: str | None = None):
        path = target_path if target_path is not None else self._job_log_path
        if not path:
            return
        edit = self._find_log_edit_for_path(path)
        if edit is None:
            return
        self._append_colored_line_to_edit(edit, text)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _append_table_row(self, fname: str, duration: str, status: str, full_path: str | None = None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        path_key = full_path.strip() if full_path else fname

        dur_item = QTableWidgetItem(duration)
        dur_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.table.setItem(row, 0, dur_item)

        col1 = self._build_home_filename_cell(fname, path_key)
        self.table.setCellWidget(row, 1, col1)

        col2 = self._build_home_status_cell(status)
        self.table.setCellWidget(row, 2, col2)
        self.table.setCellWidget(row, 3, self._build_home_folder_cell(path_key, col1))

        self._sync_home_table_height()
        QTimer.singleShot(0, self._sync_home_table_height)
        QTimer.singleShot(0, self._sync_home_row_selection_styles)

    def add_files_to_table(self, files: list[str]):
        for path in files:
            duration = _get_audio_duration(path)
            self._append_table_row(os.path.basename(path), duration, "Pending", full_path=path)
            self._append_log(f"[+] Added file: {os.path.basename(path)}", target_path=path)

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

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_row = selected_ranges[0].topRow()
        fname = self._filename_for_row(selected_row)
        full_path = self._path_for_row(selected_row) or fname
        path_key = full_path

        diarize = dialog.diarization_checkbox.isChecked()
        num_speakers = dialog.speaker_count_spin.value()
        translation = dialog.translation_combo.currentText()
        timestamps = dialog.timestamps_combo.currentText()

        # Require a Hugging Face token for jobs that need it.
        token = self._get_hf_token()
        if not token:
            self._append_log(
                "[warn] Hugging Face token is missing. Add it in Settings before starting this job.",
                target_path=path_key,
            )
            QMessageBox.warning(
                self,
                "Token required",
                "A valid Hugging Face token is required.\n\n"
                "Open the Settings page and add your token in the Hugging Face token field.",
            )
            return

        # Only allow one active job process at a time.
        if self._job_process is not None and self._job_process.state() != QProcess.ProcessState.NotRunning:
            if self._job_log_path:
                self._append_log(
                    "[warn] A job is already running. Wait for it to finish.",
                    target_path=self._job_log_path,
                )
            return

        self._current_full_path = full_path

        self._reset_home_row_for_new_job(selected_row)
        self._add_job_record(fname=fname, full_path=full_path, status="Processing")

        self._job_log_path = path_key
        self._append_log(
            f"[job] Starting job for {fname} "
            f"(translation='{translation}', diarization={diarize}, "
            f"num_speakers={num_speakers}, timestamps='{timestamps}')"
        )

        python = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
        self._job_process = QProcess(self)
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
            self._update_table_row_status(selected_row, "Error", pct=0)
            self._job_process = None
            self._job_log_path = None
            self._current_job_row = None
            self._current_fname = None
        else:
            self._start_estimated_progress(selected_row)

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

    def _stop_estimated_progress(self):
        if self._progress_timer.isActive():
            self._progress_timer.stop()
        self._estimated_progress_pct = 0.0
        self._estimated_progress_row = None

    def _start_estimated_progress(self, row: int):
        """Smooth simulated progress toward ~94% while the subprocess runs."""
        self._stop_estimated_progress()
        self._estimated_progress_row = row
        self._estimated_progress_pct = 5.0
        col2 = self.table.cellWidget(row, 2)
        if col2 is not None:
            self._apply_home_status_bar_style(col2, "Processing", int(self._estimated_progress_pct))
        self._sync_jobs_status_cell_for_current_job("Processing", int(self._estimated_progress_pct))
        self._progress_timer.start()

    def _on_estimated_progress_tick(self):
        if self._job_process is None or self._current_job_row is None:
            self._stop_estimated_progress()
            return
        row = self._current_job_row
        if row != self._estimated_progress_row:
            return
        col2 = self.table.cellWidget(row, 2)
        if col2 is None:
            return
        # Asymptotic approach: move smoothly toward 94%, never reach 100% until the job finishes.
        cap = 94.0
        gap = cap - self._estimated_progress_pct
        self._estimated_progress_pct += max(0.04, gap * 0.0065)
        self._estimated_progress_pct = min(self._estimated_progress_pct, cap)
        self._apply_home_status_bar_style(col2, "Processing", int(self._estimated_progress_pct))
        self._sync_jobs_status_cell_for_current_job("Processing", int(self._estimated_progress_pct))

    def _on_job_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        self._stop_estimated_progress()
        if self._current_job_row is not None:
            if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                self._append_log(f"[job] Completed job for {self._current_fname}")
                self._update_table_row_status(self._current_job_row, "Complete", pct=100)
                out = self._archive_latest_outputs_for_job(self._current_full_path or self._current_fname)
                self._update_job_record(fname=self._current_fname, status="Complete", outputs=out)
                if hasattr(self, "review_selector"):
                    self._refresh_review_items()
                if bool(self._settings().value(KEY_AUTO_OPEN_OUTPUT, False, type=bool)):
                    folder = out.get("folder") if out else self._get_output_folder()
                    if isinstance(folder, str) and folder.strip():
                        QDesktopServices.openUrl(QUrl.fromLocalFile(folder.strip()))
            else:
                self._append_log(f"[job] Job failed for {self._current_fname} (exit code {exit_code}).")
                self._update_table_row_status(self._current_job_row, "Error", pct=0)
                self._update_job_record(fname=self._current_fname, status="Error", outputs=None)
        self._job_process = None
        self._job_log_path = None
        self._current_job_row = None
        self._current_fname = None
        self._current_full_path = None

    def _add_job_record(self, fname: str, full_path: str, status: str):
        self._remove_existing_job_records_for_file(full_path)
        rec = {
            "fname": fname,
            "full_path": full_path,
            "duration": _get_audio_duration(full_path),
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

            fp = (rec.get("full_path") or "").strip()
            dur = rec.get("duration")
            if dur is None or dur == "":
                dur = _get_audio_duration(fp) if fp else "—"
            else:
                dur = str(dur)
            dur_item = QTableWidgetItem(dur)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.jobs_table.setItem(row, 0, dur_item)

            self.jobs_table.setCellWidget(row, 1, self._build_jobs_filename_cell(rec.get("fname", "")))

            status_text = rec.get("status", "")
            self.jobs_table.setCellWidget(row, 2, self._build_home_status_cell(status_text))

            path_key = fp if fp else (rec.get("fname") or "")
            self.jobs_table.setCellWidget(
                row,
                3,
                self._build_jobs_output_folder_cell(rec.get("output_folder", ""), path_key),
            )

            self.jobs_table.setRowHeight(row, HOME_TABLE_ROW_MIN_H)

    def _safe_read_text(self, path: str, limit_chars: int = 20000) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(limit_chars + 1)
            if len(data) > limit_chars:
                return data[:limit_chars] + "\n\n… (preview truncated) …"
            return data
        except Exception as e:
            return f"[error] Could not read file:\n{path}\n\n{e}"

    def _transcription_meta_path(self, out_dir: str, stem: str) -> str:
        return os.path.join(out_dir, f"{stem}{TRANSCRIPTION_META_SUFFIX}")

    def _read_transcription_meta(self, out_dir: str, stem: str) -> dict | None:
        path = self._transcription_meta_path(out_dir, stem)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _write_transcription_meta(
        self,
        out_dir: str,
        full_path: str,
        stem: str,
        dst_spanish: str,
        dst_english: str,
    ) -> None:
        payload = {
            "version": 1,
            "source_basename": os.path.basename(full_path.strip()),
            "source_full_path": os.path.abspath(full_path.strip()) if full_path else "",
            "stem": stem,
            "spanish_basename": os.path.basename(dst_spanish) if dst_spanish else "",
            "english_basename": os.path.basename(dst_english) if dst_english else "",
        }
        try:
            with open(self._transcription_meta_path(out_dir, stem), "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass

    def _review_display_name(self, out_dir: str, stem: str) -> str:
        """Label for Review UI: original source basename if sidecar exists, else stem."""
        meta = self._read_transcription_meta(out_dir, stem)
        if meta:
            sb = (meta.get("source_basename") or "").strip()
            if sb:
                return sb
        return stem

    def _archive_latest_outputs_for_job(self, full_path: str) -> dict:
        """
        mixbothtask.py writes fixed filenames in SCRIPT_DIR.
        After each successful run, move them into the output folder as
        <audio_stem>_transcription_spanish.txt / <audio_stem>_transcription_english.txt
        (overwrites prior runs with the same stem).
        """
        out_dir = self._get_output_folder()
        base = os.path.splitext(os.path.basename(full_path.strip()))[0]

        src_spanish = os.path.join(SCRIPT_DIR, OUTPUT_SPANISH_BASENAME)
        src_english = os.path.join(SCRIPT_DIR, OUTPUT_ENGLISH_BASENAME)

        dst_spanish = os.path.join(out_dir, f"{base}_transcription_spanish.txt")
        dst_english = os.path.join(out_dir, f"{base}_transcription_english.txt")

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

        if moved_any:
            self._write_transcription_meta(out_dir, full_path, base, dst_spanish, dst_english)

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
                job_out = (rec.get("output_folder") or "").strip() or out_dir
                fname = (rec.get("fname") or "").strip()
                if not fname:
                    fp = (rec.get("full_path") or "").strip()
                    fname = os.path.basename(fp) if fp else ""
                stem = ""
                sp = (rec.get("spanish_path") or "").strip()
                if sp:
                    bn = os.path.basename(sp)
                    if bn.endswith("_transcription_spanish.txt"):
                        stem = bn[: -len("_transcription_spanish.txt")]
                if not stem:
                    enp = (rec.get("english_path") or "").strip()
                    if enp:
                        bn = os.path.basename(enp)
                        if bn.endswith("_transcription_english.txt"):
                            stem = bn[: -len("_transcription_english.txt")]
                        elif bn.endswith("_translation_english.txt"):
                            stem = bn[: -len("_translation_english.txt")]
                if not fname and stem:
                    fname = self._review_display_name(job_out, stem)
                if not fname:
                    fname = stem or "—"
                items.append(
                    {
                        "label": fname,
                        "folder": job_out,
                        "audio_path": (rec.get("full_path") or "").strip(),
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
                # Group by audio stem: <stem>_transcription_spanish.txt / <stem>_transcription_english.txt
                if fn.endswith("_transcription_spanish.txt"):
                    key = fn[: -len("_transcription_spanish.txt")]
                    groups.setdefault(key, {})["spanish_path"] = full
                elif fn.endswith("_transcription_english.txt"):
                    key = fn[: -len("_transcription_english.txt")]
                    groups.setdefault(key, {})["english_path"] = full
                elif fn.endswith("_translation_english.txt"):
                    # Legacy GUI archive name (older builds)
                    key = fn[: -len("_translation_english.txt")]
                    groups.setdefault(key, {})["english_path"] = full
                groups.setdefault(key, {})["folder"] = out_dir
            for key, g in groups.items():
                if g.get("spanish_path") or g.get("english_path"):
                    # Try to recover original audio path from sidecar meta (when available).
                    meta = self._read_transcription_meta(out_dir, key)
                    ap = ""
                    if meta:
                        ap = str(meta.get("source_full_path") or "").strip()
                        if ap and not os.path.isfile(ap):
                            ap = ""
                    items.append(
                        {
                            "label": self._review_display_name(out_dir, key),
                            "folder": g.get("folder", out_dir),
                            "audio_path": ap,
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

        # Load audio for the selected Review item (if available).
        self._set_review_audio_source(it.get("audio_path", ""))

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

    def _update_table_row_status(self, row: int, status: str, pct: int | None = None):
        """Update status label + progress bar for a Home table row."""
        if not (0 <= row < self.table.rowCount()):
            return
        if pct is None:
            pct = 100 if status == "Complete" else 0
        col2 = self.table.cellWidget(row, 2)
        if col2 is not None:
            self._apply_home_status_bar_style(col2, status, pct)
        self._sync_jobs_status_cell_for_current_job(status, pct)
        self._sync_home_table_height()
        QTimer.singleShot(0, self._sync_home_table_height)