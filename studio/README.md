# Speech to Text Studio

## Overview

A local, offline desktop application for transcribing, translating, and diarizing audio interview files. The backend (`studio_engine.py`) runs WhisperX and pyannote-audio entirely on your machine — no data leaves your device. The GUI connects to the engine as a subprocess.

## Structure

```
studio/
├── studio_engine.py   # Backend — called as a subprocess by the GUI
└── gui/               # Desktop GUI (PySide6)
    ├── main.py        # Entry point
    ├── main_window.py # Main window and job logic
    ├── widgets.py     # Custom UI components
    ├── stylesheet.py  # App-wide styles
    └── nav_icons.py   # Navigation icons
```

## Requirements

- Python 3.10
- ffmpeg installed and on your PATH
- A Hugging Face token with access to pyannote speaker diarization models

## Setup

```bash
python3.10 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .\.venv\Scripts\activate       # Windows

python -m pip install --upgrade pip setuptools wheel

pip install torch==2.8.0 torchaudio==2.8.0
pip install whisperx==3.7.6 pyannote-audio==3.4.0
pip install python-dotenv PySide6 mutagen keyring
```

## Usage

Run the GUI from the `studio/` directory:

```bash
python gui/main.py
```

The engine (`studio_engine.py`) is launched automatically by the GUI — you don't need to run it directly.
