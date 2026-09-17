"""JARVIS-facing barehands tool facade.

The existing planner/dispatcher can adopt these functions without knowing
anything about the barehands HTTP protocol.
"""

from __future__ import annotations

import os

from barehands_controller import BarehandsController
from tool_result import ToolResult


def _controller() -> BarehandsController:
    return BarehandsController(
        state_dir=os.environ.get("BAREHANDS_DIR", "").strip() or None,
    )


def barehands_state(argument: str = "") -> ToolResult:
    return _controller().set_state(argument)


def barehands_present(argument: str = "") -> ToolResult:
    if "|||" not in argument:
        return ToolResult(
            success=False,
            tool="barehands_present",
            error="Use title|||body.",
            retryable=False,
        )
    title, body = argument.split("|||", 1)
    result = _controller().present(title.strip(), body)
    result.tool = "barehands_present"
    return result


def barehands_add_card(argument: str = "") -> ToolResult:
    if "|||" not in argument:
        return ToolResult(
            success=False,
            tool="barehands_add_card",
            error="Use title|||body.",
            retryable=False,
        )
    title, body = argument.split("|||", 1)
    result = _controller().add_card(title.strip(), body)
    result.tool = "barehands_add_card"
    return result


def barehands_add_image(argument: str = "") -> ToolResult:
    parts = argument.split("|||", 2)
    if not parts or not parts[0].strip():
        return ToolResult(
            success=False,
            tool="barehands_add_image",
            error="Use src|||title|||body.",
            retryable=False,
        )
    src = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""
    body = parts[2] if len(parts) > 2 else ""
    result = _controller().add_image(src, title, body)
    result.tool = "barehands_add_image"
    return result


def barehands_clear(argument: str = "") -> ToolResult:
    result = _controller().clear()
    result.tool = "barehands_clear"
    return result


def barehands_board_state(argument: str = "") -> ToolResult:
    result = _controller().board_state()
    result.tool = "barehands_board_state"
    return result
