"""
JARVIS conversation summarization - reduces context size by summarizing old messages.
"""
from typing import Dict, List

from ollama import chat

from config import CHAT_MODEL
from logger import logger


SUMMARIZE_PROMPT = """Summarize the following conversation concisely, preserving key topics, decisions, and context.

Conversation:

{conversation}

Provide a single paragraph summary."""


def summarize_messages(messages: List[Dict[str, str]], max_tokens: int = 200) -> str:
    """
    Summarize a list of conversation messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        max_tokens: Approximate maximum tokens for the summary.

    Returns:
        A concise summary string.
    """
    if not messages:
        return ""

    # Build conversation text
    conversation = ""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            conversation += f"{role.upper()}: {content}\n"

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[{
                "role": "user",
                "content": SUMMARIZE_PROMPT.format(conversation=conversation)
            }],
            options={
                "temperature": 0.3,
                "num_predict": max_tokens,
            }
        )
        summary = response.get("message", {}).get("content", "").strip()
        return summary or conversation[:500]
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")
        # Fallback: return truncated conversation
        return conversation[:max_tokens * 4]


def summarize_and_truncate(
    messages: List[Dict[str, str]],
    max_messages: int = 12,
    summarize_after: int = 20
) -> List[Dict[str, str]]:
    """
    Truncate conversation history, summarizing old messages if needed.

    Args:
        messages: Full conversation history.
        max_messages: Maximum messages to keep directly.
        summarize_after: If total exceeds this, summarize the older portion.

    Returns:
        Truncated message list, possibly with a summary as the first message.
    """
    if len(messages) <= max_messages:
        return messages

    # Split into old and recent
    split_point = len(messages) - max_messages
    old_messages = messages[:split_point]
    recent_messages = messages[split_point:]

    if len(old_messages) >= summarize_after:
        # Summarize old messages
        summary = summarize_messages(old_messages)
        summary_msg = {
            "role": "system",
            "content": f"[Previous conversation summary: {summary}]"
        }
        return [summary_msg] + recent_messages
    else:
        # Just truncate
        return recent_messages