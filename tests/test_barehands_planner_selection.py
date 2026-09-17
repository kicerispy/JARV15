import unittest

import planner


class TestBarehandsPlannerToolSelectionRules(unittest.TestCase):
    def test_prompt_explicitly_disambiguates_status_and_display(self):
        prompt = planner._planner_prompt().lower()

        expected_phrases = [
            "jarvis_status is for",
            "barehands_present is for",
            "barehands display",
            "rather than jarvis_status",
        ]

        for phrase in expected_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(
                    phrase,
                    prompt,
                )


if __name__ == "__main__":
    unittest.main()
