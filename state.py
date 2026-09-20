"""
JARVIS state management - replaces global variables in main.py.
"""
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActiveContext:
    """Tracks the current active task context for follow-up resolution."""
    site: Optional[str] = None
    last_query: Optional[str] = None
    last_tool: Optional[str] = None
    last_result: Optional[str] = None

    # Raw structured result from the most recent useful/query tool.
    # Kept separate from last_result so existing spoken/planner context
    # remains lightweight.
    last_result_data: Any = None
    last_result_index: Optional[int] = None
    last_selected_result: Any = None

    page_url: Optional[str] = None
    page_title: Optional[str] = None
    last_result_title: Optional[str] = None
    last_result_url: Optional[str] = None
    last_element: Optional[str] = None
    last_action: Optional[str] = None

    def update(
        self,
        site: Optional[str] = None,
        last_query: Optional[str] = None,
        last_tool: Optional[str] = None,
        last_result: Optional[str] = None,
        last_result_data: Any = None,
        last_result_index: Optional[int] = None,
        last_selected_result: Any = None,
        page_url: Optional[str] = None,
        page_title: Optional[str] = None,
        last_result_title: Optional[str] = None,
        last_result_url: Optional[str] = None,
        last_element: Optional[str] = None,
        last_action: Optional[str] = None,
    ) -> None:
        """Update context fields. None means no change."""
        if site is not None:
            self.site = site
        if last_query is not None:
            self.last_query = last_query
        if last_tool is not None:
            self.last_tool = last_tool
        if last_result is not None:
            self.last_result = last_result
        if last_result_data is not None:
            self.last_result_data = last_result_data
        if page_url is not None:
            self.page_url = page_url
        if page_title is not None:
            self.page_title = page_title
        if last_result_title is not None:
            self.last_result_title = last_result_title
        if last_result_url is not None:
            self.last_result_url = last_result_url
        if last_element is not None:
            self.last_element = last_element
        if last_action is not None:
            self.last_action = last_action

    def clear(self) -> None:
        """Reset all context fields."""
        self.site = None
        self.last_query = None
        self.last_tool = None
        self.last_result = None
        self.last_result_data = None
        self.last_result_index = None
        self.last_selected_result = None
        self.page_url = None
        self.page_title = None
        self.last_result_title = None
        self.last_result_url = None
        self.last_element = None
        self.last_action = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "site": self.site,
            "last_query": self.last_query,
            "last_tool": self.last_tool,
            "last_result": self.last_result,
            "last_result_data": self.last_result_data,
            "last_result_index": self.last_result_index,
            "last_selected_result": self.last_selected_result,
            "last_result_index": self.last_result_index,
            "last_selected_result": self.last_selected_result,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "last_result_title": self.last_result_title,
            "last_result_url": self.last_result_url,
            "last_element": self.last_element,
            "last_action": self.last_action,
        }


