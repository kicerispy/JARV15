import unittest

import tool_executor
from state import ActiveContext, TaskState


class TestBarehandsLiveExecutor(unittest.TestCase):
    def test_barehands_present_executes_against_live_server(self):
        plan = {
            "goal": "Show JARVIS status",
            "steps": [
                {
                    "tool": "barehands_present",
                    "argument": "JARVIS|||Executor integration works",
                }
            ],
        }

        result = tool_executor.execute_plan(
            plan,
            ActiveContext(),
            TaskState(),
            lambda message: None,
        )

        self.assertEqual(result, "done")


if __name__ == "__main__":
    unittest.main()
