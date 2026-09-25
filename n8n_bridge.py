"""n8n workflow delegation bridge for JARVIS.

n8n owns workflow-class tasks that benefit from persistent workflow state,
schedules, retries, branching, and external-service integrations. JARVIS
delegates through a local webhook and keeps real-time computer/game/browser
control in Python.

The bridge is intentionally dependency-free and fail-closed:
- n8n is opt-in via JARVIS_N8N_ENABLED.
- remote n8n endpoints require a webhook token.
- workflow dispatches are not automatically retried by JARVIS because n8n
  should own workflow retry semantics and duplicate-side-effect prevention.
"""

from __future__ import annotations

import json
import re
import socket
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


from config import (
    N8N_BASE_URL,
    N8N_ENABLED,
    N8N_TIMEOUT_SECONDS,
    N8N_WEBHOOK_PATH,
    N8N_WEBHOOK_TOKEN,
)


MAX_N8N_PAYLOAD_CHARS = 12000
MAX_N8N_RESPONSE_BYTES = 2 * 1024 * 1024


def _normalize(text: Any) -> str:
    return " ".join(
        str(text or "").strip().lower().split()
    )


def classify_n8n_request(request: str) -> Optional[str]:
    """Classify workflow tasks where n8n has an architectural advantage."""
    text = _normalize(request)
    if not text:
        return None

    # Informational n8n questions must remain normal JARVIS conversation.
    # This guard runs before workflow keywords such as "n8n workflow".
    if "n8n" in text and any(
        text.startswith(prefix)
        for prefix in (
            "what is ",
            "what's ",
            "what are ",
            "explain ",
            "how does ",
            "how do ",
            "how can ",
            "tell me about ",
        )
    ):
        return None
    # Scheduling / recurring work.
    if any(
        phrase in text
        for phrase in (
            "remind me",
            "set a reminder",
            "schedule ",
            "scheduled ",
            "schedule this",
            "every day",
            "every weekday",
            "every week",
            "every month",
            "every hour",
            "every minute",
            "daily ",
            "weekly ",
            "monthly ",
            "recurring",
            "recurring task",
            "in 5 minutes",
            "in 10 minutes",
            "in 15 minutes",
            "in 30 minutes",
            "in an hour",
            "tomorrow at ",
            "tonight at ",
        )
    ):
        return "schedule"

    # Persistent monitoring / conditional notification.
    if any(
        phrase in text
        for phrase in (
            "monitor ",
            "monitoring ",
            "keep monitoring ",
            "watch ",
            "keep an eye on ",
            "alert me when ",
            "notify me when ",
            "tell me when ",
            "let me know when ",
            "until ",
            "when this happens",
            "when it happens",
        )
    ):
        return "monitor"

    # Local Spotify automation is delegated to n8n so workflow orchestration
    # owns the request while JARVIS retains the actual Windows control.
    if (
        ("spotify" in text and any(phrase in text for phrase in (
            "play",
            "liked songs",
            "open spotify",
            "start spotify",
        )))
    ):
        return "integration"

    # Service-to-service language is workflow-shaped even when the user does
    # not explicitly say "workflow" or "automation". Require either multiple
    # recognized services or explicit cross-service wording so ordinary actions
    # such as "send an email to my inbox" remain integrations.
    service_aliases = {
        "email": ("email", "gmail", "outlook"),
        "calendar": ("calendar", "google calendar"),
        "sheets": ("sheets", "google sheets", "google spreadsheet", "spreadsheets"),
        "drive": ("drive", "google drive"),
        "slack": ("slack",),
        "discord": ("discord",),
        "telegram": ("telegram",),
        "notion": ("notion",),
        "github": ("github",),
        "gitlab": ("gitlab",),
        "jira": ("jira",),
        "linear": ("linear",),
        "trello": ("trello",),
        "todoist": ("todoist",),
        "dropbox": ("dropbox",),
        "onedrive": ("onedrive",),
        "spotify": ("spotify",),
        "twilio": ("twilio",),
        "stripe": ("stripe",),
        "salesforce": ("salesforce",),
        "hubspot": ("hubspot",),
        "wordpress": ("wordpress",),
        "reddit": ("reddit",),
        "linkedin": ("linkedin",),
        "webhook": ("webhook",),
        "rss": ("rss",),
        "airtable": ("airtable",),
    }

    mentioned_services = {
        service
        for service, aliases in service_aliases.items()
        if any(alias in text for alias in aliases)
    }

    explicit_multi_service = any(
        re.search(pattern, text)
        for pattern in (
            r"\bsync\b.+\bwith\b",
            r"\bbetween\b.+\band\b",
            r"\bwhen\b.+\bthen\b",
            r"\bafter\b.+,?\s+then\b",
            r"\bacross\s+(?:multiple|two|several)\s+(?:services|apps)\b",
            r"\bfrom\s+\w[\w .-]*\bto\s+\w[\w .-]*\b",
        )
    )

    # Explicit external-service actions should stay integration-classified
    # even when the request names two services (for example, emailing a
    # GitHub report). Reserve orchestration for explicit cross-service
    # workflows/synchronization.
    external_services = (
        "email", "gmail", "outlook", "calendar", "google calendar",
        "google sheets", "google drive", "drive", "sheets", "slack",
        "discord", "telegram", "notion", "github", "gitlab", "jira",
        "linear", "trello", "todoist", "dropbox", "onedrive", "spotify",
        "twilio", "stripe", "salesforce", "hubspot", "wordpress", "reddit",
        "linkedin", "webhook", "rss",
    )
    external_actions = (
        "send ", "email ", "post ", "create ", "add ", "update ", "save ", "sync ",
        "forward ", "share ", "upload ", "download ", "notify ", "message ",
        "schedule ",
    )

    is_external_mutation = (
        any(service in text for service in external_services)
        and any(action in text for action in external_actions)
    )

    if explicit_multi_service and (
        "sync " in text
        or "between " in text
        or "across multiple services" in text
        or "across multiple apps" in text
    ):
        return "orchestration"

    if is_external_mutation:
        return "integration"

    if len(mentioned_services) >= 2:
        return "orchestration"

    # External-service mutations and integrations are n8n-first. Read-only
    # search/lookup questions stay on the fast JARVIS/web path unless the user
    # explicitly asks for a workflow.
    # Desktop/media control can still be n8n-first when the request is about
    # an external service that benefits from orchestration (Spotify is the
    # initial example implemented by the JARVIS local-action gateway).
    media_services = ("spotify", "plex", "youtube music", "apple music")
    media_actions = ("play ", "open ", "start ", "stop ", "pause ", "resume ")
    if any(service in text for service in media_services) and any(
        action in text for action in media_actions
    ):
        return "integration"

    # External-service workflows are better represented as n8n integrations
    # than as one-off JARVIS Python branches.
    if any(
        phrase in text
        for phrase in (
            "send an email",
            "send email",
            "email me",
            "email the",
            "send a message",
            "send this to discord",
            "send to discord",
            "send to slack",
            "send to telegram",
            "post to discord",
            "post to slack",
            "post to telegram",
            "google calendar",
            "calendar event",
            "google sheets",
            "add to sheets",
            "save to notion",
            "create a github issue",
            "create a github pr",
            "create a github pull request",
            "webhook",
            "external service",
            "third-party service",
        )
    ):
        return "integration"

    # Explicit workflow/orchestration requests and multi-service pipelines.
    # Mentioning "n8n" alone is not enough: informational questions about n8n
    # should remain normal JARVIS conversations.
    if any(
        phrase in text
        for phrase in (
            "run a workflow",
            "run the workflow",
            "workflow for ",
            "create a workflow",
            "create an n8n workflow",
            "use n8n",
            "run in n8n",
            "delegate to n8n",
            "with n8n",
            "n8n workflow",
            "n8n automation",
            "automate this",
            "automate that",
            "set up an automation",
            "setup an automation",
            "build an automation",
            "automation that ",
            "automate ",
            "when ... then",
            "when this happens, ",
            "after that, ",
            "then send ",
            "then notify ",
            "then email ",
            "across multiple services",
            "across multiple apps",
            "multi-step workflow",
            "multi service workflow",
            "long-running workflow",
            "background workflow",
        )
    ):
        return "orchestration"

    return None


