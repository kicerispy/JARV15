"""
JARVIS conversation history management.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from config import CONVERSATION_HISTORY_PATH, MAX_HISTORY_FILE_SIZE
from logger import logger


class ConversationHistory:
    """Manages conversation history with file persistence and in-memory caching."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else CONVERSATION_HISTORY_PATH
        self._max_size = MAX_HISTORY_FILE_SIZE
        self._history: List[Dict[str, str]] = []
        self._loaded = False
        self._load_cached()

    def _load_cached(self) -> None:
        """Load history from file into memory cache (called once)."""
        if not self.path.exists():
            self._history = []
            self._loaded = True
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._history = data
            else:
                self._history = []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load conversation history: {e}")
            self._history = []
        self._loaded = True

    def reload(self) -> List[Dict[str, str]]:
        """Force a reload from disk, discarding any in-memory changes."""
        self._loaded = False
        self._load_cached()
        return self._history

    @property
    def history(self) -> List[Dict[str, str]]:
        """Get the in-memory history list."""
        if not self._loaded:
            self._load_cached()
        return self._history

    def load_history(self) -> List[Dict[str, str]]:
        """Load conversation history (from cache, reload=False by default)."""
        if not self._loaded:
            self._load_cached()
        return self._history

    def save_history(self, history: List[Dict[str, str]]) -> bool:
        """Replace the in-memory history and persist to file."""
        if len(history) > self._max_size:
            history = history[-self._max_size:]

        self._history = history
        self._loaded = True

        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=4, ensure_ascii=False)
            return True
        except OSError as e:
            logger.error(f"Failed to save conversation history: {e}")
            return False

    def add_message(self, role: str, content: str) -> bool:
        """Add a message to the in-memory history and persist to file."""
        if not role or not content:
            return False

        self._history.append({"role": role, "content": content})

        if len(self._history) > self._max_size:
            self._history = self._history[-self._max_size:]

        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=4, ensure_ascii=False)
            return True
        except OSError as e:
            logger.error(f"Failed to save conversation history: {e}")
            return False

    def get_history(self) -> List[Dict[str, str]]:
        """Get the full conversation history (from cache)."""
        if not self._loaded:
            self._load_cached()
        return self._history

    def clear(self) -> bool:
        """Clear all conversation history."""
        self._history = []
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return True
        except OSError as e:
            logger.error(f"Failed to clear conversation history: {e}")
            return False

    def get_recent(self, limit: int = 10) -> List[Dict[str, str]]:
        """Get the most recent messages (from cache, no disk I/O)."""
        if not self._loaded:
            self._load_cached()
        if not self._history:
            return []
        return self._history[-limit:]


conversation = ConversationHistory()


def load_history() -> List[Dict[str, str]]:
    """Load conversation history (backward compatibility)."""
    return conversation.load_history()


def save_history(history: List[Dict[str, str]]) -> bool:
    """Save conversation history."""
    return conversation.save_history(history)


def add_message(role: str, content: str) -> bool:
    """Add a message to history."""
    return conversation.add_message(role, content)


def get_history() -> List[Dict[str, str]]:
    """Get conversation history."""
    return conversation.get_history()


def get_recent(limit: int = 10) -> List[Dict[str, str]]:
    """Get the most recent messages."""
    return conversation.get_recent(limit=limit)
