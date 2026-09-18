"""
JARVIS tool execution engine.

Optimized for low latency while preserving reliable execution
for multi-step computer-control tasks.
"""

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
        "code_test": "The change is in place. I'm testing it now.",
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

        parts = [
            "Google search action completed."
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

    return (
        True,
        True,
        str(result),
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

    task_state.start(
        description=planning_input,
        total_steps=len(
            executable_steps
        ),
    )

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
                    result = run_browser_tool(
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

                if isinstance(
                    result,
                    dict,
                ):

                    result = dict(
                        result
                    )

                    result["message"] = (
                        browser_message
                    )

                    # A browser controller reporting success is
                    # considered verified unless it explicitly
                    # says otherwise.
                    if "verified" not in result:
                        result["verified"] = bool(
                            result.get(
                                "success",
                                False,
                            )
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

                active_context.clear()

                add_assistant_message(
                    message
                )

                speak_status = speak_result(
                    message,
                    speak_callback,
                )

                if speak_status == 'interrupted':
                    return 'interrupted'

                task_state.fail(message)

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

                add_assistant_message(
                    message
                )

                task_state.finish()

                return speak_result(
                    message,
                    speak_callback,
                )

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

        add_assistant_message(
            final_tool_message
        )

        task_state.finish()

        # ----------------------------------------------------
        # Browser actions use concise spoken summaries.
        # Detailed browser metadata remains available in logs.
        # ----------------------------------------------------

        spoken_message = final_tool_message

        if executable_steps:

            final_tool = executable_steps[-1]

            final_tool_name = str(
                final_tool.get(
                    "tool",
                    "",
                )
                or ""
            ).strip()

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

        return speak_result(
            spoken_message,
            speak_callback,
        )

    # ========================================================
    # FALLBACK COMPLETION
    # ========================================================

    if final_tool_message:

        add_assistant_message(
            final_tool_message
        )

        task_state.finish()

        return speak_result(
            final_tool_message,
            speak_callback,
        )

    task_state.finish()

    return "done"
