from ollama import chat


model = "gemma4:e2b"


def summarize_web_results(results):

    if not results:
        return "I could not find any information."

    response = chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": """
You are JARVIS.

Summarize the information provided.

Rules:
- Give the most important facts first.
- Be concise.
- Do not mention search results.
- Answer naturally.
"""
            },
            {
                "role": "user",
                "content": results
            }
        ]
    )

    return response["message"]["content"]