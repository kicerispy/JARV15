"""
JARVIS tool execution engine.

Optimized for low latency while preserving reliable execution
for multi-step computer-control tasks.
"""

import ast
import json
import time
from typing import Any, Dict, Optional

from logger import logger
from state import ActiveContext, TaskState
from tools import run_tool
from tool_result import ToolResult


# ============================================================
# PLAYWRIGHT BROWSER TOOLS
# ============================================================

BROWSER_TOOLS = {
    "browser_find_element",
    "browser_click_element",
    "browser_fill_element",
    "browser_press_key",
    "browser_wait_for_element",
    "browser_extract_text",
    "browser_click_first_result",
    "browser_connect",
    "browser_search_google",
    "browser_search_bing",
    "browser_click_first_bing_result",
    "browser_goto",
    "browser_page_info",
    "browser_click_result",
    "browser_back",
}


def run_browser_tool(
    tool_name: str,
    argument: str = "",
):
    """
    Dispatch browser tools through the canonical tools.py dispatcher.

    tools.run_browser_tool() is responsible for browser dispatch and
    ToolResult normalization. Keeping one dispatcher prevents the
    executor and tools layer from drifting apart.
    """

    from tools import run_browser_tool as dispatch_browser_tool

    return dispatch_browser_tool(
        tool_name,
        argument,
    )


# ============================================================
# SAFE SINGLE-ACTION RETRY
# ============================================================

# These tools are observational or otherwise safe to repeat when the tool
# explicitly marks its failure as retryable. Browser actions are excluded
# because browser_controller.py already owns DOM retry/fallback behavior.
SAFE_RETRY_TOOLS = {
    "weather",
    "current_time",
    "current_date",
    "system_status",
    "jarvis_status",
    "task_history",
    "web_search",
    "code_search",
    "code_test",
    "code_diagnose",
    "capture_screen",
    "screen_size",
    "get_active_window",
    "analyze_screen",
    "verify_screen",
    "barehands_board_state",
}


def _execute_with_safe_retry(
    tool_name: str,
    argument: str,
    task_state: TaskState,
) -> Any:
    """
    Retry one explicitly retryable safe action once.

    This is deliberately step-local: a successful retry resumes the existing
    multi-step plan instead of forcing Agent Core to restart the task.
    """
    result = run_tool(
        tool_name,
        argument,
    )

    if not (
        tool_name in SAFE_RETRY_TOOLS
        and isinstance(result, ToolResult)
        and not result.success
        and result.retryable
    ):
        return result

    logger.warning(
        "JARVIS: Retrying safe tool "
        f"{tool_name} once after a retryable failure."
    )

    time.sleep(0.15)

    task_state.record_attempt()
    task_state.record_recovery()

    return run_tool(
        tool_name,
        argument,
    )


# ============================================================
# BROWSER FALLBACK / CONTEXT
# ============================================================

def _unwrap_result_data(result: Any) -> Any:
    if isinstance(result, ToolResult):
        return result.data
    return result


def _parse_browser_argument(argument: str) -> dict:
    """Parse structured browser arguments without requiring strict JSON only."""
    raw_argument = str(argument or "").strip()

    if not raw_argument:
        return {}

    payload = {}

    try:
        payload = json.loads(raw_argument)
    except (json.JSONDecodeError, TypeError):
        try:
            payload = ast.literal_eval(raw_argument)
        except (ValueError, SyntaxError, TypeError):
            payload = {}

    return payload if isinstance(payload, dict) else {}


def _browser_target_payload(payload: dict) -> dict:
    """Return only the DOM target fields understood by browser_controller."""
    target = {}

    for key in ("selector", "text", "role", "name"):
        value = str(payload.get(key) or "").strip()
        if value:
            target[key] = value

    return target


def _browser_result_status(result: Any) -> tuple[bool, bool]:
    """Read success/verification without losing legacy dict compatibility."""
    if isinstance(result, ToolResult):
        success = bool(result.success)
        data = result.data

        if isinstance(data, dict):
            verified = bool(data.get("verified", success))
        else:
            verified = success

        return success, verified

    if isinstance(result, dict):
        return (
            bool(result.get("success", False)),
            bool(
                result.get(
                    "verified",
                    result.get("success", False),
                )
            ),
        )

    return True, True


def _observe_browser_state() -> dict:
    """Re-read the current browser page before attempting recovery."""
    try:
        from browser_controller import browser_page_info

        observed = browser_page_info()

        if isinstance(observed, dict):
            return observed

        return {
            "success": False,
            "error": "browser_page_info returned a non-dict result.",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
        }


def _augment_browser_recovery_result(
    result: Any,
    *,
    observed_before: Optional[dict] = None,
    observed_after: Optional[dict] = None,
    recovered_by: str = "",
) -> Any:
    """Attach bounded recovery evidence without changing legacy result shapes."""
    metadata = {}

    if observed_before:
        metadata["observed_before"] = observed_before

    if observed_after:
        metadata["observed_after"] = observed_after

    if recovered_by:
        metadata["recovered_by"] = recovered_by

    if not metadata:
        return result

    if isinstance(result, ToolResult):
        data = result.data

        if isinstance(data, dict):
            data = dict(data)
            data["recovery"] = metadata
        else:
            data = {
                "result": data,
                "recovery": metadata,
            }

        return ToolResult(
            success=result.success,
            tool=result.tool,
            data=data,
            error=result.error,
            retryable=result.retryable,
            observation=result.observation or metadata,
        )

    if isinstance(result, dict):
        updated = dict(result)
        updated["recovery"] = metadata
        return updated

    return result


def _browser_recovery_wait(
    argument: str,
) -> Optional[dict]:
    """Wait briefly for a DOM target to become visible before retrying."""
    payload = _parse_browser_argument(argument)
    target = _browser_target_payload(payload)

    if not target:
        return None

    wait_argument = dict(target)
    wait_argument["timeout"] = 1_500

    try:
        return run_browser_tool(
            "browser_wait_for_element",
            json.dumps(wait_argument),
        )
    except Exception as exc:
        logger.debug(
            "JARVIS: Browser recovery wait unavailable: %s",
            exc,
        )
        return None