def n8n_status() -> Dict[str, Any]:
    """Return configuration and reachability information without side effects."""
    parsed = urlparse(N8N_BASE_URL)

    enabled = N8N_ENABLED
    configured = bool(
        N8N_BASE_URL
        and N8N_WEBHOOK_PATH
    )

    host = (parsed.hostname or "").strip().lower()
    local_host = host in {
        "127.0.0.1",
        "localhost",
        "::1",
    }

    token_required = not local_host
    token_present = bool(N8N_WEBHOOK_TOKEN)

    result: Dict[str, Any] = {
        "success": False,
        "verified": False,
        "enabled": enabled,
        "configured": configured,
        "reachable": False,
        "base_url": N8N_BASE_URL,
        "webhook_path": N8N_WEBHOOK_PATH,
        "execution_owner": "n8n",
        "local_only": local_host,
    }

    if not enabled:
        result["message"] = (
            "n8n delegation is disabled. "
            "Set JARVIS_N8N_ENABLED=1 to enable it."
        )
        return result

    if not configured:
        result["message"] = "n8n delegation is enabled but not configured."
        return result

    if token_required and not token_present:
        result["message"] = (
            "Remote n8n endpoint refused because "
            "JARVIS_N8N_WEBHOOK_TOKEN is not configured."
        )
        return result

    try:
        request = Request(
            N8N_BASE_URL + "/",
            headers={
                "Accept": "text/html,application/json",
                "User-Agent": "JARVIS-n8n-bridge/1.0",
            },
            method="GET",
        )
        with urlopen(
            request,
            timeout=min(N8N_TIMEOUT_SECONDS, 3.0),
        ) as response:
            status = int(getattr(response, "status", 200) or 200)

        result.update(
            {
                "success": 200 <= status < 400,
                "verified": 200 <= status < 400,
                "reachable": True,
                "http_status": status,
                "message": (
                    "n8n is reachable."
                    if 200 <= status < 400
                    else f"n8n responded with HTTP {status}."
                ),
            }
        )
        return result

    except HTTPError as exc:
        reachable = int(exc.code) < 500
        result.update(
            {
                "reachable": reachable,
                "http_status": int(exc.code),
                "message": (
                    f"n8n is reachable but returned HTTP {exc.code}."
                    if reachable
                    else f"n8n returned HTTP {exc.code}."
                ),
            }
        )
        return result
    except (URLError, TimeoutError, OSError) as exc:
        result["message"] = f"n8n is unreachable: {exc}"
        return result
    except Exception as exc:
        result["message"] = f"n8n status check failed: {exc}"
        return result


