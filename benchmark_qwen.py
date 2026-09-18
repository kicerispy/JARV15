from ollama import chat

model = "qwen3.5:9b"

prompt = """You are JARVIS's task planner.

Available tools:
- jarvis_status: report JARVIS's own internal status or uptime.
- barehands_present: present information on the Barehands glass board.

Rules:
- jarvis_status is for reporting JARVIS's own internal status.
- barehands_present is for presenting information on the Barehands display.
- If the user asks to show, display, or present information on Barehands, use barehands_present.
- Return ONLY valid JSON.
"""

r = chat(
    model=model,
    messages=[
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": "Show a JARVIS status card on the Barehands display",
        },
    ],
    format="json",
)

print("MODEL:", model)
print("DONE:", r.get("done"))
print("DONE_REASON:", r.get("done_reason"))
print("EVAL_COUNT:", r.get("eval_count"))
print("CONTENT:", r.get("message", {}).get("content", ""))
