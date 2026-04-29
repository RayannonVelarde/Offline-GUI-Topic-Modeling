# Offline GUI — Topic Modeling & Transcription Studio

A unified offline tool combining:

- **Lucas's** Speech-to-Text Studio GUI — transcription, diarization, translation, and review of audio files using WhisperX.
- **Rayannon's** Topic Modeling pipeline — BERTopic-based topic discovery on transcript `.txt` files, with optional Ollama LLM labeling.

---

## Project Structure

```
Offline-GUI-Topic-Modeling/
├── studio/
│   ├── studio_engine.py          # Backend engine for transcription jobs
│   └── gui/
│       ├── main.py               # Entry point — run this to launch the app
│       ├── main_window.py        # Main window with all pages
│       ├── topic_modeling_page.py# Topic Modeling page (NEW — merged from Rayannon)
│       ├── widgets.py            # Shared widgets (DropZone, JobCard)
│       ├── stylesheet.py         # Light/dark theme stylesheets
│       └── nav_icons.py          # SVG nav icons (includes Topics icon)
├── topic_modeling/
│   ├── src/
│   │   ├── pipeline.py           # Orchestrates preprocess → BERTopic
│   │   ├── preprocess.py         # Cleans and segments transcript .txt files
│   │   ├── topic_modeling.py     # BERTopic model, embedding, labeling
│   │   ├── download_models.py    # Downloads sentence-transformer model
│   │   └── interview_dataset/    # Sample transcript .txt files
│   ├── models/                   # Downloaded sentence-transformer models (gitignored)
│   └── output/                   # Pipeline output CSVs, JSON, saved models
├── bulkprocessing.py
├── mixbothtask.py
├── transcribe.py
├── transcribeWhisperx.py
├── translateWhisperx.py
└── requirements.txt
```

---

## Setup

### 1. Create a virtual environment

```bash
python3.10 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Download topic modeling embedding model

```bash
cd topic_modeling/src
python download_models.py
cd ../..
```

### 4. Set your Hugging Face token (for speaker diarization)

Launch the app and go to **Settings → Hugging Face token**.

---

## Running the App

```bash
cd studio/gui
python main.py
```

---

## Pages

| Page | Description |
|------|-------------|
| **Home** | Drop audio files, configure jobs, start transcription |
| **Jobs** | Monitor running and completed transcription jobs |
| **Review** | Side-by-side transcript/translation viewer with audio sync |
| **Topic Modeling** | Run BERTopic pipeline on transcript `.txt` files |
| **Settings** | App preferences, output folder, HuggingFace token |

---

## Topic Modeling Page

1. Select a single `.txt` transcript file **or** a folder of `.txt` files.
2. Optionally specify the **interviewer speaker label** (e.g. `SPEAKER_00`) to exclude interviewer turns.
3. Optionally enable **Ollama LLM labeling** — requires Ollama running locally with a compatible model (default: `llama3.1`).
4. Click **Run Pipeline**.
5. Watch the live log. When complete, topic cards appear in the results panel with keywords and example excerpts.
6. Click **Open output folder** to access the raw CSVs, saved BERTopic model, and `_topic_summary.json`.

---

## Topic Modeling CLI (standalone)

```bash
cd topic_modeling/src

# Single file, no labeling
python pipeline.py ../src/interview_dataset/interview_01_marisa.txt

# Folder, exclude SPEAKER_00 as interviewer
python pipeline.py ../src/interview_dataset SPEAKER_00

# With Ollama labeling
python pipeline.py ../src/interview_dataset SPEAKER_00 --label llama3.1
```
