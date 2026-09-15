"""
Tests for JARVIS memory module.
"""
import os
import tempfile
import pytest
from pathlib import Path

from memory import Memory


@pytest.fixture
def memory():
    """Create a Memory instance with a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    
    mem = Memory(db_path=db_path)
    yield mem
    
    mem.close()
    if db_path.exists():
        db_path.unlink()


class TestMemory:
    """Tests for the Memory class."""

    def test_create_memory_table(self, memory):
        """Test that the memories table is created."""
        # Should not raise an error
        memory.create_memory()

    def test_save_and_get_memory(self, memory):
        """Test saving and retrieving a memory."""
        result = memory.save_memory("Test memory")
        assert result is True
        
        memories = memory.get_memories()
        assert len(memories) == 1
        assert memories[0][0] == "Test memory"

    def test_save_empty_memory(self, memory):
        """Test that empty memories are rejected."""
        result = memory.save_memory("")
        assert result is False
        
        result = memory.save_memory("   ")
        assert result is False

    def test_save_duplicate_memory(self, memory):
        """Test that duplicate memories are rejected."""
        memory.save_memory("Test memory")
        result = memory.save_memory("Test memory")
        assert result is False

    def test_case_insensitive_duplicate(self, memory):
        """Test that duplicates are detected case-insensitively."""
        memory.save_memory("Test memory")
        result = memory.save_memory("test memory")
        assert result is False

    def test_memory_exists(self, memory):
        """Test memory_exists method."""
        memory.save_memory("Test memory")
        assert memory.memory_exists("Test memory") is True
        assert memory.memory_exists("test memory") is True
        assert memory.memory_exists("Other memory") is False

    def test_get_memories_with_limit(self, memory):
        """Test getting memories with a limit."""
        for i in range(5):
            memory.save_memory(f"Memory {i}")
        
        memories = memory.get_memories(limit=3)
        assert len(memories) == 3

    def test_delete_memory(self, memory):
        """Test deleting a memory."""
        memory.save_memory("Test memory")
        
        # Get the actual ID
        import sqlite3
        conn = sqlite3.connect(str(memory.db_path))
        cursor = conn.execute("SELECT id FROM memories")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            result = memory.delete_memory(row[0])
            assert result is True
            assert memory.count() == 0

    def test_clear_all(self, memory):
        """Test clearing all memories."""
        memory.save_memory("Memory 1")
        memory.save_memory("Memory 2")
        
        count = memory.clear_all()
        assert count == 2
        assert memory.count() == 0

    def test_count(self, memory):
        """Test counting memories."""
        assert memory.count() == 0
        
        memory.save_memory("Memory 1")
        assert memory.count() == 1
        
        memory.save_memory("Memory 2")
        assert memory.count() == 2