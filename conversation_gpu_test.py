import time

import speech
from conversation_handler import handle_normal_conversation
from state import ActiveContext

SYSTEM_PROMPT = """
You are JARVIS, a personal AI assistant.
Keep answers concise.
"""

def fake_speak(text):
    print("TEST: reply =", repr(text))
    return False

print("TEST: Whisper =", "CUDA" if next(speech.model.parameters()).is_cuda else "CPU")
print("TEST: actual conversation handler")
print("TEST: qwen3.5:9b, think=False, 40 GPU layers")

t = time.perf_counter()

# Temporarily monkey-patch the chat function used by
# conversation_handler so we can test its exact message-building
# path with the desired Ollama settings.
import conversation_handler
from ollama import chat

def test_chat(model, messages):
    return chat(
        model=model,
        messages=messages,
        think=False,
        options={
            "num_gpu": 40,
            "num_predict": 100
        }
    )

conversation_handler.chat = test_chat

result = handle_normal_conversation(
    "What can you do?",
    ActiveContext(),
    SYSTEM_PROMPT,
    fake_speak
)

print("TEST: handler result =", result)
print("TEST: elapsed =", round(time.perf_counter() - t, 3))
