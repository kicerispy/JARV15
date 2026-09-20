import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch


class BrowserAgentTests(unittest.TestCase):

    def test_argument_parser_accepts_json_task(self):
        module = importlib.import_module("browser_agent")
        task, payload = module._parse_argument(
            '{"task":"find the current weather on the page","max_steps":7}'
        )
        self.assertEqual(task, "find the current weather on the page")
        self.assertEqual(payload["max_steps"], 7)

    def test_argument_parser_accepts_plain_text(self):
        module = importlib.import_module("browser_agent")
        task, payload = module._parse_argument("open example.com")
        self.assertEqual(task, "open example.com")
        self.assertEqual(payload, {})

    def test_main_runtime_does_not_import_browser_use(self):
        module = importlib.import_module("browser_agent")
        self.assertNotIn("browser_use", module.__dict__)

    def test_status_reports_missing_worker_cleanly(self):
        module = importlib.import_module("browser_agent")
        fake_python = Path(module.BASE_DIR) / "missing-browser-python.exe"
        with patch.object(module, "_browser_agent_python", return_value=fake_python):
            result = module.browser_agent_status()
        self.assertFalse(result["available"])
        self.assertFalse(result["browser_use_installed"])

    def test_run_launches_isolated_worker(self):
        module = importlib.import_module("browser_agent")
        fake_python = Path(module.BASE_DIR) / "fake-browser-python.exe"

        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "success": True,
                        "verified": True,
                        "result": "Example Domain",
                    }
                ),
                "stderr": "",
            },
        )()

        with (
            patch.object(module, "_browser_agent_python", return_value=fake_python),
            patch.object(Path, "is_file", return_value=True),
            patch.object(module, "_probe_url", return_value=True),
            patch("subprocess.run", return_value=completed) as run_mock,
            patch(
                "browser_controller.ensure_browser",
                return_value={"success": True},
            ),
        ):
            result = module.browser_agent_run(
                '{"task":"read the page title","max_steps":4}'
            )

        self.assertTrue(result["success"])
        args = run_mock.call_args.args[0]
        self.assertEqual(str(args[0]), str(fake_python))
        self.assertTrue(str(args[1]).endswith("browser_agent_worker.py"))
        self.assertEqual(
            json.loads(run_mock.call_args.kwargs["input"])["max_steps"],
            4,
        )


if __name__ == "__main__":
    unittest.main()
