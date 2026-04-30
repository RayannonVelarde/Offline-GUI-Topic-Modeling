from sentence_transformers import SentenceTransformer
from pathlib import Path

# Download and store embedding model locally for offline topic modeling

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SAVE_PATH = Path(__file__).resolve().parent.parent / "models" / "paraphrase-multilingual-MiniLM-L12-v2"

def download_model():
    if SAVE_PATH.exists():
        print("Model already exists. Skipping download.")
        return

    print("Downloading embedding model...")
    model = SentenceTransformer(MODEL_NAME)
    model.save(str(SAVE_PATH))
    print(f"Model saved to {SAVE_PATH}")

if __name__ == "__main__":
    download_model()
