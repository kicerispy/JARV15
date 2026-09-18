import unittest
from unittest.mock import patch


class PlannerModelManagerTests(unittest.TestCase):

    def test_planner_uses_model_manager_planner_model(self):
        import planner

        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {
                "message": {
                    "content": '{"goal":"test","steps":[]}'
                }
            }

        with patch.object(planner, "chat", side_effect=fake_chat):
            planner.create_plan("Run a harmless test request")

        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().planner_model,
            "planner must use the centralized ModelManager planner model",
        )


if __name__ == "__main__":
    unittest.main()