def _browser_alternate_strategy(
    tool_name: str,
    argument: str,
    observed_state: dict,
) -> tuple[str, Any]:
    """
    Try a safer alternate browser strategy.

    Result clicks can switch between the specialized first-result tool and
    the generic ordinal-result tool. DOM actions first re-check their target.
    """
    payload = _parse_browser_argument(argument)

    if tool_name == "browser_click_first_result":
        site = str(
            payload.get("site")
            or observed_state.get("site")
            or ""
        ).strip()

        query = str(
            payload.get("query")
            or ""
        ).strip()

        if site.lower() in {"google", "youtube"}:
            return (
                "browser_click_result",
                json.dumps(
                    {
                        "index": 1,
                        "site": site.lower(),
                        "query": query,
                    }
                ),
            )

    if tool_name == "browser_click_result":
        site = str(
            payload.get("site")
            or observed_state.get("site")
            or ""
        ).strip()

        query = str(
            payload.get("query")
            or ""
        ).strip()

        try:
            index = int(payload.get("index", 1))
        except (TypeError, ValueError):
            index = 1

        if index == 1 and site.lower() in {"google", "youtube"}:
            return (
                "browser_click_first_result",
                json.dumps(
                    {
                        "site": site.lower(),
                        "query": query,
                    }
                ),
            )

    dom_tools = {
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_extract_text",
    }

    if tool_name in dom_tools:
        target = _browser_target_payload(payload)

        if target:
            try:
                return (
                    "browser_find_element",
                    json.dumps(target),
                )
            except Exception:
                pass

    return "", None


def _execute_browser_with_fallback(
    tool_name: str,
    argument: str,
) -> Any:
    """
    Execute a browser action with bounded state-aware recovery.

    Recovery order:
      1. primary browser action
      2. re-observe current page
      3. wait/re-check the DOM target when applicable
      4. retry the primary action once
      5. try one safer alternate strategy
      6. use existing desktop-vision click fallback where appropriate
      7. capture final browser state for Agent Core
    """
    result = run_browser_tool(
        tool_name,
        argument,
    )

    success, verified = _browser_result_status(result)

    if success and verified:
        return result

    observed_before = _observe_browser_state()

    payload = _parse_browser_argument(argument)

    # A successful action with failed verification may already have changed
    # the page. Re-observe that state, but do not blindly click again.
    if success and not verified:
        return _augment_browser_recovery_result(
            result,
            observed_before=observed_before,
            observed_after=observed_before,
            recovered_by="state_observation",
        )

    retryable = False
    if isinstance(result, ToolResult):
        retryable = bool(result.retryable)
    elif isinstance(result, dict):
        retryable = bool(result.get("retryable", False))

    # Give dynamic pages a chance to finish rendering before retrying.
    if retryable and tool_name in {
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_extract_text",
    }:
        _browser_recovery_wait(argument)

    if retryable:
        time.sleep(0.20)

        retry_result = run_browser_tool(
            tool_name,
            argument,
        )

        retry_success, retry_verified = _browser_result_status(
            retry_result
        )

        if retry_success and retry_verified:
            return _augment_browser_recovery_result(
                retry_result,
                observed_before=observed_before,
                observed_after=_observe_browser_state(),
                recovered_by="reobserve_retry",
            )

        result = retry_result

    # Try a single alternate strategy only after re-observing the page.
    alternate_tool, alternate_argument = _browser_alternate_strategy(
        tool_name,
        argument,
        observed_before,
    )

    if alternate_tool:
        alternate_result = run_browser_tool(
            alternate_tool,
            alternate_argument,
        )

        alternate_success, alternate_verified = _browser_result_status(
            alternate_result
        )

        if alternate_tool == "browser_find_element":
            if alternate_success and alternate_verified:
                # The target exists and is visible. Retry the original action
                # now that we know the DOM has settled.
                retry_after_find = run_browser_tool(
                    tool_name,
                    argument,
                )
                final_success, final_verified = _browser_result_status(
                    retry_after_find
                )

                if final_success and final_verified:
                    return _augment_browser_recovery_result(
                        retry_after_find,
                        observed_before=observed_before,
                        observed_after=_observe_browser_state(),
                        recovered_by="dom_reobserve",
                    )

                result = retry_after_find
            else:
                result = alternate_result
        elif alternate_success and alternate_verified:
            return _augment_browser_recovery_result(
                alternate_result,
                observed_before=observed_before,
                observed_after=_observe_browser_state(),
                recovered_by=alternate_tool,
            )
        else:
            result = alternate_result

    success, verified = _browser_result_status(result)

    if success and verified:
        return result

    # Existing desktop-vision fallback remains the last browser-click resort.
    if tool_name in {"browser_click_element", "browser_click_result", "browser_click_first_result"}:
        if tool_name == "browser_click_element":
            target = (
                str(payload.get("text") or "").strip()
                or str(payload.get("role") or "").strip()
                or str(payload.get("selector") or "").strip()
            )
        else:
            if tool_name == "browser_click_result":
                index = payload.get("index", 1)
                try:
                    is_last = (
                        str(index).strip().lower() in {"last", "final"}
                        or int(index) < 0
                    )
                except Exception:
                    is_last = False
                ordinal = "last" if is_last else str(index)
            else:
                ordinal = "1"
            target = f"{ordinal} search result"

            site = str(
                payload.get("site")
                or observed_before.get("site")
                or ""
            ).strip()

            if site:
                target += f" on {site}"

        if target:
            try:
                from screen_vision import click_screen_target

                fallback = click_screen_target(target)

                if isinstance(fallback, dict) and fallback.get("success"):
                    after_fallback = _observe_browser_state()

                    return ToolResult(
                        success=True,
                        tool=tool_name,
                        data={
                            **fallback,
                            "original_browser_failure": str(
                                getattr(result, "error", "")
                                or (
                                    result.get("error", "")
                                    if isinstance(result, dict)
                                    else ""
                                )
                            ),
                            "recovered_by": "desktop_vision",
                            "observed_before": observed_before,
                            "observed_after": after_fallback,
                        },
                        observation=fallback,
                    )
            except Exception as fallback_error:
                logger.debug(
                    "JARVIS: Desktop fallback unavailable: %s",
                    fallback_error,
                )

    return _augment_browser_recovery_result(
        result,
        observed_before=observed_before,
        observed_after=_observe_browser_state(),
    )


# ============================================================
# EXECUTION TRACE
# ============================================================

LAST_EXECUTION_TRACE = []


def get_last_execution_trace():
    """
    Return the structured trace from the most recent execution.
    """
    return list(LAST_EXECUTION_TRACE)


# ============================================================
# PERFORMANCE SETTINGS
# ============================================================

# Only these actions are candidates for screen-change checks.
SCREEN_ACTION_TOOLS = {
    "click_screen",
    "double_click_screen",
    "right_click_screen",
}

# Verification is intentionally short.
#
# Single-step clicks do NOT wait for verification.
# Multi-step tasks get a quick confirmation.
SCREEN_VERIFY_TIMEOUT = 0.75
SCREEN_VERIFY_INTERVAL = 0.20


# ============================================================
# CONTEXT UPDATE
# ============================================================

