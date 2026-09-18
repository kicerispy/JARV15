import time

import speech
from ollama import chat

SYSTEM_PROMPT = """
You are JARVIS, a personal AI assistant.
Keep answers concise.

Relevant memories:

Use these naturally when relevant.
"""

messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT,
    },
    {
        "role": "user",
        "content": "hello",
    },
]

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: system chars =", len(SYSTEM_PROMPT))
print("TEST: memory items = 0")
print("TEST: sending memory section with NO memory content...")
print("TEST: think=False, num_gpu=40")

t = time.perf_counter()

response = chat(
    model="qwen3.5:9b",
    messages=messages,
    think=False,
    options={
        "num_gpu": 40,
        "num_predict": 100,
    },
)

print("TEST: elapsed =", round(time.perf_counter() - t, 3))
print("TEST: content =", repr(response.message.content))
print("TEST: thinking =", repr(getattr(response.message, "thinking", None)))
