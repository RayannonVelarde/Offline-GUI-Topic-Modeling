import re
import sys
import os
import pandas as pd
from pathlib import Path

# extract speaker label and timestamp if present
def extract_metadata(line):
    speaker = None
    timestamp = None

    speaker_match = re.match(r"^\s*([^:]+):\s*", line)
    if speaker_match:
        speaker = speaker_match.group(1).strip()

    timestamp_match = re.search(r"\d{2}:\d{2}:\d{2}", line)
    if timestamp_match:
        timestamp = timestamp_match.group(0)

    return speaker, timestamp

# remove speaker labels and timestamps from transcript text
def clean_text(line):
    line = re.sub(r"^\s*[^:]+:\s*", "", line)
    line = re.sub(r"\d{2}:\d{2}:\d{2}", "", line)
    return line.strip()
    
# assign interview role based on chosen interviewer speaker
def assign_role(speaker, interviewer_speaker):
    if speaker == interviewer_speaker:
        return "interviewer"
    return "participant"

# process one transcript file and return a cleaned dataframe
def preprocess_transcript(file_path, interviewer_speaker=None):
    data = []

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            speaker, timestamp = extract_metadata(line)
            cleaned = clean_text(line)
            
            if interviewer_speaker is None:
                role = "participant"
                include_in_topic_model = True
            else:
                role = assign_role(speaker, interviewer_speaker)
                include_in_topic_model = role == "participant"

            data.append({
                "segment_id": i,
                "speaker": speaker,
                "timestamp": timestamp,
                "role": role,
                "include_in_topic_model": include_in_topic_model,
                "cleaned_text": cleaned,
                "source_file": os.path.basename(file_path)
            })

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
        output_file = f"../output/cleaned_{name_only}.csv"

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
            output_file = f"../output/cleaned_{name_only}.csv"
            df.to_csv(output_file, index=False)

            print(f"Processed {file.name}")

            all_dfs.append(df)

        combined_df = pd.concat(all_dfs, ignore_index=True)

        folder_name = input_path.name
        combined_output = f"../output/cleaned_{folder_name}.csv"

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
