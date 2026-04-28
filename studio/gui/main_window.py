import json
import os
import re
import sys
import time
import keyring
from PySide6.QtCore import QPoint, Qt, QProcess, QSettings, QUrl, QSize, QProcessEnvironment, QTimer, QEvent
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QPainter,
    QPen,
    QMouseEvent,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
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
    QScrollBar,
)

from widgets import DropZone
from stylesheet import THEME_DARK, THEME_LIGHT, get_stylesheet
from nav_icons import (
    make_disclosure_chevron_icon,
    make_folder_open_icon,
    make_highlighter_icon,
    make_log_output_icon,
    make_nav_icon,
    make_open_external_icon,
    make_pencil_icon,
    make_remove_icon,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # QtMultimedia may be unavailable in some PySide6 builds
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]

# Path to studio_engine.py (project root, one level above this file).
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STUDIO_ENGINE_PATH = os.path.join(SCRIPT_DIR, "studio_engine.py")


def _resolve_engine_python():
    """Return the Python interpreter that should run studio_engine.py.

    Prefer the project's own virtualenv (``.venv`` next to studio_engine.py)
    because it is the only environment guaranteed to have the heavy ML deps
    (whisperx, torch, pyannote, etc.) installed. If that venv is missing —
    e.g. a fresh clone where the user hasn't run ``python -m venv .venv`` yet —
    fall back to whatever interpreter is currently running the GUI so we can
    surface a meaningful error instead of QProcess's opaque
    "execve: No such file or directory" message.
    """
    bin_name = "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    # Check studio/ dir first, then repo root (one level up) for .venv.
    for base in (SCRIPT_DIR, os.path.dirname(SCRIPT_DIR)):
        candidate = os.path.join(base, ".venv", bin_name)
        if os.path.isfile(candidate):
            return candidate
    return sys.executable

SETTINGS_ORG = "OfflineGUI"
SETTINGS_APP = "TopicModelingTranscription"

KEYRING_SERVICE = "OfflineGUI"
KEYRING_HF_USER = "huggingface_token"

KEY_THEME = "ui/theme"
KEY_OUTPUT_FOLDER = "jobs/output_folder"
KEY_DEFAULT_DIARIZATION = "jobs/default_diarization"
KEY_DEFAULT_NUM_SPEAKERS = "jobs/default_num_speakers"
KEY_DEFAULT_TIMESTAMPS = "jobs/default_timestamps"
# Legacy name kept for the persisted source-language default; the setting
# now answers "what language is the audio?" (Auto / English / Spanish).
# Paired with KEY_DEFAULT_OUTPUT_MODE for the translation on/off choice.
KEY_DEFAULT_TRANSLATION = "jobs/default_translation"
KEY_DEFAULT_OUTPUT_MODE = "jobs/default_output_mode"
KEY_AUTO_OPEN_OUTPUT = "jobs/auto_open_output_folder"
# Phase 2 advanced-settings defaults. Persisted so "last used" sticks
# between runs of the Job Options dialog.
KEY_DEFAULT_MODEL = "jobs/default_model"
KEY_DEFAULT_INITIAL_PROMPT = "jobs/default_initial_prompt"
KEY_DEFAULT_PREPROCESS = "jobs/default_preprocess"
KEY_DEFAULT_SPLIT_ON_SPEAKER = "jobs/default_split_on_speaker_change"

ENGINE_TRANSCRIPT_PREFIX = "transcription_"
ENGINE_TRANSLATION_PREFIX = "translation_"
# Sidecar next to archived transcripts: <stem>_job_meta.json. Named with a
# suffix that can't be matched by the `_transcription_` / `_translation_`
# markers used by _refresh_review_items so it's never mis-grouped.
TRANSCRIPTION_META_SUFFIX = "_job_meta.json"
# Legacy sidecar name; still read so older runs' audio-path / display-name
# metadata keeps loading. New writes go to TRANSCRIPTION_META_SUFFIX.
LEGACY_TRANSCRIPTION_META_SUFFIX = "_transcription_meta.json"
# Sidecar from studio_engine (per audio stem): <stem>_segments.json
REVIEW_SEGMENTS_SUFFIX = "_segments.json"
# Cap Review transcript preview lines so QTextBlock index stays aligned with segment index.
REVIEW_PREVIEW_MAX_LINES = 500

# Transcript line from studio_engine with --timestamps=segment, e.g.
# [00:00:03.200 → 00:00:07.800] [SPEAKER_00]: Hello
_TRANSCRIPT_SEGMENT_LINE_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2}\.\d{3})\s*→\s*(\d{2}):(\d{2}):(\d{2}\.\d{3})\]\s+\[([^\]]+)\]:\s*(.*)$"
)


def _hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h, 10) * 3600 + int(m, 10) * 60 + float(s)


# Home file table viewport: medium default, grow with real row/widget heights, cap then scroll.
HOME_TABLE_MIN_H = 260
HOME_TABLE_ABSOLUTE_MAX_PX = 720  # hard cap (rare); usual cap is available space below table top
HOME_TABLE_ROW_MIN_H = 58
# Home table: action column (folder + log + remove toolbuttons + padding).
# Three 22px buttons plus 6px spacing plus 4/8px side margins.
HOME_TABLE_FOLDER_COL_W = 136


class _HomeStatusTrack(QWidget):
    """Keeps status text in its own band above the bar and paints the label above the bar."""

    def __init__(self, status_label: QLabel, progress: QProgressBar, parent: QWidget | None = None):
        super().__init__(parent)
        self._lbl = status_label
        self._bar = progress
        self._gap_px = 4
        self._bar_h = 4
        status_label.setParent(self)
        progress.setParent(self)
        status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        lh = max(self._lbl.sizeHint().height(), self.fontMetrics().height())
        h = lh + self._gap_px + self._bar_h + 2
        return QSize(0, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, event) -> None:
        w = max(0, self.width())
        h = max(0, self.height())
        bh = min(self._bar_h, h)
        self._bar.setGeometry(0, h - bh, w, bh)
        top_h = max(0, h - bh - self._gap_px)
        self._lbl.setGeometry(0, 0, w, top_h)
        self._lbl.raise_()
        super().resizeEvent(event)


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

# Source-language picker: "what language is the audio in?". Paired with
# OUTPUT_MODE_OPTIONS below, which separately controls whether a
# translated file is written. The engine pairs es<->en automatically;
# "Auto" lets Whisper detect.
SOURCE_LANGUAGE_OPTIONS: list[str] = ["Auto", "English", "Spanish"]
SOURCE_LANGUAGE_TO_ISO: dict[str, str] = {
    "Auto": "auto",
    "English": "en",
    "Spanish": "es",
}

# Output mode: transcript only, or transcript + translation. Maps to the
# engine's --translate flag. "Original + translation" uses --translate
# auto so the engine picks the right MT engine for the resolved pair.
OUTPUT_MODE_OPTIONS: list[str] = ["Original only", "Original + translation"]
OUTPUT_MODE_TO_TRANSLATE_FLAG: dict[str, str] = {
    "Original only": "none",
    "Original + translation": "auto",
}
OUTPUT_MODE_DEFAULT = "Original + translation"

TIMESTAMP_MODE_OPTIONS: list[str] = ["No timestamps", "Per segment", "Per word"]

# Job Options: must match studio_engine.MAX_DIARIZATION_SPEAKERS (pyannote max).
MAX_JOB_NUM_SPEAKERS = 8
JOB_NUM_SPEAKERS_OPTIONS: list[str] = [str(i) for i in range(1, MAX_JOB_NUM_SPEAKERS + 1)]

# Phase 2 advanced settings. Options match studio_engine.py's CLI choices.
# MODEL_DEFAULT stays "small" to preserve the legacy latency/VRAM profile;
# users can bump to large-v3 via the Advanced block for higher quality.
MODEL_OPTIONS: list[str] = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
]
MODEL_DEFAULT = "small"

# "None" / "Normalize loudness" map to studio_engine's --preprocess flag
# values ("none" / "normalize"). The human labels are what the dropdown
# displays; PREPROCESS_LABEL_TO_FLAG resolves them back to the CLI value.
PREPROCESS_OPTIONS: list[str] = ["None", "Normalize loudness"]
PREPROCESS_LABEL_TO_FLAG: dict[str, str] = {
    "None": "none",
    "Normalize loudness": "normalize",
}
PREPROCESS_DEFAULT = "None"

# Human-readable labels for the engine's `[event] {"event":"stage", ...}`
# stream. Names match the call sites in studio_engine.py (`_emit_event`).
STAGE_LABELS: dict[str, str] = {
    "preprocess": "Preprocessing audio",
    "load_audio": "Loading audio",
    "load_asr": "Loading speech model",
    "transcribe": "Transcribing",
    "align": "Aligning words",
    "diarize": "Identifying speakers",
    "assign_speakers": "Assigning speakers",
    "split_on_speaker_change": "Splitting on speaker change",
    "translate_mt": "Translating",
    "write": "Writing output",
}

# Ordered (stage_name, pct) snapshots from studio_engine.py. Used to compute
# the next-stage cap so the tween glides toward the next real milestone
# instead of racing to a global 94% ceiling.
STAGE_ORDER: list[tuple[str, float]] = [
    ("preprocess", 0.02),
    ("load_audio", 0.05),
    ("load_asr", 0.10),
    ("transcribe", 0.20),
    ("align", 0.45),
    ("diarize", 0.60),
    ("assign_speakers", 0.70),
    ("split_on_speaker_change", 0.78),
    ("translate_mt", 0.85),
    ("write", 0.95),
]

# Default copy for the inline warning banner on the Home page. The banner is
# reused for duplicate-file notices, so the default is stored here and
# reapplied whenever the banner is shown without an explicit override.
HOME_WARNING_DEFAULT_TEXT = "Select a file from the table to start a job."


