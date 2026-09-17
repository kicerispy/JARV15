import unittest

from agent_core import JarvisAgent
from state import ActiveContext, TaskState
from tool_executor import execute_plan


class TestBarehandsAgentLiveIntegration(unittest.TestCase):
    def test_agent_runs_real_barehands_executor(self):
        def fake_planner(request, active_context=None, history_text=""):
            return {
                "goal": "Show live JARVIS status",
                "steps": [
                    {
                        "tool": "barehands_present",
                        "argument": "JARVIS|||Full agent pipeline works",
                    }
                ],
            }

        agent = JarvisAgent(
            planner=fake_planner,
            executor=execute_plan,
        )

        active_context = ActiveContext()
        task_state = TaskState()

        task = agent.run(
            "Show live JARVIS status",
            active_context,
            task_state,
            lambda message: None,
        )

        self.assertEqual(
            task.status,
            "completed",
        )

        self.assertEqual(
            task.goal,
            "Show live JARVIS status",
        )

        self.assertEqual(
            len(task.steps),
            1,
        )

        self.assertEqual(
            task.steps[0].tool,
            "barehands_present",
        )

        self.assertEqual(
            task.steps[0].status,
            "completed",
        )

        self.assertTrue(
            task.steps[0].verified,
        )

        self.assertEqual(
            task.execution_result,
            "done",
        )


if __name__ == "__main__":
    unittest.main()
