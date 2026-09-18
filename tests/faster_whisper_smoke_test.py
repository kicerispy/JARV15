import os
import time

import speech

print("TEST: backend =", type(speech.model).__name__)
print("TEST: device =", speech.WHISPER_DEVICE)
print("TEST: compute_type =", speech.WHISPER_COMPUTE_TYPE)
print("TEST: model =", speech.WHISPER_MODEL)

audio_file = ".\input.wav"

if not os.path.exists(audio_file):
    print("TEST: input.wav not found")
    raise SystemExit(1)

print("TEST: transcribing input.wav...")

t = time.perf_counter()

segments, info = speech.model.transcribe(
    audio_file,
    language="en",
    temperature=0,
)

segments = list(segments)

elapsed = time.perf_counter() - t

text = " ".join(
    segment.text
    for segment in segments
).strip()

print("TEST: elapsed =", round(elapsed, 3))
print("TEST: segments =", len(segments))
print("TEST: language =", info.language)
print("TEST: text =", repr(text))
