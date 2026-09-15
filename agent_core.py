"""
JARVIS Agent Core

High-level orchestration layer.

The Agent Core owns:
- task creation
- planning
- task metadata
- agent state
- high-level results

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
    status: str = "pending"
    attempts: int = 0
    result: Any = None
    error: Optional[str] = None


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

    created_at: float = field(
        default_factory=time.time
    )

    started_at: Optional[float] = None

    completed_at: Optional[float] = None

    error: Optional[str] = None


# ==========================================================
# JARVIS Agent
# ==========================================================

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
            task_id=str(uuid.uuid4()),
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

        return task

    # ======================================================
    # Planning
    # ======================================================

    def plan_task(
        self,
        task: AgentTask,
        history_text: str = "",
    ) -> AgentTask:

        task.status = "planning"

        logger.info(
            "JARVIS AGENT: Planning task "
            f"{task.task_id}"
        )

        try:

            plan = self.planner(
                task.request,
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

            task.steps = [
                AgentStep(
                    tool=str(
                        step.get(
                            "tool",
                            "",
                        )
                    ),
                    argument=str(
                        step.get(
                            "argument",
                            "",
                        )
                        or ""
                    ),
                )
                for step in plan.get(
                    "steps",
                    [],
                )
                if isinstance(
                    step,
                    dict,
                )
            ]

            self.state[
                "last_goal"
            ] = task.goal

        except Exception as exc:

            logger.exception(
                "JARVIS AGENT: "
                "Planning failed"
            )

            task.status = "failed"

            task.error = str(exc)

            self.state[
                "last_error"
            ] = str(exc)

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
    # Execute Existing Plan
    # ======================================================

    def execute_task(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
    ) -> AgentTask:

        if task.status in {
            "conversation",
            "failed",
            "cancelled",
        }:
            return task

        if not task.planner_result:
            task.status = "failed"
            task.error = "No valid planner result."

            self.state["last_status"] = task.status
            self.state["last_error"] = task.error

            return task

        task.status = "executing"
        task.started_at = time.time()

        logger.info(
            "JARVIS AGENT: "
            "Handing task to existing executor."
        )

        try:

            task.execution_result = self.executor(
                task.planner_result,
                active_context,
                task_state,
                speak_callback,
            )

            task.completed_at = time.time()

            result_text = str(
                task.execution_result or ""
            ).strip().lower()

            if result_text == "cancelled":

                task.status = "cancelled"

                for step in task.steps:
                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "cancelled"

            elif result_text == "done":

                task.status = "completed"

                for step in task.steps:
                    step.status = "completed"

            else:

                task.status = "failed"

                task.error = (
                    str(
                        task.execution_result
                        or "Executor reported a failure."
                    )
                )

                for step in task.steps:
                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "failed"
                        step.error = task.error

            self.state["last_result"] = (
                task.execution_result
            )

            self.state["last_status"] = (
                task.status
            )

            if task.status == "failed":
                self.state["last_error"] = (
                    task.error
                )

            logger.info(
                "JARVIS AGENT: "
                f"Execution finished with "
                f"status={task.status}"
            )

        except Exception as exc:

            task.completed_at = time.time()
            task.status = "failed"
            task.error = str(exc)

            self.state["last_error"] = str(exc)
            self.state["last_status"] = task.status

            for step in task.steps:
                if step.status in {
                    "pending",
                    "executing",
                }:
                    step.status = "failed"
                    step.error = str(exc)

            logger.exception(
                "JARVIS AGENT: Execution failed"
            )

        return task

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
        )

        return task

    # ======================================================
    # Summary
    # ======================================================

    def summarize(
        self,
        task: Optional[AgentTask] = None,
    ) -> Dict[str, Any]:

        task = task or self.current_task

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
            "duration": max(
                0.0,
                end - start,
            ),
            "result": task.execution_result,
            "error": task.error,
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

    # Use the real JARVIS state objects.
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
            text
        )

    agent = build_agent()

    task = agent.run(
        "Click the first result",
        active_context=active_context,
        task_state=task_state,
        speak_callback=test_speak,
    )

    print()
    print("========== AGENT SUMMARY ==========")
    print(agent.summarize(task))
    print("====================================")

    print()
    print("Active context after execution:")
    print(active_context)

    print()
    print("Task state after execution:")
    print(task_state)
