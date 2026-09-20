"""Browser DOM integration tests.

The live browser test is opt-in because it opens JARVIS's persistent Chromium
session. Set JARVIS_BROWSER_E2E=1 before running it on the Windows runtime.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import quote


# Running this file directly makes Python put tests\\ on sys.path instead of
# the repository root. Add the project root so imports such as planner,
# model_manager, tools, and tool_executor resolve exactly as they do when
# JARVIS is launched from the project directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DOM_TOOLS = {
    "browser_find_element",
    "browser_click_element",
    "browser_fill_element",
    "browser_press_key",
    "browser_wait_for_element",
    "browser_extract_text",
}


class BrowserDomIntegrationTests(unittest.TestCase):
    def test_dom_tools_are_registered_and_json_capable(self):
        import planner
        from tool_registry import BROWSER_TOOLS, JSON_ARGUMENT_TOOLS

        for tool_name in DOM_TOOLS:
            self.assertIn(tool_name, planner.AVAILABLE_TOOLS)
            self.assertIn(tool_name, BROWSER_TOOLS)
            self.assertIn(tool_name, JSON_ARGUMENT_TOOLS)

    def test_browser_requests_get_browser_planner_scope(self):
        import planner

        scope = planner._planner_tool_scope(
            "Find the search box in the browser, fill it with headphones, and press Enter."
        )

        self.assertIsNotNone(scope)

        for tool_name in DOM_TOOLS:
            self.assertIn(tool_name, scope)

    @unittest.skipUnless(
        os.environ.get("JARVIS_BROWSER_E2E", "").strip().lower()
        in {"1", "true", "yes", "on"},
        "Set JARVIS_BROWSER_E2E=1 to run the live browser test.",
    )
    def test_live_dom_round_trip_through_tools_and_executor(self):
        import tool_executor
        import tools

        html = """
<!doctype html>
<html>
<head><title>JARVIS DOM Test</title></head>
<body>
  <h1>JARVIS DOM Integration</h1>
  <label for="query">Search</label>
  <input id="query" name="query" aria-label="Search" />
  <button id="run" type="button">Run test</button>
  <div id="status">Idle</div>
  <div id="delayed" hidden>Delayed element ready</div>
  <script>
    const input = document.getElementById("query");
    const status = document.getElementById("status");
    const button = document.getElementById("run");
    const delayed = document.getElementById("delayed");

    button.addEventListener("click", () => {
      status.textContent = "Clicked";
      delayed.hidden = false;
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        status.textContent = "Submitted: " + input.value;
      }
    });

    setTimeout(() => {
      delayed.hidden = false;
    }, 150);
  </script>
</body>
</html>
""".strip()

        data_url = "data:text/html," + quote(html)

        goto = tools.run_tool("browser_goto", data_url)
        self.assertTrue(goto.success, str(goto))

        found = tools.run_tool(
            "browser_find_element",
            json.dumps({"role": "textbox", "name": "Search"}),
        )
        self.assertTrue(found.success, str(found))
        self.assertTrue(found.data["verified"])
        self.assertTrue(found.data["found"])

        filled = tools.run_tool(
            "browser_fill_element",
            json.dumps(
                {
                    "role": "textbox",
                    "name": "Search",
                    "value": "headphones",
                }
            ),
        )
        self.assertTrue(filled.success, str(filled))
        self.assertEqual(filled.data["requested_value"], "headphones")
        self.assertEqual(filled.data["value"], "headphones")

        pressed = tools.run_tool(
            "browser_press_key",
            json.dumps(
                {
                    "role": "textbox",
                    "name": "Search",
                    "key": "Enter",
                }
            ),
        )
        self.assertTrue(pressed.success, str(pressed))

        submitted = tools.run_tool(
            "browser_extract_text",
            json.dumps({"selector": "#status"}),
        )
        self.assertTrue(submitted.success, str(submitted))
        self.assertIn("Submitted: headphones", submitted.data["text"])

        clicked = tools.run_tool(
            "browser_click_element",
            json.dumps({"text": "Run test"}),
        )
        self.assertTrue(clicked.success, str(clicked))
        self.assertTrue(clicked.data["verified"])

        waited = tools.run_tool(
            "browser_wait_for_element",
            json.dumps(
                {
                    "selector": "#delayed",
                    "timeout": 3000,
                }
            ),
        )
        self.assertTrue(waited.success, str(waited))
        self.assertTrue(waited.data["verified"])

        extracted = tool_executor._execute_browser_with_fallback(
            "browser_extract_text",
            json.dumps({"selector": "#delayed"}),
        )
        self.assertTrue(extracted.success, str(extracted))
        self.assertIn("Delayed element ready", extracted.data["text"])

        final_page = tools.run_tool(
            "browser_extract_text",
            json.dumps({"selector": "body"}),
        )
        self.assertTrue(final_page.success, str(final_page))
        self.assertIn("JARVIS DOM Integration", final_page.data["text"])
        self.assertIn("Submitted: headphones", final_page.data["text"])
        self.assertIn("Delayed element ready", final_page.data["text"])


if __name__ == "__main__":
    unittest.main()
