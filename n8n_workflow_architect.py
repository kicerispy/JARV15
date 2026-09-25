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


MAX_TECHNIQUES = 2
MAX_QUERIES = 6
MAX_NODE_CANDIDATES = 8
MAX_NODE_TYPE_REQUESTS = 8
MAX_BEST_PRACTICE_CHARS = 12000
MAX_DESCRIPTION_CHARS = 3000


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
    ("notification", ("notify", "notification", "email", "send a message", "slack", "discord")),
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
    terms = _keyword_terms(request)
    queries = [_clean_text(request)]

    if terms:
        queries.append(" ".join(terms[:6]))

    for technique in techniques:
        queries.append(technique.replace("_", " "))

    queries.append("trigger")

    expanded = list(queries)
    for term in terms[:4]:
        expanded.append(term)

    return _unique_strings(expanded)[:MAX_QUERIES]


def _result_data(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _result_list(result: Dict[str, Any], keys: Sequence[str]) -> List[Dict[str, Any]]:
    data = _result_data(result)

    for key in ("data", *keys):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    return []


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

        if len(candidates) >= MAX_NODE_CANDIDATES:
            break

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        ref = _node_identity(item)
        if not ref:
            continue
        key = json.dumps(ref, sort_keys=True, default=str)
        if key not in deduped:
            deduped[key] = item

    return list(deduped.values())[:MAX_NODE_CANDIDATES], queries


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
        }

    result = _call(
        "get_node_types",
        {"nodeIds": refs},
    )

    return {
        "success": result.get("success") is True,
        "message": result.get("message", ""),
        "definitions": _result_list(result, ("nodeTypes", "nodes", "definitions", "results")),
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
            data.get("guidance")
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


def _quality_gate(
    request: str,
    requirements: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
    definitions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    has_trigger_candidate = any(
        _is_start_trigger_type(item.get("type"))
        or "trigger" in str(item.get("name", "")).lower()
        for item in candidates
    )

    checks = [
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

    missing = [
        check["id"]
        for check in checks
        if check["status"] == "missing"
    ]

    return {
        "ready_to_build": not missing and bool(definitions),
        "checks": checks,
        "missing": missing,
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
    node_types = _get_node_types(candidates)
    guidance = _best_practice_guidance(techniques)
    requirements = _requirements(
        request_text,
        techniques,
    )

    definitions = node_types.get("definitions", [])
    quality = _quality_gate(
        request_text,
        requirements,
        candidates,
        definitions,
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
