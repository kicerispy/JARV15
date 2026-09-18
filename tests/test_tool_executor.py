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

    def test_safe_retry_recovers_single_step_without_speaking_twice(self):
        import tool_executor
        from state import ActiveContext, TaskState
        from tool_result import ToolResult

        spoken = []
        task_state = TaskState()
        calls = {"count": 0}

        def fake_run_tool(tool_name, argument):
            calls["count"] += 1
            if calls["count"] == 1:
                return ToolResult(
                    success=False,
                    tool=tool_name,
                    error="temporary weather failure",
                    retryable=True,
                )

            return ToolResult(
                success=True,
                tool=tool_name,
                data="Weather recovered.",
            )

        with mock.patch.object(
            tool_executor,
            "run_tool",
            side_effect=fake_run_tool,
        ):
            result = tool_executor.execute_plan(
                {
                    "goal": "retry safe action",
                    "steps": [
                        {
                            "tool": "weather",
                            "argument": "Chicago",
                        }
                    ],
                },
                ActiveContext(),
                task_state,
                spoken.append,
            )

        self.assertEqual(result, "done")
        self.assertEqual(calls["count"], 2)
        self.assertEqual(task_state.attempts, 2)
        self.assertEqual(task_state.recovery_count, 1)
        self.assertEqual(spoken, ["Weather recovered."])

        trace = tool_executor.get_last_execution_trace()
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["status"], "completed")
        self.assertEqual(trace[0]["attempts"], 2)
        self.assertEqual(trace[0]["recovery_count"], 1)

    def test_non_retryable_safe_tool_runs_only_once(self):
        import tool_executor
        from state import ActiveContext, TaskState
        from tool_result import ToolResult

        task_state = TaskState()
        calls = {"count": 0}

        def fake_run_tool(tool_name, argument):
            calls["count"] += 1
            return ToolResult(
                success=False,
                tool=tool_name,
                error="deterministic failure",
                retryable=False,
            )

        with mock.patch.object(
            tool_executor,
            "run_tool",
            side_effect=fake_run_tool,
        ):
            result = tool_executor.execute_plan(
                {
                    "goal": "do not retry",
                    "steps": [
                        {
                            "tool": "weather",
                            "argument": "Chicago",
                        }
                    ],
                },
                ActiveContext(),
                task_state,
                lambda message: None,
            )

        self.assertEqual(result, "failed")
        self.assertEqual(calls["count"], 1)
        self.assertEqual(task_state.attempts, 1)
        self.assertEqual(task_state.recovery_count, 0)

        trace = tool_executor.get_last_execution_trace()
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["status"], "failed")
        self.assertEqual(trace[0]["attempts"], 1)
        self.assertEqual(trace[0]["recovery_count"], 0)


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