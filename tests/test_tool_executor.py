import unittest
from unittest import mock


class ToolExecutorProgressTests(unittest.TestCase):

    def test_progress_reports_major_milestones_without_low_level_browser_chatter(self):
        import tool_executor
        from state import TaskState

        task_state = TaskState()
        task_state.prepare("browser task", 6)
        spoken = []
        task_state.set_progress_callback(
            lambda message: spoken.append(message)
        )

        tool_executor._report_tool_progress(
            task_state,
            "browser_search_google",
            1,
            6,
        )
        tool_executor._report_tool_progress(
            task_state,
            "browser_find_element",
            2,
            6,
        )
        tool_executor._report_tool_progress(
            task_state,
            "browser_wait_for_element",
            3,
            6,
        )
        tool_executor._report_tool_progress(
            task_state,
            "browser_click_element",
            4,
            6,
        )
        tool_executor._report_tool_progress(
            task_state,
            "browser_fill_element",
            5,
            6,
        )
        tool_executor._report_tool_progress(
            task_state,
            "browser_extract_text",
            6,
            6,
        )

        assert spoken == [
            "I'm searching the browser.",
            "I'm interacting with the page.",
            "I'm reading the page.",
        ]

    def test_code_progress_collapses_multiple_discovery_tools_into_one_milestone(self):
        import tool_executor
        from state import TaskState

        task_state = TaskState()
        task_state.prepare("repair task", 5)
        spoken = []
        task_state.set_progress_callback(
            lambda message: spoken.append(message)
        )

        tool_executor._report_tool_progress(
            task_state,
            "code_search",
            1,
            5,
        )
        tool_executor._report_tool_progress(
            task_state,
            "find_file",
            2,
            5,
        )
        tool_executor._report_tool_progress(
            task_state,
            "read_file",
            3,
            5,
        )
        tool_executor._report_tool_progress(
            task_state,
            "edit_file",
            4,
            5,
        )
        tool_executor._report_tool_progress(
            task_state,
            "code_test",
            5,
            5,
        )

        assert spoken == [
            "I'm locating the relevant code.",
            "I'm inspecting the relevant source.",
            "I'm applying the change.",
            "I'm validating the result.",
        ]


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

    def test_safe_retry_resumes_existing_multi_step_plan(self):
        import tool_executor
        from state import ActiveContext, TaskState
        from tool_result import ToolResult

        task_state = TaskState()
        calls = []
        current_time_attempts = {"count": 0}

        def fake_run_tool(tool_name, argument):
            calls.append(tool_name)

            if tool_name == "current_time":
                current_time_attempts["count"] += 1
                if current_time_attempts["count"] == 1:
                    return ToolResult(
                        success=False,
                        tool=tool_name,
                        error="temporary time service failure",
                        retryable=True,
                    )

                return ToolResult(
                    success=True,
                    tool=tool_name,
                    data="12:00 PM",
                )

            return ToolResult(
                success=True,
                tool=tool_name,
                data=f"{tool_name} completed",
            )

        with mock.patch.object(
            tool_executor,
            "run_tool",
            side_effect=fake_run_tool,
        ):
            result = tool_executor.execute_plan(
                {
                    "goal": "resume after safe retry",
                    "steps": [
                        {"tool": "weather", "argument": "Chicago"},
                        {"tool": "current_time", "argument": "Chicago"},
                        {"tool": "current_date", "argument": ""},
                    ],
                },
                ActiveContext(),
                task_state,
                lambda message: None,
            )

        self.assertEqual(result, "done")
        self.assertEqual(
            calls,
            [
                "weather",
                "current_time",
                "current_time",
                "current_date",
            ],
        )
        # TaskState counters describe the current step. The trace keeps
        # the retry accounting for earlier steps, so step 2 remains
        # observable after execution advances to step 3.
        self.assertEqual(task_state.attempts, 1)
        self.assertEqual(task_state.recovery_count, 0)

        trace = tool_executor.get_last_execution_trace()
        self.assertEqual(len(trace), 3)
        self.assertEqual(trace[0]["tool"], "weather")
        self.assertEqual(trace[1]["tool"], "current_time")
        self.assertEqual(trace[1]["attempts"], 2)
        self.assertEqual(trace[1]["recovery_count"], 1)
        self.assertEqual(trace[1]["status"], "completed")
        self.assertEqual(trace[2]["tool"], "current_date")
        self.assertEqual(trace[2]["status"], "completed")


    def test_browser_dom_retry_reobserves_and_recovers(self):
        import tool_executor
        from tool_result import ToolResult

        calls = []

        def fake_browser_tool(tool_name, argument):
            calls.append(tool_name)

            if tool_name == "browser_click_element":
                if calls.count("browser_click_element") == 1:
                    return ToolResult(
                        success=False,
                        tool=tool_name,
                        error="element detached",
                        retryable=True,
                    )

                return ToolResult(
                    success=True,
                    tool=tool_name,
                    data={
                        "success": True,
                        "verified": True,
                        "message": "Button clicked.",
                    },
                )

            if tool_name == "browser_wait_for_element":
                return {
                    "success": True,
                    "verified": True,
                    "found": True,
                    "visible": True,
                }

            raise AssertionError(f"Unexpected browser tool: {tool_name}")

        browser_states = [
            {
                "success": True,
                "url": "https://example.com/form",
                "title": "Example Form",
            },
            {
                "success": True,
                "url": "https://example.com/form",
                "title": "Example Form",
            },
        ]

        with mock.patch.object(
            tool_executor,
            "run_browser_tool",
            side_effect=fake_browser_tool,
        ), mock.patch(
            "browser_controller.browser_page_info",
            side_effect=browser_states,
        ), mock.patch.object(
            tool_executor.time,
            "sleep",
        ):
            result = tool_executor._execute_browser_with_fallback(
                "browser_click_element",
                '{"text":"Submit"}',
            )

        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.success)
        self.assertEqual(
            calls,
            [
                "browser_click_element",
                "browser_wait_for_element",
                "browser_click_element",
            ],
        )
        self.assertEqual(
            result.data["recovery"]["recovered_by"],
            "reobserve_retry",
        )
        self.assertEqual(
            result.data["recovery"]["observed_before"]["title"],
            "Example Form",
        )

    def test_browser_result_click_uses_alternate_strategy(self):
        import tool_executor

        calls = []

        def fake_browser_tool(tool_name, argument):
            calls.append(tool_name)

            if tool_name == "browser_click_first_result":
                return {
                    "success": False,
                    "verified": False,
                    "retryable": True,
                    "error": "specialized first-result click failed",
                }

            if tool_name == "browser_click_result":
                return {
                    "success": True,
                    "verified": True,
                    "index": 1,
                    "site": "google",
                    "result_title": "Recovered Result",
                    "after_url": "https://example.com/recovered",
                }

            raise AssertionError(f"Unexpected browser tool: {tool_name}")

        browser_state = {
            "success": True,
            "url": "https://www.google.com/search?q=test",
            "title": "test - Google Search",
        }

        with mock.patch.object(
            tool_executor,
            "run_browser_tool",
            side_effect=fake_browser_tool,
        ), mock.patch(
            "browser_controller.browser_page_info",
            return_value=browser_state,
        ), mock.patch.object(
            tool_executor.time,
            "sleep",
        ):
            result = tool_executor._execute_browser_with_fallback(
                "browser_click_first_result",
                '{"site":"google","query":"test"}',
            )

        self.assertEqual(
            calls,
            [
                "browser_click_first_result",
                "browser_click_first_result",
                "browser_click_result",
            ],
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertEqual(
            result["recovery"]["recovered_by"],
            "browser_click_result",
        )

    def test_browser_failed_verification_observes_without_double_clicking(self):
        import tool_executor

        calls = []

        def fake_browser_tool(tool_name, argument):
            calls.append(tool_name)
            return {
                "success": True,
                "verified": False,
                "error": "navigation target was unexpected",
                "before_url": "https://example.com/start",
                "after_url": "https://example.com/other",
            }

        observed = {
            "success": True,
            "url": "https://example.com/other",
            "title": "Unexpected Page",
        }

        with mock.patch.object(
            tool_executor,
            "run_browser_tool",
            side_effect=fake_browser_tool,
        ), mock.patch(
            "browser_controller.browser_page_info",
            return_value=observed,
        ):
            result = tool_executor._execute_browser_with_fallback(
                "browser_click_result",
                '{"index":1,"site":"youtube"}',
            )

        self.assertEqual(
            calls,
            [
                "browser_click_result",
            ],
        )
        self.assertEqual(
            result["recovery"]["recovered_by"],
            "state_observation",
        )
        self.assertEqual(
            result["recovery"]["observed_after"]["title"],
            "Unexpected Page",
        )


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