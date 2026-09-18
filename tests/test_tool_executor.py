import unittest
from unittest import mock


class ToolExecutorFailureTests(unittest.TestCase):

    def test_unexpected_tool_exception_returns_failed_without_speaking(self):
        import tool_executor
        from state import ActiveContext, TaskState

        spoken = []
        active_context = ActiveContext()
        task_state = TaskState()

        plan = {
            "goal": "trigger test failure",
            "steps": [
                {
                    "tool": "weather",
                    "argument": "Testville",
                }
            ],
        }

        with mock.patch.object(
            tool_executor,
            "run_tool",
            side_effect=RuntimeError("simulated tool crash"),
        ):
            result = tool_executor.execute_plan(
                plan,
                active_context,
                task_state,
                spoken.append,
            )

        self.assertEqual(result, "failed")
        self.assertEqual(spoken, [])
        self.assertEqual(task_state.status, "failed")

        trace = tool_executor.get_last_execution_trace()
        self.assertEqual(len(trace), 1)

        entry = trace[0]
        self.assertEqual(entry["tool"], "weather")
        self.assertEqual(entry["status"], "failed")
        self.assertFalse(entry["success"])
        self.assertFalse(entry["verified"])
        self.assertEqual(entry["failure_type"], "exception")
        self.assertIn(
            "simulated tool crash",
            entry["message"],
        )

        failure_result = entry["result"]
        self.assertFalse(failure_result.success)
        self.assertTrue(failure_result.retryable)
        self.assertIn(
            "simulated tool crash",
            failure_result.error,
        )

    def test_unexpected_tool_exception_clears_non_browser_context(self):
        import tool_executor
        from state import ActiveContext, TaskState

        active_context = ActiveContext(
            site="google",
            last_query="test",
            last_tool="browser_search_google",
            page_url="https://www.google.com/",
            page_title="Google",
        )
        task_state = TaskState()

        with mock.patch.object(
            tool_executor,
            "run_tool",
            side_effect=RuntimeError("simulated failure"),
        ):
            result = tool_executor.execute_plan(
                {
                    "goal": "context failure",
                    "steps": [
                        {
                            "tool": "weather",
                            "argument": "Testville",
                        }
                    ],
                },
                active_context,
                task_state,
                lambda message: None,
            )

        self.assertEqual(result, "failed")
        self.assertIsNone(active_context.site)
        self.assertIsNone(active_context.last_query)
        self.assertIsNone(active_context.page_url)
        self.assertEqual(task_state.status, "failed")


if __name__ == "__main__":
    unittest.main()