def run_n8n_workflow(
    request: str,
    workflow_class: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Delegate one workflow-class task to the configured n8n gateway."""
    normalized_request = " ".join(
        str(request or "").strip().split()
    )

    normalized_class = _normalize(workflow_class)

    # Prefer the native n8n instance-level MCP transport when enabled.
    # Keep the existing webhook gateway as a stable fallback for installations
    # that have not enabled MCP yet.
    try:
        from config import N8N_MCP_ENABLED
    except Exception:
        N8N_MCP_ENABLED = False

    if N8N_MCP_ENABLED:
        from n8n_mcp import run_workflow_request
        return run_workflow_request(
            request=normalized_request,
            workflow_class=normalized_class,
            context=context,
        )

    if not N8N_ENABLED:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": (
                "n8n workflow delegation is disabled. "
                "Enable it with JARVIS_N8N_ENABLED=1."
            ),
        }

    if not normalized_request:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": "The n8n workflow request was empty.",
        }

    if normalized_class not in {
        "schedule",
        "monitor",
        "integration",
        "orchestration",
    }:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": f"Unsupported n8n workflow class: {normalized_class}.",
        }

    parsed = urlparse(N8N_BASE_URL)
    host = (parsed.hostname or "").strip().lower()
    local_host = host in {"127.0.0.1", "localhost", "::1"}

    if not local_host and not N8N_WEBHOOK_TOKEN:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": (
                "Remote n8n dispatch requires "
                "JARVIS_N8N_WEBHOOK_TOKEN."
            ),
        }

    gateway_url = (
        N8N_BASE_URL
        + "/"
        + N8N_WEBHOOK_PATH
    )

    bounded_context = context if isinstance(context, dict) else {}

    body: Dict[str, Any] = {
        "protocol_version": "1",
        "source": "JARVIS",
        "request": normalized_request,
        "workflow_class": normalized_class,
        "context": bounded_context,
        "execution_policy": {
            "owner": "n8n",
            "allow_local_fallback": False,
            "retry_owner": "n8n",
        },
    }

    serialized = json.dumps(
        body,
        ensure_ascii=False,
        default=str,
    )

    if len(serialized) > MAX_N8N_PAYLOAD_CHARS:
        # Keep the user request and workflow metadata, but bound contextual
        # state so a large JARVIS observation cannot become an n8n flood.
        body["context"] = {}
        body["context_truncated"] = True
        serialized = json.dumps(
            body,
            ensure_ascii=False,
            default=str,
        )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "JARVIS-n8n-bridge/1.0",
    }

    if N8N_WEBHOOK_TOKEN:
        headers["X-JARVIS-N8N-TOKEN"] = N8N_WEBHOOK_TOKEN

    http_request = Request(
        gateway_url,
        data=serialized.encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(
            http_request,
            timeout=N8N_TIMEOUT_SECONDS,
        ) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read(MAX_N8N_RESPONSE_BYTES + 1)

        if len(raw) > MAX_N8N_RESPONSE_BYTES:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "workflow_class": normalized_class,
                "message": "n8n returned an oversized response.",
            }

        text = raw.decode(
            "utf-8",
            errors="replace",
        ).strip()

        try:
            payload: Any = json.loads(text) if text else {}
        except (TypeError, ValueError):
            payload = {"message": text}

        if 200 <= status < 300:
            result: Dict[str, Any] = {
                "success": True,
                "verified": True,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "workflow_class": normalized_class,
                "http_status": status,
                "accepted": True,
            }

            if isinstance(payload, dict):
                result.update(payload)
            elif payload:
                result["response"] = payload

            if (
                result.get("success") is False
                or result.get("accepted") is False
            ):
                result["success"] = False
                result["verified"] = False
                result["accepted"] = False
                result["message"] = str(
                    result.get("message")
                    or result.get("error")
                    or f"n8n rejected the {normalized_class} workflow."
                )
                return result

            if not result.get("message"):
                result["message"] = (
                    f"n8n accepted the {normalized_class} workflow."
                )

            return result

        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "http_status": status,
            "message": f"n8n rejected the workflow with HTTP {status}.",
        }

    except HTTPError as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "http_status": int(exc.code),
            "message": f"n8n workflow dispatch failed with HTTP {exc.code}.",
        }
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": f"n8n workflow dispatch failed: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "workflow_class": normalized_class,
            "message": f"n8n workflow dispatch failed: {exc}",
        }

