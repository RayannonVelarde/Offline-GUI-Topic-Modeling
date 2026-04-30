"""
Topic Modeling page for the Speech to Text Studio GUI.

Wraps Rayannon's pipeline (topic_modeling/src/pipeline.py) so users can:
  1. Pick a transcript .txt file (or folder of .txt files) from disk.
  2. Optionally specify the interviewer speaker label to exclude.
  3. Optionally enable Ollama LLM labeling and choose the model name.
  4. Run the full pipeline (preprocess → BERTopic) in a subprocess.
  5. View the live log output and the resulting topic summary JSON.
  6. Show more excerpts for each topic.
  7. Click excerpts to open the original transcript and highlight the matching text.
"""

from __future__ import annotations

import json
import os
import re
import sys

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Path resolution: topic_modeling/src lives two levels above this file
# (studio/gui/  →  studio/  →  project root  →  topic_modeling/src)
_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
_STUDIO_DIR = os.path.dirname(_GUI_DIR)
_PROJECT_ROOT = os.path.dirname(_STUDIO_DIR)
_PIPELINE_SCRIPT = os.path.join(_PROJECT_ROOT, "topic_modeling", "src", "pipeline.py")
_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "topic_modeling", "output")

# Use the same venv resolution as studio_engine
def _resolve_python() -> str:
    bin_name = "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    for base in (_STUDIO_DIR, _PROJECT_ROOT):
        candidate = os.path.join(base, ".venv", bin_name)
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


