import sys
import os
import json
import shutil
from pathlib import Path
import pandas as pd
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from hdbscan import HDBSCAN
from umap import UMAP

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# load cleaned transcript data from csv
def load_data(file_path):
    df = pd.read_csv(file_path)

    if "cleaned_text" not in df.columns:
        raise ValueError("CSV must contain a cleaned_text column")

    df = df.dropna(subset=["cleaned_text"]).copy()
    df["cleaned_text"] = df["cleaned_text"].astype(str).str.strip()
    
    if "include_in_topic_model" in df.columns:
        df["include_in_topic_model"] = df["include_in_topic_model"].astype(str).str.lower()
        df = df[df["include_in_topic_model"].isin(["true"])].copy()

    if df.empty:
        raise ValueError("No usable transcript segments found")

    documents = df["cleaned_text"].tolist()

    return df, documents

# generate sentence embeddings using multilingual embedding model
def generate_embeddings(documents):
    model_path = Path(__file__).resolve().parent.parent / "models" / "paraphrase-multilingual-MiniLM-L12-v2"

    if not model_path.exists():
        raise FileNotFoundError(
            f"Embedding model not found at {model_path}. "
            "Run: python download_models.py"
        )

    model = SentenceTransformer(str(model_path))
    embeddings = model.encode(documents, show_progress_bar=True)
    return embeddings

