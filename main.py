"""
JARVIS - Main entry point.

Includes lightweight performance timing so we can identify
latency between speech recognition, command routing, planning,
tool execution, and response generation.
"""

import sys
import threading
import time
from typing import Optional

from code_gen import handle_code_generation, is_code_request, is_complex_code_request
from response_pipeline import speak_response
from agent_core import JarvisAgent

from commands import (
    get_fast_command,
    is_cancel_command,
    is_creative_request,
    is_end_conversation_command,
    is_remember_command,
    is_shutdown_command,
    normalize_command,
    should_resolve_context,
    wants_first_result,
)
from config import (
    PROFILE_PATH,
    TYPED_INPUT_ENABLED,
)
from typed_input import TypedInputChannel
from context_aware import JarvisContext
from context_resolver import resolve_followup
from conversation import ConversationHistory
from conversation_handler import (
    handle_normal_conversation,
    run_memory_analysis_background,
)
from logger import logger
from model_manager import ModelManager
from barehands_state import set_barehands_state
from smart_router import route_command
from memory import create_memory
from planner import (
    create_plan,
    is_software_change_request,
    is_software_diagnostic_request,
    is_software_repair_request,
)
from state import JarvisState
from task_controller import (
    BackgroundTaskController,
    is_task_acknowledgement,
    is_task_status_request,
)
from tool_executor import execute_plan


# ============================================================
# AGENT CORE
# ============================================================
jarvis_agent = JarvisAgent()


# ============================================================
# PERFORMANCE TIMING
# ============================================================

class _AnyEvent:
    """Event-like adapter that wakes when any supplied event is set."""

    def __init__(self, *events):
        self._events = tuple(
            event
            for event in events
            if event is not None
        )

    def is_set(self) -> bool:
        return any(
            event.is_set()
            for event in self._events
        )

    def wait(self, timeout=None) -> bool:
        if self.is_set():
            return True

        if timeout is None:
            while not self.is_set():
                time.sleep(0.02)
            return True

        deadline = time.monotonic() + max(float(timeout), 0.0)

        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.02, remaining))

        return True


def perf_now() -> float:
    """
    Return a high-resolution performance timestamp.
    """
    return time.perf_counter()


def log_perf(
    label: str,
    start_time: float,
) -> float:
    """
    Log elapsed time since start_time.

    Returns a fresh timestamp so callers can chain timing.
    """

    elapsed = perf_now() - start_time

    logger.info(
        f"PERF: {label}: {elapsed:.3f}s"
    )

    return perf_now()


def should_run_background_memory_analysis(user_input: str) -> bool:
    """Avoid loading the chat model during active software-engineering work."""
    text = str(user_input or "").strip()

    if not text:
        return False

    if (
        is_software_repair_request(text)
        or is_software_change_request(text)
        or is_software_diagnostic_request(text)
    ):
        return False

    return True


def shutdown_background_tasks(state: JarvisState) -> None:
    """Cancel and drain any active background task before runtime teardown."""
    controller = getattr(state, "task_controller", None)

    if controller is not None and controller.has_active_task():
        controller.cancel_current()
        controller.wait_for_current()
    else:
        state.task_state.finish()


# ============================================================
# PROFILE
# ============================================================

def load_profile():
    """Load user profile from profile.json."""

    try:

        with open(
            PROFILE_PATH,
            "r",
            encoding="utf-8",
        ) as f:

            import json

            profile = json.load(f)

        return profile

    except FileNotFoundError:

        print(
            'JARVIS: profile.json not found. '
            'Create one with at least {"name": "YourName"} '
            'in the project folder and try again.'
        )

        sys.exit(1)

    except (json.JSONDecodeError, KeyError) as e:

        print(
            f"JARVIS: profile.json exists but is invalid ({e}). "
            "Check the file's contents and try again."
        )

        sys.exit(1)


# ============================================================
# SYSTEM PROMPT
# ============================================================

def build_system_prompt(
    user_name: str,
    context: JarvisContext,
    profile: Optional[dict] = None,
) -> str:
    """Build the system prompt for JARVIS."""

    context_str = context.build_context_string()

    if profile is None:
        profile = load_profile()

    persona_traits = (
        profile
        .get("preferences", {})
        .get("persona_traits", {})
    )

    wit = persona_traits.get(
        "wit",
        0.4,
    )

    formality = persona_traits.get(
        "formality",
        0.85,
    )

    technical_depth = persona_traits.get(
        "technical_depth",
        0.7,
    )

    tone_parts: list[str] = []

    if wit > 0.3:

        tone_parts.append(
            "You have a subtle, sophisticated wit. "
            "Your humor is dry and understated."
        )

    if formality > 0.7:

        tone_parts.append(
            "You are formally polite and maintain a composed demeanor. "
            "Use the user's name sparingly, only when it adds warmth or clarity."
        )

    if technical_depth > 0.6:

        tone_parts.append(
            "You are technically precise, favoring accuracy over speculation."
        )

    if not tone_parts:

        tone_parts.append(
            "You are JARVIS â€” composed, efficient, and precise."
        )

    tone_note = " ".join(
        tone_parts
    )

    return f"""
You are JARVIS, a personal AI assistant.

You are calm, precise, intelligent, and efficient.

Keep answers concise unless the user asks for more detail.

Address the user naturally when appropriate. Do not repeat the user's name unnecessarily.

Use saved memories and recent conversation context when relevant.

{tone_note}

You refer to yourself as JARVIS.

You use confident, understated phrasing.

Never pretend to have completed an action unless a tool
actually completed it.

When a tool completes an action, treat that result as
part of the conversation context.

You are not merely a coding assistant.

Programming, computer control, web research, vision,
automation, file management, and other capabilities are
tools that you can use when appropriate.

Remain JARVIS regardless of which capability you are using.

USER & PROJECT CONTEXT:

{context_str}

For wake-word acknowledgement, use brief natural phrases such as:

"Yes?"

"Executing."

"Very well. I am on it."

Do not insert the user's name into routine responses.
"""


