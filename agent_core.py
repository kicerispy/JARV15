"""
JARVIS Agent Core

Autonomous task orchestration layer.

Flow:

    request
       ↓
     plan
       ↓
    execute
       ↓
    observe
       ↓
    success? ── yes ──> completed
       │
       no
       ↓
     replan
       ↓
    execute again

The existing tool_executor.py remains responsible for:
- executing tools
- task state
- cancellation
- screen verification
- retries/recovery
- active context updates
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from logger import logger
from planner import create_plan, validate_plan
from tool_executor import execute_plan
from state import ActiveContext, TaskState


# ==========================================================
# Agent Step
# ==========================================================

@dataclass
class AgentStep:
    tool: str
    argument: str = ""

    description: str = ""

    status: str = "pending"

    attempts: int = 0

    result: Any = None

    error: Optional[str] = None

    verified: bool = False

    observation: str = ""


# ==========================================================
# Agent Task
# ==========================================================

@dataclass
class AgentTask:
    task_id: str

    request: str

    goal: str = ""

    status: str = "created"

    steps: List[AgentStep] = field(
        default_factory=list
    )

    active_context: Dict[str, Any] = field(
        default_factory=dict
    )

    planner_result: Optional[Dict[str, Any]] = None

    execution_result: Any = None

    observations: List[str] = field(
        default_factory=list
    )

    replan_count: int = 0

    max_replans: int = 2

    current_step: int = -1

    created_at: float = field(
        default_factory=time.time
    )

    started_at: Optional[float] = None

    completed_at: Optional[float] = None

    error: Optional[str] = None


# ==========================================================
# JARVIS Agent
# ==========================================================


# ============================================================
# Browser State Observation Helpers
# ============================================================

BROWSER_STATE_TOOLS = {
    "browser_connect",
    "browser_search_google",
    "browser_search_bing",
    "browser_click_first_bing_result",
    "browser_goto",
    "browser_page_info",
}


def _is_browser_trace(trace):
    for entry in trace or []:
        tool = str(entry.get("tool", "")).strip()

        if tool in BROWSER_STATE_TOOLS:
            return True

    return False


def _capture_browser_state():
    try:
        from browser_controller import browser_page_info

        result = browser_page_info()

        if not isinstance(result, dict):
            return {
                "success": False,
                "error": (
                    "browser_page_info returned "
                    "a non-dict result"
                ),
            }

        return result

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
        }


class JarvisAgent:

    def __init__(
        self,
        planner=create_plan,
        executor=execute_plan,
    ):
        self.planner = planner
        self.executor = executor

        self.current_task: Optional[
            AgentTask
        ] = None

        self.state: Dict[str, Any] = {
            "last_request": "",
            "last_goal": "",
            "last_result": None,
            "last_status": "",
            "last_error": None,
            "replans": 0,
        }

    # ======================================================
    # Create Task
    # ======================================================

    def create_task(
        self,
        request: str,
        active_context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AgentTask:

        task = AgentTask(
            task_id=str(
                uuid.uuid4()
            ),
            request=str(
                request or ""
            ).strip(),
            active_context=dict(
                active_context or {}
            ),
        )

        self.current_task = task

        self.state[
            "last_request"
        ] = task.request

        self.state[
            "last_error"
        ] = None

        self.state[
            "replans"
        ] = 0

        return task

    # ======================================================
    # Progress Reporting
    # ======================================================

    @staticmethod
    def _announce(message: str, speak_callback) -> None:
        """Give the user a concise milestone update without exposing internals."""
        try:
            if speak_callback:
                speak_callback(message)
        except Exception as exc:
            logger.debug(
                f"JARVIS AGENT: Progress announcement skipped: {exc}"
            )

    def _should_report_progress(self, task: AgentTask) -> bool:
        request = task.request.lower()
        progress_terms = (
            "fix",
            "debug",
            "repair",
            "diagnose",
            "refactor",
            "investigate",
            "inspect",
        )
        return (
            len(task.steps) > 1
            or any(term in request for term in progress_terms)
        )

    # ======================================================
    # Build Steps
    # ======================================================

    def _build_steps(
        self,
        plan: Dict[str, Any],
    ) -> List[AgentStep]:

        steps: List[AgentStep] = []

        for step in plan.get(
            "steps",
            [],
        ):

            if not isinstance(
                step,
                dict,
            ):
                continue

            tool = str(
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

            if not tool:
                continue

            steps.append(
                AgentStep(
                    tool=tool,
                    argument=argument,
                    description=str(
                        step.get(
                            "description",
                            "",
                        )
                        or ""
                    ),
                )
            )

        return steps

    # ======================================================
    # Planning
    # ======================================================

    def plan_task(
        self,
        task: AgentTask,
        history_text: str = "",
        planning_request: Optional[str] = None,
    ) -> AgentTask:

        task.status = "planning"

        request_for_planner = (
            planning_request
            if planning_request is not None
            else task.request
        )

        logger.info(
            "JARVIS AGENT: Planning task "
            f"{task.task_id}"
        )

        try:

            plan = self.planner(
                request_for_planner,
                active_context=(
                    task.active_context
                ),
                history_text=history_text,
            )

            plan = validate_plan(
                plan
            )

            task.planner_result = plan

            task.goal = str(
                plan.get(
                    "goal",
                    "",
                )
                or ""
            )

            task.steps = self._build_steps(
                plan
            )

            self.state[
                "last_goal"
            ] = task.goal

        except Exception as exc:

            logger.exception(
                "JARVIS AGENT: "
                "Planning failed"
            )

            task.status = "failed"

            task.error = str(
                exc
            )

            self.state[
                "last_error"
            ] = str(
                exc
            )

            self.state[
                "last_status"
            ] = task.status

            return task

        if not task.steps:

            task.status = "conversation"

            self.state[
                "last_status"
            ] = task.status

            logger.info(
                "JARVIS AGENT: "
                "No executable tools required."
            )

            return task

        task.status = "ready"

        self.state[
            "last_status"
        ] = task.status

        logger.info(
            "JARVIS AGENT: Planned "
            f"{len(task.steps)} step(s)"
        )

        for index, step in enumerate(
            task.steps,
            start=1,
        ):

            logger.info(
                "JARVIS AGENT STEP "
                f"{index}: "
                f"{step.tool}"
                f"({step.argument})"
            )

        return task

    # ======================================================
    # Build Replan Request
    # ======================================================

    def _build_replan_request(
        self,
        task: AgentTask,
    ) -> str:

        lines = [
            "Replan the task below because the previous plan "
            "did not complete successfully.",
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            "Previous observations:",
        ]

        if task.observations:
            for observation in task.observations:
                lines.append(
                    f"- {observation}"
                )
        else:
            lines.append(
                "- No reliable observation was recorded."
            )

        # Include current browser state when available.
        browser_state = task.active_context.get(
            "browser_state",
            {},
        )

        if isinstance(browser_state, dict):

            if browser_state.get("success"):
                lines.extend(
                    [
                        "",
                        "Current browser state:",
                        (
                            "URL: "
                            f"{browser_state.get('url', '')}"
                        ),
                        (
                            "Title: "
                            f"{browser_state.get('title', '')}"
                        ),
                    ]
                )

                pages = browser_state.get("pages")

                if isinstance(pages, list) and pages:
                    lines.append(
                        "Open browser pages:"
                    )

                    for page in pages:
                        if not isinstance(page, dict):
                            continue

                        page_url = page.get(
                            "url",
                            "",
                        )

                        page_title = page.get(
                            "title",
                            "",
                        )

                        lines.append(
                            f"- {page_title!r} — "
                            f"{page_url!r}"
                        )

            elif browser_state.get("error"):
                lines.extend(
                    [
                        "",
                        "Browser state observation error:",
                        str(
                            browser_state.get(
                                "error"
                            )
                        ),
                    ]
                )

        lines.extend(
            [
                "",
                "Previous execution result:",
                str(
                    task.execution_result
                    or ""
                ),
                "",
                "Previous error:",
                str(
                    task.error
                    or ""
                ),
                "",
                "Create a new plan that attempts to "
                "complete the original goal from the "
                "current computer state.",
            ]
        )

        return "\n".join(lines)

    # ======================================================
    # Record Execution Observation
    # ======================================================

    def _record_execution_observation(
        self,
        task: AgentTask,
        attempt: int,
        execution_result: Any,
    ) -> None:
        """
        Record execution observations and capture actual
        browser state whenever browser tools were involved.
        """
        from tool_executor import get_last_execution_trace

        trace = get_last_execution_trace()

        result_text = str(execution_result)

        # Overall execution result.
        task.observations.append(
            f"Execution attempt {attempt}: {result_text}"
        )

        # Structured step observations.
        for entry in trace:
            index = entry.get("index", -1)
            tool = entry.get("tool", "")
            argument = entry.get("argument", "")
            status = entry.get("status", "")
            verified = entry.get("verified", False)
            message = entry.get("message", "")
            success = entry.get("success")

            if success is True:
                outcome = "completed"
            elif success is False:
                outcome = "failed"
            else:
                outcome = status or "unknown"

            verification = (
                "verified"
                if verified
                else "unverified"
            )

            detail = (
                f"Execution attempt {attempt}: "
                f"Step {index + 1} {tool}"
            )

            if argument:
                detail += f"({argument})"

            detail += (
                f" {outcome} {verification}"
            )

            if message:
                detail += f" — {message}"

            task.observations.append(detail)

        # Capture actual browser state.
        if _is_browser_trace(trace):
            browser_state = _capture_browser_state()

            task.active_context["browser_state"] = (
                browser_state
            )

            if browser_state.get("success"):
                url = browser_state.get("url", "")
                title = browser_state.get("title", "")

                task.active_context["browser_url"] = url
                task.active_context["browser_title"] = title

                task.observations.append(
                    "Browser state after execution: "
                    f"title={title!r}, url={url!r}"
                )

            else:
                error = browser_state.get(
                    "error",
                    "Unknown browser-state error",
                )

                task.observations.append(
                    "Browser state observation failed: "
                    f"{error}"
                )

    def _apply_step_status(
        self,
        task: AgentTask,
        success: bool,
        result: Any,
    ) -> None:

        result_text = str(
            result
            or ""
        ).strip()

        # ----------------------------------------------------
        # Prefer exact per-step execution trace.
        # ----------------------------------------------------

        try:

            from tool_executor import (
                get_last_execution_trace,
            )

            trace = get_last_execution_trace()

        except Exception:

            trace = []

        if trace:

            for entry in trace:

                raw_index = entry.get(
                    "index",
                    0,
                )

                try:
                    index = int(
                        raw_index
                    ) - 1
                except Exception:
                    continue

                if index < 0 or index >= len(
                    task.steps
                ):
                    continue

                step = task.steps[index]

                step.attempts += 1

                step.result = entry.get(
                    "result"
                )

                step.observation = str(
                    entry.get(
                        "message",
                        "",
                    )
                    or ""
                )

                step.verified = bool(
                    entry.get(
                        "verified",
                        False,
                    )
                )

                entry_success = bool(
                    entry.get(
                        "success",
                        False,
                    )
                )

                entry_status = str(
                    entry.get(
                        "status",
                        "",
                    )
                ).lower()

                if (
                    entry_success
                    and entry_status != "failed"
                ):

                    step.status = "completed"

                    if not step.verified:
                        step.verified = True

                    step.error = None

                else:

                    step.status = "failed"

                    step.error = str(
                        entry.get(
                            "message",
                            result_text,
                        )
                        or result_text
                    )

                task.current_step = index

            return

        # ----------------------------------------------------
        # Legacy fallback.
        #
        # Only mark the final step rather than every step.
        # This prevents one failure from incorrectly marking
        # the entire plan as failed.
        # ----------------------------------------------------

        if task.steps:

            index = min(
                max(
                    task.current_step,
                    0,
                ),
                len(task.steps) - 1,
            )

            step = task.steps[index]

            task.current_step = index
            step.attempts += 1
            step.result = result
            step.observation = result_text

            if success:

                step.status = "completed"
                step.verified = True
                step.error = None

            else:

                step.status = "failed"
                step.error = result_text

    # ======================================================
    # Execute Plan Once
    # ======================================================

    def _execute_once(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
    ) -> str:

        if not task.planner_result:
            return "failed"

        task.status = "executing"

        logger.info(
            "JARVIS AGENT: Executing plan "
            f"(attempt={task.replan_count + 1})"
        )

        # The executor processes the complete plan, but keep
        # a sensible current-step baseline for legacy fallback.
        task.current_step = 0

        try:

            result = self.executor(
                task.planner_result,
                active_context,
                task_state,
                speak_callback,
            )

            task.execution_result = result

            result_text = str(
                result
                or ""
            ).strip().lower()

            self._record_execution_observation(
                task,
                task.replan_count + 1,
                result,
            )

            if result_text == "cancelled":

                task.status = "cancelled"

                for step in task.steps:

                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "cancelled"

                return "cancelled"

            if result_text == "interrupted":

                task.status = "failed"

                task.error = (
                    "Execution was interrupted."
                )

                return "failed"

            if result_text == "failed":

                self._apply_step_status(
                    task,
                    success=False,
                    result=result,
                )

                task.error = str(
                    result
                )

                return "failed"

            if result_text == "done":

                self._apply_step_status(
                    task,
                    success=True,
                    result=result,
                )

                return "done"

            self._apply_step_status(
                task,
                success=False,
                result=result,
            )

            task.error = (
                "Executor returned an "
                "unexpected result."
            )

            return "failed"

        except Exception as exc:

            logger.exception(
                "JARVIS AGENT: "
                "Execution failed"
            )

            task.execution_result = str(
                exc
            )

            task.error = str(
                exc
            )

            self._apply_step_status(
                task,
                success=False,
                result=exc,
            )

            return "failed"

    # ======================================================
    # Autonomous Execute
    # ======================================================

    def execute_task(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
        history_text: str = "",
    ) -> AgentTask:

        if task.status in {
            "conversation",
            "failed",
            "cancelled",
        }:
            return task

        if not task.planner_result:

            task.status = "failed"

            task.error = (
                "No valid planner result."
            )

            self.state[
                "last_status"
            ] = task.status

            self.state[
                "last_error"
            ] = task.error

            return task

        task.started_at = (
            task.started_at
            or time.time()
        )

        report_progress = self._should_report_progress(task)

        if report_progress:
            self._announce(
                "I'm on it. I'll keep you updated and let you know when it's finished.",
                speak_callback,
            )

        while True:

            result = self._execute_once(
                task,
                active_context,
                task_state,
                speak_callback,
            )

            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            if result == "done":

                task.status = "completed"

                task.completed_at = (
                    time.time()
                )

                self.state[
                    "last_result"
                ] = task.execution_result

                self.state[
                    "last_status"
                ] = task.status

                self.state[
                    "last_error"
                ] = None

                self.state[
                    "replans"
                ] = task.replan_count

                logger.info(
                    "JARVIS AGENT: Task completed "
                    f"after {task.replan_count} replan(s)."
                )

                if report_progress:
                    self._announce(
                        "The task is complete.",
                        speak_callback,
                    )

                return task

            # ------------------------------------------------
            # Cancelled
            # ------------------------------------------------

            if result == "cancelled":

                task.status = "cancelled"

                task.completed_at = (
                    time.time()
                )

                self.state[
                    "last_status"
                ] = task.status

                return task

            # ------------------------------------------------
            # Failure
            # ------------------------------------------------

            if result == "failed":

                if (
                    task.replan_count
                    >= task.max_replans
                ):

                    task.status = "failed"

                    task.completed_at = (
                        time.time()
                    )

                    self.state[
                        "last_result"
                    ] = task.execution_result

                    self.state[
                        "last_status"
                    ] = task.status

                    self.state[
                        "last_error"
                    ] = task.error

                    self.state[
                        "replans"
                    ] = task.replan_count

                    logger.error(
                        "JARVIS AGENT: "
                        "Maximum replans reached."
                    )

                    if report_progress:
                        self._announce(
                            "I wasn't able to complete the task.",
                            speak_callback,
                        )

                    return task

                # --------------------------------------------
                # REPLAN
                # --------------------------------------------

                task.replan_count += 1

                self.state[
                    "replans"
                ] = task.replan_count

                logger.warning(
                    "JARVIS AGENT: "
                    f"Execution failed. "
                    f"Replanning "
                    f"({task.replan_count}/"
                    f"{task.max_replans})..."
                )

                if report_progress:
                    self._announce(
                        "That approach didn't work as expected. I'm adjusting the plan and trying again.",
                        speak_callback,
                    )

                planning_request = (
                    self._build_replan_request(
                        task
                    )
                )

                replanned = self.plan_task(
                    task,
                    history_text=history_text,
                    planning_request=planning_request,
                )

                if replanned.status in {
                    "conversation",
                    "failed",
                }:

                    return replanned

                continue

    # ======================================================
    # Full Run
    # ======================================================

    def run(
        self,
        request: str,
        active_context,
        task_state,
        speak_callback,
        history_text: str = "",
    ) -> AgentTask:

        task = self.create_task(
            request,
            active_context=(
                active_context.to_dict()
                if hasattr(
                    active_context,
                    "to_dict",
                )
                else dict(
                    active_context or {}
                )
            ),
        )

        task = self.plan_task(
            task,
            history_text=history_text,
        )

        if task.status in {
            "conversation",
            "failed",
        }:

            return task

        task = self.execute_task(
            task,
            active_context,
            task_state,
            speak_callback,
            history_text=history_text,
        )

        return task

    # ======================================================
    # Summary
    # ======================================================

    def summarize(
        self,
        task: Optional[AgentTask] = None,
    ) -> Dict[str, Any]:

        task = (
            task
            or self.current_task
        )

        if task is None:

            return {
                "status": "idle"
            }

        start = (
            task.started_at
            or task.created_at
        )

        end = (
            task.completed_at
            or time.time()
        )

        return {
            "task_id": task.task_id,
            "request": task.request,
            "goal": task.goal,
            "status": task.status,
            "step_count": len(
                task.steps
            ),
            "current_step": (
                task.current_step
            ),
            "duration": max(
                0.0,
                end - start,
            ),
            "result": (
                task.execution_result
            ),
            "error": task.error,
            "replans": task.replan_count,
            "observations": list(
                task.observations
            ),
            "steps": [
                {
                    "tool": step.tool,
                    "argument": step.argument,
                    "status": step.status,
                    "attempts": step.attempts,
                    "verified": step.verified,
                    "result": step.result,
                    "error": step.error,
                    "observation": step.observation,
                }
                for step in task.steps
            ],
        }


# ==========================================================
# Factory
# ==========================================================

def build_agent() -> JarvisAgent:

    return JarvisAgent(
        planner=create_plan,
        executor=execute_plan,
    )


# ==========================================================
# Standalone Test
# ==========================================================

if __name__ == "__main__":

    active_context = ActiveContext(
        site="google",
        last_query="Wi-Fi skeleton",
        last_tool="search_website",
        last_result=None,
    )

    task_state = TaskState()

    def test_speak(text):
        print(
            "[TEST SPEAK]",
            text,
        )

    agent = build_agent()

    task = agent.run(
        "Click the first result",
        active_context=active_context,
        task_state=task_state,
        speak_callback=test_speak,
    )

    print()
    print(
        "========== AGENT SUMMARY =========="
    )

    print(
        agent.summarize(task)
    )

    print(
        "===================================="
    )

    print()
    print(
        "Active context after execution:"
    )

    print(
        active_context
    )

    print()
    print(
        "Task state after execution:"
    )

    print(
        task_state
    )