def _update_browser_active_context(
    tool_name: str,
    result: Any,
    active_context: ActiveContext,
    argument: str = "",
) -> None:
    """Copy useful browser observations into ActiveContext."""
    raw = _unwrap_result_data(result)
    if not isinstance(raw, dict):
        return

    if tool_name in BROWSER_TOOLS:
        active_context.last_tool = tool_name
        active_context.last_action = tool_name

    if raw.get("url"):
        active_context.page_url = str(raw.get("url"))
    if raw.get("after_url"):
        active_context.page_url = str(raw.get("after_url"))
    if raw.get("title"):
        active_context.page_title = str(raw.get("title"))
    if raw.get("after_title"):
        active_context.page_title = str(raw.get("after_title"))
    if raw.get("result_title"):
        active_context.last_result_title = str(raw.get("result_title"))
    if raw.get("result_url"):
        active_context.last_result_url = str(raw.get("result_url"))

    page_url = str(
        raw.get("after_url")
        or raw.get("url")
        or active_context.page_url
        or ""
    )
    lowered_url = page_url.lower()

    if raw.get("site"):
        active_context.site = str(raw.get("site")).strip().lower()
    elif "youtube.com" in lowered_url:
        active_context.site = "youtube"
    elif "google." in lowered_url:
        active_context.site = "google"
    elif "bing.com" in lowered_url:
        active_context.site = "bing"

    if raw.get("query"):
        active_context.last_query = str(raw.get("query"))

    # Browser-native searches return page metadata but do not echo the
    # search query in their controller payload. Preserve the exact query
    # from the executed tool argument so later commands can resolve
    # "click the second result", "click that", etc. without model planning.
    if tool_name in {
        "browser_search_google",
        "browser_search_bing",
    }:
        search_query = str(argument or "").strip()
        if search_query:
            active_context.last_query = search_query
            active_context.site = (
                "google"
                if tool_name == "browser_search_google"
                else "bing"
            )

    try:
        from urllib.parse import parse_qs, urlparse
        parsed_query = parse_qs(urlparse(page_url).query)
        if active_context.site == "google" and parsed_query.get("q"):
            active_context.last_query = parsed_query["q"][0]
        elif active_context.site == "youtube" and parsed_query.get("search_query"):
            active_context.last_query = parsed_query["search_query"][0]
    except Exception:
        pass

    if raw.get("element_text"):
        active_context.last_element = str(raw.get("element_text"))
    elif raw.get("text") and tool_name == "browser_extract_text":
        active_context.last_element = str(raw.get("text"))[:500]


def update_active_context(
    plan: Dict[str, Any],
    active_context: ActiveContext,
    result_message: str = "",
) -> None:
    """
    Update active context from executed tool steps.
    """

    steps = plan.get(
        "steps",
        [],
    )

    if not isinstance(
        steps,
        list,
    ):
        return

    for step in steps:

        if not isinstance(
            step,
            dict,
        ):
            continue

        tool_name = str(
            step.get(
                "tool",
                "",
            )
            or ""
        ).strip()

        argument = str(
            step.get(
                "argument",
                "",
            )
            or ""
        )

        # ----------------------------------------------------
        # Website search
        # ----------------------------------------------------

        if tool_name in {
            "browser_page_info",
            "browser_connect",
            "browser_goto",
            "browser_search_google",
            "browser_search_bing",
            "browser_click_first_bing_result",
            "browser_click_first_result",
            "browser_click_result",
            "browser_back",
            "browser_click_element",
            "browser_fill_element",
            "browser_press_key",
            "browser_wait_for_element",
            "browser_extract_text",
        }:
            active_context.last_tool = tool_name
            active_context.last_action = tool_name
            if result_message:
                active_context.last_result = str(result_message)

            raw = result_message if isinstance(result_message, dict) else None

        if tool_name == "search_website":

            parts = argument.split(
                "|",
                1,
            )

            if len(parts) == 2:

                active_context.site = (
                    parts[0]
                    .strip()
                    .lower()
                )

                active_context.last_query = (
                    parts[1]
                    .strip()
                )

            active_context.last_tool = (
                tool_name
            )

            if result_message:

                active_context.last_result = (
                    str(result_message)
                )

            continue

        # ----------------------------------------------------
        # General tool context
        # ----------------------------------------------------

        if tool_name in {
            "open_website",
            "open_program",
            "click_screen",
            "double_click_screen",
            "right_click_screen",
            "move_mouse",
            "scroll_screen",
            "type_text",
            "press_key",
            "analyze_screen",
            "capture_screen",
            "weather",
            "current_time",
            "current_date",
            "system_status",
            "jarvis_status",
            "browser_connect",
            "browser_search_google",
            "browser_search_bing",
            "browser_click_first_bing_result",
            "browser_goto",
            "browser_page_info",
            "browser_click_first_result",
            "code_search",
            "code_test",
            "code_checkpoint",
            "code_restore_checkpoint",
        }:

            active_context.last_tool = (
                tool_name
            )

            if result_message:

                active_context.last_result = (
                    str(result_message)
                )


# ============================================================
# FAST SCREEN VERIFICATION
# ============================================================

def quick_screen_verify() -> bool:
    """
    Perform a very short screen-change check.

    This is intentionally much faster than the previous
    multi-second verification path.
    """

    try:

        from screen_vision import wait_for_change

        return bool(
            wait_for_change(
                timeout=SCREEN_VERIFY_TIMEOUT,
                interval=SCREEN_VERIFY_INTERVAL,
            )
        )

    except Exception as e:

        logger.debug(
            f"JARVIS: Quick screen verification unavailable: {e}"
        )

        return True


# ============================================================
# VERIFY ACTION WHEN NECESSARY
# ============================================================

def verify_action_for_task(
    tool_name: str,
    result: Any,
    multi_step: bool,
) -> Any:
    """
    Add lightweight verification to screen actions only
    when they are part of a multi-step task.

    Single-step commands are intentionally not delayed.

    ToolResult is supported while preserving legacy dict
    compatibility.
    """

    # --------------------------------------------------------
    # Non-screen actions require no screen verification.
    # --------------------------------------------------------

    if tool_name not in SCREEN_ACTION_TOOLS:

        return result

    # --------------------------------------------------------
    # Single-step actions should remain fast.
    # --------------------------------------------------------

    if not multi_step:

        return result

    # --------------------------------------------------------
    # Unwrap ToolResult for the existing verification logic.
    # --------------------------------------------------------

    if isinstance(
        result,
        ToolResult,
    ):
        raw_result = result.data

        if not isinstance(
            raw_result,
            dict,
        ):
            return result

        if not result.success:
            return result

        verified_result = dict(
            raw_result
        )

        result_data_is_tool_result = True

    elif isinstance(
        result,
        dict,
    ):
        raw_result = result

        if not result.get(
            "success",
            False,
        ):
            return result

        verified_result = dict(
            raw_result
        )

        result_data_is_tool_result = False

    else:
        return result

    # --------------------------------------------------------
    # Quick screen-change check.
    # --------------------------------------------------------

    changed = quick_screen_verify()

    verified_result["screen_changed"] = (
        changed
    )

    if changed:
        verified_result["verified"] = True
        verified_result["verification_status"] = "verified"
    else:
        verified_result["verified"] = True
        verified_result["verification_status"] = "inconclusive"
        verified_result["verification_note"] = (
            "No immediate visible screen change was detected."
        )

    if result_data_is_tool_result:
        result.data = verified_result
        result.observation = verified_result
        return result

    return verified_result