# ============================================================
# FAST COMMAND EXECUTION
# ============================================================

def execute_fast_command(
    tool_name: str,
    argument: str,
    user_input: str,
    state: JarvisState,
    speak_callback,
) -> str:
    """
    Execute a deterministic command without using
    the LLM planner or background memory analysis.
    """

    logger.info(
        f"JARVIS: Executing fast command: "
        f"{tool_name}"
        + (
            f" ({argument})"
            if argument
            else ""
        )
    )

    start = perf_now()

    plan = {
        "goal": user_input,
        "resolved_command": user_input,
        "steps": [
            {
                "tool": tool_name,
                "argument": argument,
            }
        ],
    }

    result = execute_plan(
        plan,
        state.active_context,
        state.task_state,
        speak_callback,
    )

    elapsed = perf_now() - start

    logger.info(
        f"PERF: fast command '{tool_name}' "
        f"execution: {elapsed:.3f}s"
    )

    return result


# ============================================================
# PROCESS COMMAND
# ============================================================

def process_command(
    user_input: str,
    state: JarvisState,
    conversation: ConversationHistory,
    system_prompt: str,
    speak_callback,
) -> str:
    """
    Process a single user command.

    Returns:
        "done"
        "cancelled"
        "interrupted"
        "shutdown"
    """

    command_start = perf_now()

    if user_input is None:
        return "done"

    # --------------------------------------------------------
    # Normalize
    # --------------------------------------------------------

    normalize_start = perf_now()

    user_input = normalize_command(
        user_input
    )

    logger.info(
        f"PERF: command normalization: "
        f"{perf_now() - normalize_start:.3f}s"
    )

    if not user_input:
        return "done"

    # Optional Barehands visual lifecycle state.
    set_barehands_state("thinking")

    logger.info(
        f"USER: {user_input}"
    )

    task_controller = getattr(
        state,
        "task_controller",
        None,
    )

    # ========================================================
    # CONTEXTUAL YOUTUBE FOLLOW-UP
    # ========================================================
    #
    # When JARVIS is already working with a YouTube search,
    # short follow-ups such as:
    #
    #   click the first result
    #   open the first video
    #   play the first result
    #   click the first link
    #   choose the top result
    #
    # should reuse the existing YouTube search query instead
    # of being interpreted as a brand-new search for words such
    # as "first result".
    #
    # We reuse the existing ActiveContext rather than creating
    # another memory system.
    # ========================================================

    active_site = (
        state.active_context.site or ""
    ).strip().lower()

    active_query = (
        state.active_context.last_query or ""
    ).strip()

    if (
        active_site == "youtube"
        and
        active_query
        and
        wants_first_result(user_input)
    ):

        original_followup = user_input

        user_input = (
            "click the first organic YouTube result for "
            f"{active_query}"
        )

        logger.info(
            "JARVIS: Resolved YouTube follow-up "
            f"'{original_followup}' -> '{user_input}'"
        )

    logger.info(
        "PERF: command processing started."
    )

    # ==================================================
    # END CONVERSATION
    # ==================================================

    if is_end_conversation_command(
        user_input
    ):

        logger.info(
            "JARVIS: Returning to wake-word mode."
        )

        state.continuous_mode = False
        state.active_context.clear()

        # Do not mark an active background task as complete just
        # because the conversational mode is ending.
        if (
            task_controller is None
            or not task_controller.has_active_task()
        ):
            state.task_state.finish()

        state.pending_input = None

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "done"

    # ==================================================
    # CANCEL
    # ==================================================

    if is_cancel_command(
        user_input
    ):

        background_cancelled = False

        if task_controller is not None:
            background_cancelled = (
                task_controller.cancel_current()
            )

        if background_cancelled:

            state.continuous_mode = True
            state.pending_input = None
            state.active_context.clear()

            logger.info(
                "JARVIS: Background task cancellation requested."
            )

            reply = "Stopping the current task."

            conversation.add_message(
                "assistant",
                reply,
            )

            speak_callback(reply)

            return "cancelled"

        if not state.task_state.is_active():

            logger.info(
                "JARVIS: No active task to cancel."
            )

            reply = "There is nothing to stop."

            conversation.add_message(
                "assistant",
                reply,
            )

            speak_callback(reply)

            return "done"

        state.task_state.cancel()
        state.continuous_mode = False
        state.pending_input = None
        state.active_context.clear()

        logger.info(
            "JARVIS: Command cancelled."
        )

        state.task_state.finish()

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "cancelled"

    # ==================================================
    # BACKGROUND TASK STATUS
    # ==================================================

    if (
        task_controller is not None
        and is_task_status_request(user_input)
    ):

        reply = task_controller.status_message()

        conversation.add_message(
            "assistant",
            reply,
        )

        logger.info(
            f"JARVIS TASK CONTROLLER: {reply}"
        )

        interrupted = speak_callback(
            reply
        )

        if interrupted:
            state.pending_input = _listen_after_barge_in()

            if state.pending_input:
                return "interrupted"

        return "done"

    # ==================================================
    # SHUTDOWN
    # ==================================================

    if is_shutdown_command(
        user_input
    ):

        if (
            task_controller is not None
            and task_controller.has_active_task()
        ):
            task_controller.cancel_current()
        else:
            state.task_state.finish()

        reply = "Shutting down. Goodbye."

        conversation.add_message(
            "user",
            user_input,
        )

        conversation.add_message(
            "assistant",
            reply,
        )

        logger.info(
            f"JARVIS: {reply}"
        )

        speak_start = perf_now()

        speak_callback(
            reply
        )

        logger.info(
            f"PERF: shutdown TTS: "
            f"{perf_now() - speak_start:.3f}s"
        )

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "shutdown"

    # ==================================================
    # BACKGROUND TASK BUSY GUARD
    # ==================================================

    if (
        task_controller is not None
        and task_controller.has_active_task()
    ):

        pending_route = route_command(
            user_input
        )

        if pending_route.kind == "conversation":

            if is_task_acknowledgement(user_input):
                reply = (
                    "Understood. I'm continuing with the current task."
                )
            else:
                reply = (
                    "I'm still working on the current task. "
                    "Say stop if you'd like me to cancel it."
                )

            logger.info(
                "JARVIS TASK CONTROLLER: "
                "Handled conversation while task is active."
            )

            speak_callback(reply)

            return "done"

        if pending_route.kind in {
            "fast",
            "contextual",
            "agent",
        }:

            reply = (
                "I'm already handling another task. "
                "Say stop first if you'd like me to cancel it."
            )

            logger.info(
                "JARVIS TASK CONTROLLER: "
                "Rejected concurrent action."
            )

            speak_callback(reply)

            return "done"

    # ==================================================
    # REMEMBER
    # ==================================================

    if is_remember_command(
        user_input
    ):

        fact = user_input[8:].strip()

        conversation.add_message(
            "user",
            user_input,
        )

        if fact:

            from memory import save_memory

            memory_start = perf_now()

            save_memory(
                fact
            )

            logger.info(
                f"PERF: save memory: "
                f"{perf_now() - memory_start:.3f}s"
            )

            reply = "I will remember that."

        else:

            reply = (
                "What would you like me to remember?"
            )

        conversation.add_message(
            "assistant",
            reply,
        )

        logger.info(
            f"JARVIS: {reply}"
        )

        speak_start = perf_now()

        interrupted = speak_callback(
            reply
        )

        logger.info(
            f"PERF: remember TTS: "
            f"{perf_now() - speak_start:.3f}s"
        )

        if interrupted:

            state.pending_input = (
                _listen_after_barge_in()
            )

            if state.pending_input:
                return "interrupted"

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "done"

    # ==================================================
    # WHAT DO YOU REMEMBER
    # ==================================================

    if user_input.lower() == "what do you remember":

        from memory import get_memories

        memory_start = perf_now()

        memories = get_memories()

        logger.info(
            f"PERF: get memories: "
            f"{perf_now() - memory_start:.3f}s"
        )

        if not memories:

            reply = (
                "I currently have no saved memories."
            )

        else:

            memory_items = [
                item[0]
                for item in memories
            ]

            reply = (
                "Your saved memories are: "
                + ". ".join(memory_items)
            )

        conversation.add_message(
            "user",
            user_input,
        )

        conversation.add_message(
            "assistant",
            reply,
        )

        logger.info(
            f"JARVIS: {reply}"
        )

        speak_start = perf_now()

        interrupted = speak_callback(
            reply
        )

        logger.info(
            f"PERF: memory response TTS: "
            f"{perf_now() - speak_start:.3f}s"
        )

        if interrupted:

            state.pending_input = (
                _listen_after_barge_in()
            )

            if state.pending_input:
                return "interrupted"

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "done"

    # ==================================================
    # SAVE USER INPUT
    # ==================================================

    conversation.add_message(
        "user",
        user_input,
    )

    # ==================================================
    # FAST COMMAND
    # ==================================================

    fast_start = perf_now()

    fast_command = get_fast_command(
        user_input
    )

    logger.info(
        f"PERF: fast-command lookup: "
        f"{perf_now() - fast_start:.3f}s"
    )

    if fast_command:

        # ==================================================
        # MULTI-STEP FAST COMMAND
        # ==================================================

        if isinstance(
            fast_command,
            dict
        ):

            fast_steps = fast_command.get(
                "steps",
                []
            )

            if fast_steps:

                logger.info(
                    "JARVIS: Fast multi-step command detected."
                )

                # The deterministic router has already done
                # the planning. Pass the complete plan to the
                # normal executor as ONE task.
                #
                # This allows execute_plan() to recognize that
                # the task is multi-step and avoid speaking
                # every intermediate tool result.

                fast_plan = {
                    "goal": user_input,
                    "resolved_command": user_input,
                    "steps": fast_steps,
                }

                execution_start = perf_now()

                # --------------------------------------------------
                # Agent execution
                #
                # Keep deterministic fast-command planning, but
                # execute the resulting task through JarvisAgent so
                # failures can trigger observation + replanning.
                # --------------------------------------------------

                agent_task = jarvis_agent.create_task(
                    user_input,
                    active_context=(
                        state.active_context.to_dict()
                        if hasattr(
                            state.active_context,
                            "to_dict",
                        )
                        else dict(
                            state.active_context or {}
                        )
                    ),
                )

                # The fast router already produced the plan.
                # Do not spend another LLM call planning the same
                # task. Give the existing agent the deterministic
                # plan and let its execution/replan loop manage it.
                agent_task.planner_result = fast_plan

                agent_task.goal = str(
                    fast_plan.get(
                        "goal",
                        user_input,
                    )
                    or user_input
                )

                agent_task.steps = (
                    jarvis_agent._build_steps(
                        fast_plan
                    )
                )

                agent_task.status = "ready"

                if task_controller is not None:
                    started = task_controller.start(
                        agent_task,
                        state.active_context,
                        state.task_state,
                        speak_callback,
                        history_text="",
                    )

                    if not started:
                        reply = (
                            "I'm already handling another task."
                        )
                        conversation.add_message(
                            "assistant",
                            reply,
                        )
                        speak_callback(reply)
                        return "done"

                    result = "task_started"

                    logger.info(
                        "JARVIS AGENT: Fast task queued in "
                        "background controller."
                    )

                else:
                    agent_task = (
                        jarvis_agent.execute_task(
                            agent_task,
                            state.active_context,
                            state.task_state,
                            speak_callback,
                            history_text="",
                        )
                    )

                    result = (
                        "done"
                        if agent_task.status == "completed"
                        else (
                            "cancelled"
                            if agent_task.status == "cancelled"
                            else "failed"
                        )
                    )

                    logger.info(
                        "JARVIS AGENT: Fast task "
                        f"status={agent_task.status}, "
                        f"replans={agent_task.replan_count}"
                    )

                logger.info(
                    f"PERF: fast multi-step execution: "
                    f"{perf_now() - execution_start:.3f}s"
                )

                logger.info(
                    f"PERF: total command processing: "
                    f"{perf_now() - command_start:.3f}s"
                )

                return result

            logger.warning(
                "JARVIS: Fast command returned an empty plan."
            )

            logger.info(
                f"PERF: total command processing: "
                f"{perf_now() - command_start:.3f}s"
            )

            return "done"

        # ==================================================
        # OLD SINGLE-STEP FAST COMMAND FORMAT
        # ==================================================

        elif (
            isinstance(
                fast_command,
                tuple
            )
            and len(
                fast_command
            ) == 2
        ):

            tool_name, argument = fast_command

            logger.info(
                f"JARVIS: Fast command detected: "
                f"{tool_name}"
                + (
                    f" ({argument})"
                    if argument
                    else ""
                )
            )

            result = execute_fast_command(
                tool_name,
                argument,
                user_input,
                state,
                speak_callback,
            )

            logger.info(
                f"PERF: total command processing: "
                f"{perf_now() - command_start:.3f}s"
            )

            return result

        # ==================================================
        # UNKNOWN FAST COMMAND FORMAT
        # ==================================================

        logger.warning(
            "JARVIS: Fast command returned "
            "an unsupported format."
        )

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "done"

    # ==================================================
    # CREATIVE REQUEST
    # ==================================================

    creative_start = perf_now()

    creative = is_creative_request(
        user_input
    )

    logger.info(
        f"PERF: creative lookup: "
        f"{perf_now() - creative_start:.3f}s"
    )

    if creative:

        normal_start = perf_now()

        result = handle_normal_conversation(
            user_input,
            state.active_context,
            system_prompt,
            speak_callback,
        )

        logger.info(
            f"PERF: creative conversation: "
            f"{perf_now() - normal_start:.3f}s"
        )

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        # Analyze memory only after the user-facing response is complete.
        memory_analysis_start = perf_now()

        if should_run_background_memory_analysis(user_input):

            run_memory_analysis_background(

                user_input

            )

        logger.info(
            f"PERF: memory-analysis dispatch: "
            f"{perf_now() - memory_analysis_start:.3f}s"
        )

        return result

    # ==================================================
    # CODE GENERATION
    # ==================================================

    code_check_start = perf_now()

    code_request = is_code_request(
        user_input
    )

    logger.info(
        f"PERF: code-request lookup: "
        f"{perf_now() - code_check_start:.3f}s"
    )

    if code_request and not is_complex_code_request(user_input):

        code_start = perf_now()

        result = handle_code_generation(
            user_input
        )

        logger.info(
            f"PERF: code generation: "
            f"{perf_now() - code_start:.3f}s"
        )

        conversation.add_message(
            "assistant",
            result,
        )

        logger.info(
            f"JARVIS: {result}"
        )

        speak_start = perf_now()

        interrupted = speak_callback(
            result
        )

        logger.info(
            f"PERF: code TTS: "
            f"{perf_now() - speak_start:.3f}s"
        )

        if interrupted:

            state.pending_input = (
                _listen_after_barge_in()
            )

            if state.pending_input:
                return "interrupted"

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        return "done"

    # ==================================================
    # BUILD HISTORY
    # ==================================================

    history_start = perf_now()

    history_text = ""

    for message in conversation.get_recent(
        limit=10
    ):

        role = message.get(
            "role",
            "",
        )

        content = message.get(
            "content",
            "",
        )

        if content:

            history_text += (
                f"{role.upper()}: "
                f"{content}\n"
            )

    logger.info(
        f"PERF: history build: "
        f"{perf_now() - history_start:.3f}s"
    )

    # ==================================================
    # CONTEXT RESOLUTION
    # ==================================================

    planning_input = user_input

    context_check_start = perf_now()

    needs_context = should_resolve_context(
        user_input
    )

    logger.info(
        f"PERF: context check: "
        f"{perf_now() - context_check_start:.3f}s"
    )

    if needs_context:

        context_start = perf_now()

        planning_input = resolve_followup(
            user_input,
            state.active_context.to_dict(),
            history_text,
        )

        logger.info(
            f"PERF: context resolution: "
            f"{perf_now() - context_start:.3f}s"
        )

        if planning_input != user_input:

            logger.info(
                f"Context resolved: "
                f"'{user_input}' -> "
                f"'{planning_input}'"
            )

    # ==================================================
    # ==================================================
    # SMART ROUTING: DIRECT CONVERSATION
    # ==================================================

    route_start = perf_now()

    route_decision = route_command(
        user_input
    )

    logger.info(
        "JARVIS: Smart route: "
        f"{route_decision.kind} "
        f"({route_decision.reason})"
    )

    logger.info(
        f"PERF: smart routing: "
        f"{perf_now() - route_start:.3f}s"
    )

    if route_decision.kind == "conversation":

        conversation_start = perf_now()

        result = handle_normal_conversation(
            planning_input,
            state.active_context,
            system_prompt,
            speak_callback,
        )

        logger.info(
            f"PERF: smart conversation: "
            f"{perf_now() - conversation_start:.3f}s"
        )

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        # Analyze memory only after the user-facing response is complete.
        memory_analysis_start = perf_now()

        if should_run_background_memory_analysis(user_input):

            run_memory_analysis_background(

                user_input

            )

        logger.info(
            f"PERF: memory-analysis dispatch: "
            f"{perf_now() - memory_analysis_start:.3f}s"
        )

        return result

    # AGENT CORE PLANNING
    # ==================================================

    planner_start = perf_now()

    try:

        agent_task = jarvis_agent.create_task(
            planning_input,
            state.active_context.to_dict(),
        )

        if task_controller is not None:

            started = task_controller.start_planning(
                agent_task,
                state.active_context,
                state.task_state,
                history_text=history_text,
            )

            logger.info(
                f"PERF: background task submission: "
                f"{perf_now() - planner_start:.3f}s"
            )

            if not started:

                reply = (
                    "I'm already handling another task. "
                    "Say stop first if you'd like me to cancel it."
                )

                speak_callback(reply)
                return "done"

            result = "task_started"

            if should_run_background_memory_analysis(user_input):

                run_memory_analysis_background(

                    user_input

                )

            return result

        jarvis_agent.plan_task(
            agent_task,
            history_text=history_text,
        )

        steps = agent_task.steps

    except Exception as e:

        logger.error(
            f"Agent Core planning error: {e}"
        )

        agent_task = None
        steps = []

    logger.info(
        f"PERF: agent planning: "
        f"{perf_now() - planner_start:.3f}s"
    )
    # ==================================================
    # NORMAL CONVERSATION
    # ==================================================

    if not steps:

        conversation_start = perf_now()

        result = handle_normal_conversation(
            planning_input,
            state.active_context,
            system_prompt,
            speak_callback,
        )

        logger.info(
            f"PERF: normal conversation: "
            f"{perf_now() - conversation_start:.3f}s"
        )

        logger.info(
            f"PERF: total command processing: "
            f"{perf_now() - command_start:.3f}s"
        )

        # Analyze memory only after the user-facing response is complete.
        memory_analysis_start = perf_now()

        if should_run_background_memory_analysis(user_input):

            run_memory_analysis_background(

                user_input

            )

        logger.info(
            f"PERF: memory-analysis dispatch: "
            f"{perf_now() - memory_analysis_start:.3f}s"
        )

        return result

    # ==================================================
    # EXECUTE AGENT TASK
    # ==================================================

    execution_start = perf_now()

    if agent_task is None:

        result = "I couldn't create a task for that request."

    else:

        if task_controller is not None:

            started = task_controller.start(
                agent_task,
                state.active_context,
                state.task_state,
                speak_callback,
                history_text=history_text,
            )

            if not started:
                result = (
                    "I'm already handling another task."
                )

                speak_callback(result)

                return "done"

            result = "task_started"

            logger.info(
                "JARVIS AGENT: Task queued in "
                "background controller."
            )

        else:

            result = jarvis_agent.execute_task(
                agent_task,
                state.active_context,
                state.task_state,
                speak_callback,
            )

    logger.info(
        f"PERF: agent execution: {perf_now() - execution_start:.3f}s"
    )

    logger.info(
        f"PERF: total command processing: {perf_now() - command_start:.3f}s"
    )

    # Analyze memory only after the user-facing task is complete.
    memory_analysis_start = perf_now()

    if should_run_background_memory_analysis(user_input):

        run_memory_analysis_background(

            user_input

        )

    logger.info(
        f"PERF: memory-analysis dispatch: "
        f"{perf_now() - memory_analysis_start:.3f}s"
    )

    return result


