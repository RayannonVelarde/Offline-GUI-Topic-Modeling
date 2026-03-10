from bertopic import BERTopic
from sentence_transformers import SentenceTransformer

# load transcript (each line = one document)
with open("../data/transcription_english.txt", "r", encoding="utf-8") as f:
    documents = [line.strip() for line in f if line.strip()]

# load embedding model
embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# create BERTopic model
topic_model = BERTopic(
    embedding_model=embedding_model,
    language="multilingual",
    min_topic_size=10  # adjust later if needed
)

# fit model
topics, probs = topic_model.fit_transform(documents)

# print topic summary
print("\nTopic Overview:")
print(topic_model.get_topic_info())

# print top keywords per topic
for topic_id in topic_model.get_topic_info()["Topic"]:
    if topic_id == -1:
        continue  # skip outliers
    print(f"\nTopic {topic_id}:")
    print(topic_model.get_topic(topic_id))
