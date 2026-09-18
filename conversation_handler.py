"""
JARVIS conversation handler - manages normal conversation flow.
"""
import threading

from ollama import chat

from config import (
    CHAT_MODEL,
    CHAT_NUM_GPU,
    CHAT_NUM_PREDICT,
    CHAT_THINK,
    MAX_HISTORY_MESSAGES,
    MAX_MEMORIES_IN_PROMPT,
)
from conversation import get_recent
from logger import logger
from memory import get_memories
from state import ActiveContext


def get_memory_context() -> str:
    """Get a formatted string of recent memories for the system prompt."""
    memories = get_memories(limit=MAX_MEMORIES_IN_PROMPT)
    if not memories:
        return "No saved memories."

    memory_text = ""
    for item in memories:
        memory_text += f"- {item[0]}\n"
    return memory_text


def build_conversation_messages(
    user_input: str,
    active_context: ActiveContext,
    system_prompt: str
) -> list:
    """
    Build the message list for the LLM conversation.

    Args:
        user_input: The user's current message.
        active_context: Current active task context.
        system_prompt: Base system prompt.

    Returns:
        List of message dicts for the LLM.
    """
    memories = get_memory_context()

    active_site = active_context.site or "none"
    active_query = active_context.last_query or "none"
    active_tool = active_context.last_tool or "none"
    page_url = active_context.page_url or "none"
    page_title = active_context.page_title or "none"
    last_result_title = active_context.last_result_title or "none"
    last_element = active_context.last_element or "none"

    try:
        from task_memory import format_recent
        recent_tasks = format_recent(3)
    except Exception:
        recent_tasks = "Recent task memory unavailable."

    active_task_text = f"""
Current active task context:

Website: {active_site}

Search query: {active_query}

Last tool: {active_tool}

Current page URL: {page_url}

Current page title: {page_title}

Last selected result: {last_result_title}

Last browser element: {last_element}

Recent JARVIS tasks:
{recent_tasks}
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt + f"""

Relevant memories:

{memories}

{active_task_text}

Use these naturally when relevant.
"""
        }
    ]

    messages.extend(get_recent(limit=MAX_HISTORY_MESSAGES))
    messages.append({"role": "user", "content": user_input})

    return messages


def handle_normal_conversation(
    user_input: str,
    active_context: ActiveContext,
    system_prompt: str,
    speak_callback
) -> str:
    """
    Handle a normal conversation turn (no tools needed).

    Args:
        user_input: The user's message.
        active_context: Current active task context.
        system_prompt: Base system prompt.
        speak_callback: Function to speak text aloud.

    Returns:
        Status string: "done" or "interrupted".
    """
    messages = build_conversation_messages(user_input, active_context, system_prompt)

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=messages,
            think=CHAT_THINK,
            options={
                "num_gpu": CHAT_NUM_GPU,
                "num_predict": CHAT_NUM_PREDICT,
            },
        )
        jarvis_reply = response.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        jarvis_reply = "I encountered an error while processing that."

    from conversation import add_message
    add_message("assistant", jarvis_reply)

    logger.info(f"JARVIS: {jarvis_reply}")

    interrupted = speak_callback(jarvis_reply)
    if interrupted:
        return "interrupted"
    return "done"


def run_memory_analysis_background(text: str) -> None:
    """Run memory analysis in a background thread."""
    def _analyze() -> None:
        try:
            from memory_ai import analyze_memory
            analyze_memory(text)
        except Exception as e:
            logger.warning(f"Memory analysis skipped: {e}")

    thread = threading.Thread(target=_analyze, daemon=True)
    thread.start()
