"""n8n workflow architect for JARVIS.

This module is intentionally read-only. It uses the live n8n MCP tool catalog
to design and audit workflows from verified node schemas and workflow guidance.
Mutation/execution stays behind the existing n8n MCP tools until the architect
has a stable validation contract.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MAX_TECHNIQUES = 3
MAX_QUERIES = 18
MAX_NODE_CANDIDATES = 8
MAX_DISCOVERED_NODE_CANDIDATES = 32
MAX_NODE_TYPE_REQUESTS = 8
MAX_BEST_PRACTICE_CHARS = 12000
MAX_DESCRIPTION_CHARS = 3000


_NODE_ID_RE = re.compile(
    r"(?:@n8n/n8n-nodes-[A-Za-z0-9_-]+|n8n-nodes-[A-Za-z0-9_-]+)\.[A-Za-z0-9_.-]+"
)


_TECHNIQUE_KEYWORDS: Sequence[Tuple[str, Sequence[str]]] = (
    ("scheduling", ("schedule", "scheduled", "every day", "every hour", "cron", "recurring")),
    ("chatbot", ("chatbot", "chat bot", "chat assistant", "conversational")),
    ("form_input", ("form", "form submission", "form input")),
    ("scraping_and_research", ("scrape", "scraping", "research", "crawl", "website data")),
    ("monitoring", ("monitor", "monitoring", "watch", "alert me when", "health check")),
    ("enrichment", ("enrich", "enrichment", "lookup", "augment")),
    ("triage", ("triage", "classify", "route", "priority", "ticket")),
    ("content_generation", ("generate content", "write", "draft", "summarize", "summary")),
    ("document_processing", ("document", "pdf", "file processing", "extract document")),
    ("data_extraction", ("extract data", "parse", "extract fields")),
    ("data_analysis", ("analyze data", "analysis", "analytics", "report")),
    ("data_transformation", ("transform", "normalize", "map fields", "convert data")),
    ("data_persistence", ("database", "store", "save", "persist", "insert", "update record")),
    ("notification", (
        "notify",
        "notification",
        "alert",
        "alert me",
        "send me an alert",
        "email",
        "send a message",
        "slack",
        "discord",
    )),
    ("knowledge_base", ("knowledge base", "rag", "vector", "knowledge")),
    ("human_in_the_loop", ("approval", "approve", "human review", "human in the loop")),
    ("web_app", ("web app", "webhook", "api endpoint", "http endpoint")),
)


_STOPWORDS = {
    "a", "about", "after", "all", "an", "and", "are", "as", "at", "be",
    "build", "by", "can", "create", "do", "for", "from", "get", "give",
    "how", "i", "in", "into", "is", "it", "make", "me", "my", "of", "on",
    "or", "please", "run", "send", "that", "the", "this", "to", "use",
    "using", "want", "with", "workflow", "workflows",
}


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _unique_strings(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        item = _clean_text(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _infer_techniques(request: str) -> List[str]:
    text = _clean_text(request).lower()
    matches: List[Tuple[int, str]] = []

    for technique, keywords in _TECHNIQUE_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            matches.append((score, technique))

    matches.sort(key=lambda item: (-item[0], item[1]))
    if matches:
        return [technique for _, technique in matches[:MAX_TECHNIQUES]]

    return ["data_transformation"]


def _keyword_terms(request: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", _clean_text(request))
    return _unique_strings(
        token
        for token in tokens
        if token.lower() not in _STOPWORDS
    )[:12]


def _search_queries(request: str, techniques: Sequence[str]) -> List[str]:
    text = _clean_text(request).lower()
    terms = _keyword_terms(request)
    queries = [_clean_text(request)]

    if terms:
        queries.append(" ".join(terms[:6]))

    queries.append("trigger")

    if "github" in text and "issue" in text:
        queries.extend([
            "GitHub issues",
            "GitHub issue trigger",
            "GitHub issue",
        ])

    if any(marker in text for marker in ("alert", "notify", "notification", "message me")):
        queries.extend([
            "notification",
            "email slack discord",
            "Slack notification",
            "Email send",
        ])

    if any(marker in text for marker in ("summarize", "summary", "summarizes", "generate", "write")):
        queries.extend([
            "text generation",
            "AI text generation",
            "OpenAI text generation",
            "LLM text generation",
        ])

    if any(marker in text for marker in ("bug", "condition", "when", "if")):
        queries.append("conditional filter")

    for technique in techniques:
        queries.append(technique.replace("_", " "))

    for term in terms[:4]:
        queries.append(term)

    return _unique_strings(queries)[:MAX_QUERIES]


def _result_data(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        return {}

    for envelope_key in ("data", "result", "output"):
        nested = data.get(envelope_key)
        if isinstance(nested, dict):
            data = nested

    return data


def _parse_json_text(value: str) -> Any:
    text = str(value or "").strip()
    if not text:
        return None

    candidates = [text]
    if text.startswith(chr(96) * 3) and text.endswith(chr(96) * 3):
        lines = text.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            continue

    return None


_DISCRIMINATOR_PATTERNS = {
    "resource": re.compile(
        r"resource\s*(?:[:=]|=>|\()\s*[\"]?([A-Za-z0-9_.-]+)",
        re.IGNORECASE,
    ),
    "operation": re.compile(
        r"operation\s*(?:[:=]|=>|\()\s*[\"]?([A-Za-z0-9_.-]+)",
        re.IGNORECASE,
    ),
    "mode": re.compile(
        r"mode\s*(?:[:=]|=>|\()\s*[\"]?([A-Za-z0-9_.-]+)",
        re.IGNORECASE,
    ),
    "version": re.compile(
        r"version\s*(?:[:=]|=>|\()\s*[\"]?([0-9]+(?:\.[0-9]+)*)",
        re.IGNORECASE,
    ),
}


def _parse_node_discriminators(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, pattern in _DISCRIMINATOR_PATTERNS.items():
        match = pattern.search(str(text or ""))
        if not match:
            continue
        value = match.group(1).strip()
        if key == "version":
            try:
                result[key] = float(value)
            except ValueError:
                result[key] = value
        else:
            result[key] = value
    return result


def _node_items_from_text(value: str) -> List[Dict[str, Any]]:
    parsed = _parse_json_text(value)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        for key in ("nodes", "results", "items"):
            nested = parsed.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]

    text = str(value or "")
    matches = list(_NODE_ID_RE.finditer(text))
    if not matches:
        return []

    items: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        node_id = match.group(0)
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)

        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)

        # Prefer the text on the same line plus a small following window.
        window_end = min(
            next_start,
            max(line_end, match.end() + 500),
        )
        window = text[match.end():window_end]

        # If the result formatter puts discriminators before the node id,
        # include the current line prefix as well.
        if match.start() > line_start:
            window = text[line_start:window_end]

        item: Dict[str, Any] = {
            "nodeId": node_id,
            "type": node_id,
            "name": node_id.rsplit(".", 1)[-1],
            "_search_text": window,
        }
        item.update(_parse_node_discriminators(window))
        items.append(item)

    return items


def _looks_like_node_schema(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False

    markers = (
        "interface ",
        "type ",
        "export interface",
        "export type",
        "parameters:",
        "properties:",
        "credentials:",
        "displayname:",
        "description:",
    )
    return any(marker in normalized for marker in markers)


def _definition_items_from_text(value: str) -> List[Dict[str, Any]]:
    parsed = _parse_json_text(value)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        for key in ("nodeTypes", "definitions", "results", "items"):
            nested = parsed.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]

        if parsed:
            return [parsed]

    text = str(value or "").strip()
    if not text or not _looks_like_node_schema(text):
        return []

    node_ids = _unique_strings(_NODE_ID_RE.findall(text))
    return [
        {
            "nodeId": node_ids[0] if node_ids else None,
            "type": node_ids[0] if node_ids else None,
            "name": (
                node_ids[0].rsplit(".", 1)[-1]
                if node_ids
                else "n8n node definition"
            ),
            "content": _clip(text, MAX_BEST_PRACTICE_CHARS),
        }
    ]


def _result_list(result: Dict[str, Any], keys: Sequence[str]) -> List[Dict[str, Any]]:
    data = _result_data(result)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    containers: List[Dict[str, Any]] = [data]
    while containers:
        container = containers.pop(0)
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, str):
                items = _node_items_from_text(value)
                if items:
                    return items
            if isinstance(value, dict):
                containers.append(value)

        for key in ("data", "result", "output", "content"):
            nested = container.get(key)
            if isinstance(nested, dict):
                containers.append(nested)
            elif isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            elif isinstance(nested, str):
                items = _node_items_from_text(nested)
                if items:
                    return items

    return []


def _structured_result_list(
    result: Dict[str, Any],
    keys: Sequence[str],
) -> List[Dict[str, Any]]:
    """Extract structured list payloads without interpreting arbitrary strings."""
    data = _result_data(result)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    containers: List[Dict[str, Any]] = [data]
    while containers:
        container = containers.pop(0)

        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                containers.append(value)

        for key in ("data", "result", "output", "content"):
            nested = container.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            if isinstance(nested, dict):
                containers.append(nested)

    return []


def _result_text(result: Dict[str, Any], keys: Sequence[str]) -> str:
    data = _result_data(result)

    def walk(value: Any) -> str:
        if isinstance(value, dict):
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            for key in ("data", "result", "output", "content"):
                text = walk(value.get(key))
                if text:
                    return text
        elif isinstance(value, list):
            for item in value:
                text = walk(item)
                if text:
                    return text
        return ""

    return walk(data)


def _call(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from n8n_mcp import call_tool

    result = call_tool(
        tool_name,
        arguments if isinstance(arguments, dict) else {},
    )
    return result if isinstance(result, dict) else {
        "success": False,
        "verified": False,
        "message": "n8n MCP returned an invalid result.",
    }


def _is_start_trigger_type(node_type: Any) -> bool:
    value = str(node_type or "").lower()
    return any(
        marker in value
        for marker in (
            "manualtrigger",
            "scheduletrigger",
            "webhook",
            "chattrigger",
            "formtrigger",
            "trigger",
        )
    )


def _node_identity(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    node_id = (
        item.get("nodeId")
        or item.get("nodeType")
        or item.get("id")
        or item.get("type")
        or item.get("name")
    )
    if not node_id:
        return None

    ref: Dict[str, Any] = {"nodeId": str(node_id)}
    for key in ("version", "typeVersion", "resource", "operation", "mode"):
        if item.get(key) is not None:
            ref[key] = item[key]
    return ref


def _node_relevance(request: str, item: Dict[str, Any]) -> Tuple[int, int, int, str]:
    request_terms = {
        token.lower()
        for token in _keyword_terms(request)
    }
    haystack = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("nodeId") or ""),
            str(item.get("type") or ""),
        ]
    ).lower()

    exact_hits = sum(
        1
        for term in request_terms
        if term and term in haystack
    )

    capability_hits = 0
    for capability, _markers in _required_capabilities(request):
        if capability == "trigger":
            continue
        if _capability_matches_node(capability, item):
            capability_hits += 1

    trigger_bonus = 1 if _is_start_trigger_type(item.get("type")) else 0

    return (
        capability_hits,
        exact_hits,
        trigger_bonus,
        str(item.get("name") or "").lower(),
    )


def _augment_nodes_from_guidance(
    request: str,
    candidates: Sequence[Dict[str, Any]],
    guidance: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for item in candidates:
        ref = _node_identity(item)
        if ref:
            key = str(ref.get("nodeId"))
            merged[key] = dict(item)

    guidance_text = "\n".join(
        str(item.get("guidance") or "")
        for item in guidance
        if isinstance(item, dict)
    )
    for node_id in _unique_strings(_NODE_ID_RE.findall(guidance_text)):
        merged.setdefault(
            node_id,
            {
                "nodeId": node_id,
                "type": node_id,
                "name": node_id.rsplit(".", 1)[-1],
                "_source": "best_practice_guidance",
            },
        )

    ranked = sorted(
        merged.values(),
        key=lambda item: _node_relevance(request, item),
        reverse=True,
    )
    return ranked[:MAX_NODE_CANDIDATES]


def _discover_nodes(
    request: str,
    techniques: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    candidates: List[Dict[str, Any]] = []
    queries = _search_queries(request, techniques)

    for query in queries:
        result = _call(
            "search_nodes",
            {
                "queries": [query],
                "usage": "workflow",
            },
        )
        if result.get("success") is not True:
            continue

        values = _result_list(result, ("nodes", "results", "items"))
        candidates.extend(values)

    required_capabilities = [
        capability
        for capability, _markers in _required_capabilities(request)
    ]

    # The normal search/ranking pass can legitimately fill all eight slots with
    # triggers or lookalike nodes. Backfill any required capability that is still
    # absent with a targeted live n8n search before ranking the final set.
    for capability in required_capabilities:
        if any(
            _capability_matches_node(capability, item)
            for item in candidates
        ):
            continue

        for query in _capability_search_queries(request, capability):
            result = _call(
                "search_nodes",
                {
                    "queries": [query],
                    "usage": "workflow",
                },
            )
            if result.get("success") is not True:
                continue

            values = _result_list(result, ("nodes", "results", "items"))
            candidates.extend(values)

            if any(
                _capability_matches_node(capability, item)
                for item in values
            ):
                break

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        ref = _node_identity(item)
        if not ref:
            continue
        key = json.dumps(ref, sort_keys=True, default=str)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
        elif len(str(item.get("_search_text") or "")) > len(
            str(existing.get("_search_text") or "")
        ):
            deduped[key] = item

        if len(deduped) >= MAX_DISCOVERED_NODE_CANDIDATES:
            continue

    ranked = sorted(
        deduped.values(),
        key=lambda item: _node_relevance(request, item),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    selected_keys = set()

    # Reserve capacity for the best live node satisfying each explicitly
    # requested capability. This prevents a generic trigger or classifier from
    # crowding out the actual LLM/condition/notification node we need.
    for capability in required_capabilities:
        matches = [
            item
            for item in ranked
            if _capability_matches_node(capability, item)
        ]
        if not matches:
            continue

        best = matches[0]
        ref = _node_identity(best)
        key = json.dumps(ref, sort_keys=True, default=str) if ref else ""
        if key and key not in selected_keys:
            selected.append(best)
            selected_keys.add(key)

    for item in ranked:
        ref = _node_identity(item)
        key = json.dumps(ref, sort_keys=True, default=str) if ref else ""
        if not key or key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        if len(selected) >= MAX_NODE_CANDIDATES:
            break

    return selected[:MAX_NODE_CANDIDATES], queries


def _deprecated_node_ids(
    definition_text: str,
    candidates: Sequence[Dict[str, Any]],
) -> List[str]:
    text = str(definition_text or "")
    deprecated: List[str] = []

    for item in candidates:
        node_id = str(
            item.get("nodeId")
            or item.get("id")
            or item.get("type")
            or ""
        ).strip()
        if not node_id:
            continue

        escaped = re.escape(node_id)
        matches = list(re.finditer(
            rf"type\s*:\s*['\"]{escaped}['\"]",
            text,
            re.IGNORECASE,
        ))
        for match in matches:
            window = text[max(0, match.start() - 1400):match.end() + 200]
            if "@deprecated" in window.lower():
                deprecated.append(node_id)
                break

    return _unique_strings(deprecated)


def _get_node_types(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    refs: List[Dict[str, Any]] = []
    for item in candidates:
        ref = _node_identity(item)
        if ref:
            refs.append(ref)
        if len(refs) >= MAX_NODE_TYPE_REQUESTS:
            break

    if not refs:
        return {
            "success": False,
            "message": "No node definitions were returned by search_nodes.",
            "definitions": [],
            "schema_errors": [],
            "invalid_node_ids": [],
            "deprecated_node_ids": [],
        }

    definitions: List[Dict[str, Any]] = []
    definition_texts: List[str] = []
    schema_errors: List[str] = []
    invalid_node_ids: List[str] = []
    deprecated_node_ids: List[str] = []
    successes = 0
    messages: List[str] = []

    for ref in refs:
        result = _call(
            "get_node_types",
            {"nodeIds": [ref]},
        )
        if result.get("success") is not True:
            messages.append(str(result.get("message") or "get_node_types failed"))
            continue

        successes += 1
        structured = _structured_result_list(
            result,
            ("nodeTypes", "definitions", "results"),
        )
        definition_text = _result_text(
            result,
            ("definitions", "documentation", "content"),
        )

        if structured:
            definitions.extend(structured)

        if definition_text:
            definition_texts.append(definition_text)
            if not structured:
                parsed_definitions = _definition_items_from_text(definition_text)
                if parsed_definitions:
                    definitions.extend(parsed_definitions)

            error_pattern = re.compile(
                r"Error:\s*Node ['\"]([^'\"]+)['\"] (?P<message>[^\n]+)",
                re.IGNORECASE,
            )
            for match in error_pattern.finditer(definition_text):
                node_id = _clean_text(match.group(1))
                message = _clean_text(match.group("message"))
                if node_id:
                    invalid_node_ids.append(node_id)
                if message:
                    schema_errors.append(f"{node_id}: {message}")

            deprecated_node_ids.extend(
                _deprecated_node_ids(
                    definition_text,
                    [ref],
                )
            )

    invalid_node_ids = _unique_strings(invalid_node_ids)
    schema_errors = _unique_strings(schema_errors)
    deprecated_node_ids = _unique_strings(deprecated_node_ids)

    return {
        "success": successes > 0,
        "message": (
            f"Retrieved schemas for {successes}/{len(refs)} requested nodes."
            + (f" Failures: {' | '.join(messages[:3])}" if messages else "")
        ),
        "definitions": definitions,
        "definition_text": _clip(
            "\n\n".join(definition_texts),
            MAX_BEST_PRACTICE_CHARS,
        ),
        "schema_errors": schema_errors,
        "invalid_node_ids": invalid_node_ids,
        "deprecated_node_ids": deprecated_node_ids,
    }


def _best_practice_guidance(techniques: Sequence[str]) -> List[Dict[str, Any]]:
    guidance: List[Dict[str, Any]] = []

    for technique in techniques[:MAX_TECHNIQUES]:
        result = _call(
            "get_workflow_best_practices",
            {"technique": technique},
        )
        if result.get("success") is not True:
            continue

        data = _result_data(result)
        reference = (
            data.get("documentation")
            or data.get("guidance")
            or data.get("reference")
            or data.get("content")
            or data
        )

        guidance.append(
            {
                "technique": technique,
                "guidance": _clip(reference, MAX_BEST_PRACTICE_CHARS),
            }
        )

    return guidance


def _requirements(request: str, techniques: Sequence[str]) -> Dict[str, Any]:
    text = _clean_text(request).lower()

    external_effects = any(
        marker in text
        for marker in (
            "send email",
            "send a message",
            "post to",
            "create issue",
            "update github",
            "write to",
            "save to",
            "delete",
            "publish",
            "notify",
            "alert",
            "alert me",
            "message me",
        )
    )

    return {
        "trigger": {
            "required": True,
            "reason": "Every deployable workflow needs an explicit trigger.",
        },
        "validation": {
            "required": True,
            "reason": "Inputs should be validated before downstream processing.",
        },
        "error_handling": {
            "required": external_effects or "monitor" in text or "alert" in text,
            "reason": "External effects and monitoring workflows need an explicit failure path.",
        },
        "retry_policy": {
            "required": external_effects or "http" in text or "api" in text,
            "reason": "Remote calls should have bounded retry behavior where appropriate.",
        },
        "empty_data_behavior": {
            "required": True,
            "reason": "The workflow should define what happens when an upstream node emits zero items.",
        },
        "observability": {
            "required": external_effects or "monitor" in text,
            "reason": "Important automations should expose enough execution evidence to diagnose failures.",
        },
        "side_effect_review": {
            "required": external_effects,
            "reason": "Side-effecting nodes should be explicitly identified before publish.",
        },
        "techniques": list(techniques),
    }


def _required_capabilities(request: str) -> List[Tuple[str, Tuple[str, ...]]]:
    text = _clean_text(request).lower()
    capabilities: List[Tuple[str, Tuple[str, ...]]] = [
        ("trigger", ("trigger",)),
    ]

    if "github" in text and "issue" in text:
        capabilities.append(("github_source", ("github",)))
    if any(marker in text for marker in ("summarize", "summarizes", "summary", "summarization")):
        capabilities.append((
            "summarization",
            (
                "openai",
                "gemini",
                "claude",
                "grok",
                "llm",
                "language",
                "textgenerator",
                "text generator",
                "basicllm",
                "basic llm",
            ),
        ))
    if any(marker in text for marker in ("bug", "when", "if", "condition", "identify")):
        capabilities.append(("condition", ("if", "switch", "filter", "router")))
    if any(marker in text for marker in ("alert", "notify", "notification", "message me")):
        capabilities.append((
            "notification",
            (
                "slack",
                "email",
                "gmail",
                "discord",
                "telegram",
                "teams",
                "notification",
            ),
        ))

    return capabilities



def _node_search_text(item: Dict[str, Any]) -> str:
    """Return stable node identity/configuration text, excluding noisy search excerpts."""
    values = (
        item.get("name"),
        item.get("nodeId"),
        item.get("type"),
        item.get("resource"),
        item.get("operation"),
        item.get("mode"),
        item.get("description"),
    )
    return " ".join(str(value or "") for value in values).strip().lower()


def _node_tokens(item: Dict[str, Any]) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _node_search_text(item)))


def _capability_matches_node(capability: str, item: Dict[str, Any]) -> bool:
    """Determine whether a discovered node actually satisfies a required capability."""
    capability = str(capability or "").strip().lower()
    tokens = _node_tokens(item)
    identity = _node_search_text(item)
    node_id = str(item.get("nodeId") or item.get("type") or "").lower()
    resource = str(item.get("resource") or "").lower()
    operation = str(item.get("operation") or "").lower()

    if capability == "trigger":
        return _is_start_trigger_type(node_id) or "trigger" in tokens

    if capability == "github_source":
        if "githubtrigger" in tokens:
            return True
        return (
            "github" in tokens
            and (
                resource in {"issue", "issues"}
                or operation in {
                    "getissue",
                    "getissues",
                    "getmany",
                    "getall",
                    "search",
                    "get",
                    "list",
                }
            )
        )

    if capability == "summarization":
        return any(
            marker in identity
            for marker in (
                "openai",
                "gemini",
                "claude",
                "anthropic",
                "grok",
                "textgenerator",
                "text generator",
                "basicllm",
                "basic llm",
            )
        ) or ("llm" in identity and "classifier" not in identity)

    if capability == "condition":
        return bool({"if", "switch", "filter", "router"} & tokens)

    if capability == "notification":
        action_markers = (
            "slack",
            "email",
            "gmail",
            "discord",
            "telegram",
            "teams",
            "twilio",
            "notification",
        )
        if not any(marker in identity for marker in action_markers):
            return False
        # Trigger nodes monitor events; they should not satisfy a notification action.
        if "trigger" in tokens and not (
            {"send", "message", "notification"} & tokens
            or " send" in identity
        ):
            return False
        return True

    return False


def _capability_search_queries(
    request: str,
    capability: str,
) -> List[str]:
    """Return bounded, capability-specific searches used to fill discovery gaps."""
    capability = str(capability or "").strip().lower()
    text = _clean_text(request).lower()

    if capability == "github_source":
        return _unique_strings(
            [
                "GitHub issue trigger",
                "GitHub issues node",
                "GitHub issue",
            ]
        )

    if capability == "summarization":
        return _unique_strings(
            [
                "OpenAI text generation",
                "LLM text generation",
                "AI text generation",
            ]
        )

    if capability == "condition":
        return _unique_strings(
            [
                "IF node",
                "Switch node",
                "conditional filter",
            ]
        )

    if capability == "notification":
        return _unique_strings(
            [
                "Slack send",
                "Send Email",
                "Telegram message",
            ]
        )

    if capability == "trigger":
        if "github" in text and "issue" in text:
            return ["GitHub issue trigger", "trigger"]
        return ["trigger"]

    return []


def _quality_gate(
    request: str,
    requirements: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
    definitions: Sequence[Dict[str, Any]],
    schema_errors: Sequence[str] = (),
) -> Dict[str, Any]:
    has_trigger_candidate = any(
        _is_start_trigger_type(item.get("type"))
        or "trigger" in str(item.get("name", "")).lower()
        for item in candidates
    )

    capability_checks: List[Dict[str, Any]] = []
    for capability, markers in _required_capabilities(request):
        if capability == "trigger":
            found = has_trigger_candidate
        else:
            found = any(
                _capability_matches_node(capability, item)
                for item in candidates
            )

        capability_checks.append({
            "id": capability,
            "status": "verified" if found else "missing",
            "message": (
                f"Required capability '{capability}' was discovered."
                if found
                else f"Required capability '{capability}' was not discovered from live n8n nodes."
            ),
        })

    checks = capability_checks + [
        {
            "id": "trigger",
            "status": "candidate" if has_trigger_candidate else "missing",
            "message": "A trigger candidate was discovered." if has_trigger_candidate else "No obvious trigger node was discovered; search explicitly for the intended trigger.",
        },
        {
            "id": "node_schemas",
            "status": "verified" if definitions else "missing",
            "message": "Exact node definitions were retrieved from n8n." if definitions else "No exact node definitions were retrieved.",
        },
        {
            "id": "input_validation",
            "status": "required" if requirements["validation"]["required"] else "optional",
            "message": requirements["validation"]["reason"],
        },
        {
            "id": "error_handling",
            "status": "required" if requirements["error_handling"]["required"] else "recommended",
            "message": requirements["error_handling"]["reason"],
        },
        {
            "id": "retry_policy",
            "status": "required" if requirements["retry_policy"]["required"] else "recommended",
            "message": requirements["retry_policy"]["reason"],
        },
        {
            "id": "empty_data_behavior",
            "status": "required",
            "message": requirements["empty_data_behavior"]["reason"],
        },
        {
            "id": "observability",
            "status": "required" if requirements["observability"]["required"] else "recommended",
            "message": requirements["observability"]["reason"],
        },
        {
            "id": "side_effect_review",
            "status": "required" if requirements["side_effect_review"]["required"] else "not_required",
            "message": requirements["side_effect_review"]["reason"],
        },
    ]

    if schema_errors:
        checks.append({
            "id": "schema_safety",
            "status": "filtered",
            "message": (
                "n8n rejected some discovered node configurations; "
                "those nodes were filtered before the architecture was evaluated."
            ),
        })

    missing = [
        check["id"]
        for check in checks
        if check["status"] in {"missing", "blocked"}
    ]

    return {
        "ready_to_build": not missing and bool(definitions),
        "checks": checks,
        "missing": missing,
        "schema_errors": list(schema_errors),
        "note": (
            "This pass is read-only. Build/update/test/publish must use the "
            "existing n8n MCP mutation tools after the architecture is accepted."
        ),
    }


def design_workflow(
    request: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_text = _clean_text(request)
    if not request_text:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "Workflow architecture request is empty.",
        }

    context = dict(context or {})
    techniques = _infer_techniques(request_text)
    candidates, queries = _discover_nodes(
        request_text,
        techniques,
    )
    guidance = _best_practice_guidance(techniques)
    candidates = _augment_nodes_from_guidance(
        request_text,
        candidates,
        guidance,
    )
    node_types = _get_node_types(candidates)
    requirements = _requirements(
        request_text,
        techniques,
    )

    rejected_node_ids = {
        str(item).strip()
        for item in (
            list(node_types.get("invalid_node_ids", []))
            + list(node_types.get("deprecated_node_ids", []))
        )
        if str(item).strip()
    }
    candidates = [
        item for item in candidates
        if str(
            item.get("nodeId")
            or item.get("id")
            or item.get("type")
            or ""
        ) not in rejected_node_ids
    ]

    if rejected_node_ids:
        filtered_types = _get_node_types(candidates)
        if filtered_types.get("success") is True:
            node_types = filtered_types

    definitions = node_types.get("definitions", [])
    quality = _quality_gate(
        request_text,
        requirements,
        candidates,
        definitions,
        node_types.get("schema_errors", []),
    )

    return {
        "success": True,
        "verified": bool(node_types.get("success")),
        "retryable": False,
        "terminal": True,
        "execution_owner": "n8n",
        "mode": "design",
        "request": request_text,
        "context": context,
        "techniques": techniques,
        "search_queries": queries,
        "requirements": requirements,
        "best_practices": guidance,
        "required_capabilities": [
            capability
            for capability, _markers in _required_capabilities(request_text)
        ],
        "node_candidates": [
            {
                "name": item.get("name"),
                "nodeId": item.get("nodeId") or item.get("id") or item.get("type"),
                "type": item.get("type"),
                "version": item.get("version") or item.get("typeVersion"),
                "resource": item.get("resource"),
                "operation": item.get("operation"),
                "mode": item.get("mode"),
                "description": _clip(item.get("description", ""), MAX_DESCRIPTION_CHARS),
            }
            for item in candidates
        ],
        "node_definitions": definitions,
        "quality_gate": quality,
        "message": (
            "n8n workflow architecture discovered from live node schemas and guidance."
        ),
    }


def audit_workflow(
    workflow_id: str,
) -> Dict[str, Any]:
    workflow_id = _clean_text(workflow_id)
    if not workflow_id:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "Workflow ID is required for an audit.",
        }

    result = _call(
        "get_workflow_details",
        {
            "workflowId": workflow_id,
            "detailLevel": "full",
        },
    )
    if result.get("success") is not True:
        return result

    data = _result_data(result)
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "message": "n8n did not return workflow metadata.",
        }

    nodes = workflow.get("nodes")
    connections = workflow.get("connections")
    nodes = nodes if isinstance(nodes, list) else []
    connections = connections if isinstance(connections, dict) else {}

    node_types = [
        str(node.get("type") or "").lower()
        for node in nodes
        if isinstance(node, dict)
    ]

    has_trigger = any(
        _is_start_trigger_type(node_type)
        for node_type in node_types
    )
    has_error_node = any(
        "errortrigger" in node_type or "error trigger" in node_type
        for node_type in node_types
    )
    has_http = any("httprequest" in node_type for node_type in node_types)
    has_wait = any("wait" in node_type for node_type in node_types)

    findings: List[Dict[str, Any]] = []

    if not has_trigger:
        findings.append({
            "severity": "high",
            "id": "missing_trigger",
            "message": "No trigger node was found in the workflow graph.",
            "suggested_capability": "trigger",
        })

    if has_http:
        findings.append({
            "severity": "medium",
            "id": "http_resilience_review",
            "message": "HTTP Request nodes are present; review retry, timeout, response validation, and failure routing.",
            "suggested_capability": "http resilience",
        })

    if has_wait:
        findings.append({
            "severity": "low",
            "id": "wait_review",
            "message": "A Wait node is present; verify that the delay is intentional and downstream actions remain safe after resume.",
            "suggested_capability": "wait/resume handling",
        })

    if not has_error_node:
        findings.append({
            "severity": "medium",
            "id": "missing_error_strategy",
            "message": "No Error Trigger node was found; consider per-node error handling or a dedicated error workflow.",
            "suggested_capability": "error handling",
        })

    active = bool(workflow.get("active"))
    if active and findings:
        findings.append({
            "severity": "high",
            "id": "active_with_open_findings",
            "message": "Workflow is active while architecture findings remain unresolved.",
            "suggested_capability": "pre-publish quality gate",
        })

    return {
        "success": True,
        "verified": True,
        "retryable": False,
        "terminal": True,
        "execution_owner": "n8n",
        "mode": "audit",
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name"),
        "active": active,
        "node_count": len(nodes),
        "connection_count": sum(
            1
            for value in connections.values()
            if isinstance(value, dict)
        ),
        "findings": findings,
        "quality_gate": {
            "ready_to_publish": not any(
                finding["severity"] == "high"
                for finding in findings
            ),
            "finding_count": len(findings),
        },
        "message": "n8n workflow audit completed from the live workflow graph.",
    }


def run_architect(
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    arguments = arguments if isinstance(arguments, dict) else {}

    mode = _clean_text(arguments.get("mode") or "design").lower()
    if mode == "audit":
        return audit_workflow(
            str(arguments.get("workflow_id") or ""),
        )

    return design_workflow(
        str(arguments.get("request") or ""),
        arguments.get("context") if isinstance(arguments.get("context"), dict) else {},
    )
