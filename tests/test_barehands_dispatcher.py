import unittest
from unittest.mock import patch

import barehands_tools
import tools
from tool_result import ToolResult


class TestBarehandsDispatcher(unittest.TestCase):
    def test_barehands_state_dispatches(self):
        expected = ToolResult(
            success=True,
            tool="barehands_state",
            data={"state": "thinking"},
        )

        with patch(
            "barehands_tools.barehands_state",
            return_value=expected,
        ) as mock_tool:
            result = tools.run_tool("barehands_state", "thinking")

        mock_tool.assert_called_once_with("thinking")
        self.assertEqual(result, expected)

    def test_barehands_present_dispatches(self):
        expected = ToolResult(
            success=True,
            tool="barehands_present",
            data={"ok": True},
        )

        with patch(
            "barehands_tools.barehands_present",
            return_value=expected,
        ) as mock_tool:
            result = tools.run_tool(
                "barehands_present",
                "JARVIS|||Hello from JARVIS",
            )

        mock_tool.assert_called_once_with("JARVIS|||Hello from JARVIS")
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