class TopicModelingPage(QFrame):
    """Full topic-modeling pipeline control page."""

    def __init__(self, theme_getter=None, parent=None):
        super().__init__(parent)
        self.setObjectName("topics-page")
        self._theme_getter = theme_getter  # callable() → "light" | "dark"
        self._process: QProcess | None = None

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
        outer.addSpacing(4)

        # ── Options card ─────────────────────────────────────────────────
        options_card = QFrame()
        options_card.setObjectName("settings-card")
        options_lay = QVBoxLayout(options_card)
        options_lay.setContentsMargins(16, 14, 16, 14)
        options_lay.setSpacing(12)

        section_lbl = QLabel("Pipeline options")
        section_lbl.setObjectName("section-title")
        options_lay.addWidget(section_lbl)

        # Input path row
        input_row = QHBoxLayout()
        input_lbl = QLabel("Input (.txt file or folder):")
        input_lbl.setObjectName("settings-label")
        input_lbl.setFixedWidth(220)
        self._input_edit = QLineEdit()
        self._input_edit.setObjectName("settings-input")
        self._input_edit.setPlaceholderText("Select a transcript file or folder…")
        self._input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        browse_file_btn = QPushButton("File…")
        browse_file_btn.setObjectName("add-btn")
        browse_file_btn.setFixedWidth(68)
        browse_file_btn.clicked.connect(self._browse_file)
        browse_folder_btn = QPushButton("Folder…")
        browse_folder_btn.setObjectName("add-btn")
        browse_folder_btn.setFixedWidth(72)
        browse_folder_btn.clicked.connect(self._browse_folder)
        input_row.addWidget(input_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        input_row.addWidget(self._input_edit, 1)
        input_row.addWidget(browse_file_btn, 0)
        input_row.addWidget(browse_folder_btn, 0)
        options_lay.addLayout(input_row)

        # Interviewer speaker row
        spk_row = QHBoxLayout()
        spk_lbl = QLabel("Interviewer speaker label:")
        spk_lbl.setObjectName("settings-label")
        spk_lbl.setFixedWidth(220)
        self._speaker_edit = QLineEdit()
        self._speaker_edit.setObjectName("settings-input")
        self._speaker_edit.setPlaceholderText(
            "e.g. Interviewer or SPEAKER_00  (leave blank to include all speakers)"
        )
        spk_row.addWidget(spk_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        spk_row.addWidget(self._speaker_edit, 1)
        options_lay.addLayout(spk_row)

        # Ollama labeling row
        ollama_row = QHBoxLayout()
        self._ollama_checkbox = QCheckBox("Enable Ollama LLM topic labeling")
        self._ollama_checkbox.setObjectName("job-options-checkbox")
        self._ollama_checkbox.toggled.connect(self._sync_ollama_model_enabled)
        ollama_row.addWidget(self._ollama_checkbox)
        ollama_row.addStretch(1)
        options_lay.addLayout(ollama_row)

        model_row = QHBoxLayout()
        model_lbl = QLabel("Ollama model name:")
        model_lbl.setObjectName("settings-label")
        model_lbl.setFixedWidth(220)
        self._model_edit = QLineEdit("llama3.1")
        self._model_edit.setObjectName("settings-input")
        self._model_edit.setEnabled(False)
        model_row.addWidget(model_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        model_row.addWidget(self._model_edit, 1)
        options_lay.addLayout(model_row)

        outer.addWidget(options_card)

        # ── Run button row ────────────────────────────────────────────────
        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._run_btn = QPushButton("▶  Run Pipeline")
        self._run_btn.setObjectName("start-btn")
        self._run_btn.setAttribute(Qt.WA_StyledBackground, True)
        self._run_btn.setFixedWidth(148)
        self._run_btn.clicked.connect(self._on_run_clicked)
        run_row.addWidget(self._run_btn)
        outer.addLayout(run_row)

        # ── Bottom splitter: log | results ───────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        # Log panel
        log_frame = QFrame()
        log_frame.setObjectName("settings-card")
        log_vlay = QVBoxLayout(log_frame)
        log_vlay.setContentsMargins(14, 12, 14, 12)
        log_vlay.setSpacing(8)
        log_title = QLabel("Pipeline log")
        log_title.setObjectName("section-title")
        log_vlay.addWidget(log_title)
        self._log_edit = QTextEdit()
        self._log_edit.setObjectName("home-file-log")
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(200)
        log_vlay.addWidget(self._log_edit, 1)

        # Results panel
        results_frame = QFrame()
        results_frame.setObjectName("settings-card")
        results_vlay = QVBoxLayout(results_frame)
        results_vlay.setContentsMargins(14, 12, 14, 12)
        results_vlay.setSpacing(8)

        results_header = QHBoxLayout()
        results_title = QLabel("Topic results")
        results_title.setObjectName("section-title")
        results_header.addWidget(results_title, 1)
        self._open_output_btn = QPushButton("Open output folder")
        self._open_output_btn.setObjectName("add-btn")
        self._open_output_btn.clicked.connect(self._open_output_folder)
        results_header.addWidget(self._open_output_btn, 0)
        results_vlay.addLayout(results_header)

        # Scrollable topic cards area
        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._results_inner = QWidget()
        self._results_inner_lay = QVBoxLayout(self._results_inner)
        self._results_inner_lay.setContentsMargins(0, 0, 0, 0)
        self._results_inner_lay.setSpacing(8)
        self._results_inner_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._no_results_lbl = QLabel(
            "Run the pipeline to see topic results here."
        )
        self._no_results_lbl.setObjectName("page-sub")
        self._no_results_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._results_inner_lay.addWidget(self._no_results_lbl)
        self._results_scroll.setWidget(self._results_inner)
        results_vlay.addWidget(self._results_scroll, 1)

        splitter.addWidget(log_frame)
        splitter.addWidget(results_frame)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])

        outer.addWidget(splitter, 1)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _sync_ollama_model_enabled(self, checked: bool) -> None:
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

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select transcript folder",
            self._input_edit.text().strip() or _PROJECT_ROOT,
        )
        if path:
            self._input_edit.setText(path)

    def _open_output_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        out = _OUTPUT_DIR
        os.makedirs(out, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _append_log(self, text: str, color: str | None = None) -> None:
        line = text.rstrip("\n")
        theme = self._theme_getter() if self._theme_getter else "light"
        if color is None:
            lower = line.lower()
            if "error" in lower or "traceback" in lower or "exception" in lower:
                color = "#ef4444"
            elif "complete" in lower or "success" in lower or "saved" in lower:
                color = "#22c55e"
            else:
                color = "#ffffff" if theme == "dark" else "#0f172a"
        cur = self._log_edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(line + "\n", fmt)
        self._log_edit.setTextCursor(cur)
        self._log_edit.ensureCursorVisible()

    def _on_run_clicked(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._append_log("[warn] Pipeline is already running.", "#eab308")
            return

        input_path = self._input_edit.text().strip()
        if not input_path:
            self._append_log("[error] Please select an input transcript file or folder.", "#ef4444")
            return
        if not os.path.exists(input_path):
            self._append_log(f"[error] Path does not exist: {input_path}", "#ef4444")
            return
        if not os.path.isfile(_PIPELINE_SCRIPT):
            self._append_log(
                f"[error] Pipeline script not found at:\n  {_PIPELINE_SCRIPT}\n"
                "Make sure topic_modeling/src/pipeline.py exists.",
                "#ef4444",
            )
            return

        # Clear log and results
        self._log_edit.clear()
        self._clear_results()

        python = _resolve_python()
        args = [_PIPELINE_SCRIPT, input_path]

        speaker = self._speaker_edit.text().strip()
        if speaker:
            args.append(speaker)

        if self._ollama_checkbox.isChecked():
            args.append("--label")
            model = self._model_edit.text().strip() or "llama3.1"
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
            self._append_log(
                f"[error] Failed to start pipeline: {self._process.errorString()}",
                "#ef4444",
            )
            self._process = None
        else:
            self._run_btn.setEnabled(False)
            self._run_btn.setText("Running…")

    def _on_stdout(self) -> None:
        if not self._process:
            return
        data = self._process.readAllStandardOutput()
        if data:
            for ln in data.data().decode("utf-8", errors="replace").splitlines():
                if ln.strip():
                    self._append_log(ln)

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
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self._append_log("[pipeline] Pipeline completed successfully.", "#22c55e")
            QTimer.singleShot(500, self._load_latest_results)
        else:
            self._append_log(
                f"[pipeline] Pipeline failed (exit code {exit_code}).", "#ef4444"
            )
        self._process = None

    # ── Results loading ───────────────────────────────────────────────────

    def _clear_results(self) -> None:
        """Remove all dynamically added topic cards."""
        while self._results_inner_lay.count() > 0:
            item = self._results_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._no_results_lbl = QLabel("Run the pipeline to see topic results here.")
        self._no_results_lbl.setObjectName("page-sub")
        self._no_results_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._results_inner_lay.addWidget(self._no_results_lbl)

    def _load_latest_results(self) -> None:
        """Find the most recently written *_topic_summary.json and render it."""
        out_dir = _OUTPUT_DIR
        if not os.path.isdir(out_dir):
            return
        candidates = [
            os.path.join(out_dir, fn)
            for fn in os.listdir(out_dir)
            if fn.endswith("_topic_summary.json")
        ]
        if not candidates:
            self._append_log("[warn] No topic_summary.json found in output dir.", "#eab308")
            return
        candidates.sort(key=os.path.getmtime, reverse=True)
        latest = candidates[0]
        try:
            with open(latest, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception as e:
            self._append_log(f"[error] Could not read results: {e}", "#ef4444")
            return
        self._render_results(summary, latest)

    def load_results_from_file(self, path: str) -> None:
        """Public entry for loading a specific summary JSON (future use)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception as e:
            self._append_log(f"[error] Could not load {path}: {e}", "#ef4444")
            return
        self._render_results(summary, path)

    def _render_results(self, summary: list[dict], source_path: str) -> None:
        """Replace the placeholder with one card per topic."""
        # Remove placeholder
        while self._results_inner_lay.count() > 0:
            item = self._results_inner_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if not summary:
            lbl = QLabel("No topics found in results.")
            lbl.setObjectName("page-sub")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_inner_lay.addWidget(lbl)
            return

        source_lbl = QLabel(f"Source: {os.path.basename(source_path)}")
        source_lbl.setObjectName("settings-label")
        self._results_inner_lay.addWidget(source_lbl)

        for entry in summary:
            card = self._make_topic_card(entry)
            self._results_inner_lay.addWidget(card)

        self._results_inner_lay.addStretch(1)

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
            self._append_log(
                "[error] Could not find the original transcript file for this excerpt.",
                "#ef4444",
            )
            return

        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except Exception as e:
            self._append_log(f"[error] Could not open transcript: {e}", "#ef4444")
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
                self._append_log(
                    "[warn] Transcript opened, but the highlight mapping was out of range.",
                    "#eab308",
                )
        else:
            self._append_log(
                "[warn] Transcript opened, but the exact excerpt could not be highlighted.",
                "#eab308",
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
                hidden_count = len(examples) - 3

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
