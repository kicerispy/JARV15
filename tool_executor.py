"""
JARVIS tool execution engine.

Optimized for low latency while preserving reliable execution
for multi-step computer-control tasks.
"""

import ast
import json
import time
from typing import Any, Dict

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
# BROWSER FALLBACK / CONTEXT
# ============================================================

def _unwrap_result_data(result: Any) -> Any:
    if isinstance(result, ToolResult):
        return result.data
    return result


def _execute_browser_with_fallback(
    tool_name: str,
    argument: str,
) -> Any:
    """Execute a browser action and use desktop vision for click fallback."""
    result = run_browser_tool(tool_name, argument)

    try:
        unsuccessful = isinstance(result, ToolResult) and not result.success

        if unsuccessful and isinstance(result, ToolResult) and result.retryable:
            time.sleep(0.20)
            retry_result = run_browser_tool(tool_name, argument)
            if isinstance(retry_result, ToolResult) and retry_result.success:
                return retry_result
            result = retry_result
            unsuccessful = isinstance(result, ToolResult) and not result.success
        if isinstance(result, dict):
            unsuccessful = not bool(result.get("success", False))

        if not unsuccessful:
            return result

        if tool_name in {"browser_click_element", "browser_click_result"}:
            payload = {}
            raw_argument = str(argument or "{}").strip()
            try:
                payload = json.loads(raw_argument)
            except (json.JSONDecodeError, TypeError):
                try:
                    payload = ast.literal_eval(raw_argument)
                except (ValueError, SyntaxError):
                    payload = {}
            if not isinstance(payload, dict):
                payload = {}

            if tool_name == "browser_click_element":
                target = (
                    str(payload.get("text") or "").strip()
                    or str(payload.get("role") or "").strip()
                    or str(payload.get("selector") or "").strip()
                )
            else:
                index = payload.get("index", 1)
                try:
                    is_last = str(index).strip().lower() in {"last", "final"} or int(index) < 0
                except Exception:
                    is_last = False
                ordinal = "last" if is_last else str(index)
                target = f"{ordinal} search result"
                if payload.get("site"):
                    target += f" on {payload['site']}"

            if target:
                try:
                    from screen_vision import click_screen_target
                    fallback = click_screen_target(target)
                    if isinstance(fallback, dict) and fallback.get("success"):
                        return ToolResult(
                            success=True,
                            tool=tool_name,
                            data={
                                **fallback,
                                "original_browser_failure": (
                                    str(
                                        getattr(result, "error", "")
                                        or (
                                            result.get("error", "")
                                            if isinstance(result, dict)
                                            else ""
                                        )
                                    )
                                ),
                                "recovered_by": "desktop_vision",
                            },
                            observation=fallback,
                        )
                except Exception as fallback_error:
                    logger.debug(
                        "JARVIS: Desktop fallback unavailable: %s",
                        fallback_error,
                    )
    except Exception as exc:
        logger.debug(
            "JARVIS: Browser fallback evaluation failed: %s",
            exc,
        )

    return result


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
    """Emit concise progress updates for significant task stages."""
    messages = {
        "code_search": "I'm locating the relevant code.",
        "read_file": "I've found the relevant file. I'm inspecting it now.",
        "edit_file": "I'm applying the change.",
        "write_file": "I'm writing the updated code.",
        "code_test": "I'm running the validation now.",
        "browser_connect": "I'm connecting to the browser.",
        "browser_find_element": "I'm locating the browser element.",
        "browser_click_element": "I'm interacting with the browser element.",
        "browser_click_first_result": "I'm selecting the result through the browser DOM.",
        "browser_fill_element": "I'm filling the browser input.",
        "browser_wait_for_element": "I'm waiting for the page element.",
        "browser_extract_text": "I'm reading the page content.",
    }

    message = messages.get(tool_name)
    if message:
        prefix = f"Step {index} of {total}. "
        task_state.report_progress(prefix + message)

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
        return extracted or "The browser element contains no readable text."

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

    if tool in {"code_test", "verify_screen"}:
        return text or "Validation complete."

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

                # Ordinary tools execute once and therefore have
                # exactly one attempt with no recovery.
                task_state.attempts = 1
                task_state.recovery_count = 0

                if tool_name in BROWSER_TOOLS:
                    result = _execute_browser_with_fallback(
                        tool_name,
                        argument,
                    )
                else:
                    result = run_tool(
                        tool_name,
                        argument,
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

            logger.error(
                f"JARVIS: Tool error "
                f"({tool_name}): {e}"
            )

            error_message = (
                f"I couldn't complete the "
                f"{tool_name} action."
            )

            active_context.clear()

            add_assistant_message(
                error_message
            )

            logger.info(
                f"JARVIS: {error_message}"
            )

            task_state.record_error(error_message)
            task_state.fail(error_message)

            # -------------------------------------------------
            # IMPORTANT:
            #
            # speak_result() returns "done" when TTS finishes.
            # That does NOT mean the task succeeded.
            #
            # Preserve the execution failure so JarvisAgent
            # can trigger its replan/recovery loop.
            # -------------------------------------------------

            speak_status = speak_result(
                error_message,
                speak_callback,
            )

            if speak_status == "interrupted":
                return "interrupted"

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
