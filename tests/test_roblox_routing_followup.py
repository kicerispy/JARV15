import unittest


class RobloxRoutingFollowupTests(unittest.TestCase):

    def test_generic_script_followup_uses_roblox_context(self):
        from planner import _deterministic_roblox_context_plan

        plan = _deterministic_roblox_context_plan(
            "find the scripts that control the core gameplay systems",
            {
                "site": "roblox",
                "last_tool": "roblox__get_project_structure",
            },
        )

        self.assertIsNotNone(plan)
        self.assertEqual(
            [step["tool"] for step in plan["steps"]],
            ["roblox__search_files"],
        )

    def test_generic_followup_without_roblox_context_is_not_forced(self):
        from planner import _deterministic_roblox_context_plan

        self.assertIsNone(
            _deterministic_roblox_context_plan(
                "find the scripts in this folder",
                {
                    "site": "google",
                    "last_tool": "browser_search_google",
                },
            )
        )

    def test_gameplay_followup_is_roblox_without_prior_context(self):
        from planner import _deterministic_roblox_context_plan

        plan = _deterministic_roblox_context_plan(
            "find the scripts that control the core gameplay systems",
            {},
        )

        self.assertIsNotNone(plan)
        self.assertEqual(
            [step["tool"] for step in plan["steps"]],
            ["roblox__search_files"],
        )

    def test_diagnostic_request_remains_read_only(self):
        from planner import _deterministic_roblox_plan

        plan = _deterministic_roblox_plan(
            "inspect my Roblox game for errors, find anything that looks broken, and explain what you find before changing anything"
        )

        self.assertIsNotNone(plan)
        tools = [step["tool"] for step in plan["steps"]]
        self.assertEqual(
            tools,
            [
                "roblox__get_place_info",
                "roblox__get_project_structure",
                "roblox__search_files",
                "roblox__get_output_log",
            ],
        )

        mutation_tools = {
            "roblox__set_property",
            "roblox__mass_set_property",
            "roblox__set_properties",
            "roblox__create_object",
            "roblox__delete_object",
            "roblox__set_script_source",
            "roblox__edit_script_lines",
            "roblox__insert_script_lines",
            "roblox__delete_script_lines",
            "roblox__execute_luau",
            "roblox__start_playtest",
            "roblox__stop_playtest",
        }

        self.assertTrue(
            mutation_tools.isdisjoint(tools)
        )


if __name__ == "__main__":
    unittest.main()
