import unittest


class RobloxPlannerRouteTests(unittest.TestCase):

    def test_connection_request_is_deterministic(self):
        from planner import _deterministic_roblox_plan

        plan = _deterministic_roblox_plan(
            "Check my Roblox Studio connection"
        )

        self.assertIsNotNone(plan)
        self.assertEqual(
            [step["tool"] for step in plan["steps"]],
            ["roblox_mcp_status"],
        )

    def test_inspection_request_is_deterministic(self):
        from planner import _deterministic_roblox_plan

        plan = _deterministic_roblox_plan(
            "Inspect my Roblox game"
        )

        self.assertIsNotNone(plan)
        self.assertEqual(
            [step["tool"] for step in plan["steps"]],
            [
                "roblox__get_place_info",
                "roblox__get_project_structure",
            ],
        )

    def test_non_roblox_request_is_not_captured(self):
        from planner import _deterministic_roblox_plan

        self.assertIsNone(
            _deterministic_roblox_plan(
                "Check my Python project"
            )
        )


if __name__ == "__main__":
    unittest.main()
