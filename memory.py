"""
JARVIS persistent memory using SQLite.
"""
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from config import DATABASE_PATH


class Memory:
    """Manages JARVIS's persistent memory using SQLite."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DATABASE_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self.create_memory()

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def create_memory(self) -> None:
        """Initialize the memories table if it doesn't exist."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory ON memories(memory)")
            conn.commit()
        finally:
            conn.close()

    def _normalize(self, text: str) -> str:
        """Normalize text for duplicate checking."""
        return " ".join(text.strip().lower().split())

    def memory_exists(self, text: str) -> bool:
        """Check if a memory already exists (case-insensitive)."""
        normalized = self._normalize(text)
        cursor = self.conn.execute(
            "SELECT 1 FROM memories WHERE LOWER(memory) = ? LIMIT 1",
            (normalized,)
        )
        return cursor.fetchone() is not None

    def save_memory(self, text: str) -> bool:
        """Save a memory if it doesn't already exist."""
        if not text or not text.strip():
            return False

        if self.memory_exists(text):
            return False

        try:
            self.conn.execute(
                "INSERT INTO memories (memory) VALUES (?)",
                (text.strip(),)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_memories(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Tuple[str]]:
        """Get memories, optionally limited. Returns list of (memory,) tuples."""
        query = "SELECT memory FROM memories ORDER BY id DESC"
        params: List[int] = []

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        if offset is not None:
            if limit is None:
                query += " LIMIT -1"
            query += " OFFSET ?"
            params.append(offset)

        cursor = self.conn.execute(query, params)
        memories = cursor.fetchall()
        memories.reverse()  # Return in chronological order
        return memories

    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory by ID."""
        cursor = self.conn.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def clear_all(self) -> int:
        """Delete all memories. Returns count deleted."""
        cursor = self.conn.execute("DELETE FROM memories")
        self.conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        """Get total memory count."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM memories")
        return cursor.fetchone()[0]


# Global memory instance
memory = Memory()


def create_memory() -> None:
    """Initialize memory (kept for backward compatibility)."""
    memory.create_memory()


def save_memory(text: str) -> bool:
    """Save a memory."""
    return memory.save_memory(text)


def get_memories(limit: Optional[int] = None) -> List[Tuple[str]]:
    """Get memories."""
    return memory.get_memories(limit=limit)


def memory_exists(text: str) -> bool:
    """Check if memory exists."""
    return memory.memory_exists(text)


def delete_memory(memory_id: int) -> bool:
    """Delete a memory by ID."""
    return memory.delete_memory(memory_id)
