"""
JARVIS background task controller.

Runs Agent Core planning and execution in a daemon worker so the main voice/UI
loop stays responsive. Speech produced by the worker is queued and drained by
the main loop so TTS never talks over microphone capture.
"""

from __future__ import annotations

import threading
import time
import inspect
from queue import Empty, Queue
from typing import Any, Callable, Dict, Optional

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


_TASK_ACKNOWLEDGEMENT_PHRASES = (
    "ok",
    "okay",
    "all right",
    "alright",
    "got it",
    "understood",
    "sounds good",
    "sure",
    "thanks",
    "thank you",
)


def is_task_acknowledgement(text: str) -> bool:
    """Return True for short conversational acknowledgements while a task runs."""
    normalized = " ".join(str(text or "").strip().lower().split())
    return normalized in _TASK_ACKNOWLEDGEMENT_PHRASES


class BackgroundTaskController:
    """Owns at most one active Agent Core task at a time."""

    def __init__(self, agent: Any):
        self.agent = agent
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._task: Any = None
        self._task_state: Any = None
        self._last_task: Any = None

        self._speech_queue: Queue[str] = Queue()
        self._pending_speech_count = 0
        self._last_pending_message = ""
        # Track messages already delivered for the current task. The queue
        # de-duplication above only covers messages that are waiting; this set
        # also prevents the same completion from being spoken again after the
        # first copy has already been drained.
        self._task_spoken_messages: set[str] = set()
        self._completion_event = threading.Event()

    def _is_running_locked(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def has_active_task(self) -> bool:
        with self._lock:
            return (
                self._is_running_locked()
                and self._task is not None
            )

    def _begin(
        self,
        task: Any,
        task_state: Any,
        thread_target: Callable[..., None],
        thread_args: tuple,
        initial_message: str = "",
    ) -> bool:
        """Reserve the controller and launch a daemon worker."""
        with self._lock:
            if self._is_running_locked() or self._task is not None:
                return False

            self._task = task
            self._task_state = task_state
            self._task_spoken_messages.clear()
            self._completion_event.clear()

            thread = threading.Thread(
                target=thread_target,
                args=thread_args,
                name="JARVIS-TaskController",
                daemon=True,
            )

            self._thread = thread

            if initial_message:
                self._queue_speech(initial_message)

            thread.start()

            logger.info(
                "JARVIS TASK CONTROLLER: "
                f"Started background task "
                f"{getattr(task, 'task_id', '')}"
            )

            return True

    def start(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        speak_callback: Any,
        history_text: str = "",
    ) -> bool:
        """Start an already-planned task without blocking the caller."""
        if task is None:
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

        return self._begin(
            task,
            task_state,
            self._run,
            (
                task,
                active_context,
                task_state,
                history_text,
            ),
        )

    def start_planning(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        history_text: str = "",
    ) -> bool:
        """Plan and execute a task entirely in the background."""
        if task is None:
            return False

        description = str(
            getattr(task, "request", "")
            or "background task"
        ).strip()

        task.status = "planning"
        task.started_at = None
        task.initial_acknowledged = True

        if hasattr(task_state, "prepare"):
            task_state.prepare(
                description=description,
                total_steps=0,
            )

        return self._begin(
            task,
            task_state,
            self._run_planning,
            (
                task,
                active_context,
                task_state,
                history_text,
            ),
            initial_message="On it.",
        )

    @property
    def completion_event(self) -> threading.Event:
        """Event set when the current background task finishes."""
        return self._completion_event

    def clear_completion_signal(self) -> None:
        """Clear a previously observed task-completion signal."""
        self._completion_event.clear()

    def consume_completion_signal(self) -> bool:
        """Return whether a task completed, then clear the signal."""
        with self._lock:
            was_set = self._completion_event.is_set()
            if was_set:
                self._completion_event.clear()
            return was_set

    def prepare_followup_wait(self) -> tuple[Optional[threading.Event], bool]:
        """Prepare a race-free wait for a background task to finish.

        Returns (event, False) when a task is still running. Returns
        (None, True) when completion was already signalled. Returns
        (None, False) when there is no active task and no new completion.
        """
        with self._lock:
            if self._is_running_locked() and self._task is not None:
                self._completion_event.clear()
                return self._completion_event, False

            completed = self._completion_event.is_set()
            if completed:
                self._completion_event.clear()
            return None, completed

    def _clear_pending_speech_locked(self) -> int:
        """Discard queued worker speech while the controller lock is held."""
        cleared = 0

        while True:
            try:
                self._speech_queue.get_nowait()
            except Empty:
                break

            self._speech_queue.task_done()
            cleared += 1

        self._pending_speech_count = 0
        self._last_pending_message = ""
        return cleared

    def clear_pending_speech(self) -> int:
        """Discard worker speech that has not started playing yet."""
        with self._lock:
            return self._clear_pending_speech_locked()

    def _queue_speech(self, message: str) -> bool:
        """Queue worker speech for safe playback by the main loop."""
        text = str(message or "").strip()

        if not text:
            return False

        with self._lock:
            task_state = self._task_state

            if task_state is not None:
                try:
                    if task_state.is_cancelled():
                        return False
                except Exception:
                    pass

            if text in self._task_spoken_messages:
                return False

            if (
                self._pending_speech_count > 0
                and text == self._last_pending_message
            ):
                return False

            self._task_spoken_messages.add(text)
            self._last_pending_message = text
            self._pending_speech_count += 1

            if text.lower().startswith("found '") and "on the page." in text.lower():
                try:
                    stack = inspect.stack()[1:5]
                    callers = [
                        f"{frame_info.frame.f_code.co_filename.split(chr(92))[-1]}:"
                        f"{frame_info.lineno}::{frame_info.frame.f_code.co_name}"
                        for frame_info in stack
                    ]
                    logger.info(
                        "JARVIS TASK CONTROLLER: Queueing browser-find speech "
                        f"count={len(self._task_spoken_messages)} "
                        f"callers={' <- '.join(callers)}"
                    )
                except Exception:
                    pass

            self._speech_queue.put(text)

        return False

    def drain_speech(
        self,
        speak_callback: Any,
        max_messages: int = 8,
    ) -> int:
        """Play queued worker speech from the main voice/UI loop."""
        drained = 0

        while drained < max_messages:
            with self._lock:
                task_state = self._task_state

                if task_state is not None:
                    try:
                        if task_state.is_cancelled():
                            self._clear_pending_speech_locked()
                            break
                    except Exception:
                        pass

            try:
                message = self._speech_queue.get_nowait()
            except Empty:
                break

            with self._lock:
                self._pending_speech_count = max(
                    self._pending_speech_count - 1,
                    0,
                )
                if self._pending_speech_count == 0:
                    self._last_pending_message = ""

            try:
                if speak_callback:
                    speak_callback(message)
            except Exception as exc:
                logger.debug(
                    f"JARVIS TASK CONTROLLER: Queued speech failed: {exc}"
                )
            finally:
                self._speech_queue.task_done()

            drained += 1

        return drained

    @staticmethod
    def _background_speak(
        speak_callback: Any,
        message: str,
    ) -> bool:
        """Keep Agent Core's speech callback worker-safe."""
        try:
            return bool(
                speak_callback(message)
            )
        except Exception as exc:
            logger.debug(
                f"JARVIS TASK CONTROLLER: Background speech skipped: {exc}"
            )
            return False

    def _run(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        history_text: str,
    ) -> None:
        """Execute an already-planned task."""
        try:
            if task_state.is_cancelled():
                task.status = "cancelled"
                task.completed_at = time.time()
                task_state.finish()
                return

            completed_task = self.agent.execute_task(
                task,
                active_context,
                task_state,
                lambda message: self._background_speak(
                    self._queue_speech,
                    message,
                ),
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

            self._queue_speech(
                "I wasn't able to complete the task."
            )

        finally:
            self._finish_worker(task)

    def _run_planning(
        self,
        task: Any,
        active_context: Any,
        task_state: Any,
        history_text: str,
    ) -> None:
        """Plan first, then execute, without blocking the main loop."""
        worker_speak = lambda message: self._background_speak(
            self._queue_speech,
            message,
        )

        try:
            if task_state.is_cancelled():
                task.status = "cancelled"
                task.completed_at = time.time()
                task_state.finish()
                return

            planned = self.agent.plan_task(
                task,
                history_text=history_text,
            )

            if task_state.is_cancelled():
                task.status = "cancelled"
                task.completed_at = time.time()
                task_state.finish()
                return

            if planned.status == "conversation":
                task.status = "failed"
                task.error = (
                    "The planner classified an Agent-routed request "
                    "as conversation."
                )
                task.completed_at = time.time()
                task_state.fail(task.error)
                self._queue_speech(
                    "I couldn't create an action plan for that request."
                )
                return

            if not getattr(planned, "steps", None):
                task.status = "failed"
                task.error = (
                    "The planner returned no executable steps "
                    "for an action request."
                )
                task.completed_at = time.time()
                task_state.fail(task.error)
                self._queue_speech(
                    "I couldn't create an action plan for that request."
                )
                return

            if planned.status == "failed":
                task.completed_at = time.time()
                task_state.fail(
                    getattr(
                        planned,
                        "error",
                        "Planning failed.",
                    )
                )
                self._queue_speech(
                    "I wasn't able to create a valid plan for that task."
                )
                return

            completed_task = self.agent.execute_task(
                planned,
                active_context,
                task_state,
                worker_speak,
                history_text=history_text,
            )

            if completed_task is not None:
                task = completed_task

        except Exception as exc:
            logger.exception(
                "JARVIS TASK CONTROLLER: "
                "Background planning crashed"
            )

            task.status = "failed"
            task.error = str(exc)
            task.completed_at = time.time()

            try:
                task_state.fail(str(exc))
            except Exception:
                pass

            self._queue_speech(
                "I wasn't able to complete the task."
            )

        finally:
            self._finish_worker(task)

    def _finish_worker(self, task: Any) -> None:
        with self._lock:
            self._last_task = task

            if self._task is task:
                self._task = None
                self._task_state = None

            self._thread = None
            self._completion_event.set()

        try:
            from task_memory import record_task
            record_task(
                request=getattr(task, "request", ""),
                goal=getattr(task, "goal", ""),
                status=getattr(task, "status", ""),
                result=getattr(task, "execution_result", ""),
                error=getattr(task, "error", ""),
                replans=getattr(task, "replan_count", 0),
            )
        except Exception as exc:
            logger.debug(
                f"JARVIS TASK CONTROLLER: Task memory skipped: {exc}"
            )

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
                # Mark the task cancelled before releasing the controller
                # lock so no worker speech can slip into the queue after the
                # cancellation decision has been made.
                task_state.cancel()
            except Exception as exc:
                logger.warning(
                    f"JARVIS TASK CONTROLLER: Cancellation error: {exc}"
                )

            # Remove worker announcements already waiting in the queue.
            # The main loop will provide the single explicit cancellation
            # response instead of replaying stale progress afterward.
            self._clear_pending_speech_locked()

        logger.info(
            "JARVIS TASK CONTROLLER: "
            f"Cancellation requested for "
            f"{getattr(task, 'task_id', '')}"
        )
        return True

    def snapshot(self) -> Dict[str, Any]:
        """Return a thread-safe best-effort task snapshot."""
        with self._lock:
            task = self._task or self._last_task
            task_state = self._task_state

            snapshot: Dict[str, Any] = {
                "active": (
                    self._is_running_locked()
                    and self._task is not None
                ),
                "task_id": getattr(task, "task_id", None),
                "request": getattr(task, "request", ""),
                "goal": getattr(task, "goal", ""),
                "task_status": getattr(task, "status", "none"),
                "replan_count": getattr(task, "replan_count", 0),
                "current_step": getattr(task, "current_step", -1),
                "total_steps": len(
                    getattr(task, "steps", [])
                    or []
                ),
                "error": getattr(task, "error", None),
            }

        if task_state is not None:
            try:
                snapshot["state"] = task_state.to_dict()
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
            task_status = str(
                snapshot.get(
                    "task_status",
                    "working",
                )
            )

            if (
                task_status == "cancellation_requested"
                or state.get("cancelled")
            ):
                return "I'm stopping the current task."

            if (
                task_status == "planning"
                or status == "starting"
            ):
                return "I'm planning the task now."

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

            current_tool = str(
                state.get("current_tool", "") or ""
            ).strip()

            activity = {
                "code_checkpoint": "I'm creating a safety checkpoint.",
                "code_search": "I'm locating the relevant code.",
                "find_file": "I'm locating the relevant file.",
                "list_files": "I'm locating the relevant files.",
                "read_file": "I'm inspecting the relevant source.",
                "code_diagnose": "I'm checking what is actually failing.",
                "edit_file": "I'm applying the change.",
                "write_file": "I'm updating the code.",
                "delete_file": "I'm removing the requested code.",
                "code_test": "I'm validating the result.",
                "browser_connect": "I'm connecting to the browser.",
                "browser_search_google": "I'm searching the browser.",
                "browser_search_bing": "I'm searching the browser.",
                "browser_goto": "I'm navigating to the page.",
                "browser_click_first_result": "I'm interacting with the page.",
                "browser_click_first_bing_result": "I'm interacting with the page.",
                "browser_click_result": "I'm interacting with the page.",
                "browser_click_element": "I'm interacting with the page.",
                "browser_fill_element": "I'm filling in the page.",
                "browser_press_key": "I'm entering the requested input.",
                "browser_extract_text": "I'm reading the page.",
                "open_website": "I'm opening the website.",
                "open_program": "I'm opening the application.",
            }.get(
                current_tool,
                "",
            )

            if activity and total > 0 and current > 0:
                return (
                    f"{activity} "
                    f"I'm on step {current} of {total}."
                )

            if activity:
                return activity

            if total > 0 and current > 0:
                return (
                    f"I'm working on it. "
                    f"I'm on step {current} of {total}."
                )

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

        if last_status == "conversation":
            return "The last request was handled as conversation."

        if last_status == "failed":
            return "The last background task did not complete."

        return "I'm not currently running a background task."

    def wait_for_current(
        self,
        timeout: Optional[float] = None,
    ) -> bool:
        """Wait for the active worker to finish. Intended for tests/shutdown."""
        with self._lock:
            thread = self._thread

        if thread is None:
            return True

        thread.join(timeout=timeout)
        return not thread.is_alive()
