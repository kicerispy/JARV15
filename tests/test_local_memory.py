import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_memory


class LocalMemoryTests(unittest.TestCase):
    def test_remember_recall_and_forget_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            memory_dir = Path(tmp)

            with patch.object(local_memory, "_MEMORY_PATH", path),                  patch.object(local_memory, "_MEMORY_DIR", memory_dir):
                stored = local_memory.remember(
                    "Jordan prefers concise spoken confirmations.",
                    kind="preference",
                    tags=["voice", "qol"],
                )
                self.assertTrue(stored["success"])

                results = local_memory.recall("concise spoken confirmations", limit=3)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["kind"], "preference")

                forgotten = local_memory.forget("concise spoken confirmations")
                self.assertEqual(forgotten["removed"], 1)
                self.assertEqual(local_memory.recall("concise spoken confirmations"), [])

    def test_fts5_index_is_created_and_used_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            memory_dir = Path(tmp)

            with patch.object(local_memory, "_MEMORY_PATH", path), \
                 patch.object(local_memory, "_MEMORY_DIR", memory_dir):
                stored = local_memory.remember(
                    "JARVIS should prefer a local recovery playbook before retrying blindly.",
                    kind="lesson",
                    tags=["healing", "recovery"],
                )
                self.assertTrue(stored["success"])

                status = local_memory.memory_status()
                if status["fts5_enabled"]:
                    self.assertTrue(
                        Path(status["fts5_index"]).exists()
                    )

                results = local_memory.recall(
                    "local recovery playbook",
                    limit=3,
                )
                self.assertTrue(results)
                self.assertEqual(results[0]["kind"], "lesson")

    def test_memory_deduplicates_exact_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            with patch.object(local_memory, "_MEMORY_PATH", path),                  patch.object(local_memory, "_MEMORY_DIR", Path(tmp)):
                local_memory.remember("Use qwen for normal chat.", kind="procedure")
                local_memory.remember("Use qwen for normal chat.", kind="procedure")
                status = local_memory.memory_status()
                self.assertEqual(status["records"], 1)


if __name__ == "__main__":
    unittest.main()
