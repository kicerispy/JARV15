import time

import speech
from conversation_handler import build_conversation_messages
from state import ActiveContext
from ollama import chat

SYSTEM_PROMPT = """
You are JARVIS, a personal AI assistant.
Keep answers concise.
"""

messages = build_conversation_messages(
    "What can you do?",
    ActiveContext(),
    SYSTEM_PROMPT,
)

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: messages =", len(messages))
print("TEST: total chars =", sum(len(str(m.get("content", ""))) for m in messages))
print("TEST: sending exact conversation payload to qwen3.5:9b...")
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
