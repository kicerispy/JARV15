import os
import unittest
from unittest.mock import patch

from barehands_tools import (
    _controller,
    barehands_add_card,
    barehands_add_image,
    barehands_clear,
    barehands_present,
    barehands_state,
)
from tool_result import ToolResult


class BarehandsToolsTests(unittest.TestCase):
    def test_controller_uses_barehands_state_directory(self):
        with patch.dict(os.environ, {"BAREHANDS_DIR": r"C:\barehands"}, clear=False):
            controller = _controller()
        self.assertEqual(str(controller.state_dir), r"C:\barehands\state")

    def test_present_requires_title_and_body(self):
        result = barehands_present("JARVIS")
        self.assertFalse(result.success)
        self.assertEqual(result.tool, "barehands_present")

    @patch("barehands_tools._controller")
    def test_present_dispatches_title_and_body(self, controller_factory):
        controller = controller_factory.return_value
        controller.present.return_value = ToolResult(
            success=True,
            tool="present",
            data={"a": "present"},
        )

        result = barehands_present("JARVIS|||Hello")

        controller.present.assert_called_once_with("JARVIS", "Hello")
        self.assertTrue(result.success)
        self.assertEqual(result.tool, "barehands_present")

    @patch("barehands_tools._controller")
    def test_add_card_dispatches_title_and_body(self, controller_factory):
        controller = controller_factory.return_value
        controller.add_card.return_value = ToolResult(success=True, tool="add_card")

        result = barehands_add_card("Plan|||Hello")

        controller.add_card.assert_called_once_with("Plan", "Hello")
        self.assertTrue(result.success)

    @patch("barehands_tools._controller")
    def test_add_image_dispatches_all_arguments(self, controller_factory):
        controller = controller_factory.return_value
        controller.add_image.return_value = ToolResult(success=True, tool="add_img")

        result = barehands_add_image("https://example.com/a.png|||Image|||Details")

        controller.add_image.assert_called_once_with(
            "https://example.com/a.png",
            "Image",
            "Details",
        )
        self.assertTrue(result.success)

    @patch("barehands_tools._controller")
    def test_clear_and_state_dispatch(self, controller_factory):
        controller = controller_factory.return_value
        controller.clear.return_value = ToolResult(success=True, tool="clear")
        controller.set_state.return_value = ToolResult(success=True, tool="state")

        clear_result = barehands_clear()
        state_result = barehands_state("thinking")

        controller.clear.assert_called_once_with()
        controller.set_state.assert_called_once_with("thinking")
        self.assertTrue(clear_result.success)
        self.assertTrue(state_result.success)


if __name__ == "__main__":
    unittest.main()
