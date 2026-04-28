"""
studio_engine.py — Studio backend engine (Step C).

Subprocess contract (called by studio/gui/main_window.py):

    python studio_engine.py <audio_path>
        --num-speakers N   (clamped to 1..MAX_DIARIZATION_SPEAKERS, currently 8)
        [--model {tiny,base,small,medium,large-v2,large-v3,large-v3-turbo}]
        [--compute-type {auto,float32,float16,int8,int8_float16}]
        [--batch-size N]
        [--translate {none,whisper,opus-mt,nllb}]
        [--timestamps {none,segment,word}]
        [--diarize | --no-diarize]
        [--split-on-speaker-change | --no-split-on-speaker-change]
        [--condition-on-previous-text | --no-condition-on-previous-text]
        [--initial-prompt "text"]
        [--preprocess {none,normalize}]
        [--output-dir DIR]

Outputs (written to --output-dir, default = this script's directory so the
GUI rename logic in _archive_latest_outputs_for_job finds them):

    transcription_<src_iso>.txt   (always; e.g. transcription_es.txt)
    translation_<tgt_iso>.txt     (only when --translate != none; e.g. translation_en.txt)
    <audio_stem>_segments.json    (always; segment timing + text for Review / tooling)

stdout:
    Free-text `[engine] …` log lines for the GUI's log panel.

stderr:
    Free-text stderr, plus structured progress events on lines prefixed
    `[event] ` containing a single JSON object. See STUDIO_ENGINE.md for
    the event schema.

Environment:
    HUGGINGFACE_TOKEN is required only when --diarize is set.

Key quality levers Step C introduces (all opt-in; defaults preserve the
legacy output contract from Step B):

    1. Real ASR knobs — `--model`, `--compute-type`, `--batch-size`,
       `--initial-prompt`, and `--no-condition-on-previous-text` (the
       latter is the OpenAI-recommended hallucination-avoidance default).
       CLI default model stays `small` for fast/stable GUI behavior;
       bump to `large-v3` once performance testing on real project
       audio has signed off on the trade-off.
    2. Dedicated MT — opus-mt (Helsinki-NLP/opus-mt-{src}-{tgt}) is the
       only translator the engine will run after transcription. Whatever
       `--translate` value the caller passes (`auto`, `whisper`, `nllb`,
       `auto-en`, or `opus-mt`), the resolver collapses it to opus-mt as
       long as a target language is set. `--translate none` still skips
       the translation file. Translated segments inherit the source
       segment's timing and speaker label segment-by-segment, no Whisper
       second pass required.
    3. Diarize-then-split — `stage_split_segments_by_speaker` walks
       word-level speakers and splits a segment wherever adjacent words
       disagree. Fixes the "one segment, two speakers" collapse. Off by
       default because it changes output line count; flip on with
       `--split-on-speaker-change` when the GUI is ready.
    4. Optional audio preprocessing — `--preprocess normalize` runs an
       ffmpeg loudnorm + 80 Hz highpass prepass. Default `none`.
    5. Structured progress events on stderr.

Back-compat: `--translate` still accepts the legacy values `whisper`,
`nllb`, and `auto-en` so an un-updated GUI keeps working. Each of them
collapses directly to opus-mt in `run()` (with a warning log); none
of them route through any intermediate engine.

Still deferred (Step D):
    - Benchmarking campaigns on real project audio for MT choice and
      ASR size/compute trade-offs.
    - `torch.load` compatibility via `torch.serialization.add_safe_globals`
      once the required class list is enumerated from a full run.

See STUDIO_ENGINE.md (project root) for the full engine doc.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

# Heavy imports (torch, whisperx, pyannote.audio, pandas, transformers) are
# deferred into stage functions so `python studio_engine.py --help` stays
# instant and CLI validation errors don't pay the model-load cost.


SCRIPT_DIR = Path(__file__).resolve().parent

MODEL_CHOICES = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
)
COMPUTE_CHOICES = ("auto", "float32", "float16", "int8", "int8_float16")
# Translation engine is locked to opus-mt for every translation. The
# remaining choices (`auto`, `whisper`, `auto-en`, `nllb`) are kept only
# so older GUI/CLI invocations keep parsing; the resolver in `run()`
# collapses every non-`none` value directly to `opus-mt` whenever a
# target language is available. `--translate none` is the only way to
# skip the translation file.
TRANSLATE_CHOICES = ("auto", "none", "whisper", "auto-en", "opus-mt", "nllb")
TIMESTAMP_CHOICES = ("none", "segment", "word")
PREPROCESS_CHOICES = ("none", "normalize")
LANGUAGE_CHOICES = ("auto", "en", "es")

PYANNOTE_SAMPLE_RATE = 16000  # matches whisperx.load_audio's output rate

# Source ISO -> default target ISO when the GUI/user did not override.
# Spanish pairs with English; English pairs with Spanish.
DEFAULT_TARGET_FOR_SOURCE = {"es": "en", "en": "es"}

# (src, tgt) -> opus-mt model id. opus-mt is the only translation engine
# the engine runs: every non-`none` `--translate` value (`auto`,
# `opus-mt`, and the back-compat `whisper`/`nllb`/`auto-en`) collapses to
# opus-mt in `run()`, regardless of target language.
OPUS_MT_MODELS = {
    ("es", "en"): "Helsinki-NLP/opus-mt-es-en",
    ("en", "es"): "Helsinki-NLP/opus-mt-en-es",
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# Pyannote/WhisperX diarization: GUI and CLI both clamp --num-speakers to this
# upper bound (typical conversations; larger values rarely help accuracy).
MAX_DIARIZATION_SPEAKERS = 8


@dataclass
class EngineConfig:
    """All knobs for one run. One object, one source of truth."""

    audio_path: Path

    # Diarization
    num_speakers: int = 2
    diarize: bool = True
    # Off by default: splitting changes the output line count, which is
    # a user-visible contract change. Flip on with --split-on-speaker-change
    # once the GUI consumer is ready for the new shape.
    split_on_speaker_change: bool = False

    # ASR
    # Conservative default: "small" matches legacy behavior from
    # mixbothtask.py and Step B. Bump to "large-v3" once performance
    # testing on real project audio confirms the latency/VRAM trade-off.
    model: str = "small"
    compute_type: str = "auto"
    batch_size: int = 16
    condition_on_previous_text: bool = False
    initial_prompt: Optional[str] = None

    # Translation
    # opus-mt is forced for every translation. The accepted values are
    # kept for back-compat, but the resolver in `run()` collapses
    # everything except "none" to "opus-mt" once a target language is
    # known. "none" still skips the translation file.
    translate: str = "auto"  # "auto" | "none" | "whisper" | "opus-mt" | "nllb"

    # Output / audio
    timestamps: str = "none"             # "none" | "segment" | "word"
    preprocess: str = "none"             # "none" | "normalize"
    output_dir: Path = field(default_factory=lambda: SCRIPT_DIR)
    # Source language for ASR. "auto" lets Whisper detect; otherwise an
    # ISO code from LANGUAGE_CHOICES (currently "en" or "es").
    language: str = "auto"

    # Auth
    hf_token: Optional[str] = None

    def resolve_output_paths(
        self, src_iso: str, tgt_iso: Optional[str]
    ) -> tuple[Path, Optional[Path]]:
        """Return (transcript_path, translation_path) following the
        `transcription_<src>.txt` / `translation_<tgt>.txt` contract.

        ``tgt_iso`` is None when no translation will be produced
        (``--translate none`` or no target language).
        """
        transcript_path = self.output_dir / f"transcription_{src_iso}.txt"
        if tgt_iso is None:
            return transcript_path, None
        return transcript_path, self.output_dir / f"translation_{tgt_iso}.txt"


# --------------------------------------------------------------------------- #
# Logging and structured events
# --------------------------------------------------------------------------- #


Logger = Callable[[str], None]


def _make_logger() -> Logger:
    def log(msg: str) -> None:
        print(f"[engine] {msg}", flush=True)

    return log


def _emit_event(event: str, **kwargs) -> None:
    """Write one structured progress event to stderr.

    Format: ``[event] {"event": "<event>", ...}\\n``

    The first positional argument is the event *type* (``"start"``,
    ``"stage"``, ``"write"``, ``"done"``, ``"error"``, ...). Stage events
    typically pass ``name="<stage_name>"`` as a kwarg, so this parameter
    is deliberately *not* called ``name`` — that would collide with the
    caller's kwarg and raise ``TypeError: got multiple values for 'name'``.

    Events are cheap and always on. If the GUI doesn't parse them they
    just appear as extra lines in the log panel.
    """
    payload = {"event": event}
    payload.update(kwargs)
    try:
        line = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        line = json.dumps({"event": event, "payload_error": True})
    print(f"[event] {line}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Torch / pickle compatibility
# --------------------------------------------------------------------------- #


def _apply_torch_compat() -> None:
    """
    pyannote 3.x ships checkpoints pickled with objects PyTorch 2.6 blocks
    under its new ``weights_only=True`` default. Step C keeps the
    ``mixbothtask.py`` workaround (global monkey-patch of ``torch.load``).
    A tighter fix via ``torch.serialization.add_safe_globals([...])`` is
    Step D — it needs an end-to-end run to enumerate the class list.
    """
    import torch

    original_load = torch.load

    def _trusted_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = _trusted_load  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Audio preprocessing (optional)
# --------------------------------------------------------------------------- #


def _maybe_preprocess_audio(
    audio_path: Path, mode: str, log: Logger
) -> Path:
    """
    If ``mode == "normalize"``, run an ffmpeg prepass that applies an 80 Hz
    high-pass (rumble/DC removal) and EBU R128 loudnorm, and downmixes to
    16 kHz mono. Returns the path to the processed wav file.

    If ffmpeg is missing or fails, logs a warning and falls back to the
    original audio path. Never raises.
    """
    if mode == "none":
        return audio_path

    tmp_dir = Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"studio_engine_preproc_{audio_path.stem}.wav"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", str(PYANNOTE_SAMPLE_RATE),
        "-ac", "1",
        str(out_path),
    ]
    log(f"Preprocessing audio (loudnorm + 80 Hz HPF) -> {out_path}")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError:
        log("WARN: ffmpeg not found on PATH; skipping preprocess.")
        return audio_path
    except subprocess.CalledProcessError as e:
        tail = e.stderr.decode("utf-8", errors="replace")[-500:]
        log(f"WARN: ffmpeg preprocess failed; using original audio. Tail: {tail}")
        return audio_path

    return out_path


# --------------------------------------------------------------------------- #
# Compute-type resolution
# --------------------------------------------------------------------------- #


def _resolve_compute_type(requested: str, device: str) -> str:
    """Expand ``"auto"`` to device-appropriate default; otherwise passthrough."""
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


# --------------------------------------------------------------------------- #
# Stages — audio & ASR
# --------------------------------------------------------------------------- #


def stage_load_audio(log: Logger, audio_path: Path):
    import whisperx

    log("Loading audio...")
    return whisperx.load_audio(str(audio_path))


def stage_load_asr_model(
    config: EngineConfig, device: str, compute_type: str, log: Logger
):
    import whisperx

    asr_options = {
        "condition_on_previous_text": config.condition_on_previous_text,
    }
    if config.initial_prompt:
        asr_options["initial_prompt"] = config.initial_prompt

    log(
        f"Loading WhisperX model "
        f"(model={config.model}, compute_type={compute_type}, device={device}, "
        f"condition_on_previous_text={config.condition_on_previous_text}, "
        f"initial_prompt={'set' if config.initial_prompt else 'unset'})..."
    )
    return whisperx.load_model(
        config.model,
        device,
        compute_type=compute_type,
        asr_options=asr_options,
    )


def stage_transcribe(asr_model, audio, config: EngineConfig, log: Logger):
    """Transcribe audio in the configured source language.

    When ``config.language == "auto"`` we omit the ``language=`` kwarg so
    Whisper auto-detects; the detected language is later read from the
    result's ``"language"`` key.
    """
    if config.language == "auto":
        log("Transcribing audio (source language: auto-detect)...")
        return asr_model.transcribe(audio, batch_size=config.batch_size)
    log(f"Transcribing audio (source language: {config.language})...")
    return asr_model.transcribe(
        audio, batch_size=config.batch_size, language=config.language
    )


def stage_align(segments, audio, device: str, language_code: str, log: Logger):
    """
    CTC forced alignment for the source-language transcription. Produces
    word-level start/end timestamps that feed speaker assignment, segment
    splitting, and the ``--timestamps=word`` output mode.

    Alignment is source-language-specific: the wav2vec2 CTC head's
    vocabulary is per-language, so running an es head on en audio (and
    vice versa) is structurally broken. The translation output reuses
    the source segments' timing segment-by-segment (opus-mt is the only
    MT engine), so it does not need its own alignment pass.
    """
    import whisperx

    log(f"Loading alignment model (wav2vec2 for {language_code})...")
    model_a, metadata = whisperx.load_align_model(
        language_code=language_code, device=device
    )
    log(f"Aligning {language_code} transcription...")
    return whisperx.align(
        segments, model_a, metadata, audio, device, return_char_alignments=False
    )


# --------------------------------------------------------------------------- #
# Stages — diarization
# --------------------------------------------------------------------------- #


def stage_diarize(audio, config: EngineConfig, device: str, log: Logger):
    """
    Run pyannote speaker diarization against the already-loaded waveform.

    - We pass the in-memory waveform as
      ``{"waveform": tensor, "sample_rate": 16000}`` instead of the file
      path, so we don't decode twice.
    - We pass ``min_speakers=1, max_speakers=<num_speakers>`` instead of
      exact ``num_speakers=N``, because exact-N forces pyannote to split
      genuinely single-speaker audio into N clusters.
    """
    import torch
    from pyannote.audio import Pipeline

    log("Loading speaker diarization model (pyannote/speaker-diarization-3.1)...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=config.hf_token,
    )
    pipeline.to(torch.device(device))

    # whisperx.load_audio returns float32 mono at 16 kHz, shape (N,).
    # pyannote wants shape (channels, samples).
    waveform = torch.from_numpy(audio).unsqueeze(0)
    audio_input = {"waveform": waveform, "sample_rate": PYANNOTE_SAMPLE_RATE}

    log(
        f"Diarizing (min_speakers=1, max_speakers={config.num_speakers})..."
    )
    return pipeline(
        audio_input,
        min_speakers=1,
        max_speakers=config.num_speakers,
    )


def stage_build_diarize_df(diarize_segments, log: Logger):
    import pandas as pd

    rows = []
    for turn, _, speaker in diarize_segments.itertracks(yield_label=True):
        rows.append(
            {
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": str(speaker),
            }
        )
    if not rows:
        log("WARNING: no diarization turns returned")
        return pd.DataFrame(columns=["start", "end", "speaker"])

    df = pd.DataFrame(rows)
    log(f"Found {df['speaker'].nunique()} speakers across {len(df)} turns")
    return df


def stage_assign_speakers(diarize_df, result, log: Logger, label: str):
    import whisperx

    log(f"Assigning speakers to {label} segments...")
    return whisperx.assign_word_speakers(diarize_df, result)


# --------------------------------------------------------------------------- #
# Stages — speaker-change splitting
# --------------------------------------------------------------------------- #


def _dominant_speaker(words: Iterable[dict]) -> Optional[str]:
    """Pick the most common non-empty speaker across a list of words."""
    counts: dict = {}
    for w in words:
        spk = w.get("speaker")
        if spk:
            counts[spk] = counts.get(spk, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def stage_split_segments_by_speaker(result, log: Logger, label: str):
    """
    Walk each segment's words and split the segment wherever two adjacent
    words disagree on speaker. Preserves everything else (text is rebuilt
    by joining the word tokens of each sub-group).

    No-op on segments that lack word-level speaker info — e.g. any
    segment that wasn't aligned, or whose words didn't get speaker
    labels assigned.
    """
    new_segments: List[dict] = []
    split_count = 0
    scanned = 0

    for segment in result.get("segments", []):
        scanned += 1
        words = segment.get("words") or []
        word_speakers = [w.get("speaker") for w in words if w.get("speaker")]

        if len(words) < 2 or len(set(word_speakers)) < 2:
            # Nothing to split. Leave segment as-is.
            new_segments.append(segment)
            continue

        # Group consecutive words by speaker.
        groups: List[List[dict]] = [[words[0]]]
        for w in words[1:]:
            prev_spk = groups[-1][-1].get("speaker")
            this_spk = w.get("speaker")
            if this_spk and prev_spk and this_spk != prev_spk:
                groups.append([w])
            else:
                groups[-1].append(w)

        if len(groups) == 1:
            new_segments.append(segment)
            continue

        split_count += 1
        for group in groups:
            group_text = " ".join(
                (w.get("word") or "").strip() for w in group
            ).strip()
            sub_segment = {
                **{k: v for k, v in segment.items() if k not in ("words", "text")},
                "start": group[0].get("start", segment.get("start")),
                "end": group[-1].get("end", segment.get("end")),
                "text": group_text,
                "speaker": _dominant_speaker(group)
                or group[0].get("speaker")
                or segment.get("speaker")
                or "Unknown",
                "words": group,
            }
            new_segments.append(sub_segment)

    if split_count:
        log(
            f"[{label}] Split {split_count} of {scanned} segment(s) at "
            f"speaker-change boundaries."
        )
    else:
        log(f"[{label}] No speaker-change splits needed.")

    new_result = dict(result)
    new_result["segments"] = new_segments
    return new_result


# --------------------------------------------------------------------------- #
# Stages — dedicated MT (es -> en)
# --------------------------------------------------------------------------- #


def _build_mt_pipeline(
    src_iso: str,
    tgt_iso: str,
    device: str,
    log: Logger,
):
    """
    Return a callable ``translate(texts: list[str]) -> list[str]`` for the
    requested (src, tgt) pair using opus-mt.
    """
    from transformers import pipeline as hf_pipeline

    hf_device = 0 if device == "cuda" else -1

    model_id = OPUS_MT_MODELS.get((src_iso, tgt_iso))
    if model_id is None:
        raise ValueError(
            f"No opus-mt model registered for {src_iso}->{tgt_iso}. "
            f"Extend OPUS_MT_MODELS."
        )
    log(f"Loading MT model {model_id}...")
    translator = hf_pipeline(
        "translation", model=model_id, device=hf_device
    )

    def translate(texts: List[str]) -> List[str]:
        outs = translator(texts, batch_size=16, max_length=512, truncation=True)
        return [o["translation_text"] for o in outs]

    return translate


def stage_translate_mt(
    source_result,
    src_iso: str,
    tgt_iso: str,
    device: str,
    log: Logger,
):
    """
    Translate the (already-aligned, speaker-assigned, possibly split)
    source-language segments into ``tgt_iso`` using a dedicated MT model.

    Returns a result dict shaped like the Whisper output (``{"segments":
    [...]}``) so the downstream writer path is unified. Each translated
    segment inherits ``start``, ``end``, and ``speaker`` from its source
    counterpart — so the translation file has correct timing and correct
    speaker labels segment-by-segment, without any further alignment.
    """
    segments = source_result.get("segments", [])
    if not segments:
        log(f"No {src_iso} segments to translate.")
        return {"segments": []}

    translate = _build_mt_pipeline(src_iso, tgt_iso, device, log)

    log(
        f"Translating {len(segments)} segments {src_iso}->{tgt_iso} "
        f"with opus-mt..."
    )
    texts = [(seg.get("text") or "").strip() for seg in segments]
    translated_texts = translate(texts)

    translated_segments = []
    for seg, ttext in zip(segments, translated_texts):
        translated_segments.append(
            {
                "start": seg.get("start"),
                "end": seg.get("end"),
                "speaker": seg.get("speaker", "Unknown"),
                "text": (ttext or "").strip(),
            }
        )
    return {"segments": translated_segments}


# --------------------------------------------------------------------------- #
# Output formatting
# --------------------------------------------------------------------------- #


def _format_timestamp(seconds) -> str:
    """Format seconds as HH:MM:SS.mmm. Returns --:--:--.--- for None/invalid."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "--:--:--.---"
    if s < 0 or s != s:  # negative or NaN
        return "--:--:--.---"
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    secs = s - hours * 3600 - minutes * 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _segment_has_word_times(segment) -> bool:
    words = segment.get("words")
    if not words:
        return False
    return any(("start" in w) for w in words)


def _format_line(segment, mode: str) -> str:
    """
    Render one segment as a single output line.

    Modes:
      none     -> "[SPEAKER_XX]: text"
      segment  -> "[HH:MM:SS.mmm → HH:MM:SS.mmm] [SPEAKER_XX]: text"
      word     -> "[SPEAKER_XX]: [ts]word1 [ts]word2 ..."
                  (falls back to segment formatting if the segment has no
                  word-level timing — e.g. MT output that inherited
                  segment-level timing, or any unaligned segment)
    """
    speaker = segment.get("speaker") or "Unknown"
    text = (segment.get("text") or "").strip()

    if mode == "none":
        return f"[{speaker}]: {text}"

    if mode == "segment":
        start = _format_timestamp(segment.get("start"))
        end = _format_timestamp(segment.get("end"))
        return f"[{start} → {end}] [{speaker}]: {text}"

    if mode == "word":
        if _segment_has_word_times(segment):
            pieces = []
            for w in segment["words"]:
                token = (w.get("word") or "").strip()
                if not token:
                    continue
                if "start" in w:
                    pieces.append(f"[{_format_timestamp(w['start'])}]{token}")
                else:
                    pieces.append(token)
            rendered = " ".join(pieces) if pieces else text
            return f"[{speaker}]: {rendered}"
        # Fallback: no word-level timing available for this segment.
        start = _format_timestamp(segment.get("start"))
        end = _format_timestamp(segment.get("end"))
        return f"[{start} → {end}] [{speaker}]: {text}"

    # Unknown mode — behave like 'none' rather than raising.
    return f"[{speaker}]: {text}"


def stage_write_transcript(
    result,
    path: Path,
    log: Logger,
    label: str,
    timestamps_mode: str,
) -> None:
    log(f"Saving {label} transcription to {path} (timestamps={timestamps_mode})...")
    path.parent.mkdir(parents=True, exist_ok=True)

    warned_word_fallback = False
    line_count = 0
    with open(path, "w", encoding="utf-8") as f:
        for segment in result.get("segments", []):
            if (
                timestamps_mode == "word"
                and not _segment_has_word_times(segment)
                and not warned_word_fallback
            ):
                log(
                    f"[{label}] --timestamps=word requested, but no word-level "
                    "timing is available for this result; falling back to "
                    "segment-level timestamps for affected lines."
                )
                warned_word_fallback = True
            f.write(_format_line(segment, timestamps_mode) + "\n")
            line_count += 1

    _emit_event(
        "write",
        label=label,
        path=str(path),
        lines=line_count,
        timestamps=timestamps_mode,
    )


def _segment_time_seconds(value) -> Optional[float]:
    """Coerce alignment/Whisper time to float seconds, or None if unusable."""
    if value is None:
        return None
    try:
        s = float(value)
    except (TypeError, ValueError):
        return None
    if s != s or s < 0:  # NaN or negative
        return None
    return s


