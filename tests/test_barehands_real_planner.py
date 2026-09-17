import unittest

import planner


class TestBarehandsRealPlanner(unittest.TestCase):
    def test_real_planner_can_plan_barehands_request(self):
        plan = planner.create_plan(
            "Show a JARVIS status card on the Barehands display"
        )

        self.assertIsInstance(
            plan,
            dict,
        )

        self.assertIn(
            "steps",
            plan,
        )

        steps = plan["steps"]

        self.assertGreater(
            len(steps),
            0,
        )

        tool_names = [
            step.get("tool")
            for step in steps
        ]

        self.assertTrue(
            any(
                tool in tool_names
                for tool in (
                    "barehands_present",
                    "barehands_add_card",
                )
            ),
            f"Expected a Barehands display tool, got: {tool_names}",
        )

        self.assertNotIn(
            "jarvis_status",
            tool_names,
        )

    def test_qwen35_planner_can_handle_real_request(self):
        original_model = planner.PLANNER_MODEL

        try:
            planner.PLANNER_MODEL = "qwen3.5:9b"

            plan = planner.create_plan(
                "Show a JARVIS status card on the Barehands display"
            )

            self.assertIsInstance(
                plan,
                dict,
            )

            self.assertGreater(
                len(plan.get("steps", [])),
                0,
            )

            tool_names = [
                step.get("tool")
                for step in plan["steps"]
            ]

            self.assertTrue(
                any(
                    tool in tool_names
                    for tool in (
                        "barehands_present",
                        "barehands_add_card",
                    )
                ),
                f"Expected a Barehands display tool, got: {tool_names}",
            )

            self.assertNotIn(
                "jarvis_status",
                tool_names,
            )

        finally:
            planner.PLANNER_MODEL = original_model


if __name__ == "__main__":
    unittest.main()