"""
JARVIS context resolver - resolves follow-up commands using conversation history.
"""
from typing import Any, Dict, Optional

from ollama import chat

from config import CHAT_MODEL
from logger import logger


_CONTEXTUAL_PATTERNS = (
    (r"^(?:click|open|play|select|choose|pick)\s+(?:the\s+)?(?:first|top)\s+(?:result|link|video|one|item)$",
     "click the first browser result"),
    (r"^(?:click|open|play|select|choose|pick)\s+(?:the\s+)?(?:second|2nd)\s+(?:result|link|video|one|item)$",
     "click the second browser result"),
    (r"^(?:click|open|play|select|choose|pick)\s+(?:the\s+)?(?:third|3rd)\s+(?:result|link|video|one|item)$",
     "click the third browser result"),
    (r"^(?:click|open|play|select|choose|pick)\s+(?:the\s+)?(?:last|final)\s+(?:result|link|video|one|item)$",
     "click the last browser result"),
    (r"^(?:go\s+)?back$", "go back in the browser"),
    (r"^(?:read|show|tell me)\s+(?:the\s+)?(?:page|page contents|page text)$",
     "read the current browser page"),
    (r"^(?:read|show|tell me)\s+(?:the\s+)?(?:title|page title)$",
     "inspect the current browser page"),
)


def _deterministic_followup(user_input: str, active_context: Dict[str, Any]) -> Optional[str]:
    normalized = " ".join(str(user_input or "").strip().lower().split())
    if not normalized:
        return None

    site = str(active_context.get("site") or "").strip().lower()
    last_title = str(active_context.get("last_result_title") or "").strip()

    for pattern, resolved in _CONTEXTUAL_PATTERNS:
        import re
        if re.match(pattern, normalized):
            if resolved.startswith("click the") and site:
                if "last browser result" in resolved:
                    return resolved + f" on {site}"
                return resolved + f" on {site}"
            return resolved

    if normalized in {"click it", "open it", "play it", "select it", "use it", "open that", "click that", "play that"}:
        if last_title:
            return f"click the browser element with visible text {last_title!r}"
        if site:
            return f"click the current browser result on {site}"

    if normalized in {"that one", "this one", "the same one", "do it", "do that", "try it", "try that"}:
        if last_title:
            return f"click the browser element with visible text {last_title!r}"
        if site:
            return f"repeat the last browser action on {site}"

    return None


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

    deterministic = _deterministic_followup(user_input, active_context)
    if deterministic:
        logger.info(f"Deterministic context resolution: '{user_input}' -> '{deterministic}'")
        return deterministic

    active_site = active_context.get("site") or "none"
    last_query = active_context.get("last_query") or "none"
    last_tool = active_context.get("last_tool") or "none"
    last_result = active_context.get("last_result") or "none"
    page_url = active_context.get("page_url") or "none"
    page_title = active_context.get("page_title") or "none"
    last_result_title = active_context.get("last_result_title") or "none"
    last_result_url = active_context.get("last_result_url") or "none"
    last_element = active_context.get("last_element") or "none"

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

Current browser page URL:
{page_url}

Current browser page title:
{page_title}

Last selected result title:
{last_result_title}

Last selected result URL:
{last_result_url}

Last browser element:
{last_element}

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