import unittest

import planner


class TestBarehandsPlannerTools(unittest.TestCase):
    def test_available_tools_contains_barehands_tools(self):
        expected = {
            "barehands_state",
            "barehands_present",
            "barehands_add_card",
            "barehands_add_image",
            "barehands_clear",
            "barehands_board_state",
        }

        self.assertTrue(expected.issubset(set(planner.AVAILABLE_TOOLS)))


if __name__ == "__main__":
    unittest.main()