@dataclass
class TaskState:
    """Tracks the current task execution state."""
    active: bool = False
    cancelled: bool = False
    status: str = "pending"
    description: Optional[str] = None
    total_steps: int = 0
    current_step: int = 0
    current_tool: Optional[str] = None
    last_result: Any = None
    last_error: Optional[str] = None
    attempts: int = 0
    recovery_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _progress_callback: Any = field(default=None, repr=False, compare=False)
    _last_progress_key: Optional[str] = field(default=None, repr=False, compare=False)
    completion_spoken: bool = False
    background_speech_owned: bool = False
    final_speech: Optional[str] = None

    def prepare(self, description: str, total_steps: int) -> None:
        """Reserve the task state for a queued background task."""
        with self._lock:
            self.active = True
            self.cancelled = False
            self.status = "starting"
            self.description = description
            self.total_steps = total_steps
            self.current_step = 0
            self.current_tool = None
            self.last_result = None
            self.last_error = None
            self.attempts = 0
            self.recovery_count = 0
            self._last_progress_key = None
            self.completion_spoken = False
            self.background_speech_owned = False
            self.final_speech = None

    def start(self, description: str, total_steps: int) -> bool:
        """Start a task unless cancellation was requested while it was queued."""
        with self._lock:
            if self.status == "cancelled" and self.cancelled:
                self.active = False
                return False

            self.active = True
            self.cancelled = False
            self.status = "running"
            self.description = description
            self.total_steps = total_steps
            self.current_step = 0
            self.current_tool = None
            self.last_result = None
            self.last_error = None
            self.attempts = 0
            self.recovery_count = 0
            self._last_progress_key = None
            self.completion_spoken = False
            self.background_speech_owned = False
            self.final_speech = None
            return True

    def update_step(self, step_number: int, tool_name: str) -> None:
        """Update the current step progress."""
        with self._lock:
            self.current_step = step_number
            self.current_tool = tool_name
            self.attempts = 0

    def set_progress_callback(self, callback: Any) -> None:
        """Set a callback used for user-facing task milestone updates."""
        with self._lock:
            self._progress_callback = callback

    def report_progress(
        self,
        message: str,
        key: Optional[str] = None,
    ) -> None:
        """Report a milestone update once per logical progress stage."""
        if not message:
            return

        text = str(message).strip()
        if not text:
            return

        progress_key = str(
            key if key is not None else text
        ).strip().lower()

        with self._lock:
            if progress_key == self._last_progress_key:
                return

            self._last_progress_key = progress_key
            callback = self._progress_callback

        if callback is not None:
            try:
                callback(text)
            except Exception:
                pass

    def record_result(self, result: Any) -> None:
        """Record the latest tool result."""
        with self._lock:
            self.last_result = result
            self.last_error = None

    def record_error(self, error: str) -> None:
        """Record the latest task error."""
        with self._lock:
            self.last_error = str(error)
            self.last_result = None

    def record_attempt(self) -> None:
        """Record another attempt for the current step."""
        with self._lock:
            self.attempts += 1

    def record_recovery(self) -> None:
        """Record a recovery attempt."""
        with self._lock:
            self.recovery_count += 1

    def mark_completion_spoken(self) -> None:
        """Record that a final user-facing completion message was delivered."""
        with self._lock:
            self.completion_spoken = True

    def set_background_speech_owned(self, enabled: bool) -> None:
        """Select whether the background controller owns final-result speech."""
        with self._lock:
            self.background_speech_owned = bool(enabled)

    def is_background_speech_owned(self) -> bool:
        """Return whether final-result speech is owned by the controller."""
        with self._lock:
            return self.background_speech_owned

    def set_final_speech(self, message: Optional[str]) -> None:
        """Store the final user-facing message for background delivery."""
        text = str(message or "").strip()
        with self._lock:
            self.final_speech = text or None

    def has_pending_final_speech(self) -> bool:
        """Return whether a final user-facing message is awaiting delivery."""
        with self._lock:
            return bool(self.final_speech)

    def take_final_speech(self) -> Optional[str]:
        """Take and clear the final user-facing message atomically."""
        with self._lock:
            message = self.final_speech
            self.final_speech = None
            return message

    def clear_final_speech(self) -> None:
        """Clear any staged final user-facing message."""
        with self._lock:
            self.final_speech = None

    def was_completion_spoken(self) -> bool:
        """Return whether a final user-facing completion message was delivered."""
        with self._lock:
            return self.completion_spoken

    def complete(self) -> None:
        """Mark the current task as completed."""
        with self._lock:
            self.active = False
            self.cancelled = False
            self.status = "completed"

    def fail(self, error: Optional[str] = None) -> None:
        """Mark the current task as failed."""
        with self._lock:
            self.active = False
            self.cancelled = False
            self.status = "failed"
            if error is not None:
                self.last_error = str(error)

    def cancel(self) -> None:
        """Mark the current task as cancelled."""
        with self._lock:
            self.cancelled = True
            self.status = "cancelled"

    def finish(self) -> None:
        """Finish the task while preserving its final state."""
        with self._lock:
            if self.cancelled:
                self.status = "cancelled"
            elif self.status in {"running", "starting"}:
                self.status = "completed"

            self.active = False

    def is_cancelled(self) -> bool:
        """Check if the task has been cancelled."""
        with self._lock:
            return self.cancelled

    def is_active(self) -> bool:
        """Check if a task is currently active."""
        with self._lock:
            return self.active

    def to_dict(self) -> Dict[str, Any]:
        """Return a snapshot of the current task state."""
        with self._lock:
            return {
                "active": self.active,
                "cancelled": self.cancelled,
                "status": self.status,
                "description": self.description,
                "total_steps": self.total_steps,
                "current_step": self.current_step,
                "current_tool": self.current_tool,
                "last_result": self.last_result,
                "last_error": self.last_error,
                "attempts": self.attempts,
                "recovery_count": self.recovery_count,
            }


class JarvisState:
    """Centralized state for JARVIS."""

    def __init__(self) -> None:
        self.active_context = ActiveContext()
        self.task_state = TaskState()
        self.pending_input: Optional[str] = None
        self.continuous_mode: bool = False

        # Serialize microphone capture and TTS so background
        # task announcements cannot talk over the listener.
        self.io_lock = threading.RLock()

        # Initialized by main.py after JarvisAgent is created.
        self.task_controller: Any = None

    def reset(self) -> None:
        """Reset all state."""
        self.active_context.clear()
        self.task_state.finish()
        self.pending_input = None
        self.continuous_mode = False