class JobOptionsDialog(QDialog):
    """Per-run options; styled like the rest of the app (chevron menus, not native combos)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("job-options-dialog")
        self.setWindowTitle("Job Options")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(380)

        theme = getattr(parent, "_theme", THEME_LIGHT) if parent else THEME_LIGHT
        chev_col = "#94a3b8" if theme == THEME_DARK else "#475569"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        self.diarization_checkbox = QCheckBox("Enable speaker diarization")
        self.diarization_checkbox.setObjectName("job-options-checkbox")
        self.diarization_checkbox.setChecked(True)

        spk_lbl = QLabel("Number of speakers:")
        spk_lbl.setObjectName("settings-label")
        (
            self.speaker_count_field,
            self.speaker_count_value_label,
            _,
        ) = self._make_chevron_dropdown(JOB_NUM_SPEAKERS_OPTIONS, "2", chev_col)

        self.diarization_checkbox.toggled.connect(self._sync_speaker_count_enabled)
        self._sync_speaker_count_enabled()

        src_lang_lbl = QLabel("Source language:")
        src_lang_lbl.setObjectName("settings-label")
        (
            self.source_language_field,
            self.source_language_value_label,
            _,
        ) = self._make_chevron_dropdown(SOURCE_LANGUAGE_OPTIONS, "Auto", chev_col)

        output_mode_lbl = QLabel("Output mode:")
        output_mode_lbl.setObjectName("settings-label")
        (
            self.output_mode_field,
            self.output_mode_value_label,
            _,
        ) = self._make_chevron_dropdown(
            OUTPUT_MODE_OPTIONS, OUTPUT_MODE_DEFAULT, chev_col
        )

        ts_lbl = QLabel("Timestamps:")
        ts_lbl.setObjectName("settings-label")
        self.timestamps_field, self.timestamps_value_label, _ = self._make_chevron_dropdown(
            TIMESTAMP_MODE_OPTIONS, "No timestamps", chev_col
        )
        _ts_tip = (
            "Controls whether timestamps appear in the exported .txt files. "
            "Segment timing is always saved for Review (sidecar JSON) and audio sync."
        )
        self.timestamps_field.setToolTip(_ts_tip)
        ts_lbl.setToolTip(_ts_tip)

        # Advanced settings section. Collapsed by default so the dialog
        # stays compact for the common case; users who care about the
        # Phase 2 levers (model size, vocab prompt, loudness preprocess,
        # speaker-change splitting) expand it explicitly.
        self._advanced_chev_color = chev_col
        self.advanced_toggle_btn = QToolButton()
        self.advanced_toggle_btn.setObjectName("job-options-advanced-toggle")
        self.advanced_toggle_btn.setText("Advanced settings")
        self.advanced_toggle_btn.setCheckable(True)
        self.advanced_toggle_btn.setChecked(False)
        self.advanced_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced_toggle_btn.setAutoRaise(True)
        self.advanced_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.advanced_toggle_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle_btn.setIconSize(QSize(18, 18))
        self.advanced_toggle_btn.setIcon(
            make_disclosure_chevron_icon(
                expanded=False, size=18, color_hex=chev_col
            )
        )
        self.advanced_toggle_btn.toggled.connect(self._on_advanced_toggled)

        self.advanced_container = QFrame()
        self.advanced_container.setObjectName("job-options-advanced-container")
        self.advanced_container.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        adv_lay = QVBoxLayout(self.advanced_container)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(10)

        model_lbl = QLabel("Model:")
        model_lbl.setObjectName("settings-label")
        (
            self.model_field,
            self.model_value_label,
            _,
        ) = self._make_chevron_dropdown(MODEL_OPTIONS, MODEL_DEFAULT, chev_col)

        prompt_lbl = QLabel("Initial prompt (names, jargon, acronyms):")
        prompt_lbl.setObjectName("settings-label")
        self.initial_prompt_edit = QPlainTextEdit()
        self.initial_prompt_edit.setObjectName("settings-input")
        # Short placeholder: the `#settings-input` stylesheet adds 7px
        # padding top+bottom, so anything longer than a single wrapped
        # line gets clipped at the default widget height. The label
        # above already explains what the field is for.
        self.initial_prompt_edit.setPlaceholderText(
            "Optional domain vocabulary"
        )
        # Word-wrap so pasted vocab lists don't run off the right edge,
        # and use a minimum (not fixed) height so longer content grows
        # the widget within the dialog instead of getting cut off.
        self.initial_prompt_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.initial_prompt_edit.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.initial_prompt_edit.setMinimumHeight(88)

        preprocess_lbl = QLabel("Audio preprocessing:")
        preprocess_lbl.setObjectName("settings-label")
        (
            self.preprocess_field,
            self.preprocess_value_label,
            _,
        ) = self._make_chevron_dropdown(
            PREPROCESS_OPTIONS, PREPROCESS_DEFAULT, chev_col
        )

        self.split_on_speaker_checkbox = QCheckBox(
            "Split lines when speaker changes mid-segment"
        )
        self.split_on_speaker_checkbox.setObjectName("job-options-checkbox")
        self.split_on_speaker_checkbox.setChecked(False)

        adv_lay.addWidget(model_lbl)
        adv_lay.addWidget(self.model_field)
        adv_lay.addWidget(prompt_lbl)
        adv_lay.addWidget(self.initial_prompt_edit)
        adv_lay.addWidget(preprocess_lbl)
        adv_lay.addWidget(self.preprocess_field)
        adv_lay.addWidget(self.split_on_speaker_checkbox)

        self.advanced_container.setVisible(False)

        outer.addWidget(self.diarization_checkbox)
        outer.addWidget(spk_lbl)
        outer.addWidget(self.speaker_count_field)
        outer.addWidget(src_lang_lbl)
        outer.addWidget(self.source_language_field)
        outer.addWidget(output_mode_lbl)
        outer.addWidget(self.output_mode_field)
        outer.addWidget(ts_lbl)
        outer.addWidget(self.timestamps_field)
        outer.addSpacing(4)
        outer.addWidget(self.advanced_toggle_btn, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self.advanced_container)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("add-btn")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Confirm")
        ok_btn.setObjectName("start-btn")
        ok_btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ok_btn.setDefault(True)
        ok_btn.setAutoDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn, 0)
        btn_row.addWidget(ok_btn, 0)
        outer.addLayout(btn_row)

    def _make_chevron_dropdown(
        self, options: list[str], initial: str, chev_color: str
    ) -> tuple[QFrame, QLabel, QMenu]:
        initial = initial if initial in options else options[0]
        field = QFrame()
        field.setObjectName("job-options-dropdown-field")
        field.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QHBoxLayout(field)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        val = QLabel(initial)
        val.setObjectName("settings-dropdown-value")
        val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        val.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        chev = QToolButton()
        chev.setObjectName("settings-chevron-btn")
        chev.setCursor(Qt.CursorShape.PointingHandCursor)
        chev.setAutoRaise(True)
        chev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chev.setFixedSize(24, 24)
        icon_sz = 18
        chev.setIcon(make_disclosure_chevron_icon(expanded=True, size=icon_sz, color_hex=chev_color))
        chev.setIconSize(QSize(icon_sz, icon_sz))

        menu = QMenu(self)
        menu.setObjectName("settings-translation-menu")
        for opt in options:
            act = menu.addAction(opt)
            act.setData(opt)

        def _pick(a) -> None:
            val.setText(str(a.data()))

        def _open() -> None:
            pos = field.mapToGlobal(QPoint(0, field.height()))
            menu.setFixedWidth(field.width())
            menu.popup(pos)

        menu.triggered.connect(_pick)
        chev.clicked.connect(_open)

        lay.addWidget(val, 1)
        lay.addWidget(chev, 0, Qt.AlignmentFlag.AlignRight)
        return field, val, menu

    def _sync_speaker_count_enabled(self):
        self.speaker_count_field.setEnabled(self.diarization_checkbox.isChecked())

    def _on_advanced_toggled(self, checked: bool) -> None:
        """Show/hide the Advanced settings block and flip the chevron icon.

        The dialog resizes itself to fit the new content so the section
        genuinely collapses out of sight instead of leaving dead space.
        """
        self.advanced_container.setVisible(bool(checked))
        self.advanced_toggle_btn.setIcon(
            make_disclosure_chevron_icon(
                expanded=bool(checked),
                size=18,
                color_hex=self._advanced_chev_color,
            )
        )
        self.adjustSize()


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
        self._review_segments: list[dict] = []
        self._review_sync_line_count: int = 0
        self._review_highlight_idx: int | None = None
        self._review_highlight_translation: bool = False
        self._review_highlight_enabled: bool = True
        self._review_transcript_path: str = ""
        self._review_translation_path: str = ""
        # When *_segments.json is missing, build equal-length slices after media duration is known.
        self._review_fallback_tx_lines: int = 0
        # Output folders we have already attempted legacy-filename migration
        # on this session. Keyed by canonicalized absolute path.
        self._migrated_output_dirs: set[str] = set()
        self._current_job_row: int | None = None
        self._current_fname: str | None = None
        self._estimated_progress_pct: float = 0.0
        self._estimated_progress_row: int | None = None
        self._estimated_progress_target: float = 94.0
        self._estimated_status: str = "Processing"
        # Last `done` payload from studio_engine.py (carries resolved
        # src_lang/tgt_lang and exact transcript_file/translation_file
        # paths). Read by _archive_latest_outputs_for_job, then cleared at
        # the start of the next job by _reset_home_row_for_new_job.
        self._last_done_event: dict | None = None
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

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def closeEvent(self, event):
        # Terminate the engine subprocess if a job is still running so the
        # heavy ML models don't keep consuming CPU/GPU after the window
        # closes. terminate() sends SIGTERM; kill() is the SIGKILL fallback
        # for engines that don't respond quickly during model load.
        proc = self._job_process
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            proc.terminate()
            if not proc.waitForFinished(3000):
                proc.kill()
                proc.waitForFinished(1000)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event) -> bool:
        """On Home, clear file-table selection when clicking outside a row (not only the duration cell)."""
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().eventFilter(watched, event)
        if not isinstance(event, QMouseEvent):
            return super().eventFilter(watched, event)
        if event.button() != Qt.MouseButton.LeftButton:
            return super().eventFilter(watched, event)
        if getattr(self, "_current_page", "") != "home":
            return super().eventFilter(watched, event)
        table = getattr(self, "table", None)
        if table is None:
            return super().eventFilter(watched, event)
        pos = event.globalPosition().toPoint()
        w = QApplication.widgetAt(pos)
        if w is None:
            return super().eventFilter(watched, event)
        start_btn = getattr(self, "_home_start_btn", None)
        if start_btn is not None and (w is start_btn or start_btn.isAncestorOf(w)):
            return super().eventFilter(watched, event)
        if table.isAncestorOf(w):
            if isinstance(w, QScrollBar):
                return super().eventFilter(watched, event)
            vp = table.viewport()
            local = vp.mapFromGlobal(pos)
            if table.indexAt(local).isValid():
                return super().eventFilter(watched, event)
            table.clearSelection()
            self._sync_home_row_selection_styles()
            return super().eventFilter(watched, event)
        table.clearSelection()
        self._sync_home_row_selection_styles()
        return super().eventFilter(watched, event)

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
        self._refresh_review_page_action_icons()
        self._refresh_home_log_disclosure_icons()
        self._refresh_home_remove_row_icons()
        self._refresh_settings_disclosure_icons()
        QTimer.singleShot(0, self._sync_home_row_selection_styles)
        if hasattr(self, "spanish_preview"):
            prev = self._review_highlight_idx
            self._review_highlight_idx = None
            if prev is not None:
                self._apply_review_segment_highlight(prev)
            elif self._review_player is not None and self._review_segments:
                self._sync_review_highlight_from_time_ms(int(self._review_player.position()))

    def _refresh_settings_disclosure_icons(self) -> None:
        """Update Settings chevron icons when theme changes."""
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18
        for attr in (
            "default_source_language_chevron_btn",
            "default_output_mode_chevron_btn",
        ):
            btn = getattr(self, attr, None)
            if btn is None:
                continue
            btn.setIcon(
                make_disclosure_chevron_icon(
                    expanded=True, size=icon_sz, color_hex=col
                )
            )
            btn.setIconSize(QSize(icon_sz, icon_sz))

    def _refresh_nav_icons(self):
        if not self._nav_buttons:
            return
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        active = "#ffffff"
        icon_sz = 22
        for pid, btn in self._nav_buttons.items():
            color = active if pid == self._current_page else inactive
            btn.setIcon(make_nav_icon(pid, size=icon_sz, color_hex=color))
            btn.setIconSize(QSize(icon_sz, icon_sz))

    def _refresh_home_folder_row_icons(self) -> None:
        """Match Home table folder action icons to sidebar stroke style / inactive nav color."""
        if not hasattr(self, "table"):
            return
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18
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
        icon_sz = 18
        for r in range(self.jobs_table.rowCount()):
            w = self.jobs_table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "jobs-row-open-btn":
                    btn.setIcon(make_folder_open_icon(size=icon_sz, color_hex=inactive))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

    def _refresh_review_page_action_icons(self) -> None:
        """Review header actions: folder + open-file icons (same stroke family as Home/Jobs)."""
        inactive = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18
        sz = QSize(icon_sz, icon_sz)
        folder_btn = getattr(self, "review_open_folder_btn", None)
        if folder_btn is not None:
            folder_btn.setIcon(make_folder_open_icon(size=icon_sz, color_hex=inactive))
            folder_btn.setIconSize(sz)
        for attr in ("review_open_transcript_btn", "review_open_translation_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setIcon(make_open_external_icon(size=icon_sz, color_hex=inactive))
                btn.setIconSize(sz)

    def _refresh_home_log_disclosure_icons(self) -> None:
        """Update Home action-column log/document icons when theme changes (stroke color)."""
        if not hasattr(self, "table"):
            return
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "home-row-log-btn":
                    btn.setIcon(make_log_output_icon(size=icon_sz, color_hex=col))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

    def _refresh_home_remove_row_icons(self) -> None:
        """Update Home action-column remove-from-list icons on theme change."""
        if not hasattr(self, "table"):
            return
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 3)
            if w is None:
                continue
            for btn in w.findChildren(QToolButton):
                if btn.objectName() == "home-row-remove-btn":
                    btn.setIcon(make_remove_icon(size=icon_sz, color_hex=col))
                    btn.setIconSize(QSize(icon_sz, icon_sz))
                    break

    def _get_output_folder(self) -> str:
        """Return output folder; create a sensible default if unset.

        Does NOT persist the fallback default into QSettings — that made
        "never configured" and "explicitly cleared" indistinguishable and
        left a stale absolute path behind when the project was moved. The
        setting stays blank until the user explicitly chooses a folder in
        Settings; the computed fallback is returned in-memory only.
        """
        saved = self._settings().value(KEY_OUTPUT_FOLDER, "")
        if isinstance(saved, str) and saved.strip():
            path = saved.strip()
        else:
            path = os.path.join(SCRIPT_DIR, "outputs")
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
        logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        logo.setIndent(0)
        logo.setContentsMargins(0, 0, 0, 0)
        logo.setAutoFillBackground(False)
        logo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sub = QLabel("Offline Tool")
        sub.setObjectName("sidebar-sub")
        sub.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        sub.setIndent(0)
        sub.setContentsMargins(0, 0, 0, 0)
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

        # Inline warning banner. Used for both the "no selection" hint and
        # duplicate-file notices; text is swapped per call via _show_home_warning.
        self._home_warning = QLabel(HOME_WARNING_DEFAULT_TEXT)
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
        start_btn.setEnabled(False)
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
        # Match Home: a stretchy Status column reads better than ResizeToContents (narrow bar + offset text).
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(self.jobs_table)
        self._jobs_empty_label = QLabel("No jobs yet\nGo to Home to add audio files")
        self._jobs_empty_label.setObjectName("page-sub")
        self._jobs_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._jobs_empty_label.setMinimumHeight(200)
        card_layout.addWidget(self._jobs_empty_label)
        self._jobs_recent_section = section

        layout.addWidget(card)
        layout.addStretch()
        self._sync_jobs_empty_state()
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
        _review_folder_muted = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        self.review_open_folder_btn = QToolButton()
        self.review_open_folder_btn.setObjectName("review-open-folder-btn")
        self.review_open_folder_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.review_open_folder_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_open_folder_btn.setIcon(
            make_folder_open_icon(size=18, color_hex=_review_folder_muted)
        )
        self.review_open_folder_btn.setIconSize(QSize(18, 18))
        self.review_open_folder_btn.setFixedSize(22, 22)
        self.review_open_folder_btn.setToolTip("Open containing folder")
        self.review_open_folder_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_open_folder_btn.setAutoRaise(True)
        self.review_open_folder_btn.clicked.connect(self._open_review_folder)
        selector_row.addWidget(self.review_open_folder_btn, 0, Qt.AlignmentFlag.AlignVCenter)
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
        self.review_play_btn.setIconSize(QSize(20, 20))
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

        _sync_muted_col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        _sync_active_col = "#3b82f6"

        self.review_sync_btn = QToolButton()
        self.review_sync_btn.setObjectName("review-sync-btn")
        self.review_sync_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_sync_btn.setIcon(make_highlighter_icon(size=18, color_hex=_sync_active_col))
        self.review_sync_btn.setIconSize(QSize(18, 18))
        self.review_sync_btn.setToolTip("Highlight text as audio plays")
        self.review_sync_btn.setCheckable(True)
        self.review_sync_btn.setChecked(True)
        self.review_sync_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_sync_btn.setAutoRaise(True)
        self.review_sync_btn.setFixedSize(22, 22)

        def _on_sync_toggled(checked: bool) -> None:
            self._review_highlight_enabled = checked
            self.review_sync_btn.setIcon(
                make_highlighter_icon(
                    size=18, color_hex=_sync_active_col if checked else _sync_muted_col
                )
            )
            if not checked:
                self._apply_review_segment_highlight(None)
            else:
                pos = int(self._review_player.position()) if self._review_player is not None else 0
                self._sync_review_highlight_from_time_ms(pos)

        self.review_sync_btn.toggled.connect(_on_sync_toggled)

        player_layout.addWidget(self.review_play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_seek, 1, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_time_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        player_layout.addWidget(self.review_sync_btn, 0, Qt.AlignmentFlag.AlignVCenter)
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
        left_header = QWidget()
        left_header_lay = QHBoxLayout(left_header)
        left_header_lay.setContentsMargins(0, 0, 0, 0)
        left_header_lay.setSpacing(8)
        left_title = QLabel("Transcription output")
        left_title.setObjectName("section-title")
        _review_file_muted = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        self.review_open_transcript_btn = QToolButton()
        self.review_open_transcript_btn.setObjectName("review-open-transcript-btn")
        self.review_open_transcript_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.review_open_transcript_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_open_transcript_btn.setIcon(
            make_open_external_icon(size=18, color_hex=_review_file_muted)
        )
        self.review_open_transcript_btn.setIconSize(QSize(18, 18))
        self.review_open_transcript_btn.setFixedSize(22, 22)
        self.review_open_transcript_btn.setToolTip("Open transcription file")
        self.review_open_transcript_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_open_transcript_btn.setAutoRaise(True)
        self.review_open_transcript_btn.clicked.connect(
            lambda: self._open_review_file(which="spanish")
        )
        self.review_edit_transcript_btn = QToolButton()
        self.review_edit_transcript_btn.setObjectName("review-edit-transcript-btn")
        self.review_edit_transcript_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.review_edit_transcript_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_edit_transcript_btn.setIcon(make_pencil_icon(size=18, color_hex=_review_file_muted))
        self.review_edit_transcript_btn.setIconSize(QSize(18, 18))
        self.review_edit_transcript_btn.setFixedSize(22, 22)
        self.review_edit_transcript_btn.setToolTip("Edit transcription")
        self.review_edit_transcript_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_edit_transcript_btn.setAutoRaise(True)
        self.review_edit_transcript_btn.setCheckable(True)

        def _on_transcript_edit_toggled(checked: bool) -> None:
            self.review_edit_transcript_btn.setIcon(
                make_pencil_icon(size=18, color_hex=_sync_active_col if checked else _review_file_muted)
            )
            if checked:
                self.spanish_preview.setReadOnly(False)
            else:
                self.spanish_preview.setReadOnly(True)
                path = self._review_transcript_path
                if path:
                    try:
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(self.spanish_preview.toPlainText())
                    except OSError:
                        pass

        self.review_edit_transcript_btn.toggled.connect(_on_transcript_edit_toggled)

        left_header_lay.addWidget(left_title, 1, Qt.AlignmentFlag.AlignVCenter)
        left_header_lay.addWidget(self.review_edit_transcript_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        left_header_lay.addWidget(self.review_open_transcript_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        left_layout.addWidget(left_header)
        self.spanish_preview = QTextEdit()
        self.spanish_preview.setObjectName("review-preview")
        self.spanish_preview.setReadOnly(True)
        left_layout.addWidget(self.spanish_preview, stretch=1)

        right = QFrame()
        right.setObjectName("settings-card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)
        right_header = QWidget()
        right_header_lay = QHBoxLayout(right_header)
        right_header_lay.setContentsMargins(0, 0, 0, 0)
        right_header_lay.setSpacing(8)
        right_title = QLabel("Translation output")
        right_title.setObjectName("section-title")
        self.review_open_translation_btn = QToolButton()
        self.review_open_translation_btn.setObjectName("review-open-translation-btn")
        self.review_open_translation_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.review_open_translation_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_open_translation_btn.setIcon(
            make_open_external_icon(size=18, color_hex=_review_file_muted)
        )
        self.review_open_translation_btn.setIconSize(QSize(18, 18))
        self.review_open_translation_btn.setFixedSize(22, 22)
        self.review_open_translation_btn.setToolTip("Open translation file")
        self.review_open_translation_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_open_translation_btn.setAutoRaise(True)
        self.review_open_translation_btn.clicked.connect(
            lambda: self._open_review_file(which="english")
        )
        self.review_edit_translation_btn = QToolButton()
        self.review_edit_translation_btn.setObjectName("review-edit-translation-btn")
        self.review_edit_translation_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.review_edit_translation_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.review_edit_translation_btn.setIcon(make_pencil_icon(size=18, color_hex=_review_file_muted))
        self.review_edit_translation_btn.setIconSize(QSize(18, 18))
        self.review_edit_translation_btn.setFixedSize(22, 22)
        self.review_edit_translation_btn.setToolTip("Edit translation")
        self.review_edit_translation_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review_edit_translation_btn.setAutoRaise(True)
        self.review_edit_translation_btn.setCheckable(True)

        def _on_translation_edit_toggled(checked: bool) -> None:
            self.review_edit_translation_btn.setIcon(
                make_pencil_icon(size=18, color_hex=_sync_active_col if checked else _review_file_muted)
            )
            if checked:
                self.english_preview.setReadOnly(False)
            else:
                self.english_preview.setReadOnly(True)
                path = self._review_translation_path
                if path:
                    try:
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(self.english_preview.toPlainText())
                    except OSError:
                        pass

        self.review_edit_translation_btn.toggled.connect(_on_translation_edit_toggled)

        right_header_lay.addWidget(right_title, 1, Qt.AlignmentFlag.AlignVCenter)
        right_header_lay.addWidget(self.review_edit_translation_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right_header_lay.addWidget(self.review_open_translation_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(right_header)
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
        if getattr(self, "_review_fallback_tx_lines", 0) > 0 and not self._review_segments:
            self._try_build_uniform_review_segments(self._review_fallback_tx_lines, int(dur_ms))
            if self._review_segments:
                self._review_fallback_tx_lines = 0
                left_bc = self.spanish_preview.document().blockCount()
                if self._review_highlight_translation:
                    right_bc = self.english_preview.document().blockCount()
                    self._review_sync_line_count = min(
                        self._review_sync_line_count, left_bc, right_bc, len(self._review_segments)
                    )
                else:
                    self._review_sync_line_count = min(
                        self._review_sync_line_count, left_bc, len(self._review_segments)
                    )
                if self._review_highlight_enabled:
                    self._sync_review_highlight_from_time_ms(pos)

    def _on_review_media_position(self, pos_ms: int):
        if not self.review_seek.isDragging():
            self.review_seek.setValue(max(0, int(pos_ms)))
        dur = 0 if self._review_player is None else int(self._review_player.duration())
        self.review_time_lbl.setText(f"{self._format_ms(pos_ms)} / {self._format_ms(dur)}")
        if self._review_highlight_enabled:
            self._sync_review_highlight_from_time_ms(int(pos_ms))

    def _on_review_seek_preview(self, pos_ms: int):
        dur = 0 if self._review_player is None else int(self._review_player.duration())
        self.review_time_lbl.setText(f"{self._format_ms(pos_ms)} / {self._format_ms(dur)}")
        self._sync_review_highlight_from_time_ms(int(pos_ms))

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
            form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
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

        # ── Appearance card ──────────────────────────────────────────────────
        appearance_card, appearance_layout = _make_card("Appearance")
        appearance_body = QWidget()
        appearance_form = _make_form(appearance_body)

        self.dark_mode_checkbox = QCheckBox("Enable dark mode")
        self.dark_mode_checkbox.setObjectName("theme-toggle")
        theme = self._settings().value(KEY_THEME, THEME_LIGHT)
        self.dark_mode_checkbox.setChecked(theme == THEME_DARK)
        self.dark_mode_checkbox.toggled.connect(self._on_dark_mode_toggled)
        dark_mode_row = QWidget()
        dark_mode_lay = QHBoxLayout(dark_mode_row)
        dark_mode_lay.setContentsMargins(0, 0, 0, 0)
        dark_mode_lay.setSpacing(0)
        dark_mode_lay.addWidget(self.dark_mode_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        dark_mode_lay.addStretch(1)
        appearance_form.addRow(_make_label(""), dark_mode_row)

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
        dia_lay.setContentsMargins(0, 0, 0, 0)
        dia_lay.setSpacing(0)
        dia_lay.addWidget(self.default_diarization_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        dia_lay.addStretch(1)
        defaults_form.addRow(_make_label(""), dia_row)

        self.default_speaker_spin = QSpinBox()
        self.default_speaker_spin.setObjectName("settings-input")
        self.default_speaker_spin.setRange(1, MAX_JOB_NUM_SPEAKERS)
        self.default_speaker_spin.setValue(
            max(
                1,
                min(
                    MAX_JOB_NUM_SPEAKERS,
                    int(self._settings().value(KEY_DEFAULT_NUM_SPEAKERS, 2, type=int)),
                ),
            )
        )
        self.default_speaker_spin.setFixedWidth(_SETTINGS_FIELD_MIN_W)
        self.default_speaker_spin.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self.default_speaker_spin.valueChanged.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_NUM_SPEAKERS, int(v))
        )
        self.default_speaker_spin.setEnabled(self.default_diarization_checkbox.isChecked())
        defaults_form.addRow(_make_label("Default number of speakers:"), self.default_speaker_spin)

        # Source language + Output mode are two independent concerns:
        #   * Source language answers "what language is the audio?" and maps
        #     to studio_engine.py's --language flag (auto/en/es).
        #   * Output mode answers "do we also write a translated file?" and
        #     maps to --translate (none vs auto). The engine auto-pairs
        #     es<->en when translation is on.
        #
        # Both dropdowns share the same chevron styling; the tiny helper
        # below keeps their construction in one place so layout stays
        # consistent and the diff stays small.
        col = "#94a3b8" if self._theme == THEME_DARK else "#475569"
        icon_sz = 18

        def _make_settings_chevron_dropdown(
            options: list[str],
            current: str,
            menu_object_name: str,
            on_pick,
        ) -> tuple[QFrame, QLabel, QToolButton, QMenu]:
            field = QFrame()
            field.setObjectName("settings-input")
            field.setFixedWidth(_SETTINGS_FIELD_MIN_W)
            field.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
            )
            lay = QHBoxLayout(field)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            value_lbl = QLabel(current)
            value_lbl.setObjectName("settings-dropdown-value")
            value_lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            value_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            value_lbl.setAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )

            chevron = QToolButton()
            chevron.setObjectName("settings-chevron-btn")
            chevron.setCursor(Qt.CursorShape.PointingHandCursor)
            chevron.setAutoRaise(True)
            chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chevron.setFixedSize(24, 24)
            chevron.setIcon(
                make_disclosure_chevron_icon(
                    expanded=True, size=icon_sz, color_hex=col
                )
            )
            chevron.setIconSize(QSize(icon_sz, icon_sz))

            menu = QMenu(self)
            menu.setObjectName(menu_object_name)
            for opt in options:
                act = menu.addAction(opt)
                act.setData(opt)

            def _popup() -> None:
                pos = field.mapToGlobal(QPoint(0, field.height()))
                menu.setFixedWidth(field.width())
                menu.popup(pos)

            menu.triggered.connect(
                lambda a, _lbl=value_lbl, _cb=on_pick: (
                    _lbl.setText(str(a.data())),
                    _cb(str(a.data())),
                )
            )
            chevron.clicked.connect(_popup)

            lay.addWidget(value_lbl, 1)
            lay.addWidget(chevron, 0, Qt.AlignmentFlag.AlignRight)
            return field, value_lbl, chevron, menu

        # Source language dropdown.
        self.default_source_language_options = list(SOURCE_LANGUAGE_OPTIONS)
        current_source_language = str(
            self._settings().value(KEY_DEFAULT_TRANSLATION, "Auto")
        )
        if current_source_language not in self.default_source_language_options:
            current_source_language = "Auto"

        (
            source_language_field,
            self.default_source_language_value,
            self.default_source_language_chevron_btn,
            self.default_source_language_menu,
        ) = _make_settings_chevron_dropdown(
            self.default_source_language_options,
            current_source_language,
            "settings-translation-menu",
            lambda text: self._settings().setValue(KEY_DEFAULT_TRANSLATION, str(text)),
        )
        defaults_form.addRow(_make_label("Source language:"), source_language_field)

        # Back-compat aliases: earlier code referenced `default_translation_*`.
        self.default_translation_options = self.default_source_language_options
        self.default_translation_value = self.default_source_language_value
        self.default_translation_chevron_btn = self.default_source_language_chevron_btn
        self.default_translation_menu = self.default_source_language_menu

        # Output mode dropdown.
        self.default_output_mode_options = list(OUTPUT_MODE_OPTIONS)
        current_output_mode = str(
            self._settings().value(KEY_DEFAULT_OUTPUT_MODE, OUTPUT_MODE_DEFAULT)
        )
        if current_output_mode not in self.default_output_mode_options:
            current_output_mode = OUTPUT_MODE_DEFAULT

        (
            output_mode_field,
            self.default_output_mode_value,
            self.default_output_mode_chevron_btn,
            self.default_output_mode_menu,
        ) = _make_settings_chevron_dropdown(
            self.default_output_mode_options,
            current_output_mode,
            "settings-output-mode-menu",
            lambda text: self._settings().setValue(KEY_DEFAULT_OUTPUT_MODE, str(text)),
        )
        defaults_form.addRow(_make_label("Output mode:"), output_mode_field)

        # Default model dropdown.
        self.default_model_options = list(MODEL_OPTIONS)
        current_model = str(
            self._settings().value(KEY_DEFAULT_MODEL, MODEL_DEFAULT)
        )
        if current_model not in self.default_model_options:
            current_model = MODEL_DEFAULT

        (
            model_field,
            self.default_model_value,
            self.default_model_chevron_btn,
            self.default_model_menu,
        ) = _make_settings_chevron_dropdown(
            self.default_model_options,
            current_model,
            "settings-model-menu",
            lambda text: self._settings().setValue(KEY_DEFAULT_MODEL, str(text)),
        )
        defaults_form.addRow(_make_label("Default model:"), model_field)

        # Label in the form column + checkbox avoids long caption clipping in QCheckBox.
        self.default_timestamps_checkbox = QCheckBox("Include timestamps in output")
        self.default_timestamps_checkbox.setAccessibleName("Timestamps")
        self.default_timestamps_checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.default_timestamps_checkbox.setToolTip(
            "When enabled, new jobs default to per-segment timestamps in the exported .txt. "
            "Timing for the Review page is always stored in the segment sidecar, independent of this."
        )
        self.default_timestamps_checkbox.setChecked(
            bool(self._settings().value(KEY_DEFAULT_TIMESTAMPS, True, type=bool))
        )
        self.default_timestamps_checkbox.toggled.connect(
            lambda v: self._settings().setValue(KEY_DEFAULT_TIMESTAMPS, bool(v))
        )
        ts_label = _make_label("Timestamps:")
        ts_label.setToolTip(self.default_timestamps_checkbox.toolTip())
        ts_label.setBuddy(self.default_timestamps_checkbox)
        ts_row = QWidget()
        ts_lay = QHBoxLayout(ts_row)
        ts_lay.setContentsMargins(0, 0, 0, 0)
        ts_lay.setSpacing(0)
        ts_lay.addWidget(self.default_timestamps_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        ts_lay.addStretch(1)
        defaults_form.addRow(ts_label, ts_row)

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
        auto_open_lay.setContentsMargins(0, 0, 0, 0)
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

        hf_link_color = "#4ea1f3" if getattr(self, "_theme", THEME_DARK) == THEME_DARK else "#2563eb"
        hf_link = QLabel(f'<a href="https://huggingface.co/settings/tokens" style="color:{hf_link_color};">Get a Hugging Face token</a>')
        hf_link.setObjectName("settings-hint")
        hf_link.setOpenExternalLinks(True)

        hf_hint_row = QWidget()
        hf_hint_layout = QHBoxLayout(hf_hint_row)
        hf_hint_layout.setContentsMargins(0, 0, 0, 0)
        hf_hint_layout.setSpacing(12)
        hf_hint_layout.addWidget(hf_note)
        hf_hint_layout.addWidget(hf_link)
        hf_hint_layout.addStretch()

        integration_form.addRow(_make_label(""), hf_hint_row)

        integration_layout.addWidget(integration_body)
        layout.addWidget(integration_card)

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

    def _find_table_row_for_path(self, full_path: str) -> int:
        """Return the Home-table row index whose stored path matches `full_path`,
        or -1 if no row is a match. Comparison uses the same canonical form
        (`abspath` + `normpath` + `normcase`) as `_remove_existing_job_records_for_file`.
        """
        tgt = self._canonical_file_path(full_path)
        if not tgt:
            return -1
        for r in range(self.table.rowCount()):
            if self._canonical_file_path(self._path_for_row(r)) == tgt:
                return r
        return -1

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
        self._last_done_event = None
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
            expand_btn.setIcon(make_log_output_icon(size=18, color_hex=col))
            expand_btn.setIconSize(QSize(18, 18))
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

    def _remove_home_row_by_path_key(self, path_key: str) -> None:
        """Remove a single row from the Home queue. Does NOT touch the audio
        file on disk. Silently refuses if the row is the actively-running job,
        surfacing a banner instead — cancel/stop is a separate, future action.
        """
        if not hasattr(self, "table"):
            return
        tgt = self._canonical_file_path(path_key)
        if not tgt:
            return
        target_row = -1
        for r in range(self.table.rowCount()):
            if self._canonical_file_path(self._path_for_row(r)) == tgt:
                target_row = r
                break
        if target_row < 0:
            return

        if (
            self._job_process is not None
            and self._current_job_row is not None
            and self._current_job_row == target_row
        ):
            self._show_home_warning(
                True, text="Can't remove this file while its job is running."
            )
            return

        self.table.removeRow(target_row)
        if hasattr(self, "_home_start_btn"):
            self._home_start_btn.setEnabled(self.table.rowCount() > 0)

        # Removing a row above the active job shifts the active row index
        # down by one; keep _current_job_row / _estimated_progress_row
        # pointing at the same physical row so progress updates don't drift.
        if (
            self._current_job_row is not None
            and target_row < self._current_job_row
        ):
            self._current_job_row -= 1
        if (
            self._estimated_progress_row is not None
            and target_row < self._estimated_progress_row
        ):
            self._estimated_progress_row -= 1

        self._show_home_warning(False)
        self._sync_home_table_height()
        QTimer.singleShot(0, self._sync_home_table_height)
        QTimer.singleShot(0, self._sync_home_row_selection_styles)

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
        track = getattr(col2, "_status_track", None)
        if track is not None:
            track.updateGeometry()
            track.update()

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
        btn.setIcon(make_folder_open_icon(size=18, color_hex=_folder_muted))
        btn.setIconSize(QSize(18, 18))
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
        btn.setIcon(make_folder_open_icon(size=18, color_hex=_muted))
        btn.setIconSize(QSize(18, 18))
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
        log_btn.setIcon(make_log_output_icon(size=18, color_hex=_muted))
        log_btn.setIconSize(QSize(18, 18))
        log_btn.setFixedSize(22, 22)
        log_btn.setToolTip("Show or hide log for this file")
        log_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_btn.setAutoRaise(True)
        filename_cell._expand_btn = log_btn  # type: ignore[attr-defined]
        log_btn.toggled.connect(lambda on, o=filename_cell: self._toggle_log_visibility(o, on))

        remove_btn = QToolButton()
        remove_btn.setObjectName("home-row-remove-btn")
        remove_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        remove_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        remove_btn.setIcon(make_remove_icon(size=18, color_hex=_muted))
        remove_btn.setIconSize(QSize(18, 18))
        remove_btn.setFixedSize(22, 22)
        remove_btn.setToolTip("Remove from list")
        remove_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remove_btn.setAutoRaise(True)
        remove_btn.clicked.connect(
            lambda _=False, p=pk: self._remove_home_row_by_path_key(p)
        )

        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(log_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(remove_btn, 0, Qt.AlignmentFlag.AlignTop)
        return wrap

    def _build_home_status_cell(self, status: str, top_anchor: bool = True) -> QWidget:
        sw = QWidget()
        sw.setObjectName("home-status-cell")
        sw.setAutoFillBackground(False)
        sw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        sw.setStyleSheet("background-color: transparent; border: none; border-radius: 0px;")
        sw.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        vl = QVBoxLayout(sw)
        vl.setContentsMargins(6, 4, 6, 4)
        vl.setSpacing(0)
        st_lbl = QLabel(status)
        st_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        track = _HomeStatusTrack(st_lbl, bar, sw)
        if top_anchor:
            # Home: top-anchor so the status stays in line with Duration and
            # Filename when the log panel expands a row; trailing stretch
            # absorbs the extra height below.
            vl.setAlignment(Qt.AlignmentFlag.AlignTop)
            vl.addWidget(track, 0)
            vl.addStretch(1)
        else:
            # Jobs: vertically center so fixed-height rows line up with
            # duration (VCenter) and filename.
            vl.addStretch(1)
            vl.addWidget(track, 0)
            vl.addStretch(1)
        sw._status_lbl = st_lbl  # type: ignore[attr-defined]
        sw._progress_bar = bar  # type: ignore[attr-defined]
        sw._status_track = track  # type: ignore[attr-defined]
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
        if hasattr(self, "_home_start_btn"):
            self._home_start_btn.setEnabled(True)
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
        added = 0
        duplicate_row = -1
        seen_in_batch: set[str] = set()
        for path in files:
            canon = self._canonical_file_path(path)
            if not canon or canon in seen_in_batch:
                continue
            seen_in_batch.add(canon)

            existing = self._find_table_row_for_path(path)
            if existing >= 0:
                if duplicate_row < 0:
                    duplicate_row = existing
                continue

            duration = _get_audio_duration(path)
            self._append_table_row(os.path.basename(path), duration, "Pending", full_path=path)
            self._append_log(f"[+] Added file: {os.path.basename(path)}", target_path=path)
            added += 1

        if duplicate_row >= 0:
            self._flash_duplicate_row(duplicate_row, any_added=added > 0)

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

    def _show_home_warning(self, visible: bool, text: str | None = None):
        if not hasattr(self, "_home_warning"):
            return
        if visible:
            self._home_warning.setText(text or HOME_WARNING_DEFAULT_TEXT)
        self._home_warning.setVisible(visible)

    def _flash_duplicate_row(self, row: int, any_added: bool) -> None:
        """Scroll the Home table to an existing duplicate row and surface a
        user-facing banner explaining the skip. No programmatic selection
        (would trip `_on_home_selection_changed` and immediately hide the
        banner we just showed).
        """
        item = self.table.item(row, 0)
        if item is not None:
            self.table.scrollToItem(
                item, QAbstractItemView.ScrollHint.PositionAtCenter
            )
        msg = (
            "Some files were already in the list and were skipped."
            if any_added
            else "This file has already been added."
        )
        self._show_home_warning(True, text=msg)

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
        _nspk = max(
            1,
            min(MAX_JOB_NUM_SPEAKERS, int(self._settings().value(KEY_DEFAULT_NUM_SPEAKERS, 2, type=int))),
        )
        dialog.speaker_count_value_label.setText(str(_nspk))
        dialog._sync_speaker_count_enabled()
        src_lang_default = str(self._settings().value(KEY_DEFAULT_TRANSLATION, "Auto"))
        if src_lang_default not in SOURCE_LANGUAGE_OPTIONS:
            src_lang_default = "Auto"
        dialog.source_language_value_label.setText(src_lang_default)

        output_mode_default = str(
            self._settings().value(KEY_DEFAULT_OUTPUT_MODE, OUTPUT_MODE_DEFAULT)
        )
        if output_mode_default not in OUTPUT_MODE_OPTIONS:
            output_mode_default = OUTPUT_MODE_DEFAULT
        dialog.output_mode_value_label.setText(output_mode_default)

        if bool(self._settings().value(KEY_DEFAULT_TIMESTAMPS, True, type=bool)):
            dialog.timestamps_value_label.setText("Per segment")
        else:
            dialog.timestamps_value_label.setText("No timestamps")

        # Phase 2 advanced-settings defaults. Values are clamped to legal
        # choices so a stale/corrupted QSettings value can't poison the
        # engine CLI.
        model_default = str(
            self._settings().value(KEY_DEFAULT_MODEL, MODEL_DEFAULT)
        )
        if model_default not in MODEL_OPTIONS:
            model_default = MODEL_DEFAULT
        dialog.model_value_label.setText(model_default)

        dialog.initial_prompt_edit.setPlainText(
            str(self._settings().value(KEY_DEFAULT_INITIAL_PROMPT, ""))
        )

        preprocess_default = str(
            self._settings().value(KEY_DEFAULT_PREPROCESS, PREPROCESS_DEFAULT)
        )
        if preprocess_default not in PREPROCESS_OPTIONS:
            preprocess_default = PREPROCESS_DEFAULT
        dialog.preprocess_value_label.setText(preprocess_default)

        dialog.split_on_speaker_checkbox.setChecked(
            bool(
                self._settings().value(
                    KEY_DEFAULT_SPLIT_ON_SPEAKER, False, type=bool
                )
            )
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_row = selected_ranges[0].topRow()
        fname = self._filename_for_row(selected_row)
        full_path = self._path_for_row(selected_row) or fname
        path_key = full_path

        diarize = dialog.diarization_checkbox.isChecked()
        try:
            num_speakers = int(dialog.speaker_count_value_label.text())
        except ValueError:
            num_speakers = 2
        num_speakers = max(1, min(MAX_JOB_NUM_SPEAKERS, num_speakers))
        source_language_label = dialog.source_language_value_label.text()
        output_mode_label = dialog.output_mode_value_label.text()
        timestamps = dialog.timestamps_value_label.text()

        # Phase 2 advanced-settings values from the dialog. `model` and
        # `preprocess_label` come from chevron dropdowns already limited
        # to legal choices; `initial_prompt` is stripped so blank/whitespace
        # entries don't set the flag. `preprocess_flag` is the CLI value
        # ("none" / "normalize"); `preprocess_label` is the human-readable
        # dropdown text kept for logging + QSettings.
        model = dialog.model_value_label.text()
        if model not in MODEL_OPTIONS:
            model = MODEL_DEFAULT
        initial_prompt = dialog.initial_prompt_edit.toPlainText().strip()
        preprocess_label = dialog.preprocess_value_label.text()
        if preprocess_label not in PREPROCESS_OPTIONS:
            preprocess_label = PREPROCESS_DEFAULT
        preprocess_flag = PREPROCESS_LABEL_TO_FLAG.get(preprocess_label, "none")
        split_on_speaker = dialog.split_on_speaker_checkbox.isChecked()

        # Persist the new values so the next job remembers them. Matches
        # the KEY_DEFAULT_DIARIZATION pattern used elsewhere in the app.
        s = self._settings()
        s.setValue(KEY_DEFAULT_MODEL, model)
        s.setValue(KEY_DEFAULT_INITIAL_PROMPT, initial_prompt)
        s.setValue(KEY_DEFAULT_PREPROCESS, preprocess_label)
        s.setValue(KEY_DEFAULT_SPLIT_ON_SPEAKER, bool(split_on_speaker))
        s.setValue(KEY_DEFAULT_NUM_SPEAKERS, int(num_speakers))

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
        # Log a presence flag for the initial prompt rather than its
        # contents; prompts can be long vocab lists and users shouldn't
        # have to scroll past them in the log panel.
        initial_prompt_logged = "set" if initial_prompt else "unset"
        self._append_log(
            f"[job] Starting job for {fname} "
            f"(source_language='{source_language_label}', "
            f"output_mode='{output_mode_label}', "
            f"diarization={diarize}, num_speakers={num_speakers}, "
            f"timestamps='{timestamps}', "
            f"model='{model}', preprocess='{preprocess_flag}', "
            f"split_on_speaker_change={split_on_speaker}, "
            f"initial_prompt={initial_prompt_logged})"
        )

        python = _resolve_engine_python()
        if not os.path.isfile(python):
            self._append_log(
                f"[error] Python interpreter not found at {python}. "
                "Create the project virtual environment with "
                "`python3.10 -m venv .venv` inside Offline-GUI-Topic-Modeling/ "
                "and install the requirements before running a job."
            )
            self._update_table_row_status(selected_row, "Error", pct=0)
            return
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

        out_dir = self._get_output_folder()

        # Source language -> --language flag. "Auto" lets Whisper detect
        # the source language; explicit "English"/"Spanish" skips detection.
        language_flag = SOURCE_LANGUAGE_TO_ISO.get(source_language_label, "auto")

        # Output mode -> --translate flag.
        #   Original only          -> --translate none (transcript only)
        #   Original + translation -> --translate auto (engine picks MT engine
        #                             for the resolved src<->tgt pair)
        translate_flag = OUTPUT_MODE_TO_TRANSLATE_FLAG.get(output_mode_label, "auto")

        if timestamps == "Per segment":
            timestamps_flag = "segment"
        elif timestamps == "Per word":
            timestamps_flag = "word"
        else:
            timestamps_flag = "none"

        # Phase 3 technical knobs stay hardcoded on purpose: compute type
        # auto-resolves per device inside the engine, batch size 16 matches
        # the engine default, and previous-text conditioning stays off to
        # avoid the known hallucination-loop failure mode on long audio.
        engine_args = [
            STUDIO_ENGINE_PATH,
            full_path,
            "--num-speakers", str(num_speakers),
            "--diarize" if diarize else "--no-diarize",
            "--language", language_flag,
            "--translate", translate_flag,
            "--timestamps", timestamps_flag,
            "--output-dir", out_dir,
            "--model", model,
            "--compute-type", "auto",
            "--batch-size", "16",
            "--preprocess", preprocess_flag,
            "--split-on-speaker-change" if split_on_speaker
                else "--no-split-on-speaker-change",
            "--no-condition-on-previous-text",
        ]
        # Only pass --initial-prompt when the user actually typed something.
        # An empty string would still set the flag and confuse the engine's
        # log line ("initial_prompt=set") even though there's no real prompt.
        if initial_prompt:
            engine_args += ["--initial-prompt", initial_prompt]

        self._job_process.start(python, engine_args)
        if not self._job_process.waitForStarted(5000):
            self._append_log(f"[error] Failed to start job: {self._job_process.errorString()}")
            self._update_table_row_status(selected_row, "Error", pct=0)
            self._job_process = None
            self._job_log_path = None
            self._current_job_row = None
            self._current_fname = None
            self._current_full_path = None
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
        if not self._job_process:
            return
        data = self._job_process.readAllStandardError()
        if not data:
            return
        for ln in data.data().decode("utf-8", errors="replace").splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("[event] "):
                try:
                    payload = json.loads(s[len("[event] "):])
                except (ValueError, TypeError):
                    continue
                self._handle_engine_event(payload)
                continue
            self._append_log(s)

    def _handle_engine_event(self, payload: dict) -> None:
        """Translate one structured studio_engine event into UI updates.

        Filtered out of the log; they drive the progress bar + status label
        for the active row only. No-op when no job row is active.
        """
        kind = payload.get("event")
        if self._current_job_row is None:
            return

        if kind == "start":
            self._retarget_progress(pct_floor=1.0, pct_cap=5.0, status="Starting\u2026")
            return

        if kind == "stage":
            name = str(payload.get("name") or "")
            try:
                pct = float(payload.get("pct") or 0.0) * 100.0
            except (TypeError, ValueError):
                pct = 0.0
            label = STAGE_LABELS.get(name, name or "Processing")
            next_cap = self._next_stage_cap(name, current_pct=pct)
            self._retarget_progress(pct_floor=pct, pct_cap=next_cap, status=label)
            return

        if kind == "write":
            # Emitted after each output file (including segments JSON). The
            # stage=write event at 0.95 already moved the bar; suppress.
            return

        if kind == "done":
            # _on_job_finished owns the terminal 100% snap. Stash the
            # payload so _archive_latest_outputs_for_job can use the
            # engine-reported src/tgt and exact filenames.
            self._last_done_event = dict(payload)
            return

        if kind == "error":
            etype = str(payload.get("type", "Error"))
            emsg = str(payload.get("message", "")).strip()
            line = f"[error] {etype}: {emsg}" if emsg else f"[error] {etype}"
            self._append_log(line)
            return

        if kind == "aborted":
            reason = str(payload.get("reason", "")).strip()
            self._append_log(f"[aborted] {reason}".rstrip())
            return

    def _next_stage_cap(self, name: str, current_pct: float) -> float:
        """Return the pct (0-100) the tween should glide toward after `name`."""
        for i, (n, _pct) in enumerate(STAGE_ORDER):
            if n == name and i + 1 < len(STAGE_ORDER):
                return STAGE_ORDER[i + 1][1] * 100.0
        return max(current_pct + 5.0, 99.0)

    def _stop_estimated_progress(self):
        if self._progress_timer.isActive():
            self._progress_timer.stop()
        self._estimated_progress_pct = 0.0
        self._estimated_progress_row = None
        self._estimated_progress_target = 94.0
        self._estimated_status = "Processing"

    def _start_estimated_progress(self, row: int):
        """Smooth simulated progress toward ~94% while the subprocess runs.

        Initial target is 94% so an engine that never emits [event] lines
        behaves like the legacy timer. Real engine events call into
        `_retarget_progress` to tighten the cap to the next stage's pct.
        """
        self._stop_estimated_progress()
        self._estimated_progress_row = row
        self._estimated_progress_pct = 5.0
        self._estimated_progress_target = 94.0
        self._estimated_status = "Processing"
        col2 = self.table.cellWidget(row, 2)
        if col2 is not None:
            self._apply_home_status_bar_style(col2, self._estimated_status, int(self._estimated_progress_pct))
        self._sync_jobs_status_cell_for_current_job(self._estimated_status, int(self._estimated_progress_pct))
        self._progress_timer.start()

    def _retarget_progress(self, pct_floor: float, pct_cap: float, status: str) -> None:
        """Snap the tween up to pct_floor and have it glide toward pct_cap."""
        if self._current_job_row is None:
            return
        self._estimated_progress_pct = max(self._estimated_progress_pct, float(pct_floor))
        self._estimated_progress_target = max(self._estimated_progress_pct + 0.5, float(pct_cap))
        self._estimated_status = status
        if self._estimated_progress_row is None:
            self._estimated_progress_row = self._current_job_row
        row = self._current_job_row
        col2 = self.table.cellWidget(row, 2)
        if col2 is not None:
            self._apply_home_status_bar_style(col2, status, int(self._estimated_progress_pct))
        self._sync_jobs_status_cell_for_current_job(status, int(self._estimated_progress_pct))
        if not self._progress_timer.isActive():
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
        # Asymptotic approach toward the current dynamic target. Real engine
        # stage events update _estimated_progress_target to the next stage's
        # pct; without events the target stays at 94% (legacy behavior).
        cap = self._estimated_progress_target
        gap = cap - self._estimated_progress_pct
        self._estimated_progress_pct += max(0.04, gap * 0.0065)
        self._estimated_progress_pct = min(self._estimated_progress_pct, cap)
        self._apply_home_status_bar_style(col2, self._estimated_status, int(self._estimated_progress_pct))
        self._sync_jobs_status_cell_for_current_job(self._estimated_status, int(self._estimated_progress_pct))

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
                # _archive_latest_outputs_for_job is the only other place
                # that drains _last_done_event, and we skip it on failure.
                # Clear here so a stale done payload from a partially
                # successful run can't carry into the next job.
                self._last_done_event = None
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
            "transcript_path": "",
            "translation_path": "",
            "segments_path": "",
            "src_lang": "",
            "tgt_lang": "",
            # Back-compat for older code paths still reading these keys.
            "spanish_path": "",
            "english_path": "",
        }
        self._jobs.insert(0, rec)
        self._refresh_jobs_table()

    def _apply_outputs_to_record(self, rec: dict, outputs: dict) -> None:
        rec["output_folder"] = outputs.get("folder", "")
        rec["transcript_path"] = outputs.get("transcript_path", "")
        rec["translation_path"] = outputs.get("translation_path", "")
        rec["segments_path"] = outputs.get("segments_path", "")
        rec["src_lang"] = outputs.get("src_lang", "")
        rec["tgt_lang"] = outputs.get("tgt_lang", "")
        rec["spanish_path"] = outputs.get("spanish_path", "")
        rec["english_path"] = outputs.get("english_path", "")
        rec["opened"] = time.strftime("%H:%M:%S")

    def _update_job_record(self, fname: str, status: str, outputs: dict | None):
        for rec in self._jobs:
            if rec.get("fname") == fname and rec.get("status") == "Processing":
                rec["status"] = status
                if outputs:
                    self._apply_outputs_to_record(rec, outputs)
                self._refresh_jobs_table()
                return
        # Fallback: update latest matching
        for rec in self._jobs:
            if rec.get("fname") == fname:
                rec["status"] = status
                if outputs:
                    self._apply_outputs_to_record(rec, outputs)
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
            self.jobs_table.setCellWidget(row, 2, self._build_home_status_cell(status_text, top_anchor=False))

            path_key = fp if fp else (rec.get("fname") or "")
            self.jobs_table.setCellWidget(
                row,
                3,
                self._build_jobs_output_folder_cell(rec.get("output_folder", ""), path_key),
            )

            self.jobs_table.setRowHeight(row, HOME_TABLE_ROW_MIN_H)
        self._sync_jobs_empty_state()

    def _sync_jobs_empty_state(self) -> None:
        if not hasattr(self, "jobs_table"):
            return
        empty = self.jobs_table.rowCount() == 0
        self.jobs_table.setVisible(not empty)
        self._jobs_empty_label.setVisible(empty)
        self._jobs_recent_section.setVisible(not empty)

    def _safe_read_text(self, path: str, limit_chars: int = 20000) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(limit_chars + 1)
            if len(data) > limit_chars:
                return data[:limit_chars] + "\n\n… (preview truncated) …"
            return data
        except Exception as e:
            return f"[error] Could not read file:\n{path}\n\n{e}"

    def _safe_read_text_lines(self, path: str, max_lines: int) -> tuple[str, int]:
        """Read up to ``max_lines`` full lines for Review (keeps block index = segment index)."""
        if not path:
            return "", 0
        lines: list[str] = []
        truncated = False
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= max_lines:
                        truncated = True
                        break
                    lines.append(line.rstrip("\n\r"))
        except Exception as e:
            return f"[error] Could not read file:\n{path}\n\n{e}", 0
        body = "\n".join(lines)
        n_real = len(lines)
        if truncated:
            body += "\n\n… (preview truncated) …"
        return body, n_real

    @staticmethod
    def _load_review_segments_json(path: str) -> list[dict]:
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                segs = data.get("segments")
                if isinstance(segs, list):
                    return [s for s in segs if isinstance(s, dict)]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return []

    @staticmethod
    def _parse_segment_timestamps_from_transcript_txt(path: str, max_lines: int) -> list[dict]:
        """One entry per text line: real times if line matches segment export, else nulls."""
        rows: list[dict] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, raw in enumerate(f):
                    if i >= max_lines:
                        break
                    line = raw.rstrip("\n\r")
                    m = _TRANSCRIPT_SEGMENT_LINE_RE.match(line)
                    if not m:
                        rows.append({"start": None, "end": None})
                        continue
                    sh, sm, ss, eh, em, es, _sp, _tx = m.groups()
                    rows.append(
                        {
                            "start": _hms_to_seconds(sh, sm, ss),
                            "end": _hms_to_seconds(eh, em, es),
                        }
                    )
        except OSError:
            return []
        return rows

    def _try_build_uniform_review_segments(self, tx_lines: int, dur_ms: int) -> None:
        """Approximate timing when no JSON and no embedded segment timestamps (even line split)."""
        if tx_lines <= 0 or dur_ms <= 0 or self._review_segments:
            return
        d = dur_ms / 1000.0
        self._review_segments = [
            {"start": (i / tx_lines) * d, "end": ((i + 1) / tx_lines) * d} for i in range(tx_lines)
        ]

    def _review_active_segment_index(self, t_sec: float) -> int | None:
        """Pick segment for playback time: prefer start<=t<=end, else last segment with start<=t."""
        segs = self._review_segments
        if not segs:
            return None
        best: int | None = None
        for i, seg in enumerate(segs):
            st = seg.get("start")
            if st is None:
                continue
            try:
                stf = float(st)
            except (TypeError, ValueError):
                continue
            en = seg.get("end")
            try:
                enf = float(en) if en is not None else None
            except (TypeError, ValueError):
                enf = None
            if enf is not None and stf <= t_sec <= enf:
                return i
            if stf <= t_sec:
                best = i
        return best if best is not None else 0

    def _review_active_char_format(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
        if getattr(self, "_theme", THEME_LIGHT) == THEME_DARK:
            fmt.setBackground(QColor(30, 64, 120))
            fmt.setForeground(QColor(241, 245, 249))
        else:
            fmt.setBackground(QColor(191, 219, 254))
            fmt.setForeground(QColor(15, 23, 42))
        return fmt

    def _review_extra_selection_for_block(
        self, edit: QTextEdit, block_idx: int
    ) -> QTextEdit.ExtraSelection | None:
        doc = edit.document()
        block = doc.findBlockByNumber(block_idx)
        if not block.isValid():
            return None
        sel = QTextEdit.ExtraSelection()
        # Select only this block's text (exclude the paragraph separator). Using
        # BlockUnderCursor + FullWidthSelection often paints a band that bleeds
        # vertically into the previous segment; a character range stays aligned
        # with the laid-out lines (including word wrap).
        cur = QTextCursor(doc)
        start = block.position()
        blen = block.length()
        end = start + max(blen - 1, 0)
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cur
        sel.format = self._review_active_char_format()
        return sel

    def _apply_review_segment_highlight(self, seg_idx: int | None) -> None:
        sync_n = self._review_sync_line_count
        if seg_idx is not None and sync_n > 0 and seg_idx >= sync_n:
            seg_idx = None
        if seg_idx is not None and seg_idx == self._review_highlight_idx:
            return
        self._review_highlight_idx = seg_idx

        editors: list[QTextEdit] = [self.spanish_preview]
        if self._review_highlight_translation:
            editors.append(self.english_preview)

        if seg_idx is None or not self._review_segments:
            for edit in editors:
                edit.setExtraSelections([])
        else:
            for edit in editors:
                block = edit.document().findBlockByNumber(seg_idx)
                if not block.isValid():
                    continue
                edit.setTextCursor(QTextCursor(block))
                edit.ensureCursorVisible()
            for edit in editors:
                sel = self._review_extra_selection_for_block(edit, seg_idx)
                edit.setExtraSelections([sel] if sel else [])

    def _sync_review_highlight_from_time_ms(self, pos_ms: int) -> None:
        if not self._review_segments:
            if self._review_highlight_idx is not None:
                self._apply_review_segment_highlight(None)
            return
        t = max(0.0, float(pos_ms) / 1000.0)
        idx = self._review_active_segment_index(t)
        self._apply_review_segment_highlight(idx)

    def _transcription_meta_path(self, out_dir: str, stem: str) -> str:
        return os.path.join(out_dir, f"{stem}{TRANSCRIPTION_META_SUFFIX}")

    def _read_transcription_meta(self, out_dir: str, stem: str) -> dict | None:
        # Prefer the current sidecar name; fall back to the legacy
        # `_transcription_meta.json` name so older runs still load.
        candidates = [
            os.path.join(out_dir, f"{stem}{TRANSCRIPTION_META_SUFFIX}"),
            os.path.join(out_dir, f"{stem}{LEGACY_TRANSCRIPTION_META_SUFFIX}"),
        ]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
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
        Move the engine's ``transcription_<src>.txt`` / ``translation_<tgt>.txt``
        outputs (written into ``--output-dir``) into role+language tagged
        per-audio archive names::

            <audio_stem>_transcription_<src>.txt
            <audio_stem>_translation_<tgt>.txt

        Source filenames come from the engine's ``done`` event when
        available (the only authoritative source of the resolved src/tgt
        ISO codes); otherwise we fall back to globbing the output dir for
        the ``transcription_*.txt`` / ``translation_*.txt`` patterns.

        Back-compat: the returned dict still carries ``spanish_path`` /
        ``english_path`` keys so older Review code keeps working until it
        migrates to the new ``transcript_path`` / ``translation_path``
        keys.
        """
        out_dir = self._get_output_folder()
        base = os.path.splitext(os.path.basename(full_path.strip()))[0]

        done = self._last_done_event or {}
        src_lang = (str(done.get("src_lang") or "")).strip().lower() or None
        tgt_lang_raw = done.get("tgt_lang")
        tgt_lang = (str(tgt_lang_raw or "")).strip().lower() or None

        # 1. Resolve transcript source path (engine payload first, then glob).
        src_transcript = ""
        engine_transcript = (str(done.get("transcript_file") or "")).strip()
        if engine_transcript and os.path.exists(engine_transcript):
            src_transcript = engine_transcript
        else:
            try:
                candidates = [
                    os.path.join(out_dir, fn)
                    for fn in os.listdir(out_dir)
                    if fn.startswith(ENGINE_TRANSCRIPT_PREFIX)
                    and fn.lower().endswith(".txt")
                    # Engine fresh outputs are exactly transcription_<iso>.txt
                    # (one underscore). Files already archived by us look like
                    # <stem>_transcription_<iso>.txt (>=2 underscores) and
                    # must be skipped.
                    and fn.count("_") == 1
                ]
                candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                if candidates:
                    src_transcript = candidates[0]
                    if src_lang is None:
                        stem = os.path.splitext(os.path.basename(src_transcript))[0]
                        src_lang = stem[len(ENGINE_TRANSCRIPT_PREFIX):] or src_lang
            except OSError:
                pass

        # 2. Resolve translation source path (same strategy).
        src_translation = ""
        engine_translation = (str(done.get("translation_file") or "")).strip()
        if engine_translation and os.path.exists(engine_translation):
            src_translation = engine_translation
        else:
            try:
                candidates = [
                    os.path.join(out_dir, fn)
                    for fn in os.listdir(out_dir)
                    if fn.startswith(ENGINE_TRANSLATION_PREFIX)
                    and fn.lower().endswith(".txt")
                    and fn.count("_") == 1
                ]
                candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                if candidates:
                    src_translation = candidates[0]
                    if tgt_lang is None:
                        stem = os.path.splitext(os.path.basename(src_translation))[0]
                        tgt_lang = stem[len(ENGINE_TRANSLATION_PREFIX):] or tgt_lang
            except OSError:
                pass

        # 3. Build destination paths and move.
        moved_any = False
        dst_transcript = ""
        if src_transcript and src_lang:
            dst_transcript = os.path.join(
                out_dir, f"{base}_transcription_{src_lang}.txt"
            )
            try:
                os.replace(src_transcript, dst_transcript)
                moved_any = True
            except OSError:
                dst_transcript = ""

        dst_translation = ""
        if src_translation and tgt_lang:
            dst_translation = os.path.join(
                out_dir, f"{base}_translation_{tgt_lang}.txt"
            )
            try:
                os.replace(src_translation, dst_translation)
                moved_any = True
            except OSError:
                dst_translation = ""

        # 4. Back-compat: populate spanish_path / english_path so legacy
        # readers keep working until the Review path is fully migrated.
        spanish_path = ""
        english_path = ""
        for p, lang in ((dst_transcript, src_lang), (dst_translation, tgt_lang)):
            if not p:
                continue
            if lang == "es":
                spanish_path = p
            elif lang == "en":
                english_path = p

        segments_path = ""
        engine_segments = (str(done.get("segments_file") or "")).strip()
        if engine_segments and os.path.isfile(engine_segments):
            segments_path = engine_segments

        # Sidecar meta so Review's filesystem-scan fallback can show the
        # original source filename as the row label and play back the
        # source audio. Only written when we actually archived something;
        # the stem key matches what _strip_archive_suffix returns on the
        # just-renamed files, so _review_display_name / the scan path in
        # _refresh_review_items pick it up.
        if moved_any:
            self._write_transcription_meta(
                out_dir,
                full_path,
                base,
                spanish_path,
                english_path,
            )

        # Drain the captured event so the next job starts clean even if
        # _reset_home_row_for_new_job is not called (e.g. on error paths).
        self._last_done_event = None

        return {
            "folder": out_dir,
            "transcript_path": dst_transcript,
            "translation_path": dst_translation,
            "segments_path": segments_path,
            "src_lang": src_lang or "",
            "tgt_lang": tgt_lang or "",
            "spanish_path": spanish_path,
            "english_path": english_path,
            "moved_any": moved_any,
        }

    @staticmethod
    def _strip_archive_suffix(path: str) -> str:
        """Return the audio stem from an archived output filename.

        Recognizes both the new ``<stem>_transcription_<iso>.txt`` /
        ``<stem>_translation_<iso>.txt`` naming and the legacy
        ``_transcription_spanish.txt`` / ``_transcription_english.txt`` /
        ``_translation_english.txt`` names so the Review page keeps
        finding older runs.
        """
        if not path:
            return ""
        bn = os.path.basename(path.strip())
        if not bn.lower().endswith(".txt"):
            return ""
        stem_no_ext = bn[: -len(".txt")]
        for marker in ("_transcription_", "_translation_"):
            idx = stem_no_ext.rfind(marker)
            if idx > 0:
                return stem_no_ext[:idx]
        return ""

    def _migrate_legacy_output_filenames(self, out_dir: str) -> None:
        """Conservative one-shot rename of legacy full-word language tags.

        Legacy naming -> current naming::

            <stem>_transcription_spanish.txt  ->  <stem>_transcription_es.txt
            <stem>_transcription_english.txt  ->  <stem>_translation_en.txt

        Only renames when the destination does NOT already exist and no
        plausible new-convention counterpart is already present (to avoid
        re-tagging a legacy file as a translation when the same stem also
        has a real source transcript in English). Idempotent and skipped
        after the first run per folder per session.
        """
        if not out_dir or not os.path.isdir(out_dir):
            return
        key = self._canonical_file_path(out_dir)
        if not key or key in self._migrated_output_dirs:
            return
        self._migrated_output_dirs.add(key)

        try:
            names = os.listdir(out_dir)
        except OSError:
            return
        name_set = set(names)

        for fn in list(names):
            if not fn.lower().endswith(".txt"):
                continue
            stem_no_ext = fn[: -len(".txt")]
            if stem_no_ext.endswith("_transcription_spanish"):
                base = stem_no_ext[: -len("_transcription_spanish")]
                if not base:
                    continue
                target = f"{base}_transcription_es.txt"
                if target in name_set:
                    continue
                try:
                    os.rename(
                        os.path.join(out_dir, fn),
                        os.path.join(out_dir, target),
                    )
                    name_set.discard(fn)
                    name_set.add(target)
                except OSError:
                    pass
                continue
            if stem_no_ext.endswith("_transcription_english"):
                base = stem_no_ext[: -len("_transcription_english")]
                if not base:
                    continue
                target = f"{base}_translation_en.txt"
                # If a new-convention English source transcript exists,
                # leave the legacy file alone — its semantics are
                # ambiguous and the scanner already handles it.
                if target in name_set:
                    continue
                if f"{base}_transcription_en.txt" in name_set:
                    continue
                try:
                    os.rename(
                        os.path.join(out_dir, fn),
                        os.path.join(out_dir, target),
                    )
                    name_set.discard(fn)
                    name_set.add(target)
                except OSError:
                    pass

    def _refresh_review_items(self):
        out_dir = self._get_output_folder()
        # Lazy, once-per-session migration so legacy full-word language
        # tags on disk start showing up under the new ISO-2 naming.
        self._migrate_legacy_output_filenames(out_dir)
        items: list[dict] = []
        # Canonicalized audio stems already represented by a job record so
        # the filesystem scan below doesn't double-add the same run.
        seen_stems: set[str] = set()

        # 1. Prefer recently completed jobs we already know about.
        for rec in self._jobs:
            transcript_p = (rec.get("transcript_path") or rec.get("spanish_path") or "").strip()
            translation_p = (rec.get("translation_path") or rec.get("english_path") or "").strip()
            if rec.get("status") != "Complete":
                continue
            if not (transcript_p or translation_p):
                continue
            job_out = (rec.get("output_folder") or "").strip() or out_dir
            fname = (rec.get("fname") or "").strip()
            if not fname:
                fp = (rec.get("full_path") or "").strip()
                fname = os.path.basename(fp) if fp else ""
            stem = self._strip_archive_suffix(transcript_p) or self._strip_archive_suffix(translation_p)
            if not fname and stem:
                fname = self._review_display_name(job_out, stem)
            if not fname:
                fname = stem or "—"
            if stem:
                seen_stems.add(stem.casefold())
            seg_p = (rec.get("segments_path") or "").strip()
            if not seg_p and transcript_p:
                cand = os.path.join(
                    job_out,
                    f"{self._strip_archive_suffix(transcript_p)}{REVIEW_SEGMENTS_SUFFIX}",
                )
                if os.path.isfile(cand):
                    seg_p = cand
            items.append(
                {
                    "label": fname,
                    "folder": job_out,
                    "audio_path": (rec.get("full_path") or "").strip(),
                    "transcript_path": transcript_p,
                    "translation_path": translation_p,
                    "segments_path": seg_p,
                    "src_lang": rec.get("src_lang", ""),
                    "tgt_lang": rec.get("tgt_lang", ""),
                    # Back-compat keys.
                    "spanish_path": rec.get("spanish_path", ""),
                    "english_path": rec.get("english_path", ""),
                }
            )

        # 2. Always scan the filesystem so historical runs and runs produced
        #    by earlier sessions stay visible. Stems already represented by
        #    a job record above are skipped via `seen_stems`.
        if os.path.isdir(out_dir):
            # Newest first so the "first-seen-wins" merge below prefers the
            # most recent file when the same (stem, role, lang) slot has
            # both a new-convention and a legacy file on disk.
            entries: list[tuple[float, str, str]] = []
            try:
                for fn in os.listdir(out_dir):
                    if not fn.lower().endswith(".txt"):
                        continue
                    full = os.path.join(out_dir, fn)
                    try:
                        mt = os.path.getmtime(full)
                    except OSError:
                        mt = 0.0
                    entries.append((mt, fn, full))
            except OSError:
                entries = []
            entries.sort(key=lambda e: e[0], reverse=True)

            groups: dict[str, dict] = {}
            for _mt, fn, full in entries:
                stem_no_ext = fn[: -len(".txt")]
                # Match either role with any language tag:
                #   <stem>_transcription_<iso>.txt
                #   <stem>_translation_<iso>.txt
                key = ""
                role = ""
                lang = ""
                for marker, role_name in (
                    ("_transcription_", "transcript"),
                    ("_translation_", "translation"),
                ):
                    idx = stem_no_ext.rfind(marker)
                    if idx <= 0:
                        continue
                    key = stem_no_ext[:idx]
                    lang = stem_no_ext[idx + len(marker):].lower()
                    role = role_name
                    break
                if not key or not role:
                    continue

                # Normalize legacy full-word language tags. Old pipeline
                # convention (pre-studio_engine):
                #   <stem>_transcription_spanish.txt  -> source transcript (es)
                #   <stem>_transcription_english.txt  -> translation (en)
                # The second file was stamped with the `_transcription_`
                # marker historically, but was really the translated output,
                # so re-map role accordingly.
                if lang == "spanish":
                    lang = "es"
                elif lang == "english":
                    if role == "transcript":
                        role = "translation"
                    lang = "en"

                g = groups.setdefault(key, {"folder": out_dir})
                # First-seen-wins per role+lang slot. Because `entries` is
                # sorted newest-first, newer ISO-2 files win over older
                # legacy full-word duplicates for the same stem.
                if role == "transcript":
                    if not g.get("transcript_path"):
                        g["transcript_path"] = full
                        g["src_lang"] = lang
                    if lang == "es" and not g.get("spanish_path"):
                        g["spanish_path"] = full
                    elif lang == "en" and not g.get("english_path"):
                        g["english_path"] = full
                else:
                    if not g.get("translation_path"):
                        g["translation_path"] = full
                        g["tgt_lang"] = lang
                    if lang == "en" and not g.get("english_path"):
                        g["english_path"] = full
                    elif lang == "es" and not g.get("spanish_path"):
                        g["spanish_path"] = full

            for key, g in groups.items():
                if key.casefold() in seen_stems:
                    continue
                if not (g.get("transcript_path") or g.get("translation_path")):
                    continue
                # Resolve the meta sidecar from the directory of the matched
                # file rather than the currently-configured out_dir so the
                # sidecar still loads if the user switched output folders.
                tx_path = g.get("transcript_path") or g.get("translation_path")
                match_dir = os.path.dirname(tx_path) if tx_path else out_dir
                meta = self._read_transcription_meta(match_dir, key)
                ap = ""
                if meta:
                    ap = str(meta.get("source_full_path") or "").strip()
                    if ap and not os.path.isfile(ap):
                        ap = ""
                seg_sidecar = os.path.join(match_dir, f"{key}{REVIEW_SEGMENTS_SUFFIX}")
                seg_p = seg_sidecar if os.path.isfile(seg_sidecar) else ""
                items.append(
                    {
                        "label": self._review_display_name(match_dir, key),
                        "folder": g.get("folder", out_dir),
                        "audio_path": ap,
                        "transcript_path": g.get("transcript_path", ""),
                        "translation_path": g.get("translation_path", ""),
                        "segments_path": seg_p,
                        "src_lang": g.get("src_lang", ""),
                        "tgt_lang": g.get("tgt_lang", ""),
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
            self.spanish_preview.setExtraSelections([])
            self.english_preview.setPlainText("")
            self.english_preview.setExtraSelections([])
            self._review_segments = []
            self._review_sync_line_count = 0
            self._review_highlight_idx = None
            self._review_highlight_translation = False
            self._review_fallback_tx_lines = 0
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
                self.spanish_preview.setExtraSelections([])
            if hasattr(self, "english_preview"):
                self.english_preview.setPlainText("")
                self.english_preview.setExtraSelections([])
            self._review_segments = []
            self._review_sync_line_count = 0
            self._review_highlight_idx = None
            self._review_highlight_translation = False
            self._review_fallback_tx_lines = 0
            return

        # Load audio for the selected Review item (if available).
        ap = (it.get("audio_path") or "").strip()
        self._set_review_audio_source(ap)

        folder = it.get("folder", "")
        transcript_p = (it.get("transcript_path") or it.get("spanish_path") or "").strip()
        translation_p = (it.get("translation_path") or it.get("english_path") or "").strip()
        self._review_transcript_path = transcript_p
        self._review_translation_path = translation_p
        if hasattr(self, "review_edit_transcript_btn") and self.review_edit_transcript_btn.isChecked():
            self.review_edit_transcript_btn.setChecked(False)
        if hasattr(self, "review_edit_translation_btn") and self.review_edit_translation_btn.isChecked():
            self.review_edit_translation_btn.setChecked(False)
        seg_path = (it.get("segments_path") or "").strip()
        if not seg_path and transcript_p:
            cand = os.path.join(
                os.path.dirname(transcript_p),
                f"{self._strip_archive_suffix(transcript_p)}{REVIEW_SEGMENTS_SUFFIX}",
            )
            if os.path.isfile(cand):
                seg_path = cand
        if not seg_path and ap and os.path.isfile(ap):
            audio_stem = os.path.splitext(os.path.basename(ap))[0]
            side_dir = ""
            if transcript_p:
                side_dir = os.path.dirname(transcript_p)
            elif translation_p:
                side_dir = os.path.dirname(translation_p)
            elif folder:
                side_dir = folder
            if side_dir:
                cand2 = os.path.join(side_dir, f"{audio_stem}{REVIEW_SEGMENTS_SUFFIX}")
                if os.path.isfile(cand2):
                    seg_path = cand2

        self._review_segments = self._load_review_segments_json(seg_path)
        self._review_fallback_tx_lines = 0
        self._review_highlight_idx = None
        self._review_highlight_translation = bool(translation_p and os.path.isfile(translation_p))

        if transcript_p:
            tx_body, tx_lines = self._safe_read_text_lines(transcript_p, REVIEW_PREVIEW_MAX_LINES)
            self.spanish_preview.setPlainText(tx_body)
        else:
            self.spanish_preview.setPlainText("No transcription file found.")
            tx_lines = 0

        if translation_p and os.path.isfile(translation_p):
            en_body, en_lines = self._safe_read_text_lines(translation_p, REVIEW_PREVIEW_MAX_LINES)
            self.english_preview.setPlainText(en_body)
        else:
            self.english_preview.setPlainText("No translation file found.")
            en_lines = 0

        if not self._review_segments and transcript_p and tx_lines:
            parsed = self._parse_segment_timestamps_from_transcript_txt(
                transcript_p, REVIEW_PREVIEW_MAX_LINES
            )
            if (
                len(parsed) == tx_lines
                and parsed
                and all(r.get("start") is not None and r.get("end") is not None for r in parsed)
            ):
                self._review_segments = parsed

        n_seg = len(self._review_segments)
        if n_seg and tx_lines:
            if self._review_highlight_translation and en_lines:
                self._review_sync_line_count = min(tx_lines, en_lines, n_seg)
            else:
                self._review_sync_line_count = min(tx_lines, n_seg)
        elif tx_lines:
            if self._review_highlight_translation and en_lines:
                self._review_sync_line_count = min(tx_lines, en_lines)
            else:
                self._review_sync_line_count = tx_lines
        else:
            self._review_sync_line_count = 0

        left_bc = self.spanish_preview.document().blockCount()
        if self._review_highlight_translation and en_lines:
            right_bc = self.english_preview.document().blockCount()
            self._review_sync_line_count = min(self._review_sync_line_count, left_bc, right_bc)
        elif self._review_sync_line_count:
            self._review_sync_line_count = min(self._review_sync_line_count, left_bc)

        if not self._review_segments and tx_lines > 0:
            self._review_fallback_tx_lines = tx_lines
            if self._review_player is not None and int(self._review_player.duration()) > 0:
                self._try_build_uniform_review_segments(tx_lines, int(self._review_player.duration()))
                if self._review_segments:
                    self._review_fallback_tx_lines = 0
                    n2 = len(self._review_segments)
                    if self._review_highlight_translation and en_lines:
                        right_bc = self.english_preview.document().blockCount()
                        self._review_sync_line_count = min(
                            self._review_sync_line_count, n2, left_bc, right_bc
                        )
                    else:
                        self._review_sync_line_count = min(self._review_sync_line_count, n2, left_bc)

        info_lines = [f"Folder: {folder}"]
        if ap and not os.path.isfile(ap):
            info_lines.append(f"Source audio not found at: {ap}")
        self.review_info_path.setText("\n".join(info_lines))

        self.spanish_preview.setExtraSelections([])
        self.english_preview.setExtraSelections([])

        if self._review_highlight_enabled and self._review_player is not None:
            self._sync_review_highlight_from_time_ms(int(self._review_player.position()))
        else:
            self._apply_review_segment_highlight(None)

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
        # Map legacy "spanish"/"english" labels to role buckets. The actual
        # language depends on the source language for this run, but the UI
        # column meanings are: left = source transcript, right = translation.
        if which == "spanish":
            path = (it.get("transcript_path") or it.get("spanish_path") or "").strip()
        else:
            path = (it.get("translation_path") or it.get("english_path") or "").strip()
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