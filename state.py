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

    def update(
        self,
        site: Optional[str] = None,
        last_query: Optional[str] = None,
        last_tool: Optional[str] = None,
        last_result: Optional[str] = None
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

    def clear(self) -> None:
        """Reset all context fields."""
        self.site = None
        self.last_query = None
        self.last_tool = None
        self.last_result = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Convert to dictionary."""
        return {
            "site": self.site,
            "last_query": self.last_query,
            "last_tool": self.last_tool,
            "last_result": self.last_result,
        }


@dataclass
class TaskState:
    """Tracks the current task execution state."""
    active: bool = False
    cancelled: bool = False
    description: Optional[str] = None
    total_steps: int = 0
    current_step: int = 0
    current_tool: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, description: str, total_steps: int) -> None:
        """Start a new task."""
        with self._lock:
            self.active = True
            self.cancelled = False
            self.description = description
            self.total_steps = total_steps
            self.current_step = 0
            self.current_tool = None

    def update_step(self, step_number: int, tool_name: str) -> None:
        """Update the current step progress."""
        with self._lock:
            self.current_step = step_number
            self.current_tool = tool_name

    def cancel(self) -> None:
        """Mark the current task as cancelled."""
        with self._lock:
            self.cancelled = True

    def finish(self) -> None:
        """Mark the current task as finished."""
        with self._lock:
            self.active = False
            self.cancelled = False
            self.description = None
            self.total_steps = 0
            self.current_step = 0
            self.current_tool = None

    def is_cancelled(self) -> bool:
        """Check if the task has been cancelled."""
        with self._lock:
            return self.cancelled

    def is_active(self) -> bool:
        """Check if a task is currently active."""
        with self._lock:
            return self.active


class JarvisState:
    """Centralized state for JARVIS."""

    def __init__(self) -> None:
        self.active_context = ActiveContext()
        self.task_state = TaskState()
        self.pending_input: Optional[str] = None
        self.continuous_mode: bool = False

    def reset(self) -> None:
        """Reset all state."""
        self.active_context.clear()
        self.task_state.finish()
        self.pending_input = None
        self.continuous_mode = False