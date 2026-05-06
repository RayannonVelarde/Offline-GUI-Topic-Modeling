# Offline Studio — Local Audio Transcription & Topic Discovery for Qualitative Research

Qualitative researchers often juggle four or five tools just to go from a recorded interview to organized insights. Most cloud-based options raise privacy concerns when audio contains sensitive subjects. This project collapses that workflow into one offline desktop app — no API keys, no uploads, no cloud dependency.

---

## What It Does

Offline Studio lets users upload audio files, generate speaker-labeled transcripts, review translations, and run topic modeling on transcript files — all locally. It combines a WhisperX-based speech-to-text studio with a BERTopic topic modeling pipeline inside one PySide6 desktop interface.

---

## What Makes This Different

Most transcription tools stop at the transcript. Most topic modeling tools expect clean, pre-processed text. This project chains both pipelines inside a single local interface, with speaker-aware preprocessing that lets researchers exclude interviewer turns before analysis — a gap we did not find in existing open-source tools.

---

## Target Users

- Researchers reviewing interview recordings
- Students working with transcript-based projects
- Teams analyzing meetings, interviews, or conversations
- Anyone who wants a local-first alternative to cloud transcription tools

---

## Primary Features

- **Offline transcription** using WhisperX / faster-whisper
- **Speaker diarization** for identifying different speakers
- **Translation support** for reviewing multilingual audio
- **Transcript review interface** with audio sync
- **BERTopic topic modeling** for discovering themes across transcript files
- **Speaker-aware preprocessing** to exclude interviewer turns before analysis
- **Optional local LLM labeling** through Ollama
- **Live logs** for transcription and topic modeling jobs
- **Light/dark themed PySide6 interface**
- **Local-first output** — all generated files stay on your machine

---

## Interface Preview

> Replace these image paths with your actual screenshots or GIFs.

### Home — Upload and Configure Audio Jobs

![Home page showing audio upload and job configuration](docs/images/home-page.png)

### Jobs — Track Processing Progress

![Jobs page showing active and completed transcription jobs](docs/images/jobs-page.png)

### Review — Transcript, Translation, and Audio Playback

![Review page showing transcript and translation review](docs/images/review-page.png)

### Topic Modeling — Discover Themes in Transcript Files

![Topic modeling page showing topic cards and example excerpts](docs/images/topic-modeling-page.png)

---

## Workflow

1. Upload an audio file.
2. Configure transcription and speaker options.
3. Run the transcription job.
4. Review the generated transcript and translation.
5. Run topic modeling on one transcript or a folder of transcripts.
6. Review topics, keywords, and example excerpts.

---

## System Architecture

The app is split into two main parts:

1. **PySide6 Desktop GUI** — file selection, job configuration, progress logs, review pages, settings, and topic modeling controls.
2. **Backend Processing Pipelines** — `studio_engine.py` handles transcription, diarization, and translation. `topic_modeling/src/pipeline.py` handles transcript preprocessing, BERTopic modeling, and optional Ollama-based labeling.

The GUI launches backend jobs as separate processes to keep the interface responsive while longer tasks run in the background.

![System architecture diagram](docs/images/architecture-diagram.png)

---

## Pages

| Page | Purpose |
|---|---|
| Home | Drop audio files, configure jobs, and start transcription |
| Jobs | Monitor running and completed transcription jobs |
| Review | Side-by-side transcript/translation viewer with audio sync |
| Topic Modeling | Run BERTopic pipeline on transcript `.txt` files |
| Settings | Manage preferences, output folder, and Hugging Face token |

---

## Topic Modeling Page

Users can:

- Select a single `.txt` file or a folder of `.txt` files
- Optionally exclude interviewer turns by speaker label, such as `SPEAKER_00`
- Optionally enable Ollama LLM labeling
- Run the BERTopic pipeline from the GUI
- View live logs while the pipeline runs
- Review topic cards with keywords and example excerpts
- Open the output folder when the pipeline finishes

Ollama labeling requires Ollama running locally with a compatible model such as `llama3.1`.

---

<details>
<summary>Setup & Installation</summary>

### 1. Create a virtual environment

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Download the topic modeling embedding model

```bash
cd topic_modeling/src
python download_models.py
cd ../..
```

### 4. Set your Hugging Face token

Speaker diarization requires a Hugging Face token.

Launch the app and go to:

```text
Settings → Hugging Face Token
```

</details>

---

## Running the App

```bash
cd studio/gui
python main.py
```

---

<details>
<summary>Topic Modeling CLI Standalone</summary>

