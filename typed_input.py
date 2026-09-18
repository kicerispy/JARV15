"""Non-blocking console text input channel for JARVIS."""

from __future__ import annotations

import queue
import threading
from typing import Optional


class TypedInputChannel:
    """Read console commands on a daemon thread without blocking JARVIS."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self._queue: "queue.Queue[str]" = queue.Queue()
        self.interrupt_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start the console reader when enabled and not already running."""
        if not self.enabled or (
            self._thread is not None
            and self._thread.is_alive()
        ):
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader,
            name="jarvis-typed-input",
            daemon=True,
        )
        self._thread.start()
        return True

    def _reader(self) -> None:
        print(
            "[JARVIS] Typing input enabled. "
            "Type a command and press Enter.",
            flush=True,
        )

        while not self._stop_event.is_set():
            try:
                value = input("JARVIS > ")
            except EOFError:
                return
            except KeyboardInterrupt:
                continue
            except Exception:
                return

            command = str(value or "").strip()
            if not command:
                continue

            self._queue.put(command)
            self.interrupt_event.set()

    def get_nowait(self) -> Optional[str]:
        """Return the next typed command, or None when the queue is empty."""
        try:
            command = self._queue.get_nowait()
        except queue.Empty:
            return None

        if self._queue.empty():
            self.interrupt_event.clear()

        return command

    def has_pending(self) -> bool:
        """Return whether one or more typed commands are queued."""
        return not self._queue.empty()

    def stop(self) -> None:
        """Stop the reader thread. The daemon thread will exit with JARVIS."""
        self._stop_event.set()
        self.interrupt_event.set()

    def enqueue_for_test(self, command: str) -> None:
        """Inject a command for tests without touching stdin."""
        value = str(command or "").strip()
        if not value:
            return
        self._queue.put(value)
        self.interrupt_event.set()