# ============================================================
# TASK PROGRESS
# ============================================================

def _report_tool_progress(
    task_state: TaskState,
    tool_name: str,
    index: int,
    total: int,
) -> None:
    """Emit milestone updates for meaningful task stages."""
    milestones = {
        "code_checkpoint": (
            "checkpoint",
            "I'm creating a safety checkpoint.",
        ),
        "code_search": (
            "code_discovery",
            "I'm locating the relevant code.",
        ),
        "find_file": (
            "code_discovery",
            "I'm locating the relevant file.",
        ),
        "list_files": (
            "code_discovery",
            "I'm locating the relevant files.",
        ),
        "read_file": (
            "source_inspection",
            "I'm inspecting the relevant source.",
        ),
        "code_diagnose": (
            "diagnostic",
            "I'm checking what is actually failing.",
        ),
        "edit_file": (
            "modification",
            "I'm applying the change.",
        ),
        "write_file": (
            "modification",
            "I'm updating the code.",
        ),
        "delete_file": (
            "modification",
            "I'm removing the requested code.",
        ),
        "code_test": (
            "validation",
            "I'm validating the result.",
        ),
        "browser_connect": (
            "browser_connect",
            "I'm connecting to the browser.",
        ),
        "browser_search_google": (
            "browser_search",
            "I'm searching the browser.",
        ),
        "browser_search_bing": (
            "browser_search",
            "I'm searching the browser.",
        ),
        "browser_goto": (
            "browser_navigation",
            "I'm navigating to the page.",
        ),
        "browser_click_first_result": (
            "browser_interaction",
            "I'm interacting with the page.",
        ),
        "browser_click_first_bing_result": (
            "browser_interaction",
            "I'm interacting with the page.",
        ),
        "browser_click_result": (
            "browser_interaction",
            "I'm interacting with the page.",
        ),
        "browser_click_element": (
            "browser_interaction",
            "I'm interacting with the page.",
        ),
        "browser_fill_element": (
            "browser_interaction",
            "I'm filling in the page.",
        ),
        "browser_press_key": (
            "browser_interaction",
            "I'm entering the requested input.",
        ),
        "browser_extract_text": (
            "browser_read",
            "I'm reading the page.",
        ),
        "open_website": (
            "website_open",
            "I'm opening the website.",
        ),
        "open_program": (
            "program_open",
            "I'm opening the application.",
        ),
    }

    milestone = milestones.get(tool_name)
    if milestone is None:
        return

    key, message = milestone
    task_state.report_progress(
        message,
        key=key,
    )

# ============================================================
# TOOL RESULT NORMALIZATION
# ============================================================


def format_browser_result(
    tool_name: str,
    result: Any,
) -> str:
    """
    Convert structured browser results into useful JARVIS logs.

    This does not alter the underlying result. It only produces
    a human-readable execution message.
    """

    if isinstance(result, ToolResult):
        if isinstance(result.data, dict):
            result = result.data
        else:
            return str(result)

    if not isinstance(result, dict):
        return str(result)

    success = result.get(
        "success",
        True,
    )

    if not success:

        message = result.get(
            "message",
            result.get(
                "error",
                "Browser action failed.",
            ),
        )

        return (
            f"Browser action failed: "
            f"{message}"
        )

    if tool_name == "browser_search_bing":

        url = result.get(
            "url",
            "",
        )

        title = result.get(
            "title",
            "",
        )

        query = result.get(
            "query",
            "",
        )

        parts = [
            "Bing search loaded."
        ]

        if query:
            parts.append(
                f"Query: {query}"
            )

        if title:
            parts.append(
                f"Title: {title}"
            )

        if url:
            parts.append(
                f"URL: {url}"
            )

        return " ".join(parts)

    if tool_name == "browser_search_google":

        url = result.get(
            "url",
            "",
        )

        title = result.get(
            "title",
            "",
        )

        return "Google search complete."

    if tool_name == "browser_click_first_bing_result":

        result_title = result.get(
            "result_title",
            "",
        )

        result_url = result.get(
            "result_url",
            "",
        )

        after_url = result.get(
            "after_url",
            "",
        )

        navigated = result.get(
            "navigated",
            False,
        )

        opened_new_page = result.get(
            "opened_new_page",
            False,
        )

        parts = []

        if navigated:
            parts.append(
                "Bing first-result click succeeded."
            )
        else:
            parts.append(
                "Bing first-result action completed."
            )

        if result_title:
            parts.append(
                f"Result: {result_title}"
            )

        if result_url:
            parts.append(
                f"Result URL: {result_url}"
            )

        if after_url:
            parts.append(
                f"Current URL: {after_url}"
            )

        if opened_new_page:
            parts.append(
                "Opened in a new page."
            )

        return " ".join(parts)

    if tool_name == "browser_goto":

        url = result.get(
            "url",
            "",
        )

        title = result.get(
            "title",
            "",
        )

        parts = [
            "Browser navigation succeeded."
        ]

        if title:
            parts.append(
                f"Title: {title}"
            )

        if url:
            parts.append(
                f"URL: {url}"
            )

        return " ".join(parts)

    if tool_name == "browser_page_info":

        url = result.get(
            "url",
            "",
        )

        title = result.get(
            "title",
            "",
        )

        parts = [
            "Browser page inspected."
        ]

        if title:
            parts.append(
                f"Title: {title}"
            )

        if url:
            parts.append(
                f"URL: {url}"
            )

        return " ".join(parts)

    if tool_name == "browser_find_element":
        found = bool(result.get("found"))
        visible = bool(result.get("visible"))
        element_text = str(result.get("element_text", "")).strip()
        if found and visible:
            return (
                "Browser element found"
                + (f": {element_text}" if element_text else ".")
            )
        if found:
            return "Browser element exists but is not visible."
        return "The requested browser element was not found."

    if tool_name == "browser_click_element":
        if result.get("navigated"):
            return (
                "Browser element clicked and navigation succeeded"
                + (
                    f" to {result.get('after_title')}."
                    if result.get("after_title")
                    else "."
                )
            )
        return "Browser element clicked successfully."

    if tool_name == "browser_fill_element":
        return (
            "Browser input filled successfully."
            if result.get("verified", True)
            else "Browser input was filled, but its value could not be verified."
        )

    if tool_name == "browser_press_key":
        return (
            f"Pressed {result.get('key', 'the key')} in the browser."
        )

    if tool_name == "browser_wait_for_element":
        return "The browser element is visible."

    if tool_name == "browser_extract_text":
        extracted = str(result.get("text", "") or "").strip()
        if extracted:
            return extracted

        diagnostics = result.get("diagnostics")
        if isinstance(diagnostics, dict):
            body_len = diagnostics.get("body_text_length")
            document_len = diagnostics.get("document_text_length")
            html_len = diagnostics.get("html_length")
            return (
                "The browser page contained no extractable text. "
                f"DOM body text={body_len}, document text={document_len}, "
                f"HTML={html_len} characters."
            )

        return "The browser page contained no extractable text."

    if tool_name == "browser_click_result":
        index = result.get("index", 1)
        title = str(result.get("result_title", "")).strip()
        title = " ".join(title.split())
        if title:
            return f"Opened result {index}: {title}."
        return f"Opened result {index}."

    if tool_name == "browser_back":
        title = str(result.get("after_title", "")).strip()
        return f"Returned to {title}." if title else "Went back in the browser."

    if tool_name == "browser_connect":

        url = result.get(
            "url",
            "",
        )

        title = result.get(
            "title",
            "",
        )

        parts = [
            "Browser connection succeeded."
        ]

        if title:
            parts.append(
                f"Title: {title}"
            )

        if url:
            parts.append(
                f"URL: {url}"
            )

        return " ".join(parts)

    message = result.get(
        "message",
        "Browser action completed.",
    )

    return str(message)



