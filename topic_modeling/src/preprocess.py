import re
import sys
import os
import pandas as pd

# extract speaker label and timestamp if present
def extract_metadata(line):
    speaker = None
    timestamp = None

    # capture any leading speaker label like "Tom:" or "Meeting Chairman:"
    speaker_match = re.match(r"^\s*([^:]+):\s*", line)
    if speaker_match:
        speaker = speaker_match.group(1).strip()

    # extract timestamp (e.g., 00:01:23)
    timestamp_match = re.search(r"\d{2}:\d{2}:\d{2}", line)
    if timestamp_match:
        timestamp = timestamp_match.group(0)

    return speaker, timestamp

# remove speaker labels and timestamps from transcript text
def clean_text(line):
    # remove any leading speaker label
    line = re.sub(r"^\s*[^:]+:\s*", "", line)

    # remove timestamps
    line = re.sub(r"\d{2}:\d{2}:\d{2}", "", line)

    return line.strip()
    
# assign interview role based on chosen interviewer speaker
def assign_role(speaker, interviewer_speaker):
    if speaker == interviewer_speaker:
        return "interviewer"
    return "participant"

# process the transcript file and return a cleaned dataframe
def preprocess_transcript(file_path, interviewer_speaker=None):
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
            
            # exclude interviewer turns
            if interviewer_speaker is None:
                role = "participant"
                include_in_topic_model = True
            else:
                role = assign_role(speaker, interviewer_speaker)
                include_in_topic_model = role == "participant"

            # store results in structured format
            data.append({
                "segment_id": i,
                "speaker": speaker,
                "timestamp": timestamp,
                "role": role,
                "include_in_topic_model": include_in_topic_model,
                "cleaned_text": cleaned
            })

    # convert collected data into a dataframe
    return pd.DataFrame(data)

# handles command-line input, runs preprocessing, and saves the cleaned transcript
if __name__ == "__main__":

    # ensure a transcript file was provided as a command line argument
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py <transcript_file> [interviewer_speaker]")
        sys.exit(1)

    # read transcript file path from command line
    transcript_file = sys.argv[1]
    
    # optional interviewer speaker label, e.g. SPEAKER_01
    interviewer_speaker = sys.argv[2] if len(sys.argv) > 2 else None

    # run preprocessing pipeline on transcript
    df = preprocess_transcript(transcript_file, interviewer_speaker)
    
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
    
    if interviewer_speaker is None:
        print("No interviewer speaker was provided. All segments will be included in topic modeling.")
    else:
        print(f"Interviewer speaker set to: {interviewer_speaker}")
