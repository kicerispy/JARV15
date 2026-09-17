import unittest

import planner


class TestBarehandsPlanValidation(unittest.TestCase):
    def test_barehands_tools_survive_plan_validation(self):
        barehands_tools = [
            ("barehands_state", "thinking"),
            ("barehands_present", "JARVIS|||Hello from JARVIS"),
            ("barehands_add_card", "Status|||All systems nominal"),
            ("barehands_add_image", "https://example.com/image.png|||Example|||Image"),
            ("barehands_clear", ""),
            ("barehands_board_state", ""),
        ]

        raw_plan = {
            "goal": "Use Barehands",
            "steps": [
                {"tool": tool, "argument": argument}
                for tool, argument in barehands_tools
            ],
        }

        validated = planner.validate_plan(raw_plan)

        self.assertEqual(len(validated["steps"]), len(barehands_tools))

        for expected, actual in zip(barehands_tools, validated["steps"]):
            with self.subTest(tool=expected[0]):
                self.assertEqual(actual["tool"], expected[0])
                self.assertEqual(actual["argument"], expected[1])


if __name__ == "__main__":
    unittest.main()
