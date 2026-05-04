"""
LLM Assistant panel — powered by GPT4All (fully offline).

Provides a Claude-style chat interface that can be embedded in any page.
Runs GPT4All inference in a background QThread and streams tokens to the UI.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import (
    QEvent,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_MODEL = "mistral-7b-openorca.Q4_0.gguf"
_GPT4ALL_MODEL_DIR = os.path.expanduser("~/.cache/gpt4all")

_DEFAULT_SYSTEM = (
    "You are an intelligent analysis assistant. "
    "Be concise, accurate, and helpful. "
    "When data or context is provided, base your answers on it."
)

_TOPIC_SYSTEM = """\
You are an expert analyst helping users understand interview and conversation transcripts \
and the topics discovered through BERTopic analysis.

When context is provided it will contain two sections:

TOPIC ANALYSIS — BERTopic results listing each topic's ID, keywords, segment count, \
speaker attribution, and representative example excerpts from the transcript.

TRANSCRIPT — The raw conversation text with speaker labels.

Your responsibilities:
- Answer questions about what was said, by whom, and in what context.
- Explain and interpret topic clusters using their keywords and examples.
- Identify patterns, recurring themes, and connections across topics.
- Compare how different speakers engaged with a topic when relevant.
- Quote short excerpts directly from the provided data to support your answers.
- Summarise findings in plain, accessible language.

Rules:
- Ground every answer in the provided context. Do not speculate beyond it.
- When citing a topic, mention its ID, keywords, and a short example excerpt.
- If the context does not contain enough information to answer, say so clearly.
- Keep answers concise; use bullet points for lists of three or more items.\
"""

TOPIC_QUICK_ACTIONS: list[tuple[str, str]] = [
    ("Summarize topics", "Give me a concise summary of every topic found. For each one, mention its keywords and one representative quote from the transcript."),
    ("Speaker breakdown", "For each speaker in the transcript, which topics did they bring up most? What were their main concerns or themes?"),
    ("Key insights", "What are the three most significant insights or takeaways from this transcript and topic analysis? Support each one with a quote."),
    ("Draft report", "Write a short structured report (introduction, 2–3 findings paragraphs, conclusion) summarising the main topics and themes from this transcript."),
]


# ── Worker thread ────────────────────────────────────────────────────────────


class GPT4AllStreamWorker(QThread):
    """Runs GPT4All inference in a background thread, emitting tokens as they arrive."""

    token_received = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, model_name: str, messages: list[dict], parent=None):
        super().__init__(parent)
        self._model_name = model_name
        self._messages = messages
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            from gpt4all import GPT4All  # noqa: PLC0415
        except ImportError:
            self.error.emit(
                "GPT4All is not installed.\n\n"
                "Install it with:\n"
                "  pip install gpt4all"
            )
            self.finished.emit()
            return

        system_prompt = ""
        conversation: list[dict] = []
        for msg in self._messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                conversation.append(msg)

        if not conversation:
            self.finished.emit()
            return

        last_user_msg = conversation[-1]["content"]
        prior_turns = conversation[:-1]

        try:
            model = GPT4All(self._model_name, verbose=False)
            with model.chat_session(system_prompt=system_prompt):
                if prior_turns:
                    model.current_chat_session.extend(prior_turns)
                for token in model.generate(last_user_msg, max_tokens=1024, streaming=True):
                    if self._abort:
                        break
                    self.token_received.emit(token)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


# ── Utilities ─────────────────────────────────────────────────────────────────


def fetch_gpt4all_models() -> list[str]:
    """Return .gguf model files found in the local GPT4All model cache."""
    if os.path.isdir(_GPT4ALL_MODEL_DIR):
        models = sorted(
            f for f in os.listdir(_GPT4ALL_MODEL_DIR)
            if f.lower().endswith(".gguf")
        )
        if models:
            return models
    return [DEFAULT_MODEL]


def gpt4all_is_available() -> bool:
    try:
        import gpt4all  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


# ── Message bubble ────────────────────────────────────────────────────────────


class _MessageBubble(QFrame):
    def __init__(self, text: str, role: str, theme: str = "light", parent=None):
        super().__init__(parent)
        self._role = role
        self._theme = theme
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        self._bubble = QFrame()
        self._bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        inner = QVBoxLayout(self._bubble)
        inner.setContentsMargins(12, 9, 12, 9)
        inner.setSpacing(0)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._label.setMaximumWidth(500)
        inner.addWidget(self._label)

        self._apply_colors()

        if role == "user":
            outer.addStretch(1)
            outer.addWidget(self._bubble)
        else:
            outer.addWidget(self._bubble)
            outer.addStretch(1)

    def _apply_colors(self):
        dark = self._theme == "dark"
        if self._role == "user":
            bg, fg = "#2563eb", "#ffffff"
            radius = "border-radius: 14px 14px 4px 14px;"
        else:
            bg = "#1e2433" if dark else "#f1f5f9"
            fg = "#e2e8f0" if dark else "#0f172a"
            radius = "border-radius: 14px 14px 14px 4px;"
        self._bubble.setStyleSheet(
            f"QFrame {{ background-color: {bg}; {radius} border: none; }}"
            f"QLabel {{ color: {fg}; font-size: 13px; background: transparent; border: none; }}"
        )

    def set_text(self, text: str):
        self._label.setText(text)

    def get_text(self) -> str:
        return self._label.text()


# ── Quick-action chip ─────────────────────────────────────────────────────────


class _ActionChip(QPushButton):
    def __init__(self, label: str, theme: str = "light", parent=None):
        super().__init__(label, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._apply_style(theme)

    def _apply_style(self, theme: str):
        dark = theme == "dark"
        border = "#334155" if dark else "#cbd5e1"
        color = "#94a3b8" if dark else "#475569"
        hover_bg = "#1e2d4a" if dark else "#eff6ff"
        hover_border = "#3b82f6" if dark else "#2563eb"
        hover_color = "#3b82f6" if dark else "#2563eb"
        pressed_bg = "#1e3a5f" if dark else "#dbeafe"
        dis_color = "#475569" if dark else "#94a3b8"
        dis_border = "#1e2433" if dark else "#e2e8f0"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {border};
                border-radius: 14px;
                color: {color};
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {hover_border};
                color: {hover_color};
                background-color: {hover_bg};
            }}
            QPushButton:pressed {{ background-color: {pressed_bg}; }}
            QPushButton:disabled {{ color: {dis_color}; border-color: {dis_border}; }}
        """)


