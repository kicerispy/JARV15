import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_memory
import tools


class JarvisPlatformToolsTests(unittest.TestCase):
    def test_memory_tools_are_exposed_through_public_dispatcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(local_memory, "_MEMORY_PATH", Path(tmp) / "memory.jsonl"),                  patch.object(local_memory, "_MEMORY_DIR", Path(tmp)):
                stored = tools.execute_tool(
                    "memory_remember",
                    json.dumps({
                        "text": "JARVIS test memory",
                        "kind": "lesson",
                    }),
                )
                self.assertTrue(stored.success)

                recalled = tools.execute_tool(
                    "memory_recall",
                    json.dumps({"query": "JARVIS test memory"}),
                )
                self.assertTrue(recalled.success)
                self.assertEqual(len(recalled.data["results"]), 1)

    def test_tool_health_is_available(self):
        result = tools.execute_tool("tool_health")
        self.assertTrue(result.success)
        self.assertIn("tool_count", result.data)


if __name__ == "__main__":
    unittest.main()