# ============================================================
# BARGE-IN
# ============================================================

def _listen_after_barge_in():
    """
    Listen for a command after TTS interruption.
    """

    try:

        from speech import listen
        from voice import (
            get_interrupted_audio,
            was_interrupted,
        )

        if not was_interrupted():

            return None

        logger.info(
            "JARVIS: Barge-in detected."
        )

        interrupted_audio = (
            get_interrupted_audio()
        )

        start = perf_now()

        result = listen(
            initial_audio=interrupted_audio,
            mode="continuous",
        )

        logger.info(
            f"PERF: barge-in transcription: "
            f"{perf_now() - start:.3f}s"
        )

        if result:

            logger.info(
                f"JARVIS: Barge-in command captured: "
                f"{result}"
            )

            return result

        logger.info(
            "JARVIS: Barge-in speech was not transcribed."
        )

        return None

    except Exception as e:

        logger.warning(
            f"JARVIS: Barge-in listening error: {e}"
        )

        return None

    finally:

        try:

            from voice import clear_interruption

            clear_interruption()

        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================

def main():
    """Main JARVIS entry point."""

    startup_start = perf_now()

    # ==================================================
    # INITIALIZATION
    # ==================================================

    create_memory()

    profile = load_profile()

    user_name = profile["name"]

    context = JarvisContext()

    system_prompt = build_system_prompt(
        user_name,
        context,
        profile,
    )

    state = JarvisState()
    state.task_controller = BackgroundTaskController(
        jarvis_agent
    )

    typed_input = TypedInputChannel(
        enabled=TYPED_INPUT_ENABLED
    )

    conversation = ConversationHistory()

    logger.info(
        f"PERF: base initialization: "
        f"{perf_now() - startup_start:.3f}s"
    )

    # ==================================================
    # PRELOAD WHISPER
    # ==================================================

    whisper_start = perf_now()

    voice_speak = None
    tts_status = None

    try:

        from speech import listen

        logger.info(
            "JARVIS: Preloading Whisper..."
        )

        logger.info(
            "JARVIS: Whisper ready."
        )

        logger.info(
            f"PERF: Whisper preload: "
            f"{perf_now() - whisper_start:.3f}s"
        )

    except Exception as e:

        logger.error(
            f"JARVIS: Whisper initialization failed: {e}"
        )

        logger.info(
            f"PERF: Whisper initialization failure: "
            f"{perf_now() - whisper_start:.3f}s"
        )

        listen = None

    # ==================================================
    # PRELOAD PIPER
    # ==================================================

    tts_start = perf_now()

    try:

        from voice import (
            speak as voice_speak,
            tts_status,
        )

        status = tts_status()

        logger.info(
            "JARVIS: Piper ready. "
            f"Inference = "
            f"{'CUDA' if status.get('cuda') else 'CPU'}."
        )

        logger.info(
            f"PERF: Piper preload: "
            f"{perf_now() - tts_start:.3f}s"
        )

    except Exception as e:

        logger.error(
            f"JARVIS: Piper initialization failed: {e}"
        )

        logger.info(
            f"PERF: Piper initialization failure: "
            f"{perf_now() - tts_start:.3f}s"
        )

    # ==================================================
    # ONLINE
    # ==================================================

    logger.info(
        f"JARVIS online. Welcome back."
    )

    logger.info(
        f"Project: "
        f"{context._project_info['file_count']} files, "
        f"languages: "
        f"{context._project_info['languages']}"
    )

    logger.info(
        f"PERF: startup initialization complete: "
        f"{perf_now() - startup_start:.3f}s"
    )

    typed_input.start()

    # ==================================================
    # SPEECH DEDUPLICATION
    # ==================================================

    speech_dedup_lock = threading.Lock()
    active_speech = set()
    recent_speech = {}
    duplicate_speech_window = 2.5

    def _speech_key(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    def _claim_speech(text: str):
        key = _speech_key(text)

        if not key:
            return ""

        now = time.monotonic()

        with speech_dedup_lock:
            expired = [
                value
                for value, timestamp in recent_speech.items()
                if now - timestamp >= duplicate_speech_window
            ]

            for value in expired:
                recent_speech.pop(value, None)

            if key in active_speech:
                return None

            recent_at = recent_speech.get(key)
            if (
                recent_at is not None
                and now - recent_at < duplicate_speech_window
            ):
                return None

            active_speech.add(key)

        return key

    def _finish_speech(key: str, completed: bool) -> None:
        if not key:
            return

        with speech_dedup_lock:
            active_speech.discard(key)

            if completed:
                recent_speech[key] = time.monotonic()

    # ==================================================
    # SPEAK FUNCTION
    # ==================================================

    def speak(
        text: str,
    ) -> bool:
        """Speak text aloud."""

        speak_start = perf_now()

        try:

            if voice_speak is None:
                logger.warning(
                    "JARVIS: TTS is unavailable."
                )
                return False

            speech_key = _claim_speech(text)

            if speech_key is None:
                logger.info(
                    "JARVIS: Suppressed duplicate speech: "
                    f"{_speech_key(text)}"
                )
                return False

            if not speech_key:
                return False

            completed = False

            try:
                set_barehands_state("speaking")

                try:
                    with state.io_lock:
                        result = speak_response(
                            text,
                            voice_speak,
                        )
                finally:
                    set_barehands_state("idle")

                completed = True

                logger.info(
                    f"PERF: TTS call: "
                    f"{perf_now() - speak_start:.3f}s"
                )

                return result

            finally:
                _finish_speech(
                    speech_key,
                    completed,
                )

        except Exception as e:

            logger.error(
                f"Voice error: {e}"
            )

            logger.info(
                f"PERF: failed TTS call: "
                f"{perf_now() - speak_start:.3f}s"
            )

            return False

    # ==================================================
    # SERIALIZED LISTENING
    # ==================================================

    def listen_serialized(
        initial_audio=None,
        mode="wake",
        interrupt_event=None,
    ):
        """Serialize microphone capture with optional background-task interruption."""
        if listen is None:
            return None

        set_barehands_state("listening")

        try:
            with state.io_lock:
                return listen(
                    initial_audio=initial_audio,
                    mode=mode,
                    interrupt_event=interrupt_event,
                )
        finally:
            set_barehands_state("idle")

    # ==================================================
    # STARTUP MESSAGE
    # ==================================================

    speak(
        "Welcome back. "
        "JARVIS is online."
    )

    # --------------------------------------------------
    # Warm the coding model in the background. This keeps
    # the first autonomous repair from paying the full
    # Ollama model-load cost on the critical path.
    # --------------------------------------------------
    def warm_coding_model_background():
        try:
            warmup_start = perf_now()
            ModelManager().warmup_coding_model()
            logger.info(
                "PERF: coding model background warm-up: "
                f"{perf_now() - warmup_start:.3f}s"
            )
        except Exception as exc:
            logger.warning(
                f"JARVIS: Coding model background warm-up failed: {exc}"
            )

    threading.Thread(
        target=warm_coding_model_background,
        name="JARVIS-CodingModelWarmup",
        daemon=True,
    ).start()

    # ==================================================
    # MAIN STATE MACHINE
    # ==================================================

    try:

        while True:

            # ------------------------------------------
            # Background task speech
            #
            # Worker announcements are drained here so they
            # never compete with microphone capture.
            # ------------------------------------------

            if state.task_controller is not None:
                state.task_controller.drain_speech(
                    speak
                )

            # ------------------------------------------
            # Typed console command
            #
            # Text commands share the exact same process_command()
            # pipeline as voice commands. A typed command also
            # interrupts wake-word capture so it can be handled
            # immediately.
            # ------------------------------------------

            typed_command = typed_input.get_nowait()

            if typed_command:

                process_start = perf_now()

                result = process_command(
                    typed_command,
                    state,
                    conversation,
                    system_prompt,
                    speak,
                )

                logger.info(
                    f"PERF: typed command total: "
                    f"{perf_now() - process_start:.3f}s"
                )

                if result == "shutdown":

                    shutdown_background_tasks(state)
                    break

                continue

            # ------------------------------------------
            # Pending barge-in command
            # ------------------------------------------

            if state.pending_input:

                current_input = (
                    state.pending_input
                )

                state.pending_input = None

                process_start = perf_now()

                result = process_command(
                    current_input,
                    state,
                    conversation,
                    system_prompt,
                    speak,
                )

                logger.info(
                    f"PERF: pending command total: "
                    f"{perf_now() - process_start:.3f}s"
                )

                if result == "shutdown":

                    shutdown_background_tasks(state)
                    break

                continue

            # ------------------------------------------
            # Continuous conversation mode
            # ------------------------------------------

            if state.continuous_mode:

                controller = state.task_controller

                # Prepare the completion event atomically with the active-task
                # check. This prevents a task from finishing between those
                # operations and having its wake-up signal accidentally cleared.
                completion_event = None
                if controller is not None:
                    completion_event, already_completed = (
                        controller.prepare_followup_wait()
                    )

                    if already_completed:
                        controller.drain_speech(speak)
                        state.continuous_mode = False
                        continue

                logger.info(
                    "JARVIS: Listening for follow-up..."
                )

                if listen is None:

                    logger.error(
                        "JARVIS: Whisper is unavailable."
                    )

                    state.continuous_mode = False

                    continue

                try:

                    listen_start = perf_now()

                    current_input = listen_serialized(
                        mode="continuous",
                        interrupt_event=completion_event,
                    )

                    logger.info(
                        f"PERF: follow-up listen/transcription: "
                        f"{perf_now() - listen_start:.3f}s"
                    )

                except KeyboardInterrupt:

                    state.continuous_mode = False

                    logger.info(
                        "JARVIS: Follow-up listening interrupted. "
                        "Returning to wake-word mode."
                    )

                    continue

                except Exception as e:

                    logger.error(
                        f"Listen error: {e}"
                    )

                    current_input = None

                if current_input is None:

                    if (
                        controller is not None
                        and controller.consume_completion_signal()
                    ):
                        controller.drain_speech(speak)
                        state.continuous_mode = False
                        continue

                    state.continuous_mode = False

                    logger.info(
                        "JARVIS: Conversation timeout."
                    )

                    continue

                result = process_command(
                    current_input,
                    state,
                    conversation,
                    system_prompt,
                    speak,
                )

                if result == "shutdown":

                    shutdown_background_tasks(state)
                    break

                continue

            # ------------------------------------------
            # Wake-word mode
            # ------------------------------------------

            logger.info(
                "JARVIS: Waiting for wake word..."
            )

            try:

                from wakeword import (
                    wait_for_wake_word
                )

                wake_start = perf_now()

                active_task_for_wake = (
                    state.task_controller is not None
                    and state.task_controller.has_active_task()
                )

                set_barehands_state("listening")

                try:
                    completion_event = (
                        state.task_controller.completion_event
                        if active_task_for_wake
                        and state.task_controller is not None
                        else None
                    )
                    wake_interrupt_event = _AnyEvent(
                        typed_input.interrupt_event,
                        completion_event,
                    )

                    with state.io_lock:
                        triggered = (
                            wait_for_wake_word(
                                interrupt_event=wake_interrupt_event,
                                active_task=active_task_for_wake,
                            )
                        )
                finally:
                    set_barehands_state("idle")

                logger.info(
                    f"PERF: wake listener cycle: "
                    f"{perf_now() - wake_start:.3f}s"
                )

            except Exception as e:

                logger.error(
                    f"Wake word error: {e}"
                )

                triggered = False

            if not triggered:

                continue

            # ------------------------------------------
            # Wake acknowledgement
            # ------------------------------------------

            active_task_now = (
                state.task_controller is not None
                and state.task_controller.has_active_task()
            )

            if active_task_now:
                logger.info(
                    "JARVIS: Wake detected during an active task; "
                    "skipping acknowledgement and listening directly "
                    "for the command."
                )
                interrupted = False
            else:
                interrupted = speak(
                    "Yes?"
                )

            if interrupted:

                state.pending_input = (
                    _listen_after_barge_in()
                )

                if state.pending_input:

                    state.continuous_mode = True

                    continue

            # ------------------------------------------
            # First command
            # ------------------------------------------

            if listen is None:

                logger.error(
                    "JARVIS: Whisper is unavailable."
                )

                continue

            try:

                listen_start = perf_now()

                current_input = listen_serialized(
                    mode="wake"
                )

                logger.info(
                    f"PERF: wake command "
                    f"listen/transcription: "
                    f"{perf_now() - listen_start:.3f}s"
                )

            except KeyboardInterrupt:

                logger.info(
                    "JARVIS: Command listening interrupted."
                )

                current_input = None

            except Exception as e:

                logger.error(
                    f"Listen error: {e}"
                )

                current_input = None

            if current_input is None:

                logger.info(
                    "JARVIS: No command heard."
                )

                continue

            # ------------------------------------------
            # Enter continuous mode
            # ------------------------------------------

            state.continuous_mode = True

            process_start = perf_now()

            result = process_command(
                current_input,
                state,
                conversation,
                system_prompt,
                speak,
            )

            logger.info(
                f"PERF: wake command total: "
                f"{perf_now() - process_start:.3f}s"
            )

            if result == "shutdown":

                shutdown_background_tasks(state)
                break

    except KeyboardInterrupt:

        logger.info(
            "JARVIS: Shutdown requested."
        )

        shutdown_background_tasks(state)

        speak(
            "Goodbye."
        )

    finally:
        typed_input.stop()

        try:
            from browser_controller import cleanup_browser
            cleanup_browser()
        except Exception as exc:
            logger.debug(
                f"Browser cleanup during JARVIS shutdown failed: {exc}"
            )


if __name__ == "__main__":
    main()


