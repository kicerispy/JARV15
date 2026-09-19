"""Lightweight, model-free routing for JARVIS requests.

The router intentionally avoids Ollama calls.  It classifies requests into a
small set of execution paths so the expensive planner is only used when the
request actually needs agentic work.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


RouteKind = Literal["fast", "contextual", "conversation", "agent"]


@dataclass(frozen=True)
class RouteDecision:
    """Result of deterministic request classification."""

    kind: RouteKind
    reason: str = ""
    confidence: float = 1.0


_FAST_PREFIXES = (
    "open ",
    "close ",
    "launch ",
    "start ",
    "quit ",
    "exit ",
    "turn the volume up",
    "turn the volume down",
    "volume up",
    "volume down",
    "mute",
    "unmute",
)

_FAST_EXACT = {
    "open chrome",
    "open browser",
    "close chrome",
    "turn volume up",
    "turn volume down",
    "what time is it",
    "what's the time",
    "current time",
    "what is today's date",
    "what's today's date",
    "today's date",
}

_CONTEXTUAL_EXACT = {
    "click the first result",
    "click the first link",
    "click first result",
    "click first link",
    "open the first result",
    "open the first link",
    "click the second result",
    "click the second link",
    "click second result",
    "click second link",
    "open the second result",
    "open the second link",
    "click the third result",
    "click the third link",
    "click third result",
    "click third link",
    "open the third result",
    "open the third link",
    "click the last result",
    "click the last link",
    "click last result",
    "click last link",
    "open the last result",
    "open the last link",
    "click it",
    "open it",
    "play it",
    "click that",
    "open that",
    "click this one",
    "click that one",
    "read this page",
    "read the page",
    "read page",
    "read the page text",
    "show this page",
    "what are the search results",
    "what're the search results",
    "tell me the search results",
    "show me the search results",
    "what did the search find",
    "what did you find",
}

_ACTION_WORDS = {
    "open",
    "close",
    "launch",
    "start",
    "go",
    "search",
    "look",
    "find",
    "click",
    "press",
    "type",
    "fill",
    "enter",
    "navigate",
    "download",
    "upload",
    "create",
    "make",
    "generate",
    "write",
    "edit",
    "change",
    "move",
    "delete",
    "send",
    "play",
    "run",
    "install",
    "check",
    "test",
    "build",
    "fix",
    "debug",
    "repair",
    "diagnose",
    "inspect",
    "investigate",
    "refactor",
    "modify",
    "patch",
    "resolve",
    "restore",
    "verify",
    "configure",
}

_CONVERSATION_STARTS = (
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "tell me a joke",
    "tell me a story",
    "say something funny",
    "what can you do",
    "who are you",
    "what are you",
    "help me understand",
    "explain ",
    "why ",
    "how ",
    "what ",
    "who ",
    "when ",
    "where ",
    "can you ",
    "could you ",
    "would you ",
    "is ",
    "are ",
    "do ",
    "does ",
    "did ",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _contains_action_word(text: str) -> bool:
    words = set(re.findall(r"[a-z']+", text))
    return bool(words & _ACTION_WORDS)


def _looks_multi_step(text: str) -> bool:
    """Detect explicit multi-action phrasing without involving an LLM."""
    separators = (" and ", " then ", " after that ", " next ", ";")
    if not any(separator in text for separator in separators):
        return False

    # Two or more action verbs makes escalation much more likely than normal chat.
    action_hits = sum(
        1 for word in _ACTION_WORDS if re.search(rf"\b{re.escape(word)}\b", text)
    )
    return action_hits >= 2


def route_command(command: str) -> RouteDecision:
    """Classify a user request without calling Ollama.

    Routing order is deliberate:
    1. deterministic one-shot commands
    2. active browser/context follow-ups
    3. explicit multi-step/action requests for Agent Core
    4. clearly conversational requests
    5. conservative agent fallback for action-oriented text
    """
    text = _normalize(command)

    if not text:
        return RouteDecision("conversation", "empty request", 0.50)

    if text in _CONTEXTUAL_EXACT or re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"(?:the\s+)?"
        r"(?:first|top|second|third|last|final)\s+"
        r"(?:result|link|video|one|item)$",
        text,
        re.IGNORECASE,
    ):
        return RouteDecision("contextual", "active-result follow-up", 0.99)

    if _looks_multi_step(text):
        return RouteDecision("agent", "explicit multi-step action", 0.98)

    if text in _FAST_EXACT or any(text.startswith(prefix) for prefix in _FAST_PREFIXES):
        return RouteDecision("fast", "deterministic command", 0.99)

    if (
        any(text.startswith(prefix) for prefix in _CONVERSATION_STARTS)
        and not _contains_action_word(text)
    ):
        return RouteDecision("conversation", "natural conversation/question", 0.95)

    if not _contains_action_word(text):
        return RouteDecision("conversation", "no actionable intent detected", 0.85)

    return RouteDecision("agent", "action-oriented request needs execution", 0.80)
