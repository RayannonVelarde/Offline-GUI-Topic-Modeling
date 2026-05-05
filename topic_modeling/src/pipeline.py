import os
import sys
import subprocess
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SRC_DIR.parent / "output"

def run_pipeline(input_path, interviewer_speaker=None, use_labeling=False, ollama_model="llama3.1"):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_path = Path(input_path)

    # run preprocessing
    preprocess_cmd = [sys.executable, str(SRC_DIR / "preprocess.py"), str(input_path)]
    if interviewer_speaker:
        preprocess_cmd.append(interviewer_speaker)

    print("[STAGE] preprocessing")
    print("=== Running preprocessing ===")
    subprocess.run(preprocess_cmd, check=True, cwd=SRC_DIR)

    # determine which cleaned csv to send into topic modeling
    if input_path.is_file():
        preprocessed_csv = OUTPUT_DIR / f"{input_path.stem}.csv"
    elif input_path.is_dir():
        preprocessed_csv = OUTPUT_DIR / f"{input_path.name}.csv"
    else:
        raise ValueError("Invalid input path")

    # build expected output names
    original_name = Path(preprocessed_csv).stem
    topic_results_csv = OUTPUT_DIR / f"{original_name}_topic_results.csv"
    topic_model_path = OUTPUT_DIR / f"{original_name}_topic_model"
    topic_summary_json = OUTPUT_DIR / f"{original_name}_topic_summary.json"

    # run topic modeling
    topic_cmd = [sys.executable, str(SRC_DIR / "topic_modeling.py"), str(preprocessed_csv)]
    if use_labeling:
        topic_cmd.extend(["--label", ollama_model])

    print("[STAGE] bertopic")
    print("\n=== Running topic modeling ===")
    subprocess.run(topic_cmd, check=True, cwd=SRC_DIR)

    print("[STAGE] done")
    print("\n=== Pipeline complete ===")
    print(f"Input transcript: {input_path}")
    print(f"Cleaned transcript: {preprocessed_csv}")
    print(f"Topic results: {topic_results_csv}")
    print(f"Topic model: {topic_model_path}")
    print(f"Topic summary: {topic_summary_json}")

    if use_labeling:
        print(f"GPT4All labeling: enabled ({ollama_model})")
    else:
        print("GPT4All labeling: disabled")

# CLI entry
if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <transcript_file> [interviewer_speaker] [--label] [ollama_model_name]")
        sys.exit(1)

    transcript_file = sys.argv[1]
    interviewer_speaker = None
    use_labeling = False
    ollama_model = "llama3.1"

    remaining_args = sys.argv[2:]

    # optional interviewer speaker
    if remaining_args and remaining_args[0] != "--label":
        interviewer_speaker = remaining_args[0]
        remaining_args = remaining_args[1:]

    # optional labeling flag
    if remaining_args and remaining_args[0] == "--label":
        use_labeling = True
        remaining_args = remaining_args[1:]

    # optional ollama model name
    if remaining_args:
        ollama_model = remaining_args[0]

    run_pipeline(
        transcript_file,
        interviewer_speaker=interviewer_speaker,
        use_labeling=use_labeling,
        ollama_model=ollama_model
    )
