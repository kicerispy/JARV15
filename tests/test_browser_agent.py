import importlib
import unittest
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

    def test_status_without_browser_use_is_clean(self):
        module = importlib.import_module("browser_agent")
        with patch.object(module.importlib.util, "find_spec", return_value=None):
            result = module.browser_agent_status()
        self.assertFalse(result["available"])
        self.assertFalse(result["browser_use_installed"])
        self.assertIn("browser_use=missing", result["message"])


if __name__ == "__main__":
    unittest.main()
