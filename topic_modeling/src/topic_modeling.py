import sys
import os
import pandas as pd
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer

# load cleaned transcript data from csv
def load_data(file_path):
    df = pd.read_csv(file_path)

    # ensure cleaned transcript column exists
    if "cleaned_text" not in df.columns:
        raise ValueError("CSV must contain a cleaned_text column")

    # remove empty rows
    df = df.dropna(subset=["cleaned_text"]).copy()
    df["cleaned_text"] = df["cleaned_text"].astype(str).str.strip()
    
    # exclude interviewer turns if specified
    if "include_in_topic_model" in df.columns:
        df["include_in_topic_model"] = df["include_in_topic_model"].astype(str).str.lower()
        df = df[df["include_in_topic_model"].isin(["true"])].copy()

    # remove very short segments for line-based sprint 1 testing
    df = df[df["cleaned_text"].str.len() >= 15].reset_index(drop=True)

    # stop if no usable transcript segments remain
    if df.empty:
        raise ValueError("No usable transcript segments found")

    documents = df["cleaned_text"].tolist()

    return df, documents

# generate sentence embeddings using multilingual embedding model
def generate_embeddings(documents):
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    embeddings = model.encode(documents, show_progress_bar=True)

    return embeddings

# build BERTopic model with CountVectorizer for keyword extraction
def build_topic_model():
    # remove common english stopwords for clearer topic keywords
    vectorizer_model = CountVectorizer(stop_words="english")

    topic_model = BERTopic(
        vectorizer_model=vectorizer_model,
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

    # ensure output directory exists
    os.makedirs("../output", exist_ok=True)

    output_file = f"../output/{original_name}_topic_results.csv"

    df.to_csv(output_file, index=False)

    print(f"Topic results saved to {output_file}")

    return output_file

# save the trained BERTopic model
def save_model(topic_model, original_name):
    # ensure output directory exists
    os.makedirs("../output", exist_ok=True)

    model_path = f"../output/{original_name}_topic_model"

    topic_model.save(model_path)

    print(f"Topic model saved to {model_path}")

    return model_path

# print topic summary and top keywords
def print_topic_summary(topic_model):
    topic_info = topic_model.get_topic_info()

    print("\n=== Topic Overview ===")
    print(topic_info)

    # print top keywords for each discovered topic
    for topic_id in topic_info["Topic"]:
        if topic_id == -1:
            continue  # skip outliers

        print(f"\nTopic {topic_id}:")

        keywords = topic_model.get_topic(topic_id)

        if not keywords:
            print("No keywords found")
            continue

        for word, score in keywords[:10]:
            print(f"  {word} ({score:.4f})")

# handles command-line input, runs topic modeling, and saves outputs
if __name__ == "__main__":

    # ensure a cleaned transcript csv was provided as a command line argument
    if len(sys.argv) < 2:
        print("Usage: python topic_modeling.py <cleaned_transcript_csv>")
        sys.exit(1)

    # read cleaned transcript file path from command line
    input_file = sys.argv[1]

    # get original filename without extension
    original_name = os.path.splitext(os.path.basename(input_file))[0]

    # load cleaned transcript
    df, documents = load_data(input_file)
    
    # generate embeddings
    embeddings = generate_embeddings(documents)

    # run BERTopic
    topic_model, topics, probs = run_topic_model(documents, embeddings)

    # save topic assignments
    save_results(df, topics, original_name)

    # save trained model
    save_model(topic_model, original_name)

    # print topic summary
    print_topic_summary(topic_model)
