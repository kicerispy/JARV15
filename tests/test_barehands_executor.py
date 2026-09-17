import unittest
from unittest.mock import patch

import tool_executor
from state import ActiveContext, TaskState
from tool_result import ToolResult


class TestBarehandsExecutor(unittest.TestCase):
    def test_barehands_tool_executes_through_run_tool(self):
        plan = {
            "goal": "Show JARVIS status",
            "steps": [
                {
                    "tool": "barehands_present",
                    "argument": "JARVIS|||All systems nominal",
                }
            ],
        }

        expected = ToolResult(
            success=True,
            tool="barehands_present",
            data={"ok": True},
        )

        active_context = ActiveContext()
        task_state = TaskState()

        with patch(
            "tool_executor.run_tool",
            return_value=expected,
        ) as mock_run_tool:
            result = tool_executor.execute_plan(
                plan,
                active_context,
                task_state,
                lambda message: None,
            )

        mock_run_tool.assert_called_once_with(
            "barehands_present",
            "JARVIS|||All systems nominal",
        )

        self.assertEqual(
            result,
            "done",
        )


if __name__ == "__main__":
    unittest.main()