def normalize_tool_result(
    result: Any,
) -> tuple[bool, bool, str]:
    """
    Convert different tool result formats into:

        success
        verified
        message

    ToolResult is the preferred format. Legacy dict results
    remain supported for backwards compatibility.
    """

    if isinstance(
        result,
        ToolResult,
    ):
        data = result.data

        if isinstance(
            data,
            dict,
        ):
            verified = bool(
                data.get(
                    "verified",
                    result.success,
                )
            )

            message = str(
                data.get(
                    "message",
                    result.error
                    or data.get(
                        "error",
                        "Tool completed.",
                    ),
                )
            )

            return (
                result.success,
                verified,
                message,
            )

        return (
            result.success,
            result.success,
            str(
                result.error
                or data
                or "Tool completed."
            ),
        )

    if isinstance(
        result,
        dict,
    ):
        success = bool(
            result.get(
                "success",
                True,
            )
        )

        verified = bool(
            result.get(
                "verified",
                True,
            )
        )

        message = str(
            result.get(
                "message",
                result.get(
                    "error",
                    "Tool completed.",
                ),
            )
        )

        return (
            success,
            verified,
            message,
        )

    text = str(result or "").strip()

    code_test_errors = (
        "Code test refused:",
        "Code test target not found:",
        "Compile mode requires",
        "Unsupported code test mode.",
        "Code test timed out",
        "Code test failed to start:",
        "Code validation failed.",
    )

    if text.startswith(code_test_errors):
        return (
            False,
            False,
            text,
        )

    return (
        True,
        True,
        text,
    )


# ============================================================
# ADD ASSISTANT MESSAGE
# ============================================================

def add_assistant_message(
    message: str,
) -> None:
    """
    Add a message to conversation history safely.
    """

    try:

        from conversation import add_message

        add_message(
            "assistant",
            message,
        )

    except Exception as e:

        logger.debug(
            f"JARVIS: Conversation history update skipped: {e}"
        )


# ============================================================
# SPEAK RESULT
# ============================================================


def browser_spoken_message(
    tool_name: str,
    result: Any,
) -> str:
    """
    Produce a concise spoken response for browser actions.

    Detailed URLs, titles, navigation metadata, and diagnostic
    information remain in the logs/results, but TTS should stay
    natural and fast.
    """

    if not isinstance(result, dict):
        return str(result)

    if not result.get(
        "success",
        True,
    ):
        return str(
            result.get(
                "message",
                "The browser action failed.",
            )
        )

    if tool_name == "browser_search_bing":

        query = str(
            result.get(
                "query",
                "",
            )
        ).strip()

        if query:
            return (
                f"I searched Bing for {query}."
            )

        return "I completed the Bing search."

    if tool_name == "browser_search_google":

        return "I completed the Google search."

    if tool_name == "browser_click_first_bing_result":

        result_title = str(
            result.get(
                "result_title",
                "",
            )
        ).strip()

        if result_title:
            return (
                f"Opened {result_title}."
            )

        return "I opened the first Bing result."

    if tool_name == "browser_goto":

        title = str(
            result.get(
                "title",
                "",
            )
        ).strip()

        if title:
            return (
                f"Opened {title}."
            )

        return "Navigation completed."

    if tool_name == "browser_page_info":

        title = str(
            result.get(
                "title",
                "",
            )
        ).strip()

        if title:
            return (
                f"The current page is {title}."
            )

        return "I inspected the current browser page."

    if tool_name == "browser_click_first_result":

        result_title = str(
            result.get(
                "result_title",
                "",
            )
        ).strip()

        site = str(
            result.get(
                "site",
                "",
            )
        ).strip().lower()

        if result.get("success") and result_title:
            if site == "youtube":
                return f"Opened {result_title}."
            return f"Opened {result_title}."

        if result.get("success"):
            return "I opened the first browser result."

        return "I couldn't open the first browser result."

    if tool_name == "browser_connect":

        return "The browser is connected."

    return str(
        result.get(
            "message",
            "Browser action completed.",
        )
    )



