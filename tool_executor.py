"""
JARVIS tool execution engine.

Optimized for low latency while preserving reliable execution
for multi-step computer-control tasks.
"""

from typing import Any, Dict

from logger import logger
from state import ActiveContext, TaskState
from tools import run_tool


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

    if not isinstance(
        result,
        dict,
    ):

        return result

    if not result.get(
        "success",
        False,
    ):

        return result

    # --------------------------------------------------------
    # Quick screen-change check.
    # --------------------------------------------------------

    changed = quick_screen_verify()

    verified_result = dict(
        result
    )

    verified_result["screen_changed"] = (
        changed
    )

    if changed:

        verified_result["verified"] = True

        return verified_result

    # --------------------------------------------------------
    # No visible change.
    #
    # We do not immediately fail here. Some legitimate
    # actions do not cause obvious pixel changes.
    #
    # The tool itself already reported success.
    # --------------------------------------------------------

    verified_result["verified"] = True
    verified_result["verification_note"] = (
        "No immediate visible screen change was detected."
    )

    return verified_result


# ============================================================
# TOOL RESULT NORMALIZATION
# ============================================================

def normalize_tool_result(
    result: Any,
) -> tuple[bool, bool, str]:
    """
    Convert different tool result formats into:

        success
        verified
        message
    """

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
                "Tool completed.",
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

                result = retry_with_recovery(
                    tool_name,
                    argument,
                    run_tool,
                    max_attempts=2,
                )

                if not isinstance(
                    result,
                    dict,
                ):

                    result = {
                        "success": False,
                        "message": (
                            "File operation returned "
                            "an invalid result."
                        ),
                    }

                elif not result.get(
                    "success",
                    False,
                ):

                    result = {
                        "success": False,
                        "message": str(
                            result.get(
                                "error",
                                "File operation failed.",
                            )
                        ),
                    }

                else:

                    result = result.get(
                        "result",
                        result,
                    )

            # =================================================
            # NORMAL TOOL
            # =================================================

            else:

                result = run_tool(
                    tool_name,
                    argument,
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

            logger.info(
                f"JARVIS: {message}"
            )

            # =================================================
            # FAILURE
            # =================================================

            if not success or not verified:

                active_context.clear()

                add_assistant_message(
                    message
                )

                return speak_result(
                    message,
                    speak_callback,
                )

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

            return speak_result(
                error_message,
                speak_callback,
            )

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

        return speak_result(
            final_tool_message,
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