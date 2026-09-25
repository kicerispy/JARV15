"""Deterministic intent and entity resolution for JARVIS Autonomy Kernel v2.

This module is deliberately model-free. It gives the planner/executor a cheap,
stable interpretation layer before an expensive LLM call is considered.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


_DOMAIN_PATTERNS = {
    "roblox": (
        "roblox",
        "roblox studio",
        "luau",
        "localscript",
        "modulescript",
        "remoteevent",
        "remotefunction",
        "datamodel",
        "playtest",
        "studio output",
        "gameplay system",
    ),
    "browser": (
        "browser",
        "chrome",
        "google",
        "bing",
        "youtube",
        "website",
        "web page",
        "webpage",
        "amazon",
        "reddit",
    ),
    "unreal": (
        "unreal",
        "unreal engine",
        "unreal editor",
        "unreal mcp",
        "ue5",
        "ue4",
    ),
    "code": (
        "code",
        "python",
        "repository",
        "repo",
        "git",
        "script",
        "source file",
        "function",
        "class",
        "module",
        "bug",
        "error",
        "stack trace",
        "compile",
        "test",
        "pytest",
    ),
    "system": (
        "computer",
        "windows",
        "desktop",
        "application",
        "program",
        "process",
        "folder",
        "file",
        "terminal",
    ),
}


_QUESTION_STARTS = (
    "what ",
    "what's ",
    "whats ",
    "how ",
    "how's ",
    "hows ",
    "why ",
    "where ",
    "which ",
    "who ",
    "when ",
    "is ",
    "are ",
    "can ",
    "could ",
    "would ",
    "tell me ",
    "explain ",
    "describe ",
    "show me ",
    "list ",
    "find ",
    "inspect ",
    "check ",
    "analyze ",
    "analyse ",
    "review ",
    "look at ",
    "look for ",
    "figure out ",
    "find out ",
    "take a look ",
    "have a look ",
)


_ACTION_STARTS = (
    "open ",
    "launch ",
    "start ",
    "close ",
    "click ",
    "press ",
    "type ",
    "search ",
    "navigate ",
    "go to ",
    "scroll ",
    "play ",
    "pause ",
    "stop ",
    "enable ",
    "disable ",
    "move ",
)


def _normalize(text: str) -> str:
    return " ".join(
        str(text or "").strip().lower().rstrip(".,!?;:").split()
    )


def _domain_for(text: str, active_context: Optional[Dict[str, Any]]) -> str:
    context_site = str(
        (active_context or {}).get("site", "") or ""
    ).strip().lower()

    if context_site in {"roblox", "browser", "unreal", "code", "system"}:
        if context_site == "roblox" and any(
            token in text
            for token in ("browser", "chrome", "google", "bing", "youtube")
        ):
            return "browser"
        return context_site

    scores = {
        domain: sum(1 for term in terms if term in text)
        for domain, terms in _DOMAIN_PATTERNS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def _intent_for(text: str, mode: str, domain: str) -> str:
    if any(term in text for term in ("fix ", "repair ", "debug ", "refactor ")):
        return "repair"

    if any(term in text for term in ("improve ", "upgrade ", "enhance ")):
        if "yourself" in text or "your own code" in text:
            return "self_improvement"
        return "change"

    if any(
        term in text
        for term in (
            "inspect ",
            "analyze ",
            "analyse ",
            "diagnose ",
            "investigate ",
            "review ",
            "look at ",
            "check ",
            "find ",
            "figure out ",
            "find out ",
        )
    ):
        return "inspect"

    if any(
        term in text
        for term in ("search ", "look for ", "find ")
    ) and domain in {"browser", "unreal"}:
        return "search"

    if any(
        term in text
        for term in ("click ", "press ", "open ", "launch ", "navigate ")
    ):
        return "execute"

    if mode == "answer":
        return "answer"

    if mode == "change":
        return "change"

    return "execute"


def resolve_intent(
    request: str,
    active_context: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve a cheap, deterministic intent/domain/entity packet."""
    text = _normalize(request)

    if not text:
        return {
            "mode": "conversation",
            "intent": "conversation",
            "domain": "general",
            "confidence": 1.0,
            "entities": {},
            "signals": [],
        }

    domain = _domain_for(text, active_context)

    plan_mode = str(
        (plan or {}).get("response_mode", "") or ""
    ).strip().lower()

    explicit_answer = any(
        text.startswith(prefix)
        for prefix in (
            "what ",
            "what's ",
            "whats ",
            "how ",
            "how's ",
            "hows ",
            "why ",
            "where ",
            "which ",
            "who ",
            "when ",
            "is ",
            "are ",
            "can ",
            "could ",
            "would ",
            "tell me ",
            "explain ",
            "describe ",
            "show me ",
            "list ",
        )
    )

    evidence_verbs = (
        "find ",
        "inspect ",
        "check ",
        "analyze ",
        "analyse ",
        "review ",
        "look at ",
        "look for ",
        "figure out ",
        "find out ",
        "take a look ",
        "have a look ",
    )

    # Evidence-seeking requests are answer-bearing unless the user explicitly
    # asks for a pure navigation/action outcome.
    evidence_request = any(text.startswith(prefix) for prefix in evidence_verbs)
    action_request = any(text.startswith(prefix) for prefix in _ACTION_STARTS)

    # Unreal capability searches are inherently information-bearing: the
    # returned capabilities are the result the user asked to see.
    unreal_search_request = (
        domain == "unreal"
        and any(text.startswith(prefix) for prefix in ("search ", "look for "))
    )

    # A search can be both an action and an information request. Phrases such
    # as "tell me what you find" explicitly require JARVIS to return findings.
    report_request = any(
        marker in text
        for marker in (
            "tell me what you find",
            "tell me what you found",
            "what did you find",
            "what are the results",
            "show me the results",
            "show me what you found",
            "summarize",
            "explain what",
            "report the results",
        )
    )

    answer_mode = (
        plan_mode == "answer"
        or explicit_answer
        or evidence_request
        or report_request
        or unreal_search_request
        or roblox_mcp_lifecycle_request
    )

    roblox_mcp_lifecycle_request = (
        domain == "roblox"
        and any(
            phrase in text
            for phrase in (
                "roblox mcp status",
                "roblox mcp health",
                "check roblox mcp",
                "check roblox status",
                "is roblox mcp connected",
                "is roblox connected",
                "setup roblox mcp",
                "set up roblox mcp",
                "install roblox mcp",
                "start roblox mcp",
                "start the roblox mcp",
                "repair roblox mcp",
            )
        )
    )

    # Common browser actions are not informational by themselves.
    if domain == "browser" and action_request and not (
        explicit_answer
        or report_request
        or any(
            marker in text
            for marker in (
                "tell me",
                "what did you find",
                "what are the results",
                "which result",
                "show me the results",
                "read the page",
                "summarize",
                "explain",
            )
        )
    ):
        answer_mode = False

    if plan_mode in {"action", "execute"} and not explicit_answer and not report_request:
        answer_mode = False

    mode = "answer" if answer_mode else "action"

    entities: Dict[str, Any] = {}

    quoted = re.findall(
        r'''["']([^"']+)["']''',
        request,
    )
    if quoted:
        entities["quoted"] = quoted[:5]

    if domain == "browser":
        for site in ("google", "bing", "youtube", "amazon", "reddit"):
            if site in text:
                entities["site"] = site
                break

    if domain == "roblox":
        if "scripts" in text or "script" in text:
            entities["artifact"] = "script"
        if "gameplay" in text:
            entities["system"] = "gameplay"

    signals = []
    if explicit_answer:
        signals.append("question")
    if evidence_request:
        signals.append("evidence_request")
    if action_request:
        signals.append("action_request")
    if domain != "general":
        signals.append(domain)

    intent = _intent_for(text, mode, domain)

    confidence = 0.95 if len(signals) >= 2 else 0.82

    return {
        "mode": mode,
        "intent": intent,
        "domain": domain,
        "confidence": confidence,
        "entities": entities,
        "signals": signals,
    }


def needs_evidence_answer(
    request: str,
    plan: Optional[Dict[str, Any]] = None,
    active_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True when JARVIS should explain findings instead of only confirming action."""
    result = resolve_intent(
        request,
        active_context=active_context,
        plan=plan,
    )
    return result.get("mode") == "answer"