# ── Main panel ────────────────────────────────────────────────────────────────


class LLMAssistantPanel(QFrame):
    """
    Offline AI chat panel powered by GPT4All.

    Args:
        theme:         "light" or "dark"
        system_prompt: Override the default system instruction
        quick_actions: List of (label, prompt) tuples for the chip row.
                       Pass an empty list to hide chips entirely.
        parent:        Qt parent widget
    """

    def __init__(
        self,
        theme: str = "light",
        system_prompt: str | None = None,
        quick_actions: list[tuple[str, str]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._theme = theme
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._quick_actions = quick_actions if quick_actions is not None else []
        self._history: list[dict] = []
        self._context: str = ""
        self._worker: Optional[GPT4AllStreamWorker] = None
        self._streaming_bubble: Optional[_MessageBubble] = None
        self._is_streaming = False

        self.setObjectName("ai-assistant-panel")
        self._build_ui()
        self._check_gpt4all_status()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        dark = self._theme == "dark"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("ai-header")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 10, 14, 10)
        h_lay.setSpacing(8)

        spark = QLabel("✦")
        spark.setStyleSheet("color: #2563eb; font-size: 15px; background: transparent; border: none;")
        h_lay.addWidget(spark)

        title_lbl = QLabel("AI Assistant")
        title_lbl.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent; border: none;")
        h_lay.addWidget(title_lbl)
        h_lay.addStretch(1)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            "color: #94a3b8; font-size: 10px; background: transparent; border: none;"
        )
        h_lay.addWidget(self._status_dot)

        self._model_combo = QComboBox()
        self._model_combo.setObjectName("ai-model-combo")
        self._model_combo.addItem(DEFAULT_MODEL)
        self._model_combo.setFixedHeight(26)
        self._model_combo.setMinimumWidth(130)
        self._model_combo.setStyleSheet(self._combo_css())
        h_lay.addWidget(self._model_combo)

        refresh_btn = QToolButton()
        refresh_btn.setText("⟳")
        refresh_btn.setToolTip("Refresh local GPT4All models")
        refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        refresh_btn.setAutoRaise(True)
        refresh_btn.setStyleSheet(
            "QToolButton{border:none;background:transparent;color:#64748b;font-size:15px;}"
            "QToolButton:hover{color:#2563eb;}"
        )
        refresh_btn.clicked.connect(self._check_gpt4all_status)
        h_lay.addWidget(refresh_btn)

        clear_btn = QToolButton()
        clear_btn.setText("✕")
        clear_btn.setToolTip("Clear conversation")
        clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        clear_btn.setAutoRaise(True)
        clear_btn.setStyleSheet(
            "QToolButton{border:none;background:transparent;color:#64748b;font-size:13px;}"
            "QToolButton:hover{color:#ef4444;}"
        )
        clear_btn.clicked.connect(self._clear_chat)
        h_lay.addWidget(clear_btn)

        root.addWidget(header)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(
            "border:none;border-top:1px solid #1e2433;" if dark
            else "border:none;border-top:1px solid #e2e8f0;"
        )
        root.addWidget(div)

        # ── Message scroll area ──────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background:transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(12, 12, 12, 12)
        self._msg_layout.setSpacing(8)
        self._msg_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._welcome = self._make_welcome()
        self._msg_layout.addWidget(self._welcome)
        self._msg_layout.addStretch(1)

        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll, stretch=1)

        # ── Quick-action chips ───────────────────────────────────────────────
        if self._quick_actions:
            chips_frame = QFrame()
            chips_lay = QHBoxLayout(chips_frame)
            chips_lay.setContentsMargins(12, 6, 12, 4)
            chips_lay.setSpacing(6)
            self._chips: list[_ActionChip] = []
            for label, prompt in self._quick_actions:
                chip = _ActionChip(label, theme=self._theme)
                chip.clicked.connect(lambda _=False, p=prompt: self._send_message(p))
                chips_lay.addWidget(chip)
                self._chips.append(chip)
            chips_lay.addStretch(1)
            root.addWidget(chips_frame)
        else:
            self._chips = []

        # ── Input row ────────────────────────────────────────────────────────
        input_frame = QFrame()
        i_lay = QHBoxLayout(input_frame)
        i_lay.setContentsMargins(12, 6, 12, 12)
        i_lay.setSpacing(8)

        self._input = QTextEdit()
        self._input.setObjectName("ai-input")
        self._input.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._input.setPlaceholderText("Ask a question… (Enter to send, Shift+Enter for newline)")
        self._input.setFixedHeight(58)
        self._input.setStyleSheet(self._input_css())
        self._input.installEventFilter(self)
        i_lay.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("ai-send-btn")
        self._send_btn.setFixedSize(62, 58)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(self._send_css())
        self._send_btn.clicked.connect(self._on_send_clicked)
        i_lay.addWidget(self._send_btn)

        root.addWidget(input_frame)

    def _make_welcome(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 20, 8, 8)
        lay.setSpacing(8)

        icon = QLabel("✦")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 30px; color: #2563eb; background: transparent; border: none;")
        lay.addWidget(icon)

        dark = self._theme == "dark"
        title = QLabel("AI Assistant")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-weight: 700; font-size: 15px; color: {'#f1f5f9' if dark else '#1f2937'}; "
            "background: transparent; border: none;"
        )
        lay.addWidget(title)

        self._welcome_hint = QLabel(
            "Select a transcript to load it as context,\n"
            "then run the pipeline to add topic results.\n"
            "Use the quick actions or type your own question."
        )
        self._welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_hint.setStyleSheet(
            "font-size: 12px; color: #94a3b8; background: transparent; border: none;"
        )
        lay.addWidget(self._welcome_hint)

        return w

    # ── CSS helpers ────────────────────────────────────────────────────────────

    def _combo_css(self) -> str:
        dark = self._theme == "dark"
        bg = "#1e2433" if dark else "#f1f5f9"
        fg = "#e2e8f0" if dark else "#334155"
        bd = "#2d3748" if dark else "#cbd5e1"
        pop = "#141720" if dark else "#ffffff"
        return (
            f"QComboBox{{background:{bg};border:1px solid {bd};border-radius:6px;"
            f"color:{fg};padding:2px 6px;font-size:12px;}}"
            f"QComboBox::drop-down{{border:none;width:18px;}}"
            f"QComboBox QAbstractItemView{{background:{pop};border:1px solid {bd};"
            f"selection-background-color:#2563eb;selection-color:#fff;}}"
        )

    def _input_css(self) -> str:
        dark = self._theme == "dark"
        bg = "#1e2433" if dark else "#ffffff"
        fg = "#e2e8f0" if dark else "#0f172a"
        bd = "#2d3748" if dark else "#d7dee8"
        return (
            f"QTextEdit{{background:{bg};border:1px solid {bd};border-radius:10px;"
            f"color:{fg};font-size:13px;padding:8px 10px;}}"
            f"QTextEdit:focus{{border:1.5px solid #2563eb;}}"
        )

    def _send_css(self) -> str:
        dark = self._theme == "dark"
        dis_bg = "#334155" if dark else "#e2e8f0"
        dis_fg = "#64748b" if dark else "#94a3b8"
        return (
            "QPushButton{background:#2563eb;color:#fff;border:none;"
            "border-radius:10px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:pressed{background:#1e40af;}"
            f"QPushButton:disabled{{background:{dis_bg};color:{dis_fg};}}"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def prefill_input(self, text: str) -> None:
        """Pre-fill the chat input with `text` and give it keyboard focus."""
        self._input.setPlainText(text)
        self._input.setFocus()

    def set_context(self, context_text: str):
        """Feed context (e.g. topic JSON or transcript) that will be injected into every conversation."""
        self._context = (context_text or "").strip()
        if hasattr(self, "_welcome_hint"):
            if self._context:
                has_topics = "TOPIC ANALYSIS" in self._context
                has_transcript = "TRANSCRIPT" in self._context
                if has_topics and has_transcript:
                    hint = "Topics + transcript loaded. Ask anything about the data."
                elif has_topics:
                    hint = "Topic results loaded. Ask me to summarise, compare, or explain them."
                else:
                    hint = "Transcript loaded. Ask questions or run the pipeline to add topic results."
                self._welcome_hint.setText(hint)
                self._welcome_hint.setStyleSheet(
                    "font-size: 12px; color: #22c55e; background: transparent; border: none;"
                )
            else:
                self._welcome_hint.setText(
                    "Select a transcript to load it as context,\n"
                    "then run the pipeline to add topic results.\n"
                    "Use the quick actions or type your own question."
                )
                self._welcome_hint.setStyleSheet(
                    "font-size: 12px; color: #94a3b8; background: transparent; border: none;"
                )

    def update_theme(self, theme: str):
        self._theme = theme
        self._model_combo.setStyleSheet(self._combo_css())
        self._input.setStyleSheet(self._input_css())
        self._send_btn.setStyleSheet(self._send_css())
        for chip in self._chips:
            chip._apply_style(theme)

    # ── GPT4All status ────────────────────────────────────────────────────────

    def _check_gpt4all_status(self):
        if gpt4all_is_available():
            self._status_dot.setStyleSheet(
                "color:#22c55e;font-size:10px;background:transparent;border:none;"
            )
            self._status_dot.setToolTip("GPT4All is available")
            self._refresh_models()
        else:
            self._status_dot.setStyleSheet(
                "color:#ef4444;font-size:10px;background:transparent;border:none;"
            )
            self._status_dot.setToolTip(
                "GPT4All is not installed.\n"
                "Install with: pip install gpt4all"
            )

    def _refresh_models(self):
        models = fetch_gpt4all_models()
        current = self._model_combo.currentText()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(models)
        idx = self._model_combo.findText(current)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._model_combo.blockSignals(False)

    # ── Message handling ──────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            ke = QKeyEvent(event)
            if ke.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (ke.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_send_clicked()
                    return True
        return super().eventFilter(obj, event)

    def _on_send_clicked(self):
        text = self._input.toPlainText().strip()
        if not text or self._is_streaming:
            return
        self._input.clear()
        self._send_message(text)

    def _send_message(self, text: str):
        if self._is_streaming:
            return

        # Hide welcome on first message
        if self._welcome.isVisible():
            self._welcome.hide()
            item = self._msg_layout.takeAt(self._msg_layout.count() - 1)
            if item:
                del item

        self._add_bubble(text, "user")

        # Build message list
        messages: list[dict] = [{"role": "system", "content": self._system}]
        if self._context:
            messages.append({
                "role": "user",
                "content": (
                    "Below is all the data available for this session. "
                    "Use it to answer my questions.\n\n"
                    "---\n"
                    f"{self._context}\n"
                    "---"
                ),
            })
            messages.append({
                "role": "assistant",
                "content": (
                    "I have reviewed the topic analysis results and the transcript. "
                    "I'm ready to answer questions about what was discussed, who said what, "
                    "patterns across topics, and any other aspect of the data. "
                    "What would you like to know?"
                ),
            })
        messages.extend(self._history)
        messages.append({"role": "user", "content": text})
        self._history.append({"role": "user", "content": text})

        self._streaming_bubble = self._add_bubble("▍", "assistant")
        self._set_streaming(True)

        model = self._model_combo.currentText() or DEFAULT_MODEL
        self._worker = GPT4AllStreamWorker(model, messages, parent=self)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished.connect(self._on_stream_done)
        self._worker.error.connect(self._on_stream_error)
        self._worker.start()

    def _add_bubble(self, text: str, role: str) -> _MessageBubble:
        bubble = _MessageBubble(text, role, self._theme)
        self._msg_layout.insertWidget(self._msg_layout.count(), bubble)
        QTimer.singleShot(30, self._scroll_to_bottom)
        return bubble

    def _on_token(self, token: str):
        if self._streaming_bubble is None:
            return
        current = self._streaming_bubble.get_text()
        if current == "▍":
            current = ""
        self._streaming_bubble.set_text(current + token)
        self._scroll_to_bottom()

    def _on_stream_done(self):
        if self._streaming_bubble is not None:
            txt = self._streaming_bubble.get_text()
            if txt.endswith("▍"):
                self._streaming_bubble.set_text(txt[:-1])
            self._history.append({"role": "assistant", "content": self._streaming_bubble.get_text()})
            self._streaming_bubble = None
        self._set_streaming(False)
        self._worker = None

    def _on_stream_error(self, msg: str):
        if self._streaming_bubble is not None:
            self._streaming_bubble.set_text(f"⚠ {msg}")
            self._streaming_bubble = None
        self._set_streaming(False)
        self._worker = None

    def _set_streaming(self, active: bool):
        self._is_streaming = active
        self._send_btn.setEnabled(not active)
        self._send_btn.setText("…" if active else "Send")
        for chip in self._chips:
            chip.setEnabled(not active)

    def _clear_chat(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
        self._history.clear()
        self._streaming_bubble = None
        self._is_streaming = False

        while self._msg_layout.count():
            item = self._msg_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._welcome = self._make_welcome()
        self._msg_layout.addWidget(self._welcome)
        self._msg_layout.addStretch(1)

        self.set_context(self._context)

        self._send_btn.setEnabled(True)
        self._send_btn.setText("Send")
        for chip in self._chips:
            chip.setEnabled(True)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
