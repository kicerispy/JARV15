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

    def test_planner_routes_explicit_autonomous_browser_request(self):
        import planner

        plan = planner.create_plan(
            "Use autonomous browser to find the page title on example.com",
        )

        self.assertEqual(
            plan["steps"][0]["tool"],
            "browser_agent_run",
        )

        import json

        argument = json.loads(plan["steps"][0]["argument"])
        self.assertEqual(
            argument["task"],
            "find the page title on example.com",
        )

    def test_google_result_candidates_accept_goto_and_external_urls(self):
        import asyncio
        import browser_controller

        class FakeLocator:
            def __init__(self):
                self.items = [
                    {
                        "index": 0,
                        "visible": True,
                        "title": "Example Direct",
                        "href": "https://example.com/",
                    },
                    {
                        "index": 1,
                        "visible": True,
                        "title": "Example Google Goto",
                        "href": "https://www.google.com/goto?url=encoded-target",
                    },
                ]

            async def evaluate_all(self, _script):
                return self.items

            def nth(self, index):
                return {
                    "locator_index": index,
                }

        class FakePage:
            def __init__(self):
                self.locator_instance = FakeLocator()

            def locator(self, _selector):
                return self.locator_instance

            async def wait_for_timeout(self, _milliseconds):
                return None

        page = FakePage()

        results = asyncio.run(
            browser_controller._get_google_organic_result_candidates(
                page,
                limit=10,
                timeout_ms=500,
                minimum_results=1,
            )
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Example Direct")
        self.assertEqual(results[0]["url"], "https://example.com/")
        self.assertFalse(results[0]["url_is_google_redirect"])

        self.assertEqual(results[1]["title"], "Example Google Goto")
        self.assertTrue(results[1]["url_is_google_redirect"])
        self.assertIn("/goto?url=encoded-target", results[1]["url"])


    def test_worker_prefers_explicit_url_target_for_direct_cdp_navigation(self):
        module = importlib.import_module("browser_agent_worker")

        self.assertEqual(
            module._extract_task_url(
                "Open https://example.com/docs and inspect the page"
            ),
            "https://example.com/docs",
        )

        targets = [
            {"type": "page", "id": "blank", "url": "about:blank"},
            {"type": "page", "id": "real", "url": "https://example.com/"},
        ]

        self.assertEqual(
            module._choose_page_target(
                targets,
                "https://example.com/",
            ),
            "real",
        )

        self.assertEqual(
            module._choose_page_target(
                [{"type": "page", "id": "only", "url": "about:blank"}],
                "https://example.com/",
            ),
            "only",
        )


    def test_worker_keeps_shared_browser_alive(self):
        from pathlib import Path

        source = Path("browser_agent_worker.py").read_text(encoding="utf-8")
        self.assertIn("keep_alive=True", source)

    def test_worker_uses_fast_local_ollama_settings(self):
        from pathlib import Path

        source = Path("browser_agent_worker.py").read_text(encoding="utf-8")
        self.assertIn('"think": False', source)
        self.assertIn('"num_ctx": int(', source)
        self.assertIn('"keep_alive": "5m"', source)
        self.assertIn("use_thinking=False", source)
        self.assertIn("use_judge=False", source)
        self.assertIn("enable_planning=False", source)
        self.assertIn("max_history_items=8", source)
        self.assertNotIn("max_history_items=3", source)
        self.assertIn("step_timeout=DEFAULT_STEP_TIMEOUT", source)

    def test_page_title_uses_deterministic_fast_path_without_worker(self):
        import browser_controller
        module = importlib.import_module("browser_agent")
        fake_python = Path(module.BASE_DIR) / "fake-browser-python.exe"

        with (
            patch.object(module, "_browser_agent_python", return_value=fake_python),
            patch.object(Path, "is_file", return_value=True),
            patch.object(module, "_probe_url", return_value=True),
            patch(
                "browser_controller.ensure_browser",
                return_value={"success": True},
            ),
            patch(
                "browser_controller.browser_goto",
                return_value={
                    "success": True,
                    "verified": True,
                    "url": "https://example.com/",
                    "title": "Example Domain",
                },
            ),
            patch(
                "browser_controller.browser_page_info",
                return_value={
                    "success": True,
                    "verified": True,
                    "url": "https://example.com/",
                    "title": "Example Domain",
                },
            ),
            patch("subprocess.run") as run_mock,
        ):
            result = module.browser_agent_run(
                '{"task":"Open example.com and tell me the page title.","max_steps":12}'
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertEqual(
            result["message"],
            'The page title is "Example Domain".',
        )
        self.assertEqual(
            result["mode"],
            "deterministic_browser_fast_path",
        )
        run_mock.assert_not_called()


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
            patch.object(module, "_probe_url", return_value=True),
            patch("subprocess.run", return_value=completed) as run_mock,
            patch(
                "browser_controller.ensure_browser",
                return_value={"success": True},
            ),
        ):
            result = module.browser_agent_run(
                '{"task":"inspect the current page","max_steps":4}'
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
