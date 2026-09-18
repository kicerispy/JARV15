import time

import speech
from conversation_handler import build_conversation_messages
from state import ActiveContext
from ollama import chat

SYSTEM_PROMPT = """
You are JARVIS, a personal AI assistant.
Keep answers concise.
"""

original = build_conversation_messages(
    "What can you do?",
    ActiveContext(),
    SYSTEM_PROMPT,
)

test_messages = [
    original[0],
    {"role": "user", "content": "hello"},
]

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: messages =", len(test_messages))
print("TEST: system chars =", len(test_messages[0]["content"]))
print("TEST: user =", repr(test_messages[1]["content"]))
print("TEST: sending EXACT generated system message + trivial user...")
print("TEST: think=False, num_gpu=40")

print("\n--- SYSTEM MESSAGE ---")
print(test_messages[0]["content"])
print("--- END SYSTEM MESSAGE ---\n")

t = time.perf_counter()

response = chat(
    model="qwen3.5:9b",
    messages=test_messages,
    think=False,
    options={
        "num_gpu": 40,
        "num_predict": 100,
    },
)

print("TEST: elapsed =", round(time.perf_counter() - t, 3))
print("TEST: content =", repr(response.message.content))
print("TEST: thinking =", repr(getattr(response.message, "thinking", None)))
