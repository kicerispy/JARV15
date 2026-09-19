import os
import unittest
from unittest.mock import patch

import barehands_state
from tool_result import ToolResult


class BarehandsStateBridgeTests(unittest.TestCase):

    def test_supported_states_are_forwarded(self):
        with patch.dict(
            os.environ,
            {"BAREHANDS_DIR": r"C:\barehands"},
            clear=False,
        ):
            with patch.object(
                barehands_state,
                "BarehandsController",
            ) as controller_cls:

                controller = controller_cls.return_value
                controller.set_state.return_value = ToolResult(
                    success=True,
                    tool="barehands_state",
                    data={"state": "thinking"},
                )

                for state in (
                    "idle",
                    "listening",
                    "thinking",
                    "speaking",
                ):
                    barehands_state.set_barehands_state(state)

        self.assertEqual(
            controller_cls.call_count,
            4,
        )

        self.assertEqual(
            controller.set_state.call_count,
            4,
        )

        self.assertEqual(
            [
                call.args[0]
                for call in controller.set_state.call_args_list
            ],
            [
                "idle",
                "listening",
                "thinking",
                "speaking",
            ],
        )

    def test_missing_or_broken_barehands_never_raises(self):
        with patch.dict(
            os.environ,
            {"BAREHANDS_DIR": r"C:\barehands"},
            clear=False,
        ):
            with patch.object(
                barehands_state,
                "BarehandsController",
                side_effect=RuntimeError("barehands offline"),
            ):
                barehands_state.set_barehands_state("thinking")


if __name__ == "__main__":
    unittest.main()