def _spoken_execution_summary(
    tool_name: str,
    message: str,
) -> str:
    """
    Convert internal tool results into concise, natural JARVIS speech.

    Detailed execution messages remain in logs/evidence; TTS should describe
    the outcome rather than narrate the implementation or repeat URLs.
    """
    text = str(message or "").strip()
    tool = str(tool_name or "").strip().lower()
    lowered = text.lower()

    # Source/code inspection should stay intentionally brief.
    concise = {
        "read_file": "I inspected the relevant source file.",
        "code_search": "I searched the project code for relevant matches.",
        "find_file": "I located the relevant project file.",
        "list_files": "I inspected the project file list.",
        "code_checkpoint": "I created a safety checkpoint.",
        "code_restore_checkpoint": "I restored the latest safety checkpoint.",
        "create_folder": "The folder is ready.",
        "open_folder": "The folder is open.",
        "write_file": "The file is written.",
        "edit_file": "The file is updated.",
        "delete_file": "The file is deleted.",
        "open_program": "The application is open.",
        "click_screen": "I clicked the target.",
        "double_click_screen": "I double-clicked the target.",
        "right_click_screen": "I right-clicked the target.",
        "move_mouse": "I moved to the target.",
        "scroll_screen": "I scrolled the screen.",
        "capture_screen": "I captured the screen.",
        "browser_connect": "The browser is connected.",
        "browser_search_google": "Google search complete.",
        "browser_search_bing": "Bing search complete.",
        "browser_click_first_result": "I opened the first result.",
        "browser_click_first_bing_result": "I opened the first Bing result.",
        "browser_back": "I went back in the browser.",
        "barehands_state": "The JARVIS display state is updated.",
        "barehands_present": "I put that on the JARVIS display.",
        "barehands_add_card": "I added that to the JARVIS display.",
        "barehands_add_image": "I added the image to the JARVIS display.",
        "barehands_clear": "The JARVIS display is clear.",
    }

    if tool in concise:
        return concise[tool]

    if tool == "search_website":
        if "google" in lowered:
            return "Google search complete."
        if "youtube" in lowered:
            return "YouTube search complete."
        if "bing" in lowered:
            return "Bing search complete."
        return "Search complete."

    if tool in {"open_website", "browser_goto"}:
        return "The website is open." if tool == "open_website" else "Navigation complete."

    if tool in {
        "browser_find_element",
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_wait_for_element",
        "browser_extract_text",
        "browser_click_result",
    }:
        return text or "Browser action complete."

    if tool == "weather":
        return text or "The weather information is ready."

    if tool == "current_time":
        return text or "The current time is ready."

    if tool == "current_date":
        return text or "Today's date is ready."

    if tool == "system_status":
        return text or "System status is ready."

    if tool == "startup_status":
        return text or "Startup status is ready."

    if tool in {"enable_startup", "disable_startup"}:
        return text or "Windows startup settings are updated."

    if tool == "task_history":
        return text or "Task history is ready."

    if tool == "dev_command":
        return text or "Developer command complete."

    if tool in {"code_test", "code_diagnose", "verify_screen"}:
        return text or (
            "Project diagnostics complete."
            if tool == "code_diagnose"
            else "Validation complete."
        )

    if tool == "wait":
        return "Done."

    if tool in {"type_text", "press_key"}:
        return "Done."

    if text in {"Tool completed.", "Browser action completed."}:
        return "Done."

    # Avoid narrating raw search-result or URL metadata when a generic
    # completion is enough. Preserve other genuinely useful responses.
    if lowered.startswith("searching google for "):
        return "Google search complete."
    if lowered.startswith("searching youtube for "):
        return "YouTube search complete."
    if lowered.startswith("searching bing for "):
        return "Bing search complete."

    return text or "Done."


def speak_result(
    message: str,
    speak_callback,
) -> str:
    """
    Speak a tool result and handle interruption.
    """

    interrupted = speak_callback(
        message
    )

    if interrupted:

        return "interrupted"

    return "done"


# ============================================================
# EXECUTE PLAN
# ============================================================

