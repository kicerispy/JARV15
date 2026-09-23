"""Loopback-only action gateway that lets n8n request approved JARVIS computer actions.

The gateway deliberately exposes structured, allowlisted actions instead of a raw
shell/PowerShell endpoint. n8n remains the workflow owner; JARVIS remains the
machine-control and verification owner.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

import config

logger = logging.getLogger("jarvis.n8n_local_bridge")

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024
ACTION_PATH = "/v1/jarvis/action"
HEALTH_PATH = "/healthz"

_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_lock = threading.Lock()


def _configured_token() -> str:
    return str(getattr(config, "N8N_WEBHOOK_TOKEN", "") or "").strip()


def _check_token(headers) -> bool:
    expected = _configured_token()
    if not expected:
        return True

    supplied = str(headers.get("X-JARVIS-N8N-TOKEN", "") or "").strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _error(message: str, status: int = 400) -> tuple[int, dict[str, Any]]:
    return status, {
        "success": False,
        "verified": False,
        "error": str(message),
        "message": str(message),
    }


def _call_action(action: str, arguments: Any) -> tuple[int, dict[str, Any]]:
    name = str(action or "").strip().lower()
    args = arguments if isinstance(arguments, dict) else {}

    handlers: dict[str, Callable[[], Any]] = {
        "open_program": lambda: _open_program(args.get("program")),
        "browser_goto": lambda: _browser_goto(args.get("url")),
        "browser_search_google": lambda: _browser_search_google(args.get("query")),
        "type_text": lambda: _type_text(args.get("text")),
        "press_key": lambda: _press_key(args.get("key")),
        "click_screen_target": lambda: _click_screen_target(args.get("target")),
        "analyze_screen": lambda: _analyze_screen(args.get("question")),
        "verify_screen_state": lambda: _verify_screen_state(args.get("expected")),
        "get_active_window": _get_active_window,
        "get_screen_size": _get_screen_size,
    }

    handler = handlers.get(name)
    if handler is None:
        return _error(
            f"Unsupported JARVIS local action: {name or '<empty>'}.",
            400,
        )

    try:
        result = handler()
        payload = dict(result) if isinstance(result, dict) else {
            "success": bool(result),
            "message": str(result),
        }
        payload.setdefault("action", name)
        payload.setdefault("verified", bool(payload.get("success")))
        return 200, payload
    except Exception as exc:
        logger.exception("Local action %s failed", name)
        return _error(f"JARVIS local action failed: {exc}", 500)


def _open_program(program: Any) -> dict[str, Any]:
    value = str(program or "").strip()
    if not value:
        return {"success": False, "verified": False, "error": "program is required"}

    # tools.open_program already enforces JARVIS's application allowlist.
    import tools

    message = tools.open_program(value)
    success = str(message).strip().lower().startswith("opening ")
    return {
        "success": success,
        "verified": False,
        "message": str(message),
        "program": value,
    }


def _browser_goto(url: Any) -> dict[str, Any]:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "success": False,
            "verified": False,
            "error": "browser_goto requires an http or https URL.",
        }

    from browser_controller import browser_goto

    result = browser_goto(value)
    return result if isinstance(result, dict) else {
        "success": bool(result),
        "message": str(result),
    }


def _browser_search_google(query: Any) -> dict[str, Any]:
    value = str(query or "").strip()
    if not value:
        return {"success": False, "verified": False, "error": "query is required"}

    from tools import search_website

    message = search_website("google", value)
    return {
        "success": "complete" in str(message).lower(),
        "verified": False,
        "message": str(message),
        "query": value,
    }


def _type_text(text: Any) -> dict[str, Any]:
    value = str(text or "")
    if not value:
        return {"success": False, "verified": False, "error": "text is required"}
    if len(value) > 4000:
        return {
            "success": False,
            "verified": False,
            "error": "text exceeds the 4000-character limit.",
        }

    import screen_vision

    return screen_vision.type_text(value)


def _press_key(key: Any) -> dict[str, Any]:
    value = str(key or "").strip()
    if not value:
        return {"success": False, "verified": False, "error": "key is required"}
    if len(value) > 64:
        return {
            "success": False,
            "verified": False,
            "error": "key is too long.",
        }

    import screen_vision

    return screen_vision.press_key(value)


def _click_screen_target(target: Any) -> dict[str, Any]:
    value = str(target or "").strip()
    if not value:
        return {"success": False, "verified": False, "error": "target is required"}
    if len(value) > 300:
        return {
            "success": False,
            "verified": False,
            "error": "target is too long.",
        }

    import screen_vision

    return screen_vision.click_screen_target(value)


def _analyze_screen(question: Any) -> dict[str, Any]:
    value = str(question or "").strip()
    if len(value) > 1000:
        return {
            "success": False,
            "verified": False,
            "error": "question is too long.",
        }

    import screen_vision

    return screen_vision.analyze_screen(value)


def _verify_screen_state(expected: Any) -> dict[str, Any]:
    value = str(expected or "").strip()
    if not value:
        return {"success": False, "verified": False, "error": "expected is required"}
    if len(value) > 1000:
        return {
            "success": False,
            "verified": False,
            "error": "expected is too long.",
        }

    import screen_vision

    return screen_vision.verify_screen_state(value)


def _get_active_window() -> dict[str, Any]:
    import screen_vision
    return screen_vision.get_active_window()


def _get_screen_size() -> dict[str, Any]:
    import screen_vision
    return screen_vision.get_screen_size()


class _Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS-n8n-local/1.0"

    def log_message(self, format: str, *args) -> None:
        logger.info("local-action " + format, *args)

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == HEALTH_PATH:
            self._write(200, {
                "success": True,
                "service": "JARVIS local action gateway",
                "loopback_only": True,
                "actions": sorted(_ACTION_NAMES),
            })
            return

        self._write(404, {"success": False, "message": "Not found."})

    def do_POST(self) -> None:
        if self.path != ACTION_PATH:
            self._write(404, {"success": False, "message": "Not found."})
            return

        if not _check_token(self.headers):
            self._write(401, {
                "success": False,
                "message": "Invalid JARVIS/n8n token.",
            })
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if length <= 0 or length > MAX_BODY_BYTES:
            self._write(413 if length > MAX_BODY_BYTES else 400, {
                "success": False,
                "message": "Request body is missing or too large.",
            })
            return

        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write(400, {
                "success": False,
                "message": "Request body must be valid UTF-8 JSON.",
            })
            return

        if not isinstance(payload, dict):
            self._write(400, {
                "success": False,
                "message": "Request body must be a JSON object.",
            })
            return

        status, result = _call_action(
            payload.get("action"),
            payload.get("arguments", {}),
        )
        self._write(status, result)


_ACTION_NAMES = {
    "open_program",
    "browser_goto",
    "browser_search_google",
    "type_text",
    "press_key",
    "click_screen_target",
    "analyze_screen",
    "verify_screen_state",
    "get_active_window",
    "get_screen_size",
}


def start_local_action_server() -> bool:
    """Start the JARVIS loopback action server once."""
    global _server, _server_thread

    if not bool(getattr(config, "N8N_ENABLED", False)):
        return False

    with _lock:
        if _server is not None:
            return True

        port = int(getattr(config, "N8N_LOCAL_ACTION_PORT", 8765))

        try:
            _server = ThreadingHTTPServer((HOST, port), _Handler)
        except OSError as exc:
            logger.warning(
                "JARVIS n8n local-action gateway could not start on "
                f"{HOST}:{port}: {exc}"
            )
            _server = None
            return False

        _server_thread = threading.Thread(
            target=_server.serve_forever,
            name="JARVIS-n8n-local-action",
            daemon=True,
        )
        _server_thread.start()

        logger.info(
            "JARVIS n8n local-action gateway listening on "
            f"http://{HOST}:{port}{ACTION_PATH}"
        )
        if not _configured_token():
            logger.warning(
                "JARVIS n8n local-action gateway has no token configured; "
                "access is limited to localhost and allowlisted actions."
            )
        return True


def stop_local_action_server() -> None:
    global _server, _server_thread

    with _lock:
        server = _server
        _server = None
        _server_thread = None

    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            logger.debug(
                "JARVIS n8n local-action gateway shutdown failed",
                exc_info=True,
            )


def local_action_url() -> str:
    port = int(getattr(config, "N8N_LOCAL_ACTION_PORT", 8765))
    return f"http://{HOST}:{port}{ACTION_PATH}"


def local_action_health_url() -> str:
    port = int(getattr(config, "N8N_LOCAL_ACTION_PORT", 8765))
    return f"http://{HOST}:{port}{HEALTH_PATH}"
