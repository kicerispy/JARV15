import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import resilience_kernel


class RuntimeResilienceTests(unittest.TestCase):
    def test_circuit_opens_after_repeated_failures_and_success_resets_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tool_health.json"
            with patch.object(resilience_kernel, "_HEALTH_PATH", path),                  patch.object(resilience_kernel, "_MEMORY_DIR", Path(tmp)),                  patch.object(config, "TOOL_CIRCUIT_FAILURE_THRESHOLD", 2),                  patch.object(config, "TOOL_CIRCUIT_COOLDOWN_SECONDS", 30):
                kernel = resilience_kernel.RuntimeResilience()

                kernel.record("demo_tool", success=False, error="timeout")
                result = kernel.record(
                    "demo_tool",
                    success=False,
                    retryable=True,
                    error="timeout",
                )

                self.assertTrue(result["circuit_open"])
                self.assertFalse(kernel.before("demo_tool")["allowed"])

                kernel.record("demo_tool", success=True)
                self.assertTrue(kernel.before("demo_tool")["allowed"])

    def test_failure_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tool_health.json"
            with patch.object(resilience_kernel, "_HEALTH_PATH", path),                  patch.object(resilience_kernel, "_MEMORY_DIR", Path(tmp)):
                kernel = resilience_kernel.RuntimeResilience()
                kernel.record(
                    "secret_tool",
                    success=False,
                    error="authorization: Bearer abc123-secret-value",
                )
                snapshot = kernel.snapshot()
                self.assertEqual(len(snapshot["degraded_tools"]), 1)
                self.assertNotIn("abc123-secret-value", snapshot["degraded_tools"][0]["last_error"])


if __name__ == "__main__":
    unittest.main()
