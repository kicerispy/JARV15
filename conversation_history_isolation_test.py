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

reduced_messages = [
    messages[0],
    messages[-1],
]

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: original messages =", len(messages))
print("TEST: reduced messages =", len(reduced_messages))
print(
    "TEST: reduced chars =",
    sum(len(str(m.get("content", ""))) for m in reduced_messages),
)
print("TEST: sending system + user only...")
print("TEST: think=False, num_gpu=40")

t = time.perf_counter()

response = chat(
    model="qwen3.5:9b",
    messages=reduced_messages,
    think=False,
    options={
        "num_gpu": 40,
        "num_predict": 100,
    },
)

print("TEST: elapsed =", round(time.perf_counter() - t, 3))
print("TEST: content =", repr(response.message.content))
print("TEST: thinking =", repr(getattr(response.message, "thinking", None)))
