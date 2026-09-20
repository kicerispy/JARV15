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
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    normalized = re.sub(r"[,.!?]+$", "", normalized).strip()
    return normalized


def _contains_action_word(text: str) -> bool:
    words = set(re.findall(r"[a-z']+", text))
    return bool(words & _ACTION_WORDS)


def _looks_direct_browser_navigation(text: str) -> bool:
    """Recognize direct URL navigation without involving the planner."""
    return bool(
        re.match(
            r"^(?:go to|navigate to|open|visit)\s+"
            r"(?:https?://|www\.)[^\s]+$",
            text,
            re.IGNORECASE,
        )
        or re.match(
            r"^(?:go to|navigate to|open|visit)\s+"
            r"[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?$",
            text,
            re.IGNORECASE,
        )
    )


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

    research_hints = (
        "reviews",
        "review",
        "ratings",
        "rated",
        "alternative",
        "alternatives",
        "cheaper",
        "best value",
        "best price",
        "worth buying",
        "shopping",
        "compare prices",
        "compare products",
        "comparison",
        "price",
        "buy",
        "purchase",
    )

    research_question = re.search(
        r"\b(?:what|which|who)\b.{0,80}\b"
        r"(?:best|top[- ]rated|cheapest|buy|purchase|worth)\b",
        text,
        re.IGNORECASE,
    )

    if (
        not any(signal in text for signal in {
            "code",
            "coding",
            "python",
            "javascript",
            "typescript",
            "stack trace",
            "traceback",
            "compile",
            "pytest",
            "repository",
            "git",
        })
        and (
            any(signal in text for signal in research_hints)
            or research_question is not None
        )
        and any(
            signal in text
            for signal in (
                "product",
                "products",
                "model",
                "models",
                "device",
                "devices",
                "phone",
                "phones",
                "laptop",
                "laptops",
                "computer",
                "computers",
                "monitor",
                "monitors",
                "headphone",
                "headphones",
                "earbuds",
                "keyboard",
                "mouse",
                "camera",
                "tv",
                "television",
                "router",
                "ssd",
                "gpu",
                "cpu",
                "tablet",
                "chair",
                "shoes",
                "appliance",
                "buy",
                "purchase",
                "price",
                "reviews",
                "review",
                "ratings",
                "alternative",
                "alternatives",
            )
        )
    ):
        return RouteDecision(
            "agent",
            "product research request",
            0.97,
        )

    if _looks_direct_browser_navigation(text):
        return RouteDecision("fast", "direct browser URL", 0.99)

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

    # Tool-backed informational queries must reach the agent even when
    # they are phrased as ordinary questions. The planner can then select
    # the appropriate structured API tool instead of answering from model
    # memory or routing through generic browser search.
    tool_backed_query_signals = (
        "public holiday",
        "public holidays",
        "holiday",
        "holidays",
        "define ",
        "definition of ",
        "dictionary",
        "book ",
        "books ",
        "author ",
        "authors ",
        "research paper",
        "research papers",
        "research article",
        "research articles",
        "arxiv",
        "scholarly",
        "vin ",
        "vehicle identification number",
        "vehicle vin",
        "earthquake",
        "earthquakes",
        "public api",
        "public apis",
        "free api",
        "free apis",
        "currency",
        "exchange rate",
        "exchange rates",
        "convert usd",
        "convert eur",
        "conversion rate",
        "air quality",
        "air pollution",
        "aqi",
        "pm2.5",
        "pm10",
        "weather alert",
        "weather alerts",
        "weather warning",
        "weather warnings",
        "elevation",
        "altitude",
        "geocode",
        "coordinates",
        "country information",
        "country info",
        "cryptocurrency",
        "crypto price",
        "bitcoin",
        "ethereum",
        "trivia",
        "recipe",
        "recipes",
        "meal",
        "meals",
        "tv show",
        "television",
        "anime",
        "episode",
        "episodes",
        "anime episode",
        "anime episodes",
        "studio ghibli",
        "song",
        "songs",
        "musicbrainz",
        "music",
        "research database",
        "openalex",
        "pubchem",
        "chemical",
        "molecular formula",
        "art institute",
        "artworks",
        "natural events",
        "wildfire",
        "wildfires",
        "nasa eonet",
        "sunrise",
        "sunset",
        "topographic elevation",
        "public ip",
        "my ip address",
        "reverse geocode",
        "openstreetmap",
        "news",
        "pokemon",
        "pokémon",
        "food product",
        "barcode",
        "cocktail",
        "openverse",
        "iss",
        "international space station",
        "headlines",
        "cat fact",
        "dog image",
        "gods eye",
        "god's eye",
        "aircraft contacts",
        "live aircraft",
        "vessel contacts",
        "live vessels",
        "ships",
        "ships at sea",
        "satellite contacts",
        "satellites",
        "spacecraft",
        "screen memory",
        "screenpipe",
    )

    currency_conversion_query = (
        text.startswith("convert ")
        and " to " in text
    )

    if currency_conversion_query:
        return RouteDecision(
            "agent",
            "currency-conversion query",
            0.94,
        )

    if any(signal in text for signal in tool_backed_query_signals):
        return RouteDecision("agent", "tool-backed informational query", 0.94)

    knowledge_identity_exclusions = (
        "what is your name",
        "who are you",
        "what can you do",
        "what is my name",
        "who am i",
    )

    knowledge_query_starts = (
        "what is ",
        "what are ",
        "who is ",
        "who was ",
        "tell me about ",
        "explain ",
        "how does ",
        "how do ",
        "what does ",
    )

    if (