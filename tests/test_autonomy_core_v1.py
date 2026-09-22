"""Regression tests for context-aware routing and tool failure semantics."""

from commands import deterministic_route, get_fast_command
from tool_executor import normalize_tool_result


def _roblox_context():
    return {
        "site": "roblox",
        "last_tool": "roblox__get_project_structure",
        "last_action": "roblox__get_project_structure",
    }


def test_roblox_context_blocks_generic_browser_dom_route():
    request = "find the scripts that control the core gameplay systems"

    assert deterministic_route(
        request,
        active_context=_roblox_context(),
    ) is None

    assert get_fast_command(
        request,
        active_context=_roblox_context(),
    ) is None


def test_explicit_browser_request_can_escape_roblox_context():
    plan = get_fast_command(
        "search Google for wifi skeleton",
        active_context=_roblox_context(),
    )

    assert plan is not None
    assert plan["steps"][0]["tool"] == "browser_search_google"


def test_no_context_preserves_existing_browser_dom_behavior():
    plan = get_fast_command(
        "find the search box",
    )

    assert plan is not None
    assert plan["steps"][0]["tool"] == "browser_find_element"


def test_legacy_error_strings_are_failures():
    success, verified, message = normalize_tool_result(
        "I don't know how to search github."
    )

    assert success is False
    assert verified is False
    assert "search github" in message


def test_plain_legacy_success_strings_remain_successful():
    success, verified, message = normalize_tool_result(
        "Search completed successfully."
    )

    assert success is True
    assert verified is True
    assert message == "Search completed successfully."
