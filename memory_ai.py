"""
JARVIS memory analysis - decides what's worth remembering.
"""

from ollama import chat

from config import CHAT_MODEL
from logger import logger

MEMORY_PROMPT = """
You decide if a user message contains information worth remembering.

Remember:
- preferences
- hobbies
- important facts
- personal settings

Do NOT remember:
- temporary questions
- random conversation

If it is worth remembering, reply with:
SAVE: information

If not, reply:
NO
"""


def analyze_memory(text: str) -> bool:
    """
    Analyze a user message to determine if it contains information worth remembering.

    Args:
        text: The user's message text.

    Returns:
        True if the memory was saved, False otherwise.
    """
    if not text or not text.strip():
        return False

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": MEMORY_PROMPT},
                {"role": "user", "content": text}
            ]
        )

        result = response.get("message", {}).get("content", "").strip()

        if result.startswith("SAVE:"):
            fact = result.replace("SAVE:", "").strip()
            if fact:
                from memory import save_memory
                return save_memory(fact)

        return False

    except Exception as e:
        logger.warning(f"Memory analysis failed: {e}")
        return False