def stage_write_review_segments(
    result_source,
    result_translation,
    path: Path,
    log: Logger,
    src_iso: str,
    tgt_iso: Optional[str],
) -> None:
    """Write merged segment JSON for Review sync (timing independent of --timestamps)."""
    log(f"Saving review segments sidecar to {path}...")
    path.parent.mkdir(parents=True, exist_ok=True)

    src_segments = result_source.get("segments") or []
    tgt_segments = (
        (result_translation or {}).get("segments") or []
        if result_translation is not None
        else []
    )

    rows = []
    for i, seg in enumerate(src_segments):
        speaker = seg.get("speaker") or "Unknown"
        text = (seg.get("text") or "").strip()
        trans_text: Optional[str] = None
        if i < len(tgt_segments):
            trans_text = (tgt_segments[i].get("text") or "").strip() or None

        rows.append(
            {
                "start": _segment_time_seconds(seg.get("start")),
                "end": _segment_time_seconds(seg.get("end")),
                "speaker": str(speaker),
                "text": text,
                "translation": trans_text,
            }
        )

    payload = {
        "version": 1,
        "src_lang": src_iso,
        "tgt_lang": tgt_iso,
        "segments": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _emit_event(
        "write",
        label="segments_json",
        path=str(path),
        lines=len(rows),
        timestamps="internal",
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _select_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def run(config: EngineConfig, log: Optional[Logger] = None) -> None:
    """Execute the pipeline end-to-end for one audio file."""
    log = log or _make_logger()
    _apply_torch_compat()

    start = time.time()
    device = _select_device()
    compute_type = _resolve_compute_type(config.compute_type, device)

    log(f"Device: {device} (compute_type={compute_type})")
    log(
        "Plan: "
        f"model={config.model}, "
        f"language={config.language}, "
        f"translate={config.translate}, "
        f"diarize={config.diarize}, "
        f"num_speakers={config.num_speakers}, "
        f"timestamps={config.timestamps}, "
        f"split_on_speaker_change={config.split_on_speaker_change}, "
        f"preprocess={config.preprocess}"
    )

    _emit_event(
        "start",
        model=config.model,
        language=config.language,
        translate=config.translate,
        diarize=config.diarize,
        compute_type=compute_type,
        device=device,
    )

    # -------- audio --------
    _emit_event("stage", name="preprocess", pct=0.02)
    audio_path = _maybe_preprocess_audio(config.audio_path, config.preprocess, log)

    _emit_event("stage", name="load_audio", pct=0.05)
    audio = stage_load_audio(log, audio_path)

    # -------- ASR --------
    _emit_event("stage", name="load_asr", pct=0.10)
    asr_model = stage_load_asr_model(config, device, compute_type, log)

    _emit_event("stage", name="transcribe", pct=0.20)
    result_source = stage_transcribe(asr_model, audio, config, log)

    # -------- resolve src/tgt language and translation engine --------
    # Source ISO: prefer Whisper's detected language when --language=auto;
    # otherwise honor the explicit user choice.
    detected = (result_source.get("language") or "").lower() or None
    if config.language == "auto":
        src_iso = detected or "en"
        if detected:
            log(f"Detected source language: {src_iso}")
        else:
            log("Source language detection returned nothing; defaulting to 'en'.")
    else:
        src_iso = config.language
        if detected and detected != src_iso:
            log(
                f"WARN: --language={src_iso} but Whisper detected '{detected}'. "
                "Honoring the explicit user choice."
            )

    # Target ISO follows the pairing table (es<->en today). Unknown source
    # languages produce no translation file.
    tgt_iso = DEFAULT_TARGET_FOR_SOURCE.get(src_iso)

    # Translation engine is locked to opus-mt for every translation,
    # regardless of which `--translate` value the caller passed. The
    # remaining `whisper`/`nllb`/`auto-en` choices are kept only for
    # back-compat with older GUI/CLI invocations; they all collapse to
    # opus-mt below.
    requested = config.translate
    if requested != "none" and tgt_iso is None:
        log(
            f"WARN: no default translation target for source '{src_iso}'; "
            "skipping translation output."
        )
        translate_mode = "none"
    elif requested == "none":
        translate_mode = "none"
    else:
        translate_mode = "opus-mt"
        if requested == "auto":
            log(f"Resolved --translate auto -> opus-mt (tgt={tgt_iso}).")
        elif requested != "opus-mt":
            log(
                f"--translate={requested} requested, but engine is locked "
                f"to opus-mt for all translations. Using opus-mt for "
                f"{src_iso}->{tgt_iso}."
            )

    # -------- alignment (source-language) --------
    _emit_event("stage", name="align", pct=0.45)
    try:
        result_source = stage_align(
            result_source["segments"], audio, device, src_iso, log
        )
    except Exception as exc:  # noqa: BLE001
        # Alignment can fail (no wav2vec2 head for the language, etc.). Log
        # and continue with un-aligned Whisper segments rather than aborting
        # the whole job.
        log(f"WARN: alignment failed for {src_iso}: {exc!r}. Continuing without word-level alignment.")

    # -------- diarization + speaker assignment --------
    if config.diarize:
        _emit_event("stage", name="diarize", pct=0.60)
        diarize_segments = stage_diarize(audio, config, device, log)
        diarize_df = stage_build_diarize_df(diarize_segments, log)
        if not diarize_df.empty:
            _emit_event("stage", name="assign_speakers", pct=0.70)
            result_source = stage_assign_speakers(
                diarize_df, result_source, log, src_iso
            )
        else:
            log(
                "No diarization turns produced; segments will be written with "
                "speaker=Unknown."
            )
    else:
        log("Diarization disabled; segments will be written with speaker=Unknown.")

    # -------- speaker-change splitting --------
    if config.split_on_speaker_change:
        _emit_event("stage", name="split_on_speaker_change", pct=0.78)
        result_source = stage_split_segments_by_speaker(
            result_source, log, src_iso
        )

    # -------- translation (MT) --------
    # Every translation goes through opus-mt. `translate_mode` is now
    # always "none" or "opus-mt" thanks to the resolver above.
    result_translation = None
    if translate_mode == "opus-mt":
        _emit_event("stage", name="translate_mt", pct=0.85)
        assert tgt_iso is not None, "translate_mode=='opus-mt' implies tgt_iso is set"
        result_translation = stage_translate_mt(
            result_source, src_iso, tgt_iso, device, log
        )

    # -------- resolve output paths --------
    effective_tgt = tgt_iso if result_translation is not None else None
    transcript_path, translation_path = config.resolve_output_paths(
        src_iso, effective_tgt
    )

    # -------- write --------
    _emit_event("stage", name="write", pct=0.95)
    stage_write_transcript(
        result_source, transcript_path, log, src_iso, config.timestamps
    )
    if result_translation is not None and translation_path is not None:
        stage_write_transcript(
            result_translation,
            translation_path,
            log,
            tgt_iso,
            config.timestamps,
        )

    review_segments_path = config.output_dir / f"{config.audio_path.stem}_segments.json"
    stage_write_review_segments(
        result_source,
        result_translation,
        review_segments_path,
        log,
        src_iso,
        effective_tgt,
    )

    elapsed = time.time() - start
    log(f"Done. Total execution time: {elapsed:.2f} seconds.")
    _emit_event(
        "done",
        elapsed_s=round(elapsed, 3),
        src_lang=src_iso,
        tgt_lang=tgt_iso if result_translation is not None else None,
        transcript_file=str(transcript_path),
        translation_file=str(translation_path) if translation_path is not None else None,
        segments_file=str(review_segments_path),
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="studio_engine",
        description="Studio transcription / translation / diarization engine.",
    )
    p.add_argument("audio", type=Path, help="Path to the audio file.")

    # Diarization
    p.add_argument(
        "--num-speakers",
        type=int,
        default=2,
        help=(
            "Upper bound on the number of speakers for diarization "
            f"(pyannote max_speakers). Clamped to 1..{MAX_DIARIZATION_SPEAKERS}. "
            "Default: 2."
        ),
    )
    diarize_group = p.add_mutually_exclusive_group()
    diarize_group.add_argument(
        "--diarize", dest="diarize", action="store_true",
        help="Enable speaker diarization (default).",
    )
    diarize_group.add_argument(
        "--no-diarize", dest="diarize", action="store_false",
        help="Disable speaker diarization; segments written with speaker=Unknown.",
    )
    p.set_defaults(diarize=True)

    split_group = p.add_mutually_exclusive_group()
    split_group.add_argument(
        "--split-on-speaker-change",
        dest="split_on_speaker_change", action="store_true",
        help="Split Whisper segments wherever adjacent words disagree on "
        "speaker. Off by default: splitting changes the output line "
        "count, which is a contract change; opt in once the GUI is ready.",
    )
    split_group.add_argument(
        "--no-split-on-speaker-change",
        dest="split_on_speaker_change", action="store_false",
        help="Keep Whisper's original segmentation even if a segment crosses "
        "a speaker boundary (default).",
    )
    p.set_defaults(split_on_speaker_change=False)

    # ASR
    p.add_argument(
        "--model", choices=MODEL_CHOICES, default="small",
        help="WhisperX model to load. Default: small (matches legacy "
        "behavior; fast, low VRAM). Bump to large-v3 for higher quality "
        "once performance testing has signed off on the latency/VRAM cost.",
    )
    p.add_argument(
        "--compute-type", choices=COMPUTE_CHOICES, default="auto",
        help="CTranslate2 compute type. 'auto' -> float16 on CUDA, int8 on "
        "CPU. Default: auto.",
    )
    p.add_argument(
        "--batch-size", type=int, default=16,
        help="ASR batch size. Default: 16.",
    )
    cond_group = p.add_mutually_exclusive_group()
    cond_group.add_argument(
        "--condition-on-previous-text",
        dest="condition_on_previous_text", action="store_true",
        help="Let Whisper condition each window on previous decoded text.",
    )
    cond_group.add_argument(
        "--no-condition-on-previous-text",
        dest="condition_on_previous_text", action="store_false",
        help="Disable previous-text conditioning (default; avoids "
        "hallucination loops on long-form audio).",
    )
    p.set_defaults(condition_on_previous_text=False)
    p.add_argument(
        "--initial-prompt", type=str, default=None,
        help="Optional text prompt seeded to Whisper for domain vocabulary "
        "(names, jargon, acronyms).",
    )

    # Translation
    p.add_argument(
        "--translate", choices=TRANSLATE_CHOICES, default="auto",
        help="Translation engine. opus-mt (Helsinki-NLP/opus-mt-{src}-{tgt} "
        "from OPUS_MT_MODELS) is forced for every translation, so the "
        "only meaningful choice is between producing a translation "
        "('auto'/'opus-mt'/'whisper'/'nllb'/'auto-en' — all collapse to "
        "opus-mt) and skipping it ('none'). The non-opus-mt values are "
        "kept only for back-compat with older GUI/CLI invocations.",
    )

    # Source language
    p.add_argument(
        "--language", choices=LANGUAGE_CHOICES, default="auto",
        help="Source language for ASR. 'auto' (default) lets Whisper detect; "
        "explicit 'en' or 'es' skips detection and pairs with the other "
        "language for the translation output.",
    )

    # Output / audio
    p.add_argument(
        "--timestamps", choices=TIMESTAMP_CHOICES, default="none",
        help="Timestamp annotations on output lines: 'none' (default), "
        "'segment' (HH:MM:SS.mmm per segment), or 'word' (per-word where "
        "available; falls back to 'segment' otherwise).",
    )
    p.add_argument(
        "--preprocess", choices=PREPROCESS_CHOICES, default="none",
        help="Optional audio prepass. 'normalize' -> ffmpeg loudnorm + 80 Hz "
        "highpass at 16 kHz mono. Default: none.",
    )
    p.add_argument(
        "--output-dir", type=Path, default=SCRIPT_DIR,
        help="Directory for transcription_*.txt outputs "
        "(default: this script's directory).",
    )
    return p.parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> EngineConfig:
    # .env fallback so running the script directly (outside the GUI) still
    # picks up HUGGINGFACE_TOKEN. When launched by the GUI the token is
    # already set on the QProcess environment, so this is a no-op.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    _ns = int(args.num_speakers)
    _ns = max(1, min(MAX_DIARIZATION_SPEAKERS, _ns))

    return EngineConfig(
        audio_path=args.audio,
        num_speakers=_ns,
        diarize=args.diarize,
        split_on_speaker_change=args.split_on_speaker_change,
        model=args.model,
        compute_type=args.compute_type,
        batch_size=args.batch_size,
        condition_on_previous_text=args.condition_on_previous_text,
        initial_prompt=args.initial_prompt,
        translate=args.translate,
        timestamps=args.timestamps,
        preprocess=args.preprocess,
        output_dir=args.output_dir,
        language=args.language,
        hf_token=os.getenv("HUGGINGFACE_TOKEN"),
    )


def _validate(config: EngineConfig) -> None:
    # Order matters: cheapest, most user-actionable checks first so the error
    # the user sees points at the real problem.
    if config.num_speakers < 1:
        raise ValueError(
            f"--num-speakers must be >= 1 (got {config.num_speakers})"
        )
    if config.batch_size < 1:
        raise ValueError(
            f"--batch-size must be >= 1 (got {config.batch_size})"
        )
    if config.diarize and not config.hf_token:
        raise RuntimeError(
            "Hugging Face token not found. Set HUGGINGFACE_TOKEN in the "
            "environment (or .env) or pass --no-diarize."
        )
    if not config.audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {config.audio_path}")
    config.output_dir.mkdir(parents=True, exist_ok=True)


def main(argv=None) -> int:
    args = _parse_args(argv)
    config = _config_from_args(args)
    _validate(config)
    run(config)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("[engine] interrupted", file=sys.stderr, flush=True)
        _emit_event("aborted", reason="keyboard_interrupt")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        print(
            f"[engine] FATAL: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        _emit_event("error", type=type(e).__name__, message=str(e))
        sys.exit(1)
