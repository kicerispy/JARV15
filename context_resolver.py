"""
JARVIS context resolver - resolves follow-up commands using conversation history.
"""
from typing import Any, Dict, Optional

from ollama import chat

from config import CHAT_MODEL
from logger import logger


def resolve_followup(
    user_input: str,
    active_context: Dict[str, Any],
    history_text: str
) -> str:
    """
    Resolve a contextual follow-up command into a standalone instruction.

    Args:
        user_input: The user's original command.
        active_context: Current active task context.
        history_text: Recent conversation history.

    Returns:
        Resolved standalone instruction, or the original input on failure.
    """
    if not user_input or not user_input.strip():
        return user_input

    active_site = active_context.get("site") or "none"
    last_query = active_context.get("last_query") or "none"
    last_tool = active_context.get("last_tool") or "none"
    last_result = active_context.get("last_result") or "none"

    prompt = f"""
You are JARVIS's command-context resolver.

Rewrite the user's latest command into ONE standalone
instruction for JARVIS's task planner.

Do NOT answer the user.
Do NOT explain your reasoning.
Return ONLY the standalone instruction.

Rules:

1. Preserve the active task context when appropriate.

2. If the active website is YouTube and the user says:
   "look for the trailer"
   rewrite it as:
   "Search YouTube for the Iron Man trailer."

3. If the user says:
   "look for another one"
   preserve the active website and subject when possible.

4. Never replace a known website with generic web search.

5. Resolve references like:
   "it"
   "that"
   "this"
   "the trailer"
   "the video"
   "the previous one"
   "another one"
   "there"

6. Do not invent information.

7. Preserve explicit information from the latest command.

ACTIVE TASK:

Website:
{active_site}

Previous search:
{last_query}

Previous tool:
{last_tool}

Previous result:
{last_result}

RECENT CONVERSATION:

{history_text}

LATEST COMMAND:

{user_input}
"""

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[{"role": "system", "content": prompt}],
            options={"temperature": 0.0}
        )

        resolved = response.get("message", {}).get("content", "").strip()

        if not resolved or len(resolved) > 500:
            return user_input

        logger.info(f"Context resolved: '{user_input}' -> '{resolved}'")
        return resolved

    except Exception as e:
        logger.warning(f"Context resolution skipped: {e}")
        return user_input