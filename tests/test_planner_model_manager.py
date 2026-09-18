import json
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

    def test_source_read_phase_uses_general_planner_model(self):
        import planner

        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {
                "message": {
                    "content": '{"goal":"read source","steps":[{"tool":"read_file","argument":"browser_controller.py"}]}'
                }
            }

        request = (
            "[JARVIS_INTERNAL_PHASE:SOURCE_READ]\n"
            "Read the verified browser_controller.py source."
        )

        with patch.object(planner, "chat", side_effect=fake_chat):
            result = planner.create_plan(request)

        self.assertEqual(result.get("goal"), "read source")
        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().planner_model,
        )
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("focused source-inspection planner", system)
        self.assertNotIn("REPAIR HANDOFF MODE", system)

    def test_diagnostic_test_phase_uses_general_planner_model(self):
        import planner

        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "goal": "runtime diagnostic",
                            "steps": [
                                {
                                    "tool": "code_test",
                                    "argument": json.dumps(
                                        {
                                            "mode": "browser_smoke",
                                            "path": "browser_controller.py",
                                        }
                                    ),
                                }
                            ],
                        }
                    )
                }
            }

        request = (
            "[JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]\n"
            "Run the verified browser runtime diagnostic."
        )

        with patch.object(planner, "chat", side_effect=fake_chat):
            result = planner.create_plan(request)

        self.assertEqual(result.get("goal"), "runtime diagnostic")
        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().planner_model,
        )
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("focused diagnostic test planner", system)
        self.assertNotIn("REPAIR HANDOFF MODE", system)

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
            "[JARVIS_INTERNAL_PHASE:REPAIR]\n"
            "The previous investigation phase has completed successfully.\n"
            "REPAIR PHASE RULES:\n"
            "Use the verified evidence and perform the smallest safe repair."
        )

        with patch.object(planner, "chat", side_effect=fake_chat):
            result = planner.create_plan(repair_request)

        self.assertEqual(result.get("goal"), "repair")
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("REPAIR HANDOFF MODE", system)
        self.assertIn("code_checkpoint", system)
        self.assertNotIn("expert software engineer and systems architect", system)
        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().coding_model,
            "repair handoffs must use the centralized coding model",
        )


if __name__ == "__main__":
    unittest.main()
