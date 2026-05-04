"""
Topic Modeling page for the Speech to Text Studio GUI.

Wraps Rayannon's pipeline (topic_modeling/src/pipeline.py) so users can:
  1. Pick a transcript .txt file (or folder of .txt files) from disk.
  2. Optionally specify the interviewer speaker label to exclude.
  3. Optionally enable GPT4All LLM labeling and choose the model name.
  4. Run the full pipeline (preprocess → BERTopic) in a subprocess.
  5. View topic summary JSON results and optionally stream pipeline output to stderr.
  6. Show more excerpts for each topic.
  7. Click excerpts to open the original transcript and highlight the matching text.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from PySide6.QtCore import Qt, QProcess, QThread, QTimer, QSize
from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nav_icons import make_folder_open_icon
from llm_assistant import LLMAssistantPanel, TOPIC_QUICK_ACTIONS, _TOPIC_SYSTEM

# Path resolution: topic_modeling/src lives two levels above this file
# (studio/gui/  →  studio/  →  project root  →  topic_modeling/src)
_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
_STUDIO_DIR = os.path.dirname(_GUI_DIR)
_PROJECT_ROOT = os.path.dirname(_STUDIO_DIR)
_PIPELINE_SCRIPT = os.path.join(_PROJECT_ROOT, "topic_modeling", "src", "pipeline.py")
_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "topic_modeling", "output")

# Match Settings / Review label column width for consistent alignment with other pages.
_TOPICS_LABEL_W = 236

# Cap how much transcript text is shipped to the local LLM as context.
# Even small models choke on huge prompts, and most on-device models have
# 4K–8K context windows. We trim per-file and overall total.
_AI_CONTEXT_PER_FILE_CHARS = 8000
_AI_CONTEXT_TOTAL_CHARS = 24000

_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _resolve_python() -> str:
    bin_name = "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    for base in (_STUDIO_DIR, _PROJECT_ROOT):
        candidate = os.path.join(base, ".venv", bin_name)
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


class _TopicMapWorker(QThread):
    """Background thread: loads BERTopic model, runs 2-D UMAP, emits topic coords + weights."""

    map_ready = Signal(list)
    map_failed = Signal(str)

    def __init__(self, model_path: str, summary: list[dict], parent=None):
        super().__init__(parent)
        self._model_path = model_path
        self._summary = summary

    def run(self) -> None:
        try:
            from bertopic import BERTopic
            from umap import UMAP
            import numpy as np

            model = BERTopic.load(self._model_path, embedding_model=False)
            embeddings = getattr(model, "topic_embeddings_", None)
            if embeddings is None:
                raise ValueError("topic_embeddings_ not present on loaded model")
            if len(embeddings) < 2:
                raise ValueError(f"Only {len(embeddings)} topic embedding(s) — need at least 2")

            n = len(embeddings)
            n_neighbors = max(2, min(15, n - 1))
            # Spectral init requires N > k; use random init for small models
            umap_init = "random" if n < 8 else "spectral"
            coords = UMAP(
                n_components=2, n_neighbors=n_neighbors, random_state=42,
                metric="cosine", init=umap_init,
            ).fit_transform(embeddings)

            topic_info = model.get_topic_info()
            topic_ids = list(topic_info["Topic"])

            kw_weights: dict[int, list] = {}
            for tid in topic_ids:
                if tid != -1:
                    kw_weights[tid] = model.get_topic(tid) or []

            summary_by_id = {e["topic_id"]: e for e in self._summary}
            results = []
            for i, tid in enumerate(topic_ids):
                if tid == -1:
                    continue
                entry = summary_by_id.get(int(tid), {})
                results.append({
                    "topic_id": int(tid),
                    "x": float(coords[i, 0]),
                    "y": float(coords[i, 1]),
                    "count": entry.get("segment_count", 1),
                    "label": entry.get("generated_label") or "",
                    "keywords": entry.get("keywords", []),
                    "keyword_weights": kw_weights.get(int(tid), []),
                    "examples": entry.get("examples", []),
                    "source_files": entry.get("source_files", []),
                })
            self.map_ready.emit(results)

        except Exception as exc:
            import traceback
            print(f"[map-worker] {exc}", file=sys.stderr, flush=True)
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            self.map_failed.emit(str(exc))


class TopicModelingPage(QFrame):
    """Full topic-modeling pipeline control page."""

    def __init__(self, theme_getter=None, parent=None):
        super().__init__(parent)
        self.setObjectName("topics-page")
        self._theme_getter = theme_getter  # callable() → "light" | "dark"
        self._process: QProcess | None = None
        self._did_equal_topic_split = False
        self._results_ai_splitter: QSplitter | None = None
        # Two separate context blobs, recombined and pushed to the AI panel
        # whenever either changes. This lets the chatbot reason about the
        # selected transcript even before any topic results exist.
        self._transcript_context: str = ""
        self._topics_context: str = ""
        self._last_transcript_path: str = ""

        # ── Stage-progress state ──────────────────────────────────────────
        self._stage_rows: list[tuple[str, QLabel, QLabel]] = []  # (key, icon, time)
        self._stage_active_key: str | None = None
        self._stage_start_times: dict[str, float] = {}
        self._show_labeling_stage: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: QTimer | None = None
        self._elapsed_timer: QTimer | None = None

        # ── Results state ─────────────────────────────────────────────────
        self._current_summary: list[dict] = []
        self._current_source_path: str = ""

        # ── Dual-pane map state ───────────────────────────────────────────
        self._map_topic_data: list[dict] = []
        self._selected_topic_idx: int = 0
        self._map_worker: _TopicMapWorker | None = None
        self._map_fig = None
        self._map_ax = None
        self._map_canvas = None
        self._map_frame_lay: QVBoxLayout | None = None
        self._detail_inner_lay: QVBoxLayout | None = None
        self._inner_splitter: QSplitter | None = None
        self._detail_splitter_set: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Page header ──────────────────────────────────────────────────
        title = QLabel("Topic Modeling")
        title.setObjectName("page-title")
        subtitle = QLabel(
            "Run BERTopic on transcript files produced by the transcription pipeline"
        )
        subtitle.setObjectName("page-sub")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(6)

        # ── Pipeline options — collapsible card ──────────────────────────
        options_card = QFrame()
        options_card.setObjectName("settings-card")
        options_lay = QVBoxLayout(options_card)
        options_lay.setContentsMargins(14, 10, 14, 10)
        options_lay.setSpacing(0)

        # Clickable header row with chevron
        opts_hdr = QHBoxLayout()
        opts_hdr.setSpacing(8)
        section_lbl = QLabel("Pipeline options")
        section_lbl.setObjectName("section-title")
        opts_hdr.addWidget(section_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        self._options_chevron = QToolButton()
        self._options_chevron.setObjectName("settings-chevron-btn")
        self._options_chevron.setText("▾")
        self._options_chevron.setAutoRaise(True)
        self._options_chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._options_chevron.clicked.connect(self._toggle_options_panel)
        opts_hdr.addWidget(self._options_chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        options_lay.addLayout(opts_hdr)

        # Body — hidden after Run is clicked
        self._options_body = QFrame()
        self._options_body.setObjectName("topics-options-body")
        body_lay = QVBoxLayout(self._options_body)
        body_lay.setContentsMargins(0, 8, 0, 2)
        body_lay.setSpacing(6)

        # Input path row
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_lbl = QLabel("Input (.txt file or folder):")
        input_lbl.setObjectName("settings-label")
        input_lbl.setFixedWidth(_TOPICS_LABEL_W)
        self._input_edit = QLineEdit()
        self._input_edit.setObjectName("settings-input")
        self._input_edit.setPlaceholderText("Select a transcript file or folder…")
        self._input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._input_edit.editingFinished.connect(self._on_input_path_committed)
        browse_file_btn = QPushButton("File…")
        browse_file_btn.setObjectName("add-btn")
        browse_file_btn.clicked.connect(self._browse_file)
        browse_folder_btn = QPushButton("Folder…")
        browse_folder_btn.setObjectName("add-btn")
        browse_folder_btn.clicked.connect(self._browse_folder)
        input_row.addWidget(input_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        input_row.addWidget(self._input_edit, 1)
        input_row.addWidget(browse_file_btn, 0)
        input_row.addWidget(browse_folder_btn, 0)
        body_lay.addLayout(input_row)

        # Interviewer speaker row
        spk_row = QHBoxLayout()
        spk_row.setSpacing(10)
        spk_lbl = QLabel("Exclude interviewer:")
        spk_lbl.setObjectName("settings-label")
        spk_lbl.setFixedWidth(_TOPICS_LABEL_W)
        self._speaker_combo = QComboBox()
        self._speaker_combo.setObjectName("settings-input")
        self._speaker_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._speaker_combo.addItem("None — include all speakers", None)
        spk_row.addWidget(spk_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        spk_row.addWidget(self._speaker_combo, 1)
        body_lay.addLayout(spk_row)

        speaker_hint = QLabel(
            "Choose the interviewer speaker label to exclude their questions from topic modeling."
        )
        speaker_hint.setObjectName("settings-hint")
        body_lay.addWidget(speaker_hint)

        # GPT4All labeling row
        gpt4all_row = QHBoxLayout()
        self._gpt4all_checkbox = QCheckBox("Enable GPT4All LLM topic labeling")
        self._gpt4all_checkbox.setObjectName("job-options-checkbox")
        self._gpt4all_checkbox.toggled.connect(self._sync_gpt4all_model_enabled)
        gpt4all_row.addWidget(self._gpt4all_checkbox)
        gpt4all_row.addStretch(1)
        body_lay.addLayout(gpt4all_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_lbl = QLabel("GPT4All model name:")
        model_lbl.setObjectName("settings-label")
        model_lbl.setFixedWidth(_TOPICS_LABEL_W)
        self._model_edit = QLineEdit("mistral-7b-openorca.Q4_0.gguf")
        self._model_edit.setObjectName("settings-input")
        self._model_edit.setEnabled(False)
        model_row.addWidget(model_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        model_row.addWidget(self._model_edit, 1)
        body_lay.addLayout(model_row)

        options_lay.addWidget(self._options_body)
        outer.addWidget(options_card)

        # Primary action (same placement as Home "Start Job")
        self._run_btn = QPushButton("▶  Run Pipeline")
        self._run_btn.setObjectName("start-btn")
        self._run_btn.setAttribute(Qt.WA_StyledBackground, True)
        self._run_btn.clicked.connect(self._on_run_clicked)
        outer.addWidget(self._run_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # ── Bottom splitter: topic results | AI Assistant (50/50 on first layout) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._results_ai_splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        # Results panel
        results_frame = QFrame()
        results_frame.setObjectName("settings-card")
        results_vlay = QVBoxLayout(results_frame)
        results_vlay.setContentsMargins(16, 14, 16, 14)
        results_vlay.setSpacing(10)

        results_header = QHBoxLayout()
        results_header.setSpacing(8)
        results_title = QLabel("Topic results")
        results_title.setObjectName("section-title")
        results_header.addWidget(results_title, 1)
        theme = self._theme_getter() if self._theme_getter else "light"
        _folder_muted = "#94a3b8" if theme == "dark" else "#475569"
        self._open_output_btn = QToolButton()
        self._open_output_btn.setObjectName("review-open-folder-btn")
        self._open_output_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self._open_output_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._open_output_btn.setIcon(
            make_folder_open_icon(size=18, color_hex=_folder_muted)
        )
        self._open_output_btn.setIconSize(QSize(18, 18))
        self._open_output_btn.setFixedSize(22, 22)
        self._open_output_btn.setToolTip("Open output folder")
        self._open_output_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._open_output_btn.setAutoRaise(True)
        self._open_output_btn.clicked.connect(self._open_output_folder)
        results_header.addWidget(self._open_output_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        results_vlay.addLayout(results_header)

        # ── Quality strip (shown when results are loaded) ──────────────────
        self._quality_strip = QFrame()
        self._quality_strip.setObjectName("topics-quality-strip")
        qs_lay = QHBoxLayout(self._quality_strip)
        qs_lay.setContentsMargins(4, 4, 4, 4)
        qs_lay.setSpacing(16)
        self._ql_topics = QLabel("—")
        self._ql_topics.setObjectName("settings-label")
        self._ql_outliers = QLabel("—")
        self._ql_outliers.setObjectName("settings-hint")
        self._ql_avg_size = QLabel("—")
        self._ql_avg_size.setObjectName("settings-hint")
        self._ql_coherence = QLabel("coherence: —")
        self._ql_coherence.setObjectName("settings-hint")
        for lbl in (self._ql_topics, self._ql_outliers, self._ql_avg_size, self._ql_coherence):
            qs_lay.addWidget(lbl)
        qs_lay.addStretch(1)
        self._quality_strip.setVisible(False)
        results_vlay.addWidget(self._quality_strip)

        # ── Filter bar (shown when results are loaded) ─────────────────────
        self._filter_bar = QFrame()
        self._filter_bar.setObjectName("topics-filter-bar")
        fb_lay = QHBoxLayout(self._filter_bar)
        fb_lay.setContentsMargins(4, 2, 4, 2)
        fb_lay.setSpacing(10)
        fb_src_lbl = QLabel("Source:")
        fb_src_lbl.setObjectName("settings-label")
        fb_lay.addWidget(fb_src_lbl)
        self._filter_source_combo = QComboBox()
        self._filter_source_combo.setObjectName("settings-input")
        self._filter_source_combo.setMinimumWidth(180)
        self._filter_source_combo.currentIndexChanged.connect(self._apply_filters)
        fb_lay.addWidget(self._filter_source_combo)
        fb_min_lbl = QLabel("Min size:")
        fb_min_lbl.setObjectName("settings-label")
        fb_lay.addWidget(fb_min_lbl)
        self._filter_minsize_spin = QSpinBox()
        self._filter_minsize_spin.setObjectName("settings-input")
        self._filter_minsize_spin.setMinimum(1)
        self._filter_minsize_spin.setValue(1)
        self._filter_minsize_spin.setFixedWidth(60)
        self._filter_minsize_spin.valueChanged.connect(self._apply_filters)
        fb_lay.addWidget(self._filter_minsize_spin)
        fb_lay.addStretch(1)
        self._filter_bar.setVisible(False)
        results_vlay.addWidget(self._filter_bar)

        # Inset panel for scroll content (nested box inside the results card)
        results_body = QFrame()
        results_body.setObjectName("topics-results-body")
        results_body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        results_body_lay = QVBoxLayout(results_body)
        results_body_lay.setContentsMargins(10, 10, 10, 10)
        results_body_lay.setSpacing(0)

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._results_scroll.setAttribute(Qt.WA_StyledBackground, True)
        self._results_inner = QWidget()
        self._results_inner.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._results_inner_lay = QVBoxLayout(self._results_inner)
        self._results_inner_lay.setContentsMargins(12, 0, 12, 0)
        self._results_inner_lay.setSpacing(8)
        self._add_empty_results_placeholder()
        self._results_scroll.setWidget(self._results_inner)
        results_body_lay.addWidget(self._results_scroll, 1)

        # ── Inner splitter: map (left) | detail (right) — shown when results load ──
        self._inner_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._inner_splitter.setChildrenCollapsible(False)
        self._inner_splitter.setHandleWidth(6)
        self._inner_splitter.setVisible(False)

        map_frame = QFrame()
        map_frame.setObjectName("topics-map-frame")
        self._map_frame_lay = QVBoxLayout(map_frame)
        self._map_frame_lay.setContentsMargins(0, 0, 0, 0)
        self._map_frame_lay.setSpacing(0)

        detail_frame = QFrame()
        detail_frame.setObjectName("topics-detail-pane")
        detail_frame_lay = QVBoxLayout(detail_frame)
        detail_frame_lay.setContentsMargins(0, 0, 0, 0)
        detail_frame_lay.setSpacing(0)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_inner = QWidget()
        self._detail_inner_lay = QVBoxLayout(detail_inner)
        self._detail_inner_lay.setContentsMargins(12, 8, 12, 12)
        self._detail_inner_lay.setSpacing(10)
        self._detail_inner_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        detail_scroll.setWidget(detail_inner)
        detail_frame_lay.addWidget(detail_scroll, 1)

        self._inner_splitter.addWidget(map_frame)
        self._inner_splitter.addWidget(detail_frame)
        self._inner_splitter.setStretchFactor(0, 1)
        self._inner_splitter.setStretchFactor(1, 1)

        results_body_lay.addWidget(self._inner_splitter, 1)
        results_vlay.addWidget(results_body, 1)

        # AI Assistant panel (third pane)
        ai_card = QFrame()
        ai_card.setObjectName("settings-card")
        ai_card_lay = QVBoxLayout(ai_card)
        ai_card_lay.setContentsMargins(0, 0, 0, 0)
        ai_card_lay.setSpacing(0)

        theme = self._theme_getter() if self._theme_getter else "light"
        self._ai_panel = LLMAssistantPanel(
            theme=theme,
            system_prompt=_TOPIC_SYSTEM,
            quick_actions=TOPIC_QUICK_ACTIONS,
        )
        ai_card_lay.addWidget(self._ai_panel)

        splitter.addWidget(results_frame)
        splitter.addWidget(ai_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        outer.addWidget(splitter, 1)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if not self._did_equal_topic_split and self._results_ai_splitter is not None:
            QTimer.singleShot(0, self._apply_equal_results_ai_split)

    def _apply_equal_results_ai_split(self) -> None:
        sp = self._results_ai_splitter
        if sp is None or self._did_equal_topic_split:
            return
        total = sp.width()
        if total < 48:
            QTimer.singleShot(0, self._apply_equal_results_ai_split)
            return
        gap = sp.handleWidth()
        inner = total - gap
        half = inner // 2
        sp.setSizes([half, inner - half])
        self._did_equal_topic_split = True

    def _add_empty_results_placeholder(self) -> None:
        self._no_results_lbl = QLabel("Run the pipeline to see topic results here.")
        self._no_results_lbl.setObjectName("topics-results-empty")
        self._no_results_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_results_lbl.setWordWrap(True)
        self._no_results_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._results_inner_lay.addStretch(1)
        self._results_inner_lay.addWidget(self._no_results_lbl)
        self._results_inner_lay.addStretch(1)

    # ── Live progress feed ────────────────────────────────────────────────

    def _show_progress_in_results(self, show_labeling: bool) -> None:
        """Replace the results area content with the stage-checklist widget."""
        while self._results_inner_lay.count() > 0:
            item = self._results_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._show_labeling_stage = show_labeling
        self._stage_rows = []
        self._stage_active_key = None
        self._stage_start_times = {}
        self._spinner_frame = 0

        prog = QFrame()
        prog.setObjectName("topics-progress-widget")
        prog_lay = QVBoxLayout(prog)
        prog_lay.setContentsMargins(20, 20, 20, 20)
        prog_lay.setSpacing(12)

        header_lbl = QLabel("Pipeline running…")
        header_lbl.setObjectName("section-title")
        prog_lay.addWidget(header_lbl)

        stages = [
            ("loading", "Loading transcripts"),
            ("preprocessing", "Preprocessing"),
            ("bertopic", "BERTopic" + (" + LLM labeling" if show_labeling else "")),
            ("done", "Done"),
        ]

        for key, label in stages:
            row_w = QWidget()
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 2, 0, 2)
            row_lay.setSpacing(10)

            icon_lbl = QLabel("◦")
            icon_lbl.setFixedWidth(16)
            icon_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; background: transparent;")

            name_lbl = QLabel(label)
            name_lbl.setObjectName("settings-label")

            time_lbl = QLabel("—")
            time_lbl.setObjectName("settings-hint")
            time_lbl.setFixedWidth(44)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            row_lay.addWidget(icon_lbl)
            row_lay.addWidget(name_lbl, 1)
            row_lay.addWidget(time_lbl)
            prog_lay.addWidget(row_w)
            self._stage_rows.append((key, icon_lbl, time_lbl))

        prog_lay.addStretch(1)
        self._results_inner_lay.addWidget(prog)
        self._results_inner_lay.addStretch(1)

        if self._spinner_timer:
            self._spinner_timer.stop()
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(100)

        if self._elapsed_timer:
            self._elapsed_timer.stop()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._elapsed_timer.start(1000)

        self._advance_stage("loading")

    def _advance_stage(self, key: str) -> None:
        """Mark the current active stage done and activate `key`."""
        now = time.time()
        if self._stage_active_key is not None:
            elapsed = now - self._stage_start_times.get(self._stage_active_key, now)
            for skey, icon_lbl, time_lbl in self._stage_rows:
                if skey == self._stage_active_key:
                    icon_lbl.setText("✓")
                    icon_lbl.setStyleSheet("color: #22c55e; font-size: 13px; background: transparent;")
                    time_lbl.setText(_fmt_elapsed(elapsed))
                    break

        self._stage_active_key = key
        self._stage_start_times[key] = now
        for skey, icon_lbl, time_lbl in self._stage_rows:
            if skey == key:
                icon_lbl.setText(_SPINNER_CHARS[0])
                icon_lbl.setStyleSheet("color: #2563eb; font-size: 13px; background: transparent;")
                time_lbl.setText("0:00")
                break

    def _tick_spinner(self) -> None:
        if not self._stage_active_key:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_CHARS)
        ch = _SPINNER_CHARS[self._spinner_frame]
        for skey, icon_lbl, _ in self._stage_rows:
            if skey == self._stage_active_key:
                icon_lbl.setText(ch)
                break

    def _tick_elapsed(self) -> None:
        if not self._stage_active_key:
            return
        start = self._stage_start_times.get(self._stage_active_key)
        if start is None:
            return
        for skey, _, time_lbl in self._stage_rows:
            if skey == self._stage_active_key:
                time_lbl.setText(_fmt_elapsed(time.time() - start))
                break

    def _finalize_stages(self, success: bool) -> None:
        """Stop timers and mark the active stage done (✓) or failed (✗)."""
        if self._spinner_timer:
            self._spinner_timer.stop()
            self._spinner_timer = None
        if self._elapsed_timer:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

        if not self._stage_active_key:
            return
        now = time.time()
        elapsed = now - self._stage_start_times.get(self._stage_active_key, now)
        for skey, icon_lbl, time_lbl in self._stage_rows:
            if skey == self._stage_active_key:
                if success:
                    icon_lbl.setText("✓")
                    icon_lbl.setStyleSheet("color: #22c55e; font-size: 13px; background: transparent;")
                else:
                    icon_lbl.setText("✗")
                    icon_lbl.setStyleSheet("color: #ef4444; font-size: 13px; background: transparent;")
                time_lbl.setText(_fmt_elapsed(elapsed))
                break
        self._stage_active_key = None

    # ── Collapsible options panel ─────────────────────────────────────────

    def _toggle_options_panel(self) -> None:
        if self._options_body is None or self._options_chevron is None:
            return
        visible = self._options_body.isVisible()
        self._options_body.setVisible(not visible)
        self._options_chevron.setText("▾" if not visible else "▸")

    def _collapse_options_panel(self) -> None:
        if self._options_body and self._options_body.isVisible():
            self._options_body.setVisible(False)
            if self._options_chevron:
                self._options_chevron.setText("▸")

    # ── Quality strip helpers ─────────────────────────────────────────────

    def _update_quality_strip(self, summary: list[dict]) -> None:
        if self._quality_strip is None:
            return
        n = len(summary)
        if n == 0:
            self._quality_strip.setVisible(False)
            return
        total_segs = sum(e.get("segment_count", 0) for e in summary)
        avg = total_segs / n if n else 0
        self._ql_topics.setText(f"{n} topic{'s' if n != 1 else ''}")
        self._ql_outliers.setText(f"outliers: unknown")
        self._ql_avg_size.setText(f"avg size: {avg:.1f} segs")
        self._ql_coherence.setText("coherence: —")
        self._quality_strip.setVisible(True)

    # ── Filter bar helpers ────────────────────────────────────────────────

    def _update_filter_bar(self, summary: list[dict]) -> None:
        if self._filter_bar is None or self._filter_source_combo is None:
            return
        sources: set[str] = set()
        for entry in summary:
            for sf in entry.get("source_files", []):
                if sf:
                    sources.add(sf)
        self._filter_source_combo.blockSignals(True)
        self._filter_source_combo.clear()
        self._filter_source_combo.addItem("All sources", None)
        for src in sorted(sources):
            self._filter_source_combo.addItem(src, src)
        self._filter_source_combo.blockSignals(False)
        if self._filter_minsize_spin:
            self._filter_minsize_spin.setValue(1)
        self._filter_bar.setVisible(len(sources) > 0)

    def _apply_filters(self) -> None:
        if not self._current_summary:
            return
        src_filter = (
            self._filter_source_combo.currentData()
            if self._filter_source_combo else None
        )
        min_size = self._filter_minsize_spin.value() if self._filter_minsize_spin else 1

        filtered = [
            e for e in self._current_summary
            if e.get("segment_count", 0) >= min_size
            and (
                src_filter is None
                or src_filter in (e.get("source_files") or [])
            )
        ]
        # Dual-pane view: update map + detail; fallback to card list when splitter not visible
        if self._inner_splitter and self._inner_splitter.isVisible():
            self._redraw_map_for_filter(filtered)
        else:
            self._render_topic_cards(filtered, self._current_source_path)

    def _render_topic_cards(self, summary: list[dict], source_path: str) -> None:
        """Render (or re-render) only the scrollable card area; leaves quality/filter intact."""
        while self._results_inner_lay.count() > 0:
            item = self._results_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not summary:
            lbl = QLabel("No topics match the current filter.")
            lbl.setObjectName("topics-results-empty")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._results_inner_lay.addStretch(1)
            self._results_inner_lay.addWidget(lbl)
            self._results_inner_lay.addStretch(1)
            return

        src_lbl = QLabel(f"Source: {os.path.basename(source_path)}")
        src_lbl.setObjectName("settings-label")
        self._results_inner_lay.addWidget(src_lbl)
        for entry in summary:
            card = self._make_topic_card(entry)
            self._results_inner_lay.addWidget(card)
        self._results_inner_lay.addStretch(1)

    # ── Dual-pane map view ────────────────────────────────────────────────

    def _launch_results_view(self, summary: list[dict]) -> None:
        """Switch the results area from scroll/card view to the map + detail split."""
        if not summary or self._inner_splitter is None:
            return
        self._results_scroll.setVisible(False)
        self._inner_splitter.setVisible(True)
        if not self._detail_splitter_set:
            QTimer.singleShot(0, self._set_inner_split)
        self._show_map_loading()
        self._on_topic_selected(0)
        self._launch_map_worker(summary)

    def _set_inner_split(self) -> None:
        sp = self._inner_splitter
        if sp is None or self._detail_splitter_set:
            return
        total = sp.width()
        if total < 48:
            QTimer.singleShot(0, self._set_inner_split)
            return
        gap = sp.handleWidth()
        inner = total - gap
        left = int(inner * 0.45)
        sp.setSizes([left, inner - left])
        self._detail_splitter_set = True

    def _show_map_loading(self) -> None:
        if self._map_frame_lay is None:
            return
        while self._map_frame_lay.count() > 0:
            item = self._map_frame_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        lbl = QLabel("Computing topic map…")
        lbl.setObjectName("topics-results-empty")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._map_frame_lay.addWidget(lbl)

    def _launch_map_worker(self, summary: list[dict]) -> None:
        if self._map_worker and self._map_worker.isRunning():
            return
        input_path = self._input_edit.text().strip()
        stem = self._output_stem_for_input(input_path) if input_path else None
        if not stem:
            self._on_map_failed("Could not determine model path from input selection")
            return
        model_path = os.path.join(_OUTPUT_DIR, f"{stem}_topic_model")
        if not os.path.exists(model_path):
            self._on_map_failed(f"Saved model not found at {model_path}")
            return
        self._map_worker = _TopicMapWorker(model_path, summary, parent=self)
        self._map_worker.map_ready.connect(self._on_map_ready)
        self._map_worker.map_failed.connect(self._on_map_failed)
        self._map_worker.start()

    def _on_map_ready(self, topic_data: list[dict]) -> None:
        self._map_topic_data = topic_data
        self._map_worker = None
        self._draw_scatter_map(topic_data, selected_idx=self._selected_topic_idx)
        self._on_topic_selected(self._selected_topic_idx)

    def _on_map_failed(self, error_msg: str) -> None:
        print(f"[map-worker] degrading to fallback: {error_msg}", file=sys.stderr, flush=True)
        self._map_worker = None
        self._map_topic_data = []
        self._draw_fallback_map(self._current_summary)

    def _draw_scatter_map(self, topic_data: list[dict], selected_idx: int = 0) -> None:
        if self._map_frame_lay is None:
            return
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except ImportError as exc:
            print(f"[map] matplotlib unavailable: {exc}", file=sys.stderr, flush=True)
            self._draw_fallback_map(self._current_summary)
            return

        while self._map_frame_lay.count() > 0:
            item = self._map_frame_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._map_fig = None
        self._map_ax = None
        self._map_canvas = None

        theme = self._theme_getter() if self._theme_getter else "light"
        dark = theme == "dark"
        bg = "#141720" if dark else "#f8fafc"
        fg = "#94a3b8" if dark else "#64748b"

        _PALETTE = [
            "#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b",
            "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
        ]

        fig = Figure(facecolor=bg, tight_layout=True)
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg)
        ax.axis("off")

        for i, d in enumerate(topic_data):
            size = max(60, min(800, d["count"] * 30))
            col = _PALETTE[i % len(_PALETTE)]
            is_sel = (i == selected_idx)
            ax.scatter(
                d["x"], d["y"], s=size, c=col,
                alpha=1.0 if is_sel else 0.65,
                linewidths=2.5 if is_sel else 0,
                edgecolors="#ffffff" if is_sel else "none",
                zorder=2,
            )
            short_label = str(d["topic_id"])
            if d.get("label"):
                short_label += f"\n{d['label'][:10]}"
            ax.text(
                d["x"], d["y"], short_label,
                ha="center", va="center", fontsize=6.5,
                color="#ffffff", fontweight="bold", zorder=3,
            )

        canvas = FigureCanvasQTAgg(fig)
        canvas.setObjectName("topics-map-canvas")
        self._map_fig = fig
        self._map_ax = ax
        self._map_canvas = canvas
        canvas.mpl_connect("button_press_event", self._on_map_click)
        self._map_frame_lay.addWidget(canvas, 1)
        canvas.draw()

    def _draw_fallback_map(self, summary: list[dict]) -> None:
        if self._map_frame_lay is None:
            return
        while self._map_frame_lay.count() > 0:
            item = self._map_frame_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        fb_scroll = QScrollArea()
        fb_scroll.setWidgetResizable(True)
        fb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fb_inner = QWidget()
        fb_lay = QVBoxLayout(fb_inner)
        fb_lay.setContentsMargins(12, 12, 12, 12)
        fb_lay.setSpacing(6)

        note = QLabel("Topic overview (distance map unavailable — see stderr for details)")
        note.setObjectName("settings-hint")
        note.setWordWrap(True)
        fb_lay.addWidget(note)

        for i, entry in enumerate(summary):
            tid = entry.get("topic_id", "?")
            label = entry.get("generated_label") or ""
            count = entry.get("segment_count", 0)
            txt = f"Topic {tid}"
            if label:
                txt += f"  —  {label}"
            txt += f"   ({count} seg{'s' if count != 1 else ''})"
            btn = QPushButton(txt)
            btn.setObjectName("add-btn")
            btn.clicked.connect(lambda _, idx=i: self._on_topic_selected(idx))
            fb_lay.addWidget(btn)

        fb_lay.addStretch(1)
        fb_scroll.setWidget(fb_inner)
        self._map_frame_lay.addWidget(fb_scroll, 1)

    def _on_map_click(self, event) -> None:
        if event.inaxes != self._map_ax or not self._map_topic_data:
            return
        if event.xdata is None or event.ydata is None:
            return
        best_idx = 0
        best_d = float("inf")
        for i, d in enumerate(self._map_topic_data):
            dist = (d["x"] - event.xdata) ** 2 + (d["y"] - event.ydata) ** 2
            if dist < best_d:
                best_d = dist
                best_idx = i
        self._on_topic_selected(best_idx)

    def _on_topic_selected(self, idx: int) -> None:
        self._selected_topic_idx = idx
        if self._detail_inner_lay is None:
            return

        # Resolve the topic entry (prefer worker data which has keyword_weights)
        if self._map_topic_data and idx < len(self._map_topic_data):
            data = dict(self._map_topic_data[idx])
            # Merge full JSON entry fields (examples, source_files, etc.)
            tid = data.get("topic_id")
            for entry in self._current_summary:
                if entry.get("topic_id") == tid:
                    for k, v in entry.items():
                        data.setdefault(k, v)
                    break
        elif idx < len(self._current_summary):
            data = self._current_summary[idx]
        else:
            return

        # Clear detail pane
        while self._detail_inner_lay.count() > 0:
            item = self._detail_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._build_detail_content(data)

        # Redraw map with new selection (scatter map only)
        if self._map_topic_data and self._map_canvas:
            self._draw_scatter_map(self._map_topic_data, selected_idx=idx)

    def _build_detail_content(self, data: dict) -> None:
        if self._detail_inner_lay is None:
            return
        lay = self._detail_inner_lay
        tid = data.get("topic_id", "?")
        label = data.get("generated_label") or data.get("label") or ""
        count = data.get("segment_count") or data.get("count") or 0
        keywords = data.get("keywords", [])
        kw_weights = data.get("keyword_weights", [])
        examples = data.get("examples", [])
        source_files = data.get("source_files", [])

        # Header
        hdr = QHBoxLayout()
        id_lbl = QLabel(f"Topic {tid}")
        id_lbl.setObjectName("section-title")
        hdr.addWidget(id_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        if label:
            badge = QLabel(label)
            badge.setStyleSheet(
                "background-color: #2563eb; color: #fff; border-radius: 10px;"
                " padding: 2px 10px; font-size: 11px; font-weight: 600;"
            )
            hdr.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addStretch(1)
        cnt_lbl = QLabel(f"{count} seg{'s' if count != 1 else ''}")
        cnt_lbl.setObjectName("settings-hint")
        hdr.addWidget(cnt_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        # Ask AI button
        ask_btn = QPushButton("Ask AI")
        ask_btn.setObjectName("topics-ask-ai-btn")
        ask_btn.setFixedHeight(26)
        ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ask_btn.clicked.connect(lambda: self._ask_ai_about_topic(data))
        hdr.addWidget(ask_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        lay.addLayout(hdr)

        # Keyword bar chart (matplotlib) when weights available, else chips
        if kw_weights:
            self._add_keyword_barchart(lay, kw_weights[:8])
        elif keywords:
            kw_lbl = QLabel("  ·  ".join(keywords))
            kw_lbl.setObjectName("settings-label")
            kw_lbl.setWordWrap(True)
            lay.addWidget(kw_lbl)

        # Excerpts (clickable)
        if examples:
            exc_lbl = QLabel("Representative excerpts")
            exc_lbl.setObjectName("settings-hint")
            lay.addWidget(exc_lbl)
            for i, ex in enumerate(examples[:5]):
                ex_text = f'"{ex[:240]}{"…" if len(ex) > 240 else ""}"'
                ex_lbl = QLabel(ex_text)
                ex_lbl.setObjectName("settings-hint")
                ex_lbl.setWordWrap(True)
                ex_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                src = source_files[i] if i < len(source_files) else None

                def open_exc(event, excerpt=ex, s=src):
                    self._open_excerpt_in_transcript(excerpt, s)

                ex_lbl.mousePressEvent = open_exc
                lay.addWidget(ex_lbl)

        lay.addStretch(1)

    def _add_keyword_barchart(self, parent_lay: QVBoxLayout, kw_weights: list) -> None:
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
        except ImportError:
            words = [w for w, _ in kw_weights]
            parent_lay.addWidget(QLabel("  ·  ".join(words)))
            return

        theme = self._theme_getter() if self._theme_getter else "light"
        dark = theme == "dark"
        bg = "#141720" if dark else "#f8fafc"
        bar_col = "#4c78a8"
        fg = "#94a3b8" if dark else "#475569"

        words = [w for w, _ in kw_weights]
        vals = [max(0.0, float(v)) for _, v in kw_weights]
        if not vals or max(vals) == 0:
            parent_lay.addWidget(QLabel("  ·  ".join(words)))
            return

        fig = Figure(figsize=(3, len(words) * 0.28 + 0.3), facecolor=bg)
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg)
        bars = ax.barh(range(len(words)), vals, color=bar_col, height=0.6)
        ax.set_yticks(range(len(words)))
        ax.set_yticklabels(words, color=fg, fontsize=8)
        ax.tick_params(axis="x", colors=fg, labelsize=7)
        ax.invert_yaxis()
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.xaxis.set_visible(False)
        fig.subplots_adjust(left=0.45, right=0.98, top=0.98, bottom=0.05)

        canvas = FigureCanvasQTAgg(fig)
        max_h = min(220, len(words) * 26 + 20)
        canvas.setMaximumHeight(max_h)
        parent_lay.addWidget(canvas)
        canvas.draw()

    def _ask_ai_about_topic(self, data: dict) -> None:
        tid = data.get("topic_id", "?")
        keywords = data.get("keywords", [])
        examples = data.get("examples", [])
        kw_str = ", ".join(keywords[:6]) if keywords else "(none)"
        ex_lines = "\n".join(
            f"- {ex[:200]}" for ex in examples[:2] if ex
        )
        prompt = (
            f"Tell me about Topic {tid}.\n\n"
            f"Keywords: {kw_str}\n\n"
            f"Representative excerpts:\n{ex_lines}"
        )
        self._ai_panel.prefill_input(prompt)

    def _redraw_map_for_filter(self, filtered_summary: list[dict]) -> None:
        """Narrow the map to filtered topic IDs; keep detail for currently selected if visible."""
        if not self._map_topic_data:
            self._draw_fallback_map(filtered_summary)
            return
        filtered_ids = {e.get("topic_id") for e in filtered_summary}
        filtered_data = [d for d in self._map_topic_data if d.get("topic_id") in filtered_ids]
        if not filtered_data:
            self._draw_fallback_map(filtered_summary)
            return
        # Keep selected idx valid
        sel_tid = (
            self._map_topic_data[self._selected_topic_idx].get("topic_id")
            if self._map_topic_data and self._selected_topic_idx < len(self._map_topic_data)
            else None
        )
        new_sel = 0
        for i, d in enumerate(filtered_data):
            if d.get("topic_id") == sel_tid:
                new_sel = i
                break
        self._draw_scatter_map(filtered_data, selected_idx=new_sel)
        self._on_topic_selected_by_entry(new_sel, filtered_data)

    def _on_topic_selected_by_entry(self, idx: int, topic_data: list[dict]) -> None:
        """Select topic from an arbitrary topic_data list (used after filter)."""
        if not topic_data or idx >= len(topic_data):
            return
        self._selected_topic_idx = idx
        if self._detail_inner_lay is None:
            return
        data = dict(topic_data[idx])
        tid = data.get("topic_id")
        for entry in self._current_summary:
            if entry.get("topic_id") == tid:
                for k, v in entry.items():
                    data.setdefault(k, v)
                break
        while self._detail_inner_lay.count() > 0:
            item = self._detail_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._build_detail_content(data)

    def refresh_action_icons(self) -> None:
        theme = self._theme_getter() if self._theme_getter else "light"
        col = "#94a3b8" if theme == "dark" else "#475569"
        self._open_output_btn.setIcon(make_folder_open_icon(size=18, color_hex=col))
        self._open_output_btn.setIconSize(QSize(18, 18))

    def set_input_path(self, path: str) -> None:
        """Load a transcript path from another GUI page."""
        if not path:
            return

        self._input_edit.setText(path)
        self._on_input_path_committed()
        self._append_log(
            f"[info] Loaded transcript for topic modeling: {os.path.basename(path)}",
            "#64748b",
        )

    def refresh_theme(self) -> None:
        """Align topic page with app light/dark after MainWindow applies theme."""
        self.refresh_action_icons()
        theme = self._theme_getter() if self._theme_getter else "light"
        self._ai_panel.update_theme(theme)
        if self._map_topic_data:
            self._draw_scatter_map(self._map_topic_data, selected_idx=self._selected_topic_idx)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _sync_gpt4all_model_enabled(self, checked: bool) -> None:
        self._model_edit.setEnabled(checked)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select transcript file",
            self._input_edit.text().strip() or _PROJECT_ROOT,
            "Text files (*.txt);;All Files (*)",
        )
        if path:
            self._input_edit.setText(path)
            self._on_input_path_committed()

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select transcript folder",
            self._input_edit.text().strip() or _PROJECT_ROOT,
        )
        if path:
            self._input_edit.setText(path)
            self._on_input_path_committed()

    def _on_input_path_committed(self) -> None:
        """Refresh anything that depends on the current input path."""
        path = self._input_edit.text().strip()
        if path == self._last_transcript_path:
            return
        self._last_transcript_path = path
        self._refresh_speaker_dropdown()
        self._refresh_ai_transcript_context(path)
        if path and os.path.exists(path):
            self._load_results_for_input(path, warn_if_missing=False)
        else:
            self._topics_context = ""
            self._push_ai_context()
            self._clear_results()

    def _extract_speaker_from_line(self, line: str) -> str | None:
        """
        Extract speaker labels from transcript lines like:

        [SPEAKER_00]: text
        SPEAKER_00: text
        [00:00:02.039 → 00:00:17.412] [SPEAKER_00]: text
        [SPEAKER_00]: [00:00:02.039] text
        Interviewer: text
        Participant: text
        """
        line = line.strip()

        if not line:
            return None

        # Remove one or more leading timestamps.
        while True:
            timestamp_match = re.match(
                r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                r"(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\]\s*",
                line,
            )

            if not timestamp_match:
                break

            line = line[timestamp_match.end():].strip()

        # Match speaker labels after optional timestamp removal.
        speaker_match = re.match(r"^\[?([^\]:]+)\]?:\s*", line)

        if not speaker_match:
            return None

        speaker = speaker_match.group(1).strip()

        # Avoid accidentally treating timestamps or empty labels as speakers.
        if not speaker:
            return None

        if re.match(r"^\d{2}:\d{2}:\d{2}", speaker):
            return None

        return speaker

    def _collect_speaker_labels(self, input_path: str) -> list[str]:
        """Collect unique speaker labels from a selected .txt file or folder."""
        speakers = set()

        if os.path.isfile(input_path):
            files = [input_path]
        elif os.path.isdir(input_path):
            files = [
                os.path.join(input_path, fn)
                for fn in os.listdir(input_path)
                if fn.lower().endswith(".txt")
            ]
        else:
            return []

        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        speaker = self._extract_speaker_from_line(line)
                        if speaker:
                            speakers.add(speaker)
            except Exception as e:
                self._append_log(
                    f"[warn] Could not scan speakers from {os.path.basename(file_path)}: {e}",
                    "#eab308",
                )

        return sorted(speakers)

    def _refresh_speaker_dropdown(self) -> None:
        """Populate the interviewer dropdown using speaker labels found in the selected input."""
        input_path = self._input_edit.text().strip()

        current_value = self._speaker_combo.currentData()

        self._speaker_combo.clear()
        self._speaker_combo.addItem("None — include all speakers", None)

        if not input_path or not os.path.exists(input_path):
            return

        speakers = self._collect_speaker_labels(input_path)

        for speaker in speakers:
            self._speaker_combo.addItem(speaker, speaker)

        # Restore previous selection if it still exists.
        if current_value:
            index = self._speaker_combo.findData(current_value)
            if index >= 0:
                self._speaker_combo.setCurrentIndex(index)

        if speakers:
            self._append_log(
                f"[info] Found speaker labels: {', '.join(speakers)}",
                "#64748b",
            )
        else:
            self._append_log(
                "[warn] No speaker labels found. You can still run topic modeling with all speakers included.",
                "#eab308",
            )

    # ── AI context wiring ────────────────────────────────────────────────

    def _list_transcript_files(self, path: str) -> list[str]:
        if os.path.isfile(path):
            return [path]
        if os.path.isdir(path):
            return sorted(
                os.path.join(path, fn)
                for fn in os.listdir(path)
                if fn.lower().endswith(".txt")
            )
        return []

    def _speaker_stats_from_text(self, text: str) -> str:
        """Return a compact speaker-turn summary for one transcript."""
        from collections import Counter
        counts: Counter[str] = Counter()
        for line in text.splitlines():
            speaker = self._extract_speaker_from_line(line)
            if speaker:
                counts[speaker] += 1
        if not counts:
            return ""
        parts = [f"{spk} ({n} turn{'s' if n != 1 else ''})" for spk, n in counts.most_common()]
        return "Speakers: " + ", ".join(parts)

    def _build_transcript_context(self, path: str) -> str:
        """Read the selected transcript(s) and shape them into AI context."""
        files = self._list_transcript_files(path)
        if not files:
            return ""

        header_lines = ["## TRANSCRIPT"]
        chunks: list[str] = []
        total = 0
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except Exception as e:
                self._append_log(f"[warn] Could not read {fp} for AI context: {e}", "#eab308")
                continue
            body = body.strip()
            if not body:
                continue
            stats = self._speaker_stats_from_text(body)
            truncated = False
            if len(body) > _AI_CONTEXT_PER_FILE_CHARS:
                body = body[:_AI_CONTEXT_PER_FILE_CHARS]
                truncated = True
            file_header = f"### File: {os.path.basename(fp)}"
            if truncated:
                file_header += "  (truncated to first ~8 000 chars)"
            if stats:
                file_header += f"\n{stats}"
            piece = f"{file_header}\n\n{body}"
            if total + len(piece) > _AI_CONTEXT_TOTAL_CHARS:
                chunks.append(
                    f"### File: {os.path.basename(fp)}\n[omitted — context budget reached]"
                )
                break
            chunks.append(piece)
            total += len(piece)

        if not chunks:
            return ""
        return "\n\n".join(header_lines + chunks)

    def _refresh_ai_transcript_context(self, path: str) -> None:
        self._transcript_context = self._build_transcript_context(path) if path else ""
        self._push_ai_context()

    def _push_ai_context(self) -> None:
        parts: list[str] = []
        if self._topics_context:
            parts.append(self._topics_context)
        if self._transcript_context:
            parts.append(self._transcript_context)
        self._ai_panel.set_context("\n\n".join(parts))

    def _open_output_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        out = _OUTPUT_DIR
        os.makedirs(out, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _append_log(self, text: str, color: str | None = None) -> None:
        """Echo pipeline/status lines to stderr (visible when launching from a terminal)."""
        del color  # previously used by the removed log QTextEdit for coloring
        print(text.rstrip("\n"), file=sys.stderr, flush=True)

    def _on_run_clicked(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._append_log("[warn] Pipeline is already running.", "#eab308")
            QMessageBox.warning(self, "Topic Modeling", "The pipeline is already running.")
            return

        input_path = self._input_edit.text().strip()
        if not input_path:
            self._append_log("[error] Please select an input transcript file or folder.", "#ef4444")
            QMessageBox.warning(
                self,
                "Topic Modeling",
                "Please select an input transcript file or folder.",
            )
            return
        if not os.path.exists(input_path):
            self._append_log(f"[error] Path does not exist: {input_path}", "#ef4444")
            QMessageBox.warning(
                self,
                "Topic Modeling",
                f"That path does not exist:\n{input_path}",
            )
            return
        if not os.path.isfile(_PIPELINE_SCRIPT):
            msg = (
                f"Pipeline script not found at:\n{_PIPELINE_SCRIPT}\n\n"
                "Make sure topic_modeling/src/pipeline.py exists."
            )
            self._append_log("[error] " + msg.replace("\n", " "), "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", msg)
            return

        self._clear_results()
        # Stale topic results shouldn't bleed into the next conversation;
        # transcript context stays so the user can already chat about the input.
        self._topics_context = ""
        self._push_ai_context()

        python = _resolve_python()
        args = [_PIPELINE_SCRIPT, input_path]

        speaker = self._speaker_combo.currentData()
        if speaker:
            args.append(speaker)

        if self._gpt4all_checkbox.isChecked():
            args.append("--label")
            model = self._model_edit.text().strip() or "mistral-7b-openorca.Q4_0.gguf"
            args.append(model)

        self._append_log(f"[pipeline] Starting: {os.path.basename(input_path)}")
        self._append_log(f"[pipeline] Command: {python} {' '.join(args[1:])}")

        self._process = QProcess(self)
        self._process.setWorkingDirectory(os.path.join(_PROJECT_ROOT, "topic_modeling", "src"))
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.start(python, args)

        if not self._process.waitForStarted(5000):
            err = self._process.errorString()
            self._append_log(f"[error] Failed to start pipeline: {err}", "#ef4444")
            QMessageBox.critical(self, "Topic Modeling", f"Failed to start pipeline:\n{err}")
            self._process = None
        else:
            self._run_btn.setEnabled(False)
            self._run_btn.setText("Running…")
            self._collapse_options_panel()
            self._show_progress_in_results(show_labeling=self._gpt4all_checkbox.isChecked())

    def _on_stdout(self) -> None:
        if not self._process:
            return
        data = self._process.readAllStandardOutput()
        if data:
            for ln in data.data().decode("utf-8", errors="replace").splitlines():
                if ln.strip():
                    self._append_log(ln)
                    stripped = ln.strip()
                    if stripped == "[STAGE] preprocessing":
                        self._advance_stage("preprocessing")
                    elif stripped == "[STAGE] bertopic":
                        self._advance_stage("bertopic")
                    elif stripped == "[STAGE] done":
                        self._advance_stage("done")

    def _on_stderr(self) -> None:
        if not self._process:
            return
        data = self._process.readAllStandardError()
        if data:
            for ln in data.data().decode("utf-8", errors="replace").splitlines():
                if ln.strip():
                    self._append_log(ln)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._run_btn.setEnabled(True)
        self._run_btn.setText("▶  Run Pipeline")
        success = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        self._finalize_stages(success)
        if success:
            self._append_log("[pipeline] Pipeline completed successfully.", "#22c55e")
            QTimer.singleShot(500, self._load_latest_results)
        else:
            msg = f"Pipeline failed (exit code {exit_code})."
            self._append_log(f"[pipeline] {msg}", "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", msg)
        self._process = None

    # ── Results loading ───────────────────────────────────────────────────

    def _clear_results(self) -> None:
        """Reset the results area to idle state."""
        if self._map_worker and self._map_worker.isRunning():
            self._map_worker.map_ready.disconnect()
            self._map_worker.map_failed.disconnect()
            self._map_worker.quit()
            self._map_worker = None
        self._map_topic_data = []
        self._map_fig = None
        self._map_ax = None
        self._map_canvas = None
        self._detail_splitter_set = False

        if self._inner_splitter:
            self._inner_splitter.setVisible(False)
        self._results_scroll.setVisible(True)

        while self._results_inner_lay.count() > 0:
            item = self._results_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        if self._quality_strip:
            self._quality_strip.setVisible(False)
        if self._filter_bar:
            self._filter_bar.setVisible(False)
        self._current_summary = []
        self._add_empty_results_placeholder()

    def _output_stem_for_input(self, input_path: str) -> str | None:
        """Return the output filename stem used by the topic modeling pipeline."""
        if os.path.isfile(input_path):
            return os.path.splitext(os.path.basename(input_path))[0]
        if os.path.isdir(input_path):
            return os.path.basename(os.path.normpath(input_path))
        return None

    def _summary_path_for_input(self, input_path: str) -> str | None:
        stem = self._output_stem_for_input(input_path)
        if not stem:
            return None
        return os.path.join(_OUTPUT_DIR, f"{stem}_topic_summary.json")

    def _load_summary_file(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception as e:
            self._append_log(f"[error] Could not read results: {e}", "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", f"Could not read results:\n{e}")
            return False
        self._render_results(summary, path)
        self._feed_results_to_ai(summary)
        return True

    def _load_results_for_input(self, input_path: str, warn_if_missing: bool) -> bool:
        """Load the existing summary JSON that corresponds to the selected input."""
        summary_path = self._summary_path_for_input(input_path)
        if summary_path and os.path.isfile(summary_path):
            self._append_log(
                f"[info] Loaded topic results: {os.path.basename(summary_path)}",
                "#64748b",
            )
            return self._load_summary_file(summary_path)

        self._clear_results()
        self._topics_context = ""
        self._push_ai_context()

        if warn_if_missing:
            expected = summary_path or _OUTPUT_DIR
            QMessageBox.warning(
                self,
                "Topic Modeling",
                "Pipeline finished but no topic summary JSON was found for the selected input.\n"
                f"Expected:\n{expected}",
            )
        return False

    def _load_latest_results(self) -> None:
        """Load topic results for the selected input, falling back to newest summary."""
        input_path = self._input_edit.text().strip()
        if input_path and os.path.exists(input_path):
            self._load_results_for_input(input_path, warn_if_missing=True)
            return

        out_dir = _OUTPUT_DIR
        if not os.path.isdir(out_dir):
            return
        candidates = [
            os.path.join(out_dir, fn)
            for fn in os.listdir(out_dir)
            if fn.endswith("_topic_summary.json")
        ]
        if not candidates:
            w = "[warn] No topic_summary.json found in output dir."
            self._append_log(w, "#eab308")
            QMessageBox.warning(
                self,
                "Topic Modeling",
                "Pipeline finished but no topic summary JSON was found in the output folder.\n"
                f"Expected files like *_topic_summary.json under:\n{_OUTPUT_DIR}",
            )
            return
        candidates.sort(key=os.path.getmtime, reverse=True)
        latest = candidates[0]
        self._load_summary_file(latest)

    def _feed_results_to_ai(self, summary: list[dict]) -> None:
        """Format topic results as readable context and pass them to the AI panel."""
        if not summary:
            self._topics_context = ""
            self._push_ai_context()
            return

        total_segments = sum(e.get("segment_count", 0) for e in summary)
        lines = [
            "## TOPIC ANALYSIS",
            f"Total topics: {len(summary)}  |  Total segments analysed: {total_segments}",
            "",
        ]
        for entry in summary:
            tid = entry.get("topic_id", "?")
            label = entry.get("generated_label", "")
            count = entry.get("segment_count", 0)
            keywords = entry.get("keywords", [])
            examples = entry.get("examples", [])
            source_files = entry.get("source_files", [])

            heading = f"### Topic {tid}"
            if label:
                heading += f" — {label}"
            heading += f"  ({count} segment{'s' if count != 1 else ''})"
            lines.append(heading)

            if keywords:
                lines.append(f"Keywords: {', '.join(keywords)}")

            # Collect unique source files for this topic
            unique_sources = sorted({s for s in source_files if s})
            if unique_sources:
                lines.append(f"Sources: {', '.join(unique_sources)}")

            if examples:
                lines.append("Representative excerpts:")
                for i, ex in enumerate(examples[:5]):
                    src = source_files[i] if i < len(source_files) else None
                    prefix = f"  [{src}] " if src else "  "
                    lines.append(f'{prefix}"{ex[:300]}{"…" if len(ex) > 300 else ""}"')

            lines.append("")

        self._topics_context = "\n".join(lines)
        self._push_ai_context()

    def load_results_from_file(self, path: str) -> None:
        """Public entry for loading a specific summary JSON (future use)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception as e:
            self._append_log(f"[error] Could not load {path}: {e}", "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", f"Could not load results file:\n{e}")
            return
        self._render_results(summary, path)

    def _render_results(self, summary: list[dict], source_path: str) -> None:
        """Store summary, update quality strip + filter bar, render topic cards."""
        self._current_summary = list(summary)
        self._current_source_path = source_path
        self._update_quality_strip(summary)
        self._update_filter_bar(summary)
        if not summary:
            while self._results_inner_lay.count() > 0:
                item = self._results_inner_lay.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            lbl = QLabel("No topics found in results.")
            lbl.setObjectName("topics-results-empty")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._results_inner_lay.addStretch(1)
            self._results_inner_lay.addWidget(lbl)
            self._results_inner_lay.addStretch(1)
            return
        self._launch_results_view(summary)

    # ── Transcript click-through helpers ──────────────────────────────────

    def _find_transcript_path_for_excerpt(self, source_file: str | None) -> str | None:
        """
        Find the original transcript file based on the GUI input path and source_file saved
        in the topic summary JSON.
        """
        input_path = self._input_edit.text().strip()

        if not input_path:
            return None

        # If user selected one transcript file, use it directly.
        if os.path.isfile(input_path):
            return input_path

        # If user selected a folder, use the source_file stored in the JSON.
        if os.path.isdir(input_path) and source_file:
            candidate = os.path.join(input_path, source_file)
            if os.path.isfile(candidate):
                return candidate

        return None

    def _extract_searchable_text_with_map(
        self,
        raw_line: str,
        display_offset: int,
    ) -> tuple[str, list[int]]:
        """
        Build a cleaned/searchable version of one transcript line while keeping a
        character-level map back to the raw displayed transcript.

        This lets us display speaker labels and timestamps, but still highlight
        the excerpt based on cleaned text.
        """
        line = raw_line.rstrip("\n")

        if not line:
            return "", []

        chars: list[str] = []
        mapping: list[int] = []

        i = 0

        # Remove leading timestamps like:
        # [00:00:02.039 → 00:00:17.412]
        # [00:00:02.039]
        while True:
            timestamp_match = re.match(
                r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                r"(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\]\s*",
                line[i:],
            )

            if not timestamp_match:
                break

            i += timestamp_match.end()

        # Remove leading speaker label like:
        # [SPEAKER_00]:
        # SPEAKER_00:
        # Interviewer:
        speaker_match = re.match(r"\s*\[?[^\]:]+\]?:\s*", line[i:])
        if speaker_match:
            i += speaker_match.end()

        # Walk through the rest of the line and skip inline timestamps too.
        while i < len(line):
            timestamp_match = re.match(
                r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                r"(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\]\s*",
                line[i:],
            )

            if timestamp_match:
                i += timestamp_match.end()
                continue

            chars.append(line[i])
            mapping.append(display_offset + i)
            i += 1

        # Trim leading/trailing whitespace while keeping map aligned.
        start = 0
        end = len(chars)

        while start < end and chars[start].isspace():
            start += 1

        while end > start and chars[end - 1].isspace():
            end -= 1

        cleaned_text = "".join(chars[start:end])
        cleaned_map = mapping[start:end]

        return cleaned_text, cleaned_map

    def _build_transcript_view_data(
        self,
        raw_lines: list[str],
    ) -> tuple[str, str, list[int]]:
        """
        Returns:
          - display_text: raw transcript shown to the user with labels/timestamps
          - search_text: cleaned text used for matching
          - search_to_display: maps each char in search_text back to display_text
        """
        display_text = "".join(raw_lines)

        search_parts: list[str] = []
        search_to_display: list[int] = []

        display_offset = 0

        for idx, raw_line in enumerate(raw_lines):
            cleaned_text, cleaned_map = self._extract_searchable_text_with_map(
                raw_line,
                display_offset,
            )

            if cleaned_text:
                search_parts.append(cleaned_text)
                search_to_display.extend(cleaned_map)

                # Add a newline between searchable lines so multi-line excerpts still match.
                if idx < len(raw_lines) - 1:
                    search_parts.append("\n")

                    # Map the searchable newline to the end of this raw display line.
                    newline_display_pos = display_offset + len(raw_line.rstrip("\n"))
                    search_to_display.append(newline_display_pos)

            display_offset += len(raw_line)

        search_text = "".join(search_parts)

        return display_text, search_text, search_to_display

    def _find_normalized_span(
        self,
        display_text: str,
        excerpt: str,
    ) -> tuple[int, int] | None:
        """
        Find excerpt inside display_text while treating newlines/multiple spaces as normal spaces.
        Returns character start/end positions in display_text.
        """
        target = " ".join(excerpt.split()).lower()

        if not target:
            return None

        normalized_chars = []
        index_map = []
        previous_was_space = False

        for original_index, char in enumerate(display_text):
            if char.isspace():
                if not previous_was_space:
                    normalized_chars.append(" ")
                    index_map.append(original_index)
                    previous_was_space = True
            else:
                normalized_chars.append(char.lower())
                index_map.append(original_index)
                previous_was_space = False

        normalized_text = "".join(normalized_chars)
        start_norm = normalized_text.find(target)

        # If the full excerpt does not match, try matching the first chunk.
        if start_norm == -1 and len(target) > 120:
            target = target[:120]
            start_norm = normalized_text.find(target)

        if start_norm == -1:
            return None

        end_norm = start_norm + len(target) - 1

        if start_norm >= len(index_map) or end_norm >= len(index_map):
            return None

        start_original = index_map[start_norm]
        end_original = index_map[end_norm] + 1

        return start_original, end_original

    def _open_excerpt_in_transcript(
        self,
        excerpt: str,
        source_file: str | None = None,
    ) -> None:
        """
        Open a transcript viewer dialog and highlight the clicked excerpt.

        The popup shows the raw transcript with speaker labels and timestamps,
        but matching is done against a cleaned hidden version.
        """
        transcript_path = self._find_transcript_path_for_excerpt(source_file)

        if not transcript_path:
            msg = "Could not find the original transcript file for this excerpt."
            self._append_log("[error] " + msg, "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", msg)
            return

        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except Exception as e:
            self._append_log(f"[error] Could not open transcript: {e}", "#ef4444")
            QMessageBox.warning(self, "Topic Modeling", f"Could not open transcript:\n{e}")
            return

        display_text, search_text, search_to_display = self._build_transcript_view_data(
            raw_lines
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Transcript excerpt — {os.path.basename(transcript_path)}")
        dialog.setMinimumSize(900, 650)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(os.path.basename(transcript_path))
        title.setObjectName("section-title")
        layout.addWidget(title)

        transcript_view = QTextEdit()
        transcript_view.setReadOnly(True)
        transcript_view.setPlainText(display_text)
        transcript_view.setObjectName("home-file-log")
        layout.addWidget(transcript_view, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("add-btn")
        close_btn.clicked.connect(dialog.close)
        close_row.addWidget(close_btn)

        layout.addLayout(close_row)

        span = self._find_normalized_span(search_text, excerpt)

        if span and search_to_display:
            start_search, end_search = span

            if (
                start_search < len(search_to_display)
                and (end_search - 1) < len(search_to_display)
            ):
                start_display = search_to_display[start_search]
                end_display = search_to_display[end_search - 1] + 1

                cursor = transcript_view.textCursor()
                cursor.setPosition(start_display)
                cursor.setPosition(end_display, QTextCursor.MoveMode.KeepAnchor)

                transcript_view.setTextCursor(cursor)
                transcript_view.ensureCursorVisible()
            else:
                QMessageBox.warning(
                    self,
                    "Topic Modeling",
                    "Transcript opened, but the highlight mapping was out of range.",
                )
        else:
            QMessageBox.warning(
                self,
                "Topic Modeling",
                "Transcript opened, but the exact excerpt could not be highlighted.",
            )

        dialog.exec()

    # ── Topic card rendering ──────────────────────────────────────────────

    def _make_topic_card(self, entry: dict) -> QFrame:
        """Build one compact card for a single BERTopic result entry."""
        card = QFrame()
        card.setObjectName("settings-card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        topic_id = entry.get("topic_id", "?")
        label = entry.get("generated_label") or ""
        count = entry.get("segment_count", 0)
        keywords = entry.get("keywords", [])
        examples = entry.get("examples", [])
        source_files = entry.get("source_files", [])

        # Header row: topic ID + label + segment count badge
        header_row = QHBoxLayout()
        id_lbl = QLabel(f"Topic {topic_id}")
        id_lbl.setObjectName("section-title")
        header_row.addWidget(id_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        if label:
            lbl_badge = QLabel(label)
            lbl_badge.setObjectName("topic-card-label")
            lbl_badge.setStyleSheet(
                "background-color: #2563eb; color: #fff; "
                "border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600;"
            )
            header_row.addWidget(lbl_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        header_row.addStretch(1)
        count_lbl = QLabel(f"{count} segment{'s' if count != 1 else ''}")
        count_lbl.setObjectName("settings-label")
        header_row.addWidget(count_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(header_row)

        # Keywords
        if keywords:
            kw_text = "  ·  ".join(keywords)
            kw_lbl = QLabel(kw_text)
            kw_lbl.setObjectName("settings-label")
            kw_lbl.setWordWrap(True)
            lay.addWidget(kw_lbl)

        # Example excerpts (collapsible via a small toggle)
        if examples:
            examples_widget = QWidget()
            examples_lay = QVBoxLayout(examples_widget)
            examples_lay.setContentsMargins(0, 0, 0, 0)
            examples_lay.setSpacing(6)

            excerpt_labels = []

            for i, ex in enumerate(examples):
                ex_text = f'"{ex[:220]}{"…" if len(ex) > 220 else ""}"'

                ex_lbl = QLabel(ex_text)
                ex_lbl.setObjectName("settings-hint")
                ex_lbl.setWordWrap(True)
                ex_lbl.setCursor(Qt.CursorShape.PointingHandCursor)

                source_file = source_files[i] if i < len(source_files) else None

                def open_this_excerpt(event, excerpt=ex, src=source_file):
                    self._open_excerpt_in_transcript(excerpt, src)

                ex_lbl.mousePressEvent = open_this_excerpt

                # Only show first 3 at first.
                if i >= 3:
                    ex_lbl.setVisible(False)

                excerpt_labels.append(ex_lbl)
                examples_lay.addWidget(ex_lbl)

            lay.addWidget(examples_widget)

            if len(examples) > 3:
                show_more_btn = QPushButton(f"Show more ({len(examples) - 3})")
                show_more_btn.setObjectName("show-more-btn")
                show_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                show_more_btn.setFlat(True)
                show_more_btn.setFixedWidth(135)
                show_more_btn.setStyleSheet(
                    """
                    QPushButton#show-more-btn {
                        background: transparent;
                        border: none;
                        color: #7f8ea3;
                        font-size: 12px;
                        font-weight: 500;
                        padding: 2px 0px;
                        text-align: left;
                    }

                    QPushButton#show-more-btn:hover {
                        color: #9fb3cc;
                        text-decoration: underline;
                    }
                    """
                )

                def toggle_excerpts():
                    showing_more = not excerpt_labels[3].isVisible()

                    for lbl in excerpt_labels[3:]:
                        lbl.setVisible(showing_more)

                    if showing_more:
                        show_more_btn.setText("Show less")
                    else:
                        show_more_btn.setText(f"Show more ({len(examples) - 3})")

                show_more_btn.clicked.connect(toggle_excerpts)
                lay.addWidget(show_more_btn, 0, Qt.AlignmentFlag.AlignLeft)

        return card
