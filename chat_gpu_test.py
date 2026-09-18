import time
import speech
from ollama import chat

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: qwen3:8b conversation test...")

t = time.perf_counter()

r = chat(
    model="qwen3:8b",
    messages=[
        {
            "role": "user",
            "content": "What can you do? Answer briefly."
        }
    ],
    think=False,
    options={
        "num_predict": 100
    }
)

print("TEST: elapsed =", round(time.perf_counter() - t, 3))
print("TEST: content =", repr(r.message.content))
print("TEST: thinking =", repr(getattr(r.message, "thinking", None)))
