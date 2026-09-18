from ollama import chat
from config import PLANNER_MODEL

r = chat(
    model=PLANNER_MODEL,
    messages=[
        {
            "role": "system",
            "content": (
                "Return ONLY valid JSON with this exact structure: "
                '{"goal":"test","steps":[{"tool":"barehands_present",'
                '"argument":"JARVIS|||Hello"}]}'
            ),
        },
        {
            "role": "user",
            "content": "Show a JARVIS status card on the Barehands display",
        },
    ],
    format="json",
)

print("DONE:", r.get("done"))
print("DONE_REASON:", r.get("done_reason"))
print("CONTENT:", repr(r.get("message", {}).get("content", "")))
