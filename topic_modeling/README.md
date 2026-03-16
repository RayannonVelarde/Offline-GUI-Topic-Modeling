# Topic Modeling Pipeline

Sprint 1 prototype for transcript topic modeling.

## Pipeline
1. Preprocess transcript
2. Generate sentence embeddings
3. Run BERTopic clustering
4. Output topic assignments

## Setup
Install dependencies:

pip install -r requirements.txt

## Run

From the `src` folder:

### 1. Preprocess transcript

Basic usage:
python preprocess.py ../data/transcription_english.txt

Exclude interviewer turns (example: interviewer is `SPEAKER_00`):
python preprocess.py ../data/transcription_english.txt SPEAKER_00

### 2. Run topic modeling

python topic_modeling.py ../output/cleaned_transcription_english.csv

## Output

Results are saved in the `output/` folder.