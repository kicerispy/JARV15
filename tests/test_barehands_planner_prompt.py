import unittest

import planner


class TestBarehandsPlannerPrompt(unittest.TestCase):
    def test_prompt_describes_barehands_tools(self):
        prompt = planner._planner_prompt()

        expected_phrases = [
            "barehands_state:",
            "barehands_present:",
            "barehands_add_card:",
            "barehands_add_image:",
            "barehands_clear:",
            "barehands_board_state:",
        ]

        for phrase in expected_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
