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

    def test_repair_handoff_mode_does_not_require_external_planning_request(self):
        import planner

        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {
                "message": {
                    "content": '{"goal":"repair","steps":[]}'
                }
            }

        repair_request = (
            "The previous investigation phase has completed successfully.\n"
            "REPAIR PHASE RULES:\n"
            "Use the verified evidence and perform the smallest safe repair."
        )

        with patch.object(planner, "chat", side_effect=fake_chat):
            result = planner.create_plan(repair_request)

        self.assertEqual(result.get("goal"), "repair")
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("REPAIR HANDOFF MODE", system)


if __name__ == "__main__":
    unittest.main()
