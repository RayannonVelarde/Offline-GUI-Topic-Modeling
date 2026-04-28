# Speech to Text Studio

## Overview



## Structure

```
studio/
├── studio_engine.py   # Backend — called as a subprocess by the GUI
└── gui/               # Desktop GUI (PyQt6)
    ├── main.py        # Entry point
    ├── main_window.py # Main window and job logic
    ├── widgets.py     # Custom UI components
    ├── stylesheet.py  # App-wide styles
    └── nav_icons.py   # Navigation icons
```

## Setup

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate           # macOS / Linux
# .\venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

## Usage


