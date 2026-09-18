"""
JARVIS background task controller.

Runs Agent Core work in a daemon worker so the main voice/UI loop stays
responsive. Cancellation is cooperative: the currently running tool is
allowed to return, then the executor stops before another step begins.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from logger import logger


_STATUS_PHRASES = (
    "what are you doing",
    "what are you working on",
    "what are you doing right now",
    "what's going on",
    "whats going on",
    "what is going on",
    "how is it going",
    "how's it going",
    "hows it going",
    "what step are you on",
    "what step are you at",
    "what's the status",
    "whats the status",
    "status",
    "are you still working",
    "are you still working on it",
)


def is_task_status_request(text: str) -> bool:
    """Return True for short deterministic background-task status requests."""
    normalized = " ".join(str(text or "").strip().lower().split())
    return normalized in _STATUS_PHRASES


class BackgroundTaskController:
    """Owns at most one active Agent Core task at a time."""

    def __init__(self, agent: Any):
        self.agent = agent
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._task: Any = None
        self._task_state: Any = None
        self._last_task: Any = None

    def _is_running_locked(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def has_active_task(self) -> bool:
        with self._lock:
            if not self._is_running_locked():
                return False
            return self._task is not None

    def start(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        speak_callback: Any,
        history_text: str = "",
    ) -> bool:
        """Start a queued task without blocking the caller."""
        if task is None:
            return False

        with self._lock:
            if self._is_running_locked() or self._task is not None:
                return False

            description = str(
                getattr(task, "goal", "")
                or getattr(task, "request", "")
                or "background task"
            ).strip()

            steps = list(
                getattr(task, "steps", [])
                or []
            )

            task.status = "queued"
            task.started_at = None

            if hasattr(task_state, "prepare"):
                task_state.prepare(
                    description=description,
                    total_steps=len(steps),
                )

            self._task = task
            self._task_state = task_state

            thread = threading.Thread(
                target=self._run,
                args=(
                    task,
                    active_context,
                    task_state,
                    speak_callback,
                    history_text,
                ),
                name="JARVIS-TaskController",
                daemon=True,
            )

            self._thread = thread
            thread.start()

            logger.info(
                "JARVIS TASK CONTROLLER: "
                f"Started background task {getattr(task, 'task_id', '')}"
            )

            return True

    def _run(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        speak_callback: Any,
        history_text: str,
    ) -> None:
        """Worker entry point."""
        try:
            if task_state.is_cancelled():
                task.status = "cancelled"
                task.completed_at = time.time()
                return

            completed_task = self.agent.execute_task(
                task,
                active_context,
                task_state,
                speak_callback,
                history_text=history_text,
            )

            if completed_task is not None:
                task = completed_task

        except Exception as exc:
            logger.exception(
                "JARVIS TASK CONTROLLER: "
                "Background task crashed"
            )

            task.status = "failed"
            task.error = str(exc)
            task.completed_at = time.time()

            try:
                task_state.fail(str(exc))
            except Exception:
                pass

            try:
                if speak_callback:
                    speak_callback(
                        "I wasn't able to complete the task."
                    )
            except Exception:
                pass

        finally:
            with self._lock:
                self._last_task = task
                if self._task is task:
                    self._task = None
                    self._task_state = None
                self._thread = None

            logger.info(
                "JARVIS TASK CONTROLLER: "
                f"Background task finished with status="
                f"{getattr(task, 'status', 'unknown')}"
            )

    def cancel_current(self) -> bool:
        """Request cooperative cancellation of the active task."""
        with self._lock:
            task = self._task
            task_state = self._task_state

            if task is None or not self._is_running_locked():
                return False

            task.status = "cancellation_requested"
            task.error = "Cancellation requested by the user."

        try:
            task_state.cancel()
        except Exception as exc:
            logger.warning(
                f"JARVIS TASK CONTROLLER: Cancellation error: {exc}"
            )

        logger.info(
            "JARVIS TASK CONTROLLER: "
            f"Cancellation requested for {getattr(task, 'task_id', '')}"
        )
        return True

    def snapshot(self) -> Dict[str, Any]:
        """Return a thread-safe best-effort task snapshot."""
        with self._lock:
            task = self._task or self._last_task
            task_state = self._task_state

            snapshot: Dict[str, Any] = {
                "active": self._is_running_locked() and self._task is not None,
                "task_id": getattr(task, "task_id", None),
                "request": getattr(task, "request", ""),
                "goal": getattr(task, "goal", ""),
                "task_status": getattr(task, "status", "none"),
                "replan_count": getattr(task, "replan_count", 0),
                "current_step": getattr(task, "current_step", -1),
                "total_steps": len(getattr(task, "steps", []) or []),
                "error": getattr(task, "error", None),
            }

        if task_state is not None:
            try:
                snapshot.update(
                    {
                        "state": task_state.to_dict(),
                    }
                )
            except Exception:
                pass

        return snapshot

    def status_message(self) -> str:
        """Create a concise natural-language status response."""
        snapshot = self.snapshot()

        if snapshot.get("active"):
            state = snapshot.get("state", {})
            status = str(
                state.get(
                    "status",
                    snapshot.get("task_status", "working"),
                )
            )

            if (
                snapshot.get("task_status")
                == "cancellation_requested"
                or state.get("cancelled")
            ):
                return "I'm stopping the current task."

            if status == "starting":
                return "I'm getting that task underway."

            current = int(
                state.get(
                    "current_step",
                    0,
                )
                or 0
            )

            total = int(
                state.get(
                    "total_steps",
                    snapshot.get("total_steps", 0),
                )
                or 0
            )

            tool = str(
                state.get(
                    "current_tool",
                    "",
                )
                or ""
            ).strip()

            if total > 0 and current > 0:
                if tool:
                    return (
                        f"I'm working on it. "
                        f"I'm on step {current} of {total}."
                    )

                return (
                    f"I'm working on it. "
                    f"I'm on step {current} of {total}."
                )

            if snapshot.get("task_status") == "cancellation_requested":
                return "I'm stopping the current task."

            return "I'm working on it now."

        last_status = str(
            snapshot.get(
                "task_status",
                "none",
            )
            or "none"
        )

        if last_status == "completed":
            return "The last background task is complete."

        if last_status == "cancelled":
            return "The last background task was cancelled."

        if last_status == "failed":
            return "The last background task did not complete."

        return "I'm not currently running a background task."

    def wait_for_current(self, timeout: Optional[float] = None) -> bool:
        """Wait for the active worker to finish. Intended for tests/shutdown."""
        with self._lock:
            thread = self._thread

        if thread is None:
            return True

        thread.join(timeout=timeout)
        return not thread.is_alive()