def execute_plan(
    plan: Dict[str, Any],
    active_context: ActiveContext,
    task_state: TaskState,
    speak_callback,
) -> str:
    """
    Execute a plan of tool calls.

    Optimizations:
    - No screen verification for ordinary single-step clicks.
    - Short verification only for multi-step screen actions.
    - File operations retain recovery/retry support.
    - Tool results are handled without unnecessary work.
    """

    if not isinstance(
        plan,
        dict,
    ):

        return "done"

    steps = plan.get(
        "steps",
        [],
    )

    if not isinstance(
        steps,
        list,
    ):

        return "done"

    # --------------------------------------------------------
    # Filter invalid steps
    # --------------------------------------------------------

    executable_steps = [
        step
        for step in steps
        if isinstance(
            step,
            dict,
        )
        and step.get(
            "tool",
            "",
        ) not in {
            "",
            "none",
            None,
        }
    ]

    if not executable_steps:

        return "done"

    multi_step = (
        len(executable_steps) > 1
    )

    planning_input = str(
        plan.get(
            "resolved_command",
            plan.get(
                "goal",
                "",
            ),
        )
        or ""
    )

    internal_phase = bool(
        plan.get("jarvis_internal_phase")
    )

    # Directly constructed plans may not contain a task-level
    # resolved_command or goal. Use the first executable step's
    # description as a safe fallback for task state.
    if not planning_input:
        planning_input = str(
            executable_steps[0].get(
                "description",
                "",
            )
            or ""
        )

    # --------------------------------------------------------
    # Reset execution trace
    # --------------------------------------------------------

    global LAST_EXECUTION_TRACE

    LAST_EXECUTION_TRACE = []

    # --------------------------------------------------------
    # Start task state
    # --------------------------------------------------------

    started = task_state.start(
        description=planning_input,
        total_steps=len(
            executable_steps
        ),
    )

    if not started:
        logger.info(
            "JARVIS: Task was cancelled before execution started."
        )
        active_context.clear()
        task_state.finish()
        return "cancelled"

    logger.info(
        f"Task started: "
        f"{len(executable_steps)} executable step(s)"
    )

    final_tool_message = ""
    task_completed = False

    # ========================================================
    # EXECUTE STEPS
    # ========================================================

    for index, step in enumerate(
        executable_steps,
        start=1,
    ):

        # ----------------------------------------------------
        # Cancellation before action
        # ----------------------------------------------------

        if task_state.is_cancelled():

            logger.info(
                "JARVIS: Cancellation detected."
            )

            active_context.clear()
            task_state.finish()

            return "cancelled"

        tool_name = str(
            step.get(
                "tool",
                "",
            )
            or ""
        ).strip()

        argument = str(
            step.get(
                "argument",
                "",
            )
            or ""
        )

        if not tool_name:

            continue

        task_state.update_step(
            index,
            tool_name,
        )

        logger.info(
            f"Step {index}/"
            f"{len(executable_steps)}: "
            f"Running {tool_name}"
        )

        _report_tool_progress(
            task_state,
            tool_name,
            index,
            len(executable_steps),
        )

        # ----------------------------------------------------
        # Track the exact step currently being executed.
        # ----------------------------------------------------

        LAST_EXECUTION_TRACE.append(
            {
                "index": index,
                "tool": tool_name,
                "argument": argument,
                "status": "executing",
                "success": None,
                "verified": False,
                "result": None,
                "message": "",
            }
        )

        try:

            # =================================================
            # FILE OPERATIONS
            # =================================================

            if tool_name in {
                "write_file",
                "edit_file",
                "read_file",
                "delete_file",
            }:

                from recovery import retry_with_recovery

                recovery_result = retry_with_recovery(
                    tool_name,
                    argument,
                    run_tool,
                    max_attempts=2,
                )

                # Keep task state synchronized with the actual
                # recovery executor rather than maintaining a
                # separate attempt counter.
                recovery_attempts = 1
                if isinstance(
                    recovery_result,
                    dict,
                ):
                    recovery_attempts = int(
                        recovery_result.get(
                            "attempts",
                            1,
                        )
                        or 1
                    )

                task_state.attempts = recovery_attempts
                task_state.recovery_count = max(
                    recovery_attempts - 1,
                    0,
                )

                if not isinstance(
                    recovery_result,
                    dict,
                ):
                    result = ToolResult(
                        success=False,
                        tool=tool_name,
                        error=(
                            "File operation returned "
                            "an invalid recovery result."
                        ),
                    )

                elif not recovery_result.get(
                    "success",
                    False,
                ):
                    result = ToolResult(
                        success=False,
                        tool=tool_name,
                        error=str(
                            recovery_result.get(
                                "error",
                                "File operation failed.",
                            )
                        ),
                        retryable=False,
                        observation={
                            "attempts": recovery_result.get(
                                "attempts",
                                1,
                            ),
                        },
                    )

                else:
                    recovered_result = recovery_result.get(
                        "result"
                    )

                    if isinstance(
                        recovered_result,
                        ToolResult,
                    ):
                        result = recovered_result

                    else:
                        result = ToolResult(
                            success=True,
                            tool=tool_name,
                            data=recovered_result,
                        )

            # NORMAL TOOL
            # =================================================

            else:

                # Ordinary tools execute once unless they are explicitly
                # marked safe + retryable by their tool implementation.
                task_state.attempts = 1
                task_state.recovery_count = 0

                if tool_name in BROWSER_TOOLS:
                    result = _execute_browser_with_fallback(
                        tool_name,
                        argument,
                    )
                else:
                    result = _execute_with_safe_retry(
                        tool_name,
                        argument,
                        task_state,
                    )

            # =================================================
            # BROWSER RESULT FORMATTING / VERIFICATION
            # =================================================

            if tool_name in BROWSER_TOOLS:

                # Browser controller already performs DOM-level
                # navigation checks. Surface that structured
                # result in the execution log rather than
                # collapsing it into "Tool completed."

                browser_message = format_browser_result(
                    tool_name,
                    result,
                )

                if isinstance(result, ToolResult):
                    data = result.data
                    if isinstance(data, dict):
                        data = dict(data)
                        data["message"] = browser_message
                    else:
                        data = {
                            "message": browser_message,
                            "result": data,
                        }

                    if isinstance(data, dict) and "verified" not in data:
                        data["verified"] = bool(result.success)

                    result = ToolResult(
                        success=result.success,
                        tool=result.tool,
                        data=data,
                        error=result.error,
                        retryable=result.retryable,
                        observation=result.observation,
                    )

                elif isinstance(result, dict):
                    result = dict(result)
                    result["message"] = browser_message
                    result.setdefault(
                        "verified",
                        bool(result.get("success", False)),
                    )

            # =================================================
            # OPTIONAL SCREEN VERIFICATION
            # =================================================

            result = verify_action_for_task(
                tool_name,
                result,
                multi_step,
            )

            # =================================================
            # CANCELLATION AFTER TOOL
            # =================================================

            if task_state.is_cancelled():

                logger.info(
                    "JARVIS: Task cancelled after "
                    "tool execution."
                )

                active_context.clear()
                task_state.finish()

                return "cancelled"

            # =================================================
            # NORMALIZE RESULT
            # =================================================

            success, verified, message = (
                normalize_tool_result(
                    result
                )
            )

            # ------------------------------------------------
            # Update the trace entry for this exact step.
            # ------------------------------------------------

            if LAST_EXECUTION_TRACE:

                trace_entry = LAST_EXECUTION_TRACE[-1]

                trace_entry["success"] = success
                trace_entry["verified"] = verified
                trace_entry["result"] = result
                trace_entry["message"] = message
                trace_entry["attempts"] = max(
                    1,
                    int(task_state.attempts or 1),
                )
                trace_entry["recovery_count"] = max(
                    0,
                    int(task_state.recovery_count or 0),
                )

                if success and verified:
                    trace_entry["status"] = "completed"
                else:
                    trace_entry["status"] = "failed"

            logger.info(
                f"JARVIS: {message}"
            )

            # ------------------------------------------------
            # Record the normalized result in task state.
            # ------------------------------------------------

            if tool_name in BROWSER_TOOLS:
                _update_browser_active_context(
                    tool_name,
                    result,
                    active_context,
                    argument,
                )

            if success and verified:
                task_state.record_result(result)
            else:
                task_state.record_error(message)

            # =================================================
            # FAILURE
            # =================================================

            if not success or not verified:

                if tool_name in BROWSER_TOOLS:

                    logger.error(
                        f"JARVIS: Browser verification failed "
                        f"for {tool_name}: {message}"
                    )

                    if isinstance(result, ToolResult):
                        browser_data = result.data

                        if isinstance(browser_data, dict):

                            if browser_data.get("click_error"):
                                logger.error(
                                    "JARVIS: Browser click error: "
                                    f"{browser_data.get('click_error')}"
                                )

                            if browser_data.get("before_url"):
                                logger.error(
                                    "JARVIS: Browser URL before action: "
                                    f"{browser_data.get('before_url')}"
                                )

                            if browser_data.get("after_url"):
                                logger.error(
                                    "JARVIS: Browser URL after action: "
                                    f"{browser_data.get('after_url')}"
                                )

                    elif isinstance(
                        result,
                        dict,
                    ):

                        if result.get("click_error"):
                            logger.error(
                                "JARVIS: Browser click error: "
                                f"{result.get('click_error')}"
                            )

                        if result.get("before_url"):
                            logger.error(
                                "JARVIS: Browser URL before action: "
                                f"{result.get('before_url')}"
                            )

                        if result.get("after_url"):
                            logger.error(
                                "JARVIS: Browser URL after action: "
                                f"{result.get('after_url')}"
                            )

                if tool_name in BROWSER_TOOLS:
                    # Preserve browser state so Agent Core can replan from the
                    # page that actually remains open after a failed action.
                    active_context.last_tool = tool_name
                    active_context.last_result = str(message)
                    active_context.last_action = f"failed:{tool_name}"
                    try:
                        from browser_controller import browser_page_info
                        page_info = browser_page_info()
                        if isinstance(page_info, dict) and page_info.get("success"):
                            active_context.page_url = page_info.get("url")
                            active_context.page_title = page_info.get("title")
                    except Exception:
                        pass
                else:
                    active_context.clear()

                task_state.fail(message)

                # Do not speak intermediate failures here. Agent Core owns
                # recovery/replanning and should only report the final outcome.
                return 'failed'

            # =================================================
            # SUCCESS
            # =================================================

            final_tool_message = message

            update_active_context(
                plan={
                    "steps": [
                        step,
                    ],
                },
                active_context=active_context,
                result_message=message,
            )

            # -------------------------------------------------
            # Single-step task
            #
            # FAST PATH:
            # No verification delay.
            # -------------------------------------------------

            if not multi_step:

                # Internal Agent Core phases are orchestration steps, not
                # user-facing milestones. Keep their evidence in execution
                # state and let the final task result speak for itself.
                if internal_phase:
                    task_state.finish()
                    return "done"

                # Inspection tools can return large source/results. Keep
                # those details in execution state, not in TTS or chat history.
                spoken_message = _spoken_execution_summary(
                    tool_name,
                    message,
                )

                add_assistant_message(
                    spoken_message
                )

                task_state.finish()

                speak_status = speak_result(
                    spoken_message,
                    speak_callback,
                )

                if (
                    speak_status == "done"
                    and hasattr(task_state, "mark_completion_spoken")
                ):
                    task_state.mark_completion_spoken()

                return speak_status

            # -------------------------------------------------
            # Multi-step task continues.
            # -------------------------------------------------

            task_completed = True

        except Exception as e:

            # Unexpected tool exceptions are execution evidence, not a final
            # user-facing response. Agent Core owns recovery/replanning and
            # should decide whether another approach is appropriate.
            error_detail = str(e).strip() or "Unknown tool exception."
            error_message = (
                f"{tool_name} failed with an unexpected error: "
                f"{error_detail}"
            )

            logger.error(
                f"JARVIS: Tool error ({tool_name}): {error_detail}"
            )

            exception_result = ToolResult(
                success=False,
                tool=tool_name,
                error=error_message,
                retryable=True,
                observation={
                    "failure_type": "exception",
                    "exception": error_detail,
                },
            )

            # Keep the exact failure in the execution trace so Agent Core can
            # replan from concrete evidence instead of a generic "failed".
            if LAST_EXECUTION_TRACE:
                trace_entry = LAST_EXECUTION_TRACE[-1]
                trace_entry["success"] = False
                trace_entry["verified"] = False
                trace_entry["result"] = exception_result
                trace_entry["message"] = error_message
                trace_entry["status"] = "failed"
                trace_entry["failure_type"] = "exception"
                trace_entry["attempts"] = max(
                    1,
                    int(task_state.attempts or 1),
                )
                trace_entry["recovery_count"] = max(
                    0,
                    int(task_state.recovery_count or 0),
                )

            if tool_name in BROWSER_TOOLS:
                # Preserve browser state for replanning. The failed action may
                # have changed the page before the exception was raised.
                active_context.last_tool = tool_name
                active_context.last_result = error_message
                active_context.last_action = f"failed:{tool_name}"

                try:
                    from browser_controller import browser_page_info

                    page_info = browser_page_info()

                    if (
                        isinstance(page_info, dict)
                        and page_info.get("success")
                    ):
                        active_context.page_url = page_info.get("url")
                        active_context.page_title = page_info.get("title")
                except Exception:
                    pass
            else:
                active_context.clear()

            task_state.record_error(error_message)
            task_state.fail(error_message)

            # Do not speak here. A replan may recover the task, and Agent Core
            # is responsible for the final user-facing outcome.
            return "failed"

    # ========================================================
    # MULTI-STEP COMPLETION
    # ========================================================

    if (
        task_completed
        and multi_step
        and final_tool_message
    ):

        update_active_context(
            plan=plan,
            active_context=active_context,
            result_message=final_tool_message,
        )

        final_tool = executable_steps[-1]

        final_tool_name = str(
            final_tool.get(
                "tool",
                "",
            )
            or ""
        ).strip()

        # Keep raw inspection output in execution state only.
        add_assistant_message(
            _spoken_execution_summary(
                final_tool_name,
                final_tool_message,
            )
        )

        task_state.finish()

        # ----------------------------------------------------
        # Browser actions use concise spoken summaries.
        # Detailed browser metadata remains available in logs.
        # ----------------------------------------------------

        spoken_message = _spoken_execution_summary(
            final_tool_name,
            final_tool_message,
        )

        if executable_steps:

            if final_tool_name in BROWSER_TOOLS:

                try:
                    browser_result = {
                        "success": True,
                        "message": final_tool_message,
                    }

                    # Recover structured fields from the final
                    # execution when available.
                    #
                    # The detailed result is already logged.
                    # For speech, use the concise formatter.
                    #
                    # At this point final_tool_message is the
                    # formatted diagnostic message, so construct
                    # the natural response directly from it.

                    if (
                        final_tool_name
                        == "browser_click_first_bing_result"
                    ):

                        marker = "Result: "

                        if marker in final_tool_message:

                            spoken_title = (
                                final_tool_message
                                .split(
                                    marker,
                                    1
                                )[1]
                                .split(
                                    " Result URL:",
                                    1
                                )[0]
                                .strip()
                            )

                            if spoken_title:
                                spoken_message = (
                                    f"Opened {spoken_title}."
                                )
                            else:
                                spoken_message = (
                                    "I opened the first Bing result."
                                )

                        else:
                            spoken_message = (
                                "I opened the first Bing result."
                            )

                    elif (
                        final_tool_name
                        == "browser_search_bing"
                    ):

                        marker = "Query: "

                        if marker in final_tool_message:

                            spoken_query = (
                                final_tool_message
                                .split(
                                    marker,
                                    1
                                )[1]
                                .split(
                                    " Title:",
                                    1
                                )[0]
                                .strip()
                            )

                            if spoken_query:
                                spoken_message = (
                                    f"I searched Bing for "
                                    f"{spoken_query}."
                                )
                            else:
                                spoken_message = (
                                    "I completed the Bing search."
                                )

                    elif (
                        final_tool_name
                        == "browser_search_google"
                    ):

                        spoken_message = (
                            "I completed the Google search."
                        )

                    elif (
                        final_tool_name
                        == "browser_goto"
                    ):

                        marker = "Title: "

                        if marker in final_tool_message:

                            spoken_title = (
                                final_tool_message
                                .split(
                                    marker,
                                    1
                                )[1]
                                .split(
                                    " URL:",
                                    1
                                )[0]
                                .strip()
                            )

                            if spoken_title:
                                spoken_message = (
                                    f"Opened {spoken_title}."
                                )
                            else:
                                spoken_message = (
                                    "Navigation completed."
                                )

                except Exception as e:

                    logger.debug(
                        f"JARVIS: Browser speech formatting "
                        f"fallback: {e}"
                    )

        speak_status = speak_result(
            spoken_message,
            speak_callback,
        )

        if (
            speak_status == "done"
            and hasattr(task_state, "mark_completion_spoken")
        ):
            task_state.mark_completion_spoken()

        return speak_status

    # ========================================================
    # FALLBACK COMPLETION
    # ========================================================

    if final_tool_message:

        final_tool_name = ""

        if executable_steps:
            final_tool_name = str(
                executable_steps[-1].get(
                    "tool",
                    "",
                )
                or ""
            ).strip()

        spoken_message = _spoken_execution_summary(
            final_tool_name,
            final_tool_message,
        )

        add_assistant_message(
            spoken_message
        )

        task_state.finish()

        return speak_result(
            spoken_message,
            speak_callback,
        )

    task_state.finish()

    return "done"