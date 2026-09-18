import time

import speech
from ollama import chat

messages = [
    {
        "role": "user",
        "content": "hello",
    },
]

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: messages = 1")
print("TEST: NO system message")
print("TEST: sending user message only...")
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
