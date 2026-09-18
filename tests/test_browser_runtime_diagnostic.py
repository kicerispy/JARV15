import sys
import types
import unittest
from unittest.mock import patch


class BrowserRuntimeDiagnosticTests(unittest.TestCase):

    def test_code_test_browser_smoke_uses_controller(self):
        import tools

        fake_controller = types.SimpleNamespace(
            browser_self_test=lambda: {
                "success": True,
                "verified": True,
                "message": "Browser automation smoke test passed.",
                "google_first_result": "Example result",
            }
        )

        with patch.dict(sys.modules, {"browser_controller": fake_controller}):
            result = tools.code_test(
                '{"mode":"browser_smoke","path":"browser_controller.py"}'
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["mode"], "browser_smoke")
        self.assertEqual(result["path"], "browser_controller.py")

    def test_browser_repair_fallback_prefers_runtime_smoke_test(self):
        from agent_core import JarvisAgent

        agent = JarvisAgent()
        task = agent.create_task(
            "Inspect the browser automation and fix the problem."
        )

        task.evidence.append(
            {
                "tool": "read_file",
                "target": "browser_controller.py",
                "success": True,
                "verified": True,
                "detail": "Source excerpt",
            }
        )

        plan = agent._build_phase_fallback_plan(
            task,
            require_code_test=True,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["tool"], "code_test")
        self.assertIn('"mode": "browser_smoke"', plan["steps"][0]["argument"])
        self.assertIn('"path": "browser_controller.py"', plan["steps"][0]["argument"])


if __name__ == "__main__":
    unittest.main()
