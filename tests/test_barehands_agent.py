import unittest

from agent_core import JarvisAgent
from state import ActiveContext, TaskState


class TestBarehandsAgentIntegration(unittest.TestCase):
    def test_agent_runs_barehands_plan_end_to_end(self):
        planner_calls = []
        executor_calls = []

        def fake_planner(request, active_context=None, history_text=""):
            planner_calls.append(
                {
                    "request": request,
                    "active_context": active_context,
                    "history_text": history_text,
                }
            )

            return {
                "goal": "Show JARVIS status",
                "steps": [
                    {
                        "tool": "barehands_present",
                        "argument": "JARVIS|||Agent integration works",
                    }
                ],
            }

        def fake_executor(
            plan,
            active_context,
            task_state,
            speak_callback,
        ):
            executor_calls.append(
                {
                    "plan": plan,
                    "active_context": active_context,
                    "task_state": task_state,
                    "speak_callback": speak_callback,
                }
            )
            return "done"

        agent = JarvisAgent(
            planner=fake_planner,
            executor=fake_executor,
        )

        active_context = ActiveContext()
        task_state = TaskState()

        task = agent.run(
            "Show my JARVIS status",
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
            "Show JARVIS status",
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
            task.steps[0].argument,
            "JARVIS|||Agent integration works",
        )

        self.assertEqual(
            len(planner_calls),
            1,
        )

        self.assertEqual(
            planner_calls[0]["request"],
            "Show my JARVIS status",
        )

        self.assertEqual(
            len(executor_calls),
            1,
        )

        self.assertEqual(
            executor_calls[0]["plan"]["steps"][0]["tool"],
            "barehands_present",
        )


if __name__ == "__main__":
    unittest.main()
