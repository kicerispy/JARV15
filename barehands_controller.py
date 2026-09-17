"""Optional controller for the barehands localhost interface.

JARVIS deliberately treats barehands as an external visual peripheral. This
module talks to its documented HTTP API and never imports or executes files
from the barehands repository.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tool_result import ToolResult


DEFAULT_BASE_URL = "http://127.0.0.1:8794"
DEFAULT_TIMEOUT = 1.5

VALID_STATES = {"idle", "listening", "thinking", "speaking"}

ALLOWED_BOARD_ACTIONS = {
    "add_img",
    "add_card",
    "clear",
    "reset",
    "hand",
    "give",
    "yank",
    "hover",
    "scroll_note",
    "widget",
    "explode",
    "assemble",
    "present",
}


class BarehandsController:
    """Small, synchronous HTTP adapter for a running barehands server."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = float(timeout)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read()

        if not raw:
            return None

        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _failure(tool: str, error: str, retryable: bool = True) -> ToolResult:
        return ToolResult(
            success=False,
            tool=tool,
            error=error,
            retryable=retryable,
        )

    def is_available(self) -> bool:
        """Return whether a barehands server responds to /config."""
        try:
            self._request("GET", "/config")
            return True
        except Exception:
            return False

    def set_state(self, state: str) -> ToolResult:
        """Set the barehands ring state through its command channel."""
        state = str(state or "").strip().lower()
        tool = "barehands_state"

        if state not in VALID_STATES:
            return self._failure(
                tool,
                "Invalid barehands state. Use idle, listening, thinking, or speaking.",
                retryable=False,
            )

        try:
            self._request("POST", "/cmd", {"a": "widget", "state": state})
            # The documented ring protocol is file-based, while /cmd is the
            # documented board command channel. Keep state writes explicit
            # and compatible with the server's widget command without touching
            # the barehands filesystem.
            return ToolResult(
                success=True,
                tool=tool,
                data={"state": state},
            )
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            return self._failure(tool, f"Barehands unavailable: {exc}")
        except Exception as exc:
            return self._failure(tool, f"Barehands state update failed: {exc}")

    def board_command(self, action: str, **payload: Any) -> ToolResult:
        """Send one allowlisted board command to /cmd."""
        action = str(action or "").strip()
        tool = "barehands_board_command"

        if action not in ALLOWED_BOARD_ACTIONS:
            return self._failure(
                tool,
                f"Unsupported barehands board action: {action}",
                retryable=False,
            )

        command = {"a": action, **payload}

        try:
            self._request("POST", "/cmd", command)
            return ToolResult(
                success=True,
                tool=tool,
                data=command,
            )
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            return self._failure(tool, f"Barehands unavailable: {exc}")
        except Exception as exc:
            return self._failure(tool, f"Barehands command failed: {exc}")

    def present(self, title: str, body: str) -> ToolResult:
        return self.board_command("present", title=str(title), body=str(body))

    def add_card(self, title: str, body: str) -> ToolResult:
        return self.board_command("add_card", title=str(title), body=str(body))

    def add_image(self, src: str, title: str = "", body: str = "") -> ToolResult:
        return self.board_command(
            "add_img",
            src=str(src),
            title=str(title),
            body=str(body),
        )

    def clear(self) -> ToolResult:
        return self.board_command("clear")

    def board_state(self) -> ToolResult:
        tool = "barehands_board_state"
        try:
            state = self._request("GET", "/state")
            return ToolResult(success=True, tool=tool, data=state)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            return self._failure(tool, f"Barehands unavailable: {exc}")
        except Exception as exc:
            return self._failure(tool, f"Barehands board-state read failed: {exc}")
