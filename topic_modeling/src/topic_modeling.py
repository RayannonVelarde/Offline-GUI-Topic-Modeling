import sys
import os
import json
import requests
import shutil
from pathlib import Path
import pandas as pd
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
from hdbscan import HDBSCAN
from umap import UMAP

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
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    embeddings = model.encode(documents, show_progress_bar=True)
    return embeddings

# build topic model
def build_topic_model():
    vectorizer_model = CountVectorizer(stop_words="english", ngram_range=(1,2), min_df=2)

    umap_model = UMAP(
        n_neighbors=5,
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42
    )

    hdbscan_model = HDBSCAN(
        min_cluster_size=4,
        min_samples=2,
        metric="euclidean",
        prediction_data=True
    )

    topic_model = BERTopic(
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        nr_topics=8,
        verbose=True
    )

    return topic_model
    
# run BERTopic clustering on transcript segments
def run_topic_model(documents, embeddings):
    topic_model = build_topic_model()
    topics, probs = topic_model.fit_transform(documents, embeddings)
    return topic_model, topics, probs

# save topic assignments to csv
def save_results(df, topics, original_name):
    df = df.copy()
    df["topic"] = topics

    os.makedirs("../output", exist_ok=True)
    output_file = f"../output/{original_name}_topic_results.csv"

    df.to_csv(output_file, index=False)
    print(f"Topic results saved to {output_file}")

    return output_file

# save the trained BERTopic model
def save_model(topic_model, original_name):
    os.makedirs("../output", exist_ok=True)
    model_path = f"../output/{original_name}_topic_model"
    
    if os.path.exists(model_path):
        if os.path.isdir(model_path):
            shutil.rmtree(model_path)
        else:
            os.remove(model_path)

    topic_model.save(model_path)
    print(f"Topic model saved to {model_path}")

    return model_path

# build structured summary for each topic
def build_topic_summary(topic_model, df, topics, max_keywords=8, max_examples=3):
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
        examples = example_rows["cleaned_text"].tolist()

        summary.append({
            "topic_id": int(topic_id),
            "generated_label": None,
            "keywords": keywords,
            "examples": examples,
            "source_files": example_rows["source_file"].tolist() if "source_file" in example_rows.columns else [],
            "segment_count": int(len(topic_rows))
        })

    return summary
    
# save topic summary to json
def save_topic_summary(topic_summary, original_name):
    os.makedirs("../output", exist_ok=True)

    output_file = f"../output/{original_name}_topic_summary.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(topic_summary, f, indent=2, ensure_ascii=False)

    print(f"Topic summary saved to {output_file}")
    return output_file
    
# generate a short label for one topic using local ollama
def generate_label_with_ollama(topic_entry, model_name="llama3.1"):
    prompt = f"""
You are labeling a topic from interview transcript analysis.

Create a short, human-readable topic label in 3 to 5 words.
Do not use quotation marks.
Do not explain your answer.
Return only the label.

Keywords:
{", ".join(topic_entry["keywords"])}

Representative excerpts:
- {topic_entry["examples"][0] if len(topic_entry["examples"]) > 0 else ""}
- {topic_entry["examples"][1] if len(topic_entry["examples"]) > 1 else ""}
- {topic_entry["examples"][2] if len(topic_entry["examples"]) > 2 else ""}
""".strip()

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    response.raise_for_status()
    data = response.json()

    label = data.get("response", "").strip()
    return label if label else None
    
# add ollama labels to all topics
def add_llm_labels(topic_summary, model_name="llama3.1"):
    labeled_summary = []

    for entry in topic_summary:
        entry_copy = entry.copy()
        try:
            label = generate_label_with_ollama(entry_copy, model_name=model_name)
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
    # python topic_modeling.py <cleaned_transcript_csv> --label mistral
    if len(sys.argv) < 2:
        print("Usage: python topic_modeling.py <cleaned_transcript_csv> [--label] [ollama_model_name]")
        sys.exit(1)

    input_file = sys.argv[1]

    use_labeling = False
    ollama_model_name = "llama3.1"

    if len(sys.argv) >= 3 and sys.argv[2] == "--label":
        use_labeling = True

    if len(sys.argv) >= 4:
        ollama_model_name = sys.argv[3]

    original_name = os.path.splitext(os.path.basename(input_file))[0]

    df, documents = load_data(input_file)
    embeddings = generate_embeddings(documents)
    topic_model, topics, probs = run_topic_model(documents, embeddings)

    save_results(df, topics, original_name)
    save_model(topic_model, original_name)

    topic_summary = build_topic_summary(topic_model, df, topics)

    if use_labeling:
        topic_summary = add_llm_labels(topic_summary, model_name=ollama_model_name)

    save_topic_summary(topic_summary, original_name)
    print_topic_summary(topic_model, topic_summary)