# build topic model
def build_topic_model(n_docs=None):
    custom_stop_words = list(ENGLISH_STOP_WORDS.union({
        "yes", "like", "im", "dont", "did", "oh", "okay",
        "think", "right", "know", "really"
    }))


    vectorizer_model = CountVectorizer(stop_words=custom_stop_words)

    # Scale the dimensionality-reduction + clustering parameters with the
    # number of documents. UMAP requires n_neighbors < n_docs and
    # n_components < n_docs; HDBSCAN's min_cluster_size must be at least 2
    # but not larger than the dataset. Without this, small transcripts
    # crash with "k must be <= number of training points".
    if n_docs is None or n_docs <= 0:
        n_docs = 30  # legacy default sizing

    n_neighbors = max(2, min(15, n_docs - 1))
    n_components = max(2, min(5, n_docs - 1))
    min_cluster_size = max(2, min(4, max(2, n_docs // 4)))

    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=42
    )

    hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=max(1, min(2, min_cluster_size - 1)),
        metric="euclidean",
        prediction_data=True
    )

    topic_model = BERTopic(
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        nr_topics=None,
        verbose=True
    )

    return topic_model

# run BERTopic clustering on transcript segments
def run_topic_model(documents, embeddings):
    topic_model = build_topic_model(n_docs=len(documents))
    topics, probs = topic_model.fit_transform(documents, embeddings)
    return topic_model, topics, probs

# save topic assignments to csv
def save_results(df, topics, original_name):
    df = df.copy()
    df["topic"] = topics

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{original_name}_topic_results.csv"

    df.to_csv(output_file, index=False)
    print(f"Topic results saved to {output_file}")

    return output_file

# save the trained BERTopic model
def save_model(topic_model, original_name):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / f"{original_name}_topic_model"
    
    if os.path.exists(model_path):
        if os.path.isdir(model_path):
            shutil.rmtree(model_path)
        else:
            os.remove(model_path)

    topic_model.save(model_path)
    print(f"Topic model saved to {model_path}")

    return model_path

# build structured summary for each topic
def build_topic_summary(topic_model, df, topics, max_keywords=8, max_examples=10):
    df = df.copy()
    df["topic"] = topics

    topic_info = topic_model.get_topic_info()
    summary = []

    for topic_id in topic_info["Topic"]:
        if topic_id == -1:
            continue  # skip outliers

        keywords_raw = topic_model.get_topic(topic_id)
        if not keywords_raw:
            continue

        keywords = [word for word, _ in keywords_raw[:max_keywords]]

        topic_rows = df[df["topic"] == topic_id].copy()
        if topic_rows.empty:
            continue

        example_rows = topic_rows.head(max_examples)

        example_segments = []
        for _, row in example_rows.iterrows():
            example_segments.append({
                "segment_id": int(row["segment_id"]) if "segment_id" in row and pd.notna(row["segment_id"]) else None,
                "text": row["cleaned_text"],
                "source_file": row["source_file"] if "source_file" in row else None,
                "speaker": row["speaker"] if "speaker" in row else None,
                "topic": int(topic_id)
            })

        summary.append({
            "topic_id": int(topic_id),
            "generated_label": None,
            "keywords": keywords,
            "examples": [ex["text"] for ex in example_segments],  # keep old format too
            "example_segments": example_segments,
            "source_files": [ex["source_file"] for ex in example_segments],
            "segment_count": int(len(topic_rows))
        })

    return summary
    
# save topic summary to json
def save_topic_summary(topic_summary, original_name):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_file = OUTPUT_DIR / f"{original_name}_topic_summary.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(topic_summary, f, indent=2, ensure_ascii=False)

    print(f"Topic summary saved to {output_file}")
    return output_file
    
# generate a short label for one topic using GPT4All (fully offline)
def _build_label_prompt(topic_entry):
    examples = topic_entry.get("examples", [])
    ex_lines = "\n".join(
        f"- {ex[:200]}" for ex in examples[:3] if ex
    )
    return (
        "You are labeling a topic from interview transcript analysis.\n"
        "Create a short, human-readable topic label in 3 to 5 words.\n"
        "Do not use quotation marks. Do not explain. Return only the label.\n\n"
        f"Keywords: {', '.join(topic_entry.get('keywords', []))}\n\n"
        f"Representative excerpts:\n{ex_lines}"
    )


# add GPT4All labels to all topics (loads model once for efficiency)
def add_llm_labels(topic_summary, model_name="mistral-7b-openorca.Q4_0.gguf"):
    try:
        from gpt4all import GPT4All
    except ImportError:
        print("[warn] gpt4all is not installed — skipping LLM labeling.")
        return topic_summary

    try:
        model = GPT4All(model_name, verbose=False)
    except Exception as e:
        print(f"[error] Could not load GPT4All model '{model_name}': {e}")
        return topic_summary

    labeled_summary = []
    for entry in topic_summary:
        entry_copy = entry.copy()
        try:
            prompt = _build_label_prompt(entry_copy)
            with model.chat_session():
                raw = model.generate(prompt, max_tokens=30).strip()
            label = raw.splitlines()[0].strip('" ') if raw else None
            entry_copy["generated_label"] = label
            print(f"Generated label for Topic {entry_copy['topic_id']}: {label}")
        except Exception as e:
            print(f"Could not generate label for Topic {entry_copy['topic_id']}: {e}")
            entry_copy["generated_label"] = None
        labeled_summary.append(entry_copy)

    return labeled_summary
        
# print topic summary and top keywords
def print_topic_summary(topic_model, topic_summary):
    topic_info = topic_model.get_topic_info()

    def truncate(text, max_len=200):
        return text[:max_len] + "..." if len(text) > max_len else text

    print("\n=== Topic Overview ===")
    print(topic_info)

    print("\n=== Topic Summaries ===")
    for entry in topic_summary:
        print(f"\nTopic {entry['topic_id']}")
        print(f"Label: {entry['generated_label']}")
        print(f"Keywords: {', '.join(entry['keywords'])}")
        print("Examples:")
        for example in entry["examples"]:
            print(f"  - {truncate(example)}")

# handles command-line input, runs topic modeling, and saves outputs
if __name__ == "__main__":

    # usage:
    # python topic_modeling.py <cleaned_transcript_csv>
    # python topic_modeling.py <cleaned_transcript_csv> --label
    # python topic_modeling.py <cleaned_transcript_csv> --label mistral-7b-openorca.Q4_0.gguf
    if len(sys.argv) < 2:
        print("Usage: python topic_modeling.py <cleaned_transcript_csv> [--label] [gpt4all_model_name]")
        sys.exit(1)

    input_file = sys.argv[1]

    use_labeling = False
    gpt4all_model_name = "mistral-7b-openorca.Q4_0.gguf"

    if len(sys.argv) >= 3 and sys.argv[2] == "--label":
        use_labeling = True

    if len(sys.argv) >= 4:
        gpt4all_model_name = sys.argv[3]

    original_name = os.path.splitext(os.path.basename(input_file))[0]

    df, documents = load_data(input_file)
    embeddings = generate_embeddings(documents)
    topic_model, topics, probs = run_topic_model(documents, embeddings)

    save_results(df, topics, original_name)
    save_model(topic_model, original_name)

    topic_summary = build_topic_summary(topic_model, df, topics)

    if use_labeling:
        topic_summary = add_llm_labels(topic_summary, model_name=gpt4all_model_name)

    save_topic_summary(topic_summary, original_name)
    print_topic_summary(topic_model, topic_summary)