```bash
cd topic_modeling/src

# Single file, no labeling
python pipeline.py ../src/interview_dataset/interview_01_marisa.txt

# Folder, exclude SPEAKER_00 as interviewer
python pipeline.py ../src/interview_dataset SPEAKER_00

# With Ollama labeling
python pipeline.py ../src/interview_dataset SPEAKER_00 --label llama3.1
```

</details>

---

## Project Structure

```text
Offline-GUI-Topic-Modeling/
├── studio/
│   ├── studio_engine.py           # Backend engine for transcription jobs
│   └── gui/
│       ├── main.py                # Entry point — run this to launch the app
│       ├── main_window.py         # Main window with all pages
│       ├── topic_modeling_page.py # Topic Modeling page
│       ├── widgets.py             # Shared widgets
│       ├── stylesheet.py          # Light/dark theme stylesheets
│       └── nav_icons.py           # SVG nav icons
├── topic_modeling/
│   ├── src/
│   │   ├── pipeline.py            # Orchestrates preprocess → BERTopic
│   │   ├── preprocess.py          # Cleans and segments transcript .txt files
│   │   ├── topic_modeling.py      # BERTopic model, embeddings, labeling
│   │   ├── download_models.py     # Downloads sentence-transformer model
│   │   └── interview_dataset/     # Sample transcript .txt files
│   ├── models/                    # Downloaded models, gitignored
│   └── output/                    # Output CSVs, JSON, and saved models
├── bulkprocessing.py
├── mixbothtask.py
├── transcribe.py
├── transcribeWhisperx.py
├── translateWhisperx.py
└── requirements.txt
```

---

## Testing and Validation

Testing focused on:

- Adding audio files through the GUI
- Running transcription jobs from the Home page
- Generating transcript and translation output files
- Reviewing transcripts in the Review page
- Running topic modeling on a single transcript file and a folder of files
- Excluding interviewer turns with a speaker label
- Confirming the GUI remained usable while backend jobs ran in the background

Known challenges included dependency setup, local model downloads, and performance differences across machines.

---

## Key Design Decisions

**Desktop-first interface** — The project works with local audio and transcript files. A PySide6 desktop app fits that naturally.

**Backend jobs run separately from the GUI** — Transcription and topic modeling can take time. Separate backend processes keep the GUI responsive and make log streaming straightforward.

**Offline-first workflow** — WhisperX, BERTopic, and Ollama allow the full pipeline to run without cloud services, which matters when audio contains sensitive content.

**Transcript review before analysis** — Topic modeling is only useful if the transcript is understandable. The Review page lets users inspect output before running analysis.

---

## Lessons Learned

- Building an AI-powered tool is more than running a model — workflow design, progress feedback, and output handling are just as important.
- Offline AI is good for privacy but makes dependency setup and hardware performance harder to manage.
- Keeping the GUI and backend separate made the system easier to debug and extend.
- Transcript quality affects every downstream step, including translation and topic modeling.

---

## Future Work

- Improve transcript/audio highlighting accuracy
- Add PDF and DOCX export formats
- Add better model selection controls for speed vs. accuracy
- Improve topic visualization
- Add stronger automated tests for backend pipelines
- Package the app into a simpler installer for non-technical users
- Add support for more transcript formats

---

## Team Contributions

Built over 8 weeks by a 3-person student team.

| Team Member | Main Contributions |
|---|---|
| Lucas Montoya | Speech-to-text studio GUI, transcription backend integration, diarization/translation workflow, review page, output handling |
| Rayannon Velarde | BERTopic topic modeling pipeline, transcript preprocessing, topic modeling page integration |
| Christian Gabriel Cabales | UI support, testing, documentation, integration support |

---

## Project Timeline

![Project timeline Gantt chart](docs/images/gantt-chart.png)

| Week | Sprint Focus |
|---|---|
| Week 1 | Proposal, planning, requirements, initial structure |
| Week 2 | Basic GUI layout and audio upload workflow |
| Week 3 | WhisperX transcription integration |
| Week 4 | Speaker diarization and translation workflow |
| Week 5 | Job tracking, output handling, and review page |
| Week 6 | Topic modeling pipeline integration |
| Week 7 | UI polish, testing, and bug fixes |
| Week 8 | Final documentation, screenshots, demo prep |

---

## Credits

- [WhisperX / faster-whisper](https://github.com/m-bain/whisperX) — speech transcription
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) — speaker diarization
- [BERTopic](https://github.com/MaartenGr/BERTopic) — topic modeling
- [SentenceTransformers](https://www.sbert.net/) — text embeddings
- [Ollama](https://ollama.com/) — optional local LLM topic labeling
- [PySide6](https://doc.qt.io/qtforpython/) — desktop GUI

---

## Status

Final course project prototype. Core workflow is functional. Setup may vary depending on local machine, model availability, and installed dependencies.
