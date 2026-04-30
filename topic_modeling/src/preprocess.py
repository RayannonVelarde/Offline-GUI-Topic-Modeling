import re
import sys
import os
import pandas as pd
from pathlib import Path

# extract timestamp and speaker label if present
def extract_metadata(line):
    speaker = None
    timestamp = None

    timestamp_match = re.search(r"\[(\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?)\]", line)
    if timestamp_match:
        timestamp = timestamp_match.group(1)

    line_no_time = re.sub(
        r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\]\s*",
        "",
        line
    )

    speaker_match = re.match(r"^\s*\[?([^\]:]+)\]?:\s*", line_no_time)
    if speaker_match:
        speaker = speaker_match.group(1).strip()

    return speaker, timestamp

# remove timestamps and speaker labels
def clean_text(line):
    line = re.sub(
        r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*→\s*\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\]\s*",
        "",
        line
    )
    line = re.sub(r"^\s*\[?[^\]:]+\]?:\s*", "", line)
    return line.strip()

# assign interview role based on chosen interviewer speaker
def assign_role(speaker, interviewer_speaker):
    if speaker == interviewer_speaker:
        return "interviewer"
    return "participant"

# count words in a text chunk
def word_count(text):
    return len(str(text).split())


# Sentence splitter used for the small-transcript fallback below.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_text_into_sentence_groups(text, target_words=80):
    """Split text into ~target_words-sized chunks at sentence boundaries.

    Used when a transcript ends up with too few merged segments to cluster
    (e.g. all lines share one speaker label, so build_initial_segments
    collapses everything into a single document).
    """
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]
    if not sentences:
        return []

    chunks = []
    current = []
    current_wc = 0
    for sentence in sentences:
        wc = word_count(sentence)
        if current and current_wc + wc > target_words:
            chunks.append(" ".join(current))
            current = []
            current_wc = 0
        current.append(sentence)
        current_wc += wc
    if current:
        chunks.append(" ".join(current))
    return chunks


def resegment_if_too_small(df, min_segments=8, target_words=80):
    """Re-chunk each row by sentence when a transcript collapsed to 1–N rows.

    Without this, BERTopic's UMAP/HDBSCAN fails on tiny inputs with
    "k must be less than or equal to the number of training points".
    """
    if df.empty or len(df) >= min_segments:
        return df

    rows = []
    seg_id = 0
    for _, row in df.iterrows():
        text = str(row.get("cleaned_text", "")).strip()
        chunks = chunk_text_into_sentence_groups(text, target_words=target_words)
        if not chunks:
            continue
        for chunk in chunks:
            new_row = row.to_dict()
            new_row["segment_id"] = seg_id
            new_row["cleaned_text"] = chunk
            seg_id += 1
            rows.append(new_row)

    if not rows:
        return df

    new_df = pd.DataFrame(rows)
    new_df = new_df[df.columns]
    return new_df

# build one segment record
def make_segment(segment_id, speaker, role, include_in_topic_model, cleaned_text, source_file, timestamp=None):
    return {
        "segment_id": segment_id,
        "speaker": speaker,
        "role": role,
        "include_in_topic_model": include_in_topic_model,
        "timestamp": timestamp,
        "cleaned_text": cleaned_text,
        "source_file": source_file
    }

# merge consecutive lines by speaker into initial speaker-turn chunks
def build_initial_segments(file_path, interviewer_speaker=None):
    data = []
    current_segment = None
    segment_id = 0

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            speaker, timestamp = extract_metadata(line)
            cleaned = clean_text(line)

            if not cleaned:
                continue

            # assign role
            if interviewer_speaker is None:
                role = "participant"
                include_in_topic_model = True
            else:
                role = assign_role(speaker, interviewer_speaker)
                include_in_topic_model = role == "participant"

            if current_segment is None:
                current_segment = make_segment(
                    segment_id, speaker, role, include_in_topic_model,
                    cleaned, os.path.basename(file_path), timestamp
                )
                continue

            if speaker == current_segment["speaker"]:
                current_segment["cleaned_text"] += " " + cleaned
            else:
                data.append(current_segment)
                segment_id += 1
                current_segment = make_segment(
                    segment_id, speaker, role, include_in_topic_model,
                    cleaned, os.path.basename(file_path), timestamp
                )

    if current_segment is not None:
        data.append(current_segment)

    return data

# merge when interviewer is excluded
def merge_when_interviewer_excluded(segments):
    min_words = 40

    included = [seg.copy() for seg in segments if seg["include_in_topic_model"]]

    if not included:
        return pd.DataFrame(columns=[
            "segment_id", "speaker", "role",
            "include_in_topic_model", "timestamp",
            "cleaned_text", "source_file"
        ])

    merged = []
    current = included[0].copy()

    for nxt in included[1:]:
        if word_count(current["cleaned_text"]) < min_words:
            current["cleaned_text"] += " " + nxt["cleaned_text"]
        else:
            merged.append(current)
            current = nxt.copy()

    merged.append(current)

    if len(merged) > 1 and word_count(merged[-1]["cleaned_text"]) < min_words:
        merged[-2]["cleaned_text"] += " " + merged[-1]["cleaned_text"]
        merged.pop()

    for i, seg in enumerate(merged):
        seg["segment_id"] = i

    return pd.DataFrame(merged)

# merge when interviewer is included
def merge_when_interviewer_included(segments):
    min_words = 40

    if not segments:
        return pd.DataFrame(columns=[
            "segment_id", "speaker", "role",
            "include_in_topic_model", "cleaned_text", "source_file"
        ])

    merged = []
    current = segments[0].copy()

    for nxt in segments[1:]:
        if word_count(current["cleaned_text"]) < min_words:
            current["cleaned_text"] += " " + nxt["cleaned_text"]
            current["speaker"] = "multiple"
        else:
            merged.append(current)
            current = nxt.copy()

    merged.append(current)

    if len(merged) > 1 and word_count(merged[-1]["cleaned_text"]) < min_words:
        merged[-2]["cleaned_text"] += " " + merged[-1]["cleaned_text"]
        merged[-2]["speaker"] = "multiple"
        merged.pop()

    for i, seg in enumerate(merged):
        seg["segment_id"] = i

    return pd.DataFrame(merged)

# process one transcript file
def preprocess_transcript(file_path, interviewer_speaker=None):
    initial_segments = build_initial_segments(file_path, interviewer_speaker)

    if interviewer_speaker is None:
        df = merge_when_interviewer_included(initial_segments)
    else:
        df = merge_when_interviewer_excluded(initial_segments)

    # Single-speaker transcripts (e.g. everything tagged [Unknown]) collapse
    # into one row, which crashes BERTopic. Fall back to sentence-grouped
    # chunks so the topic model has at least a handful of documents.
    return resegment_if_too_small(df)

# process file or folder
def preprocess_input(input_path, interviewer_speaker=None):
    input_path = Path(input_path)

    os.makedirs("../output", exist_ok=True)
    all_dfs = []

    if input_path.is_file():
        df = preprocess_transcript(input_path, interviewer_speaker)

        output_file = f"../output/{input_path.stem}.csv"
        df.to_csv(output_file, index=False)

        print(f"Preprocessed transcript saved to {output_file}")

        if interviewer_speaker:
            print(f"Interviewer excluded: {interviewer_speaker}")
        else:
            print("No interviewer speaker was provided. All segments will be included in topic modeling.")

        return output_file

    elif input_path.is_dir():
        files = list(input_path.glob("*.txt"))

        if not files:
            raise ValueError("No .txt files found in folder")

        for file in files:
            df = preprocess_transcript(file, interviewer_speaker)

            output_file = f"../output/{file.stem}.csv"
            df.to_csv(output_file, index=False)

            print(f"Processed {file.name}")
            all_dfs.append(df)

        combined_df = pd.concat(all_dfs, ignore_index=True)
        combined_df = resegment_if_too_small(combined_df)
        combined_output = f"../output/{input_path.name}.csv"
        combined_df.to_csv(combined_output, index=False)

        print(f"\nCombined dataset saved to {combined_output}")

        if interviewer_speaker:
            print(f"Interviewer excluded: {interviewer_speaker}")
        else:
            print("No interviewer speaker was provided. All segments will be included in topic modeling.")

        return combined_output

    else:
        raise ValueError("Invalid input path")

# CLI entry
if __name__ == "__main__":

    # usage:
    # python preprocess.py <transcript_file_or_folder>
    # python preprocess.py <transcript_file_or_folder> [interviewer_speaker]
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py <file_or_folder> [interviewer_speaker]")
        sys.exit(1)

    input_path = sys.argv[1]
    interviewer_speaker = sys.argv[2] if len(sys.argv) > 2 else None

    preprocess_input(input_path, interviewer_speaker)
