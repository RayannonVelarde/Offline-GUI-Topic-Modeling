import whisperx
import torch
from dotenv import load_dotenv
import os
import time
torch.serialization.add_safe_globals(['omegaconf.listconfig.ListConfig'])
from pyannote.audio import Pipeline
import pandas as pd
import sys

_original_torch_load = torch.load

def _trusted_load(*args, **kwargs):
    kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)

torch.load = _trusted_load

# print(torch.__version__)
# --- LOAD .ENV VARIABLES ---
load_dotenv()
your_token = os.getenv("HUGGINGFACE_TOKEN")

if your_token is None:
    raise ValueError("Hugging Face token not found! Please set it in your .env file.")

# --- SETTINGS ---
# audio_file = "Podcast_4_Interview_with_Quique.mp3"  # <--- Your Spanish audio file here
audio_file = sys.argv[1]
num_speakers = 2
if len(sys.argv) > 2:
    try:
        n = int(sys.argv[2])
        if n >= 1:
            num_speakers = n
    except ValueError:
        pass
output_txt_spanish = "transcription_spanish.txt"
output_txt_english = "transcription_english.txt"
batch_size = 8 #16
compute_type = "float32"

# --- DEVICE SETUP ---
device = "cuda" if torch.cuda.is_available() else "cpu"

start_time = time.time()

# --- LOAD AUDIO ---
print("Loading audio...")
audio = whisperx.load_audio(audio_file)

# --- LOAD WHISPERX MODEL ---
print("Loading WhisperX model...")
model = whisperx.load_model("small", device, compute_type=compute_type)

# --- TRANSCRIBE TO SPANISH ---
print("Transcribing Spanish audio...")
result_spanish = model.transcribe(audio, batch_size=batch_size, language="es")

# --- TRANSLATE TO ENGLISH ---
print("Translating Spanish audio to English...")
result_english = model.transcribe(audio, batch_size=batch_size, language="es", task="translate")

# --- ALIGN SPANISH TRANSCRIPTION ---
print("Loading alignment model...")
model_a, metadata = whisperx.load_align_model(language_code="es", device=device)

print("Aligning Spanish transcription...")
result_spanish = whisperx.align(result_spanish["segments"], model_a, metadata, audio, device, return_char_alignments=False)

# --- ALIGN ENGLISH TRANSLATION (still original audio) ---
print("Aligning English translation...")
# Even if it's translated, alignment happens against original Spanish audio
result_english = whisperx.align(result_english["segments"], model_a, metadata, audio, device, return_char_alignments=False)

# --- LOAD DIARIZATION MODEL ---
print("Loading speaker diarization model...")
# diarize_model = whisperx.DiarizationPipeline(
#     use_auth_token=your_token,
#     device=device
# )
diarize_model = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=your_token
)
diarize_model.to(torch.device(device))

# --- PERFORM DIARIZATION ---
print("Diarizing audio...")
# audio_dict = {"uri": "audio", "audio": audio_file}
diarize_segments = diarize_model(audio_file, num_speakers=num_speakers)

diarize_list = []
for turn, _, speaker in diarize_segments.itertracks(yield_label=True):
    diarize_list.append({
        "start": float(turn.start),
        "end": float(turn.end),
        "speaker":str(speaker)
    })
if not diarize_list:
    print("WARNING: No diarization found")
    diarize_df = pd.DataFrame(columns=["start", "end", "speaker"])
else:
    diarize_df = pd.DataFrame(diarize_list)
    print(f"Found {diarize_df['speaker'].nunique()} speakers")
    print("DataFrame info:")
    print(diarize_df.head())
    print("\nColumns:", diarize_df.columns.tolist())

# --- ASSIGN SPEAKERS ---
print("Assigning speakers to Spanish segments...")
result_spanish = whisperx.assign_word_speakers(diarize_df, result_spanish) #diarize_segments, result_spanish

print("Assigning speakers to English segments...")
result_english = whisperx.assign_word_speakers(diarize_df, result_english) #diarize_segments, result_english
# --- SAVE SPANISH OUTPUT ---
print(f"Saving Spanish transcription to {output_txt_spanish}...")
with open(output_txt_spanish, "w", encoding="utf-8") as f:
    for segment in result_spanish["segments"]:
        speaker = segment.get("speaker", "Unknown")
        text = segment["text"].strip()
        f.write(f"[{speaker}]: {text}\n")

# --- SAVE ENGLISH OUTPUT ---
print(f"Saving English transcription to {output_txt_english}...")
with open(output_txt_english, "w", encoding="utf-8") as f:
    for segment in result_english["segments"]:
        speaker = segment.get("speaker", "Unknown")
        text = segment["text"].strip()
        f.write(f"[{speaker}]: {text}\n")

end_time = time.time()
print("Done! Both Spanish and English transcriptions saved with speaker labels. Hurray!!")
print(f"Total execution time: {end_time - start_time:.2f} seconds.")