import unittest
from unittest import mock


class AgentCoreBrowserObservationTests(unittest.TestCase):

    def test_browser_recovery_metadata_becomes_structured_evidence(self):
        from agent_core import AgentTask, JarvisAgent
        from tool_result import ToolResult

        task = AgentTask(
            task_id="test-task",
            request="click the submit button",
        )

        result = ToolResult(
            success=False,
            tool="browser_click_element",
            error="element detached",
            retryable=True,
            data={
                "message": "Browser click failed.",
                "recovery": {
                    "recovered_by": "reobserve_retry",
                    "observed_before": {
                        "url": "https://example.com/form",
                        "title": "Example Form",
                    },
                    "observed_after": {
                        "url": "https://example.com/form",
                        "title": "Example Form",
                    },
                },
            },
        )

        trace = [
            {
                "index": 1,
                "tool": "browser_click_element",
                "argument": '{"text":"Submit"}',
                "status": "failed",
                "success": False,
                "verified": False,
                "result": result,
                "message": "Browser click failed.",
                "attempts": 2,
                "recovery_count": 1,
            }
        ]

        browser_state = {
            "success": True,
            "url": "https://example.com/form",
            "title": "Example Form",
            "open_pages": [
                {
                    "url": "https://example.com/form",
                    "title": "Example Form",
                }
            ],
        }

        with mock.patch(
            "tool_executor.get_last_execution_trace",
            return_value=trace,
        ), mock.patch(
            "browser_controller.browser_page_info",
            return_value=browser_state,
        ):
            JarvisAgent()._record_execution_observation(
                task,
                attempt=1,
                execution_result="failed",
            )

        recovery_evidence = [
            evidence
            for evidence in task.evidence
            if evidence.get("browser_recovery")
        ]

        self.assertEqual(len(recovery_evidence), 1)

        evidence = recovery_evidence[0]

        self.assertEqual(
            evidence["tool"],
            "browser_click_element",
        )
        self.assertFalse(evidence["success"])
        self.assertFalse(evidence["verified"])

        recovery = evidence["browser_recovery"]

        self.assertEqual(
            recovery["recovered_by"],
            "reobserve_retry",
        )
        self.assertEqual(
            recovery["observed_before"]["url"],
            "https://example.com/form",
        )
        self.assertEqual(
            recovery["observed_after"]["title"],
            "Example Form",
        )
        self.assertEqual(
            recovery["attempts"],
            2,
        )
        self.assertEqual(
            recovery["recovery_count"],
            1,
        )

        self.assertEqual(
            task.active_context["browser_state"]["url"],
            "https://example.com/form",
        )


    def test_replan_request_highlights_browser_recovery_history(self):
        from agent_core import AgentTask, JarvisAgent

        task = AgentTask(
            task_id="replan-task",
            request="click the Submit button",
            goal="submit the form",
            execution_result="failed",
            error="Browser click failed.",
        )

        task.active_context["browser_state"] = {
            "success": True,
            "url": "https://example.com/form",
            "title": "Example Form",
        }

        task.evidence.append(
            {
                "attempt": 1,
                "tool": "browser_click_element",
                "target": '{"text":"Submit"}',
                "success": False,
                "verified": False,
                "detail": "Browser click failed.",
                "browser_recovery": {
                    "recovered_by": "reobserve_retry",
                    "observed_before": {
                        "url": "https://example.com/form",
                        "title": "Example Form",
                    },
                    "observed_after": {
                        "url": "https://example.com/form",
                        "title": "Example Form",
                    },
                    "attempts": 2,
                    "recovery_count": 1,
                },
            }
        )

        request = JarvisAgent()._build_replan_request(task)

        self.assertIn(
            "Browser recovery history:",
            request,
        )
        self.assertIn(
            "method=reobserve_retry",
            request,
        )
        self.assertIn(
            "attempts=2",
            request,
        )
        self.assertIn(
            "retries=1",
            request,
        )
        self.assertIn(
            "Do not blindly repeat a browser strategy",
            request,
        )
        self.assertIn(
            "URL: https://example.com/form",
            request,
        )


if __name__ == "__main__":
    unittest.main()
