import re
import sys
import os
import pandas as pd
from pathlib import Path

# extract timestamp and speaker label if present
def extract_metadata(line):
    speaker = None
    timestamp = None

    timestamp_match = re.search(r"\[?(\d{2}:\d{2}:\d{2})\]?", line)
    if timestamp_match:
        timestamp = timestamp_match.group(1)
    line_no_time = re.sub(r"\[?\d{2}:\d{2}:\d{2}\]?\s*", "", line)

    speaker_match = re.match(r"^\s*\[?([^\]:]+)\]?:\s*", line_no_time)
    if speaker_match:
        speaker = speaker_match.group(1).strip()

    return speaker, timestamp

# remove timestamps and speaker labels
def clean_text(line):
    line = re.sub(r"\[?\d{2}:\d{2}:\d{2}\]?\s*", "", line)
    line = re.sub(r"^\s*\[?[^\]:]+\]?:\s*", "", line)
    return line.strip()

# assign interview role based on chosen interviewer speaker
def assign_role(speaker, interviewer_speaker):
    if speaker == interviewer_speaker:
        return "interviewer"
    return "participant"

# process one transcript file and return a cleaned dataframe
def preprocess_transcript(file_path, interviewer_speaker=None):
    data = []
    current_segment = None
    segment_id = 0

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            speaker, _ = extract_metadata(line)
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

            # start first segment
            if current_segment is None:
                current_segment = {
                    "segment_id": segment_id,
                    "speaker": speaker,
                    "role": role,
                    "include_in_topic_model": include_in_topic_model,
                    "cleaned_text": cleaned,
                    "source_file": os.path.basename(file_path)
                }
                continue

            # group consecutive lines by speaker into one segment (speaker-turn chunking)
            if speaker == current_segment["speaker"]:
                current_segment["cleaned_text"] += " " + cleaned
            else:
                data.append(current_segment)
                segment_id += 1

                current_segment = {
                    "segment_id": segment_id,
                    "speaker": speaker,
                    "role": role,
                    "include_in_topic_model": include_in_topic_model,
                    "cleaned_text": cleaned,
                    "source_file": os.path.basename(file_path)
                }

    # save last segment
    if current_segment is not None:
        data.append(current_segment)

    return pd.DataFrame(data)
    
# process file or folder
def preprocess_input(input_path, interviewer_speaker=None):
    input_path = Path(input_path)

    os.makedirs("../output", exist_ok=True)

    all_dfs = []

    # single file
    if input_path.is_file():
        df = preprocess_transcript(input_path, interviewer_speaker)

        name_only = input_path.stem
        output_file = f"../output/{name_only}.csv"

        df.to_csv(output_file, index=False)
        print(f"Preprocessed transcript saved to {output_file}")
        
        if interviewer_speaker:
            print(f"Interviewer excluded: {interviewer_speaker}")
        else:
            print("No interviewer speaker was provided. All segments will be included in topic modeling.")

        return output_file

    # folder
    elif input_path.is_dir():
        files = list(input_path.glob("*.txt"))

        if not files:
            raise ValueError("No .txt files found in folder")

        for file in files:
            df = preprocess_transcript(file, interviewer_speaker)

            name_only = file.stem
            output_file = f"../output/{name_only}.csv"
            df.to_csv(output_file, index=False)

            print(f"Processed {file.name}")

            all_dfs.append(df)

        combined_df = pd.concat(all_dfs, ignore_index=True)

        folder_name = input_path.name
        combined_output = f"../output/{folder_name}.csv"

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
