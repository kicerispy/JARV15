import json
import unittest
from unittest.mock import patch


class PlannerModelManagerTests(unittest.TestCase):

    def test_planner_uses_model_manager_planner_model(self):
        import planner

        captured = {}

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
            return {
                "message": {
                    "content": '{"goal":"test","steps":[]}'
                }
            }

        with patch.object(
            planner.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
            planner.create_plan("Run a harmless test request")

        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().planner_model,
            "planner must use the centralized ModelManager planner model",
        )

    def test_source_read_phase_uses_general_planner_model(self):
        import planner

        captured = {}

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
            return {
                "message": {
                    "content": (
                        '{"goal":"read source","steps":'
                        '[{"tool":"read_file",'
                        '"argument":"browser_controller.py"}]}'
                    )
                }
            }

        request = (
            "[JARVIS_INTERNAL_PHASE:SOURCE_READ]\n"
            "Read the verified browser_controller.py source."
        )

        with patch.object(
            planner.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
            result = planner.create_plan(request)

        self.assertEqual(result.get("goal"), "read source")
        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().planner_model,
        )
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("focused source-inspection planner", system)
        self.assertNotIn("REPAIR HANDOFF MODE", system)

    def test_change_phase_uses_dedicated_fast_planner_model(self):
        import planner

        captured = {}

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
            return {
                "message": {
                    "content": (
                        '{"goal":"change","steps":['
                        '{"tool":"code_checkpoint","argument":""},'
                        '{"tool":"edit_file","argument":"target.py|||old|||new"},'
                        '{"tool":"code_test","argument":"{'
                        '\\"mode\\":\\"pytest\\",'
                        '\\"path\\":\\"tests/test_target.py\\"}"}]}'
                    )
                }
            }

        request = (
            "[JARVIS_INTERNAL_PHASE:CHANGE]\n"
            "Implement the verified bounded software change."
        )

        with patch.object(
            planner.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
            result = planner.create_plan(request)

        self.assertEqual(result.get("goal"), "change")
        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().change_planner_model,
        )
        self.assertEqual(
            captured.get("options"),
            {
                "temperature": 0,
                "num_predict": 512,
            },
        )
        self.assertEqual(
            captured.get("keep_alive"),
            "10m",
        )
        self.assertFalse(captured.get("think"))
        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("bounded software-change planner", system)
        self.assertNotIn("REPAIR HANDOFF MODE", system)

    def test_diagnostic_test_phase_uses_general_planner_model(self):
        import planner

        captured = {}

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
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

        with patch.object(
            planner.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
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

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
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

        with patch.object(
            planner.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
            result = planner.create_plan(repair_request)

        self.assertEqual(result.get("goal"), "repair")

        system = captured.get("messages", [{}])[0].get("content", "")
        self.assertIn("REPAIR HANDOFF MODE", system)
        self.assertIn("code_checkpoint", system)
        self.assertNotIn(
            "expert software engineer and systems architect",
            system,
        )

        self.assertEqual(
            captured.get("model"),
            planner.ModelManager().coding_model,
            "repair handoffs must use the centralized coding model",
        )

        self.assertEqual(
            captured.get("keep_alive"),
            "15m",
            "repair planner should keep the coding model warm",
        )

        self.assertEqual(
            captured.get("options"),
            {
                "temperature": 0,
                "num_predict": 240,
                "num_ctx": 8192,
            },
        )


if __name__ == "__main__":
    unittest.main()
