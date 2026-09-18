import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ConversationRoutingTests(unittest.TestCase):

    def test_conversation_bypasses_agent_planner(self):
        import main
        from conversation import ConversationHistory
        from state import JarvisState

        with tempfile.TemporaryDirectory() as temp_dir:
            history = ConversationHistory(
                Path(temp_dir) / "history.json"
            )
            state = JarvisState()
            planner_calls = []

            def record_plan_call(*args, **kwargs):
                planner_calls.append((args, kwargs))

            def fake_conversation(*args, **kwargs):
                return "conversation-result"

            with (
                patch.object(main, "run_memory_analysis_background"),
                patch.object(main, "is_creative_request", return_value=False),
                patch.object(main, "is_code_request", return_value=False),
                patch.object(main.jarvis_agent, "plan_task", side_effect=record_plan_call),
                patch.object(main, "handle_normal_conversation", side_effect=fake_conversation),
            ):
                result = main.process_command(
                    "What can you do?",
                    state,
                    history,
                    "test system prompt",
                    lambda _text: False,
                )

        self.assertEqual(result, "conversation-result")
        self.assertEqual(
            planner_calls,
            [],
            "conversational requests must bypass Agent Core planning",
        )


if __name__ == "__main__":
    unittest.main()
