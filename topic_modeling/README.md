# Topic Modeling Pipeline

Simple offline pipeline for preprocessing transcripts and generating topics using BERTopic, with optional local LLM labeling.

## Pipeline

1. Preprocess transcript(s) → CSV
2. Generate embeddings + run BERTopic
3. Output topics, keywords, and examples
4. (Optional) Generate topic labels with a local LLM (Ollama)

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

## Download Embedding Model (Required Once)

This project runs fully offline. Before running topic modeling, download the embedding model:

```bash
python src/download_models.py
```

This will save the model to:

```text
models/paraphrase-multilingual-MiniLM-L12-v2/
```

This step only needs to be done once.

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

### Single transcript

```bash
python pipeline.py <path_to_file>
```

Example:

```bash
python pipeline.py transcription_english.txt
```

### Folder of transcripts

```bash
python pipeline.py <path_to_folder>
```

Example:

```bash
python pipeline.py data
```

### With topic labeling

```bash
python pipeline.py <path_to_file_or_folder> --label
```

### Use a different model

```bash
python pipeline.py <path_to_file_or_folder> --label mistral
```

### Optional: exclude a speaker

```bash
python pipeline.py <path_to_file_or_folder> SPEAKER_00
```

## Output

Saved in `output/`:

* `cleaned_<file>.csv` → cleaned transcript (per file)
* `cleaned_<folder>.csv` → combined dataset (for folder input)
* `*_topic_results.csv` → topic assignments
* `*_topic_summary.json` → topics (keywords, examples, labels)
* `*_topic_model/` → saved BERTopic model
