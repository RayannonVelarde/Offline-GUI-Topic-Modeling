# Topic Modeling Pipeline

Simple offline pipeline for preprocessing transcripts and generating topics using BERTopic, with optional local LLM labeling.

## Pipeline

1. Preprocess transcript → CSV
2. Generate embeddings + run BERTopic
3. Output topics, keywords, and examples
4. (Optional) Generate topic labels with a local LLM (Ollama)

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

### Optional: Local LLM (Ollama for labeling)

Install Ollama and download a model:

```bash
ollama pull llama3.1
```

Start Ollama (if not already running):

```bash
ollama serve
```

## Run

### Full pipeline

```bash
python pipeline.py ../data/transcription_english.txt
```

### With topic labeling

```bash
python pipeline.py ../data/transcription_english.txt --label
```

### Use a different model

```bash
python pipeline.py ../data/transcription_english.txt --label mistral
```

### Optional: exclude a speaker

```bash
python pipeline.py ../data/transcription_english.txt SPEAKER_00
```

## Output

Saved in `output/`:

* `cleaned_*.csv` → cleaned transcript
* `*_topic_results.csv` → topic assignments
* `*_topic_summary.json` → topics (keywords, examples, labels)
* `*_topic_model/` → saved BERTopic model
