import unittest


class RobloxRoutingRegressionTests(unittest.TestCase):

    def test_fast_router_does_not_hijack_explicit_roblox_requests(self):
        from commands import deterministic_route

        for command in (
            "Check my Roblox Studio connection",
            "Inspect my Roblox game",
            "inspects my Roblox game and tell me how the project is structured",
            "inspect my Roblox game for errors, find anything that looks broken, and explain what you find before changing anything",
        ):
            self.assertIsNone(
                deterministic_route(command),
                command,
            )

    def test_software_like_find_request_is_not_browser_dom_action(self):
        from commands import deterministic_route

        plan = deterministic_route(
            "find the scripts that control the core gameplay systems"
        )

        self.assertIsNone(plan)

    def test_roblox_context_expands_planner_scope(self):
        from planner import ROBLOX_TOOL_PREFIX, _planner_tool_scope

        scope = _planner_tool_scope(
            "find the scripts that control the core gameplay systems",
            active_context={
                "site": "roblox",
                "last_tool": "roblox__get_project_structure",
            },
        )

        self.assertIsNotNone(scope)
        self.assertIn("roblox_mcp_status", scope)
        self.assertTrue(
            any(
                name.startswith(ROBLOX_TOOL_PREFIX)
                for name in scope
            )
        )

    def test_explicit_no_change_language_disables_modification_gate(self):
        from planner import assess_plan

        plan = {
            "goal": "inspect Roblox game for errors",
            "steps": [
                {
                    "tool": "roblox__get_project_structure",
                    "argument": "{}",
                },
                {
                    "tool": "roblox__get_output_log",
                    "argument": "{}",
                },
            ],
        }

        issues = assess_plan(
            "inspect my Roblox game for errors, find anything that looks broken, and explain what you find before changing anything",
            plan,
        )

        self.assertFalse(
            any(
                "change request must include" in issue
                for issue in issues
            )
        )
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
