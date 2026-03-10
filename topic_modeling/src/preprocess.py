import re
import sys
import os
import pandas as pd

# extract speaker label and timestamp if present
def extract_metadata(line):
    speaker = None
    timestamp = None

    # extract speaker label (e.g., SPEAKER_00)
    speaker_match = re.search(r"\[?(SPEAKER_\d+)\]?:", line)
    if speaker_match:
        speaker = speaker_match.group(1)

    # extract timestamp (e.g., 00:01:23)
    timestamp_match = re.search(r"\d{2}:\d{2}:\d{2}", line)
    if timestamp_match:
        timestamp = timestamp_match.group(0)

    return speaker, timestamp

# remove speaker labels and timestamps from transcript text
def clean_text(line):
    # remove speaker labels
    line = re.sub(r"\[?SPEAKER_\d+\]?:", "", line)

    # remove timestamps
    line = re.sub(r"\d{2}:\d{2}:\d{2}", "", line)

    return line.strip()

# process the transcript file and return a cleaned dataframe
def preprocess_transcript(file_path):
    data = []

    # open transcript file and iterate through each line
    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()

            # skip empty lines
            if not line:
                continue

            # extract speaker and timestamp metadata
            speaker, timestamp = extract_metadata(line)

            # clean transcript text for topic modeling
            cleaned = clean_text(line)

            # store results in structured format
            data.append({
                "segment_id": i,
                "speaker": speaker,
                "timestamp": timestamp,
                "cleaned_text": cleaned
            })

    # convert collected data into a dataframe
    return pd.DataFrame(data)

# handles command-line input, runs preprocessing, and saves the cleaned transcript
if __name__ == "__main__":

    # ensure a transcript file was provided as a command line argument
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py <transcript_file>")
        sys.exit(1)

    # read transcript file path from command line
    transcript_file = sys.argv[1]

    # run preprocessing pipeline on transcript
    df = preprocess_transcript(transcript_file)
    
    # ensure output directory exists
    os.makedirs("../output", exist_ok=True)
    
    # generate output filename based on input filename
    input_name = os.path.basename(transcript_file)
    name_only, _ = os.path.splitext(input_name)

    output_file = f"../output/cleaned_{name_only}.csv"

    # save cleaned transcript to output folder
    df.to_csv(output_file, index=False)

    # confirm preprocessing completed successfully
    print(f"Preprocessed transcript saved to {output_file}")
