import planner
from ollama import chat
from config import PLANNER_MODEL

messages = [
    {
        "role": "system",
        "content": planner._planner_prompt(),
    },
    {
        "role": "user",
        "content": "Show a JARVIS status card on the Barehands display",
    },
]

r = chat(
    model=PLANNER_MODEL,
    messages=messages,
    format="json",
)

print("DONE:", r.get("done"))
print("DONE_REASON:", r.get("done_reason"))
print("PROMPT_EVAL_COUNT:", r.get("prompt_eval_count"))
print("EVAL_COUNT:", r.get("eval_count"))
print("CONTENT_LENGTH:", len(r.get("message", {}).get("content", "")))
print("CONTENT:")
print(repr(r.get("message", {}).get("content", "")))
