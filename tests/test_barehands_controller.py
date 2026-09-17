import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from barehands_controller import BarehandsController


class FakeResponse:
    def __init__(self, payload=b"{}"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class BarehandsControllerTests(unittest.TestCase):
    def test_invalid_state_is_rejected_without_http(self):
        controller = BarehandsController(state_dir=tempfile.gettempdir())
        with patch("barehands_controller.urlopen") as urlopen:
            result = controller.set_state("working")
        self.assertFalse(result.success)
        self.assertFalse(urlopen.called)

    def test_state_writes_documented_state_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = BarehandsController(state_dir=temp_dir)
            result = controller.set_state("thinking")
            self.assertTrue(result.success)
            self.assertEqual(
                Path(temp_dir, "state").read_text(encoding="utf-8"),
                "thinking",
            )

    def test_board_action_allowlist_rejects_unknown_action(self):
        controller = BarehandsController()
        with patch("barehands_controller.urlopen") as urlopen:
            result = controller.board_command("run_shell")
        self.assertFalse(result.success)
        self.assertFalse(urlopen.called)

    def test_add_card_posts_json_command(self):
        controller = BarehandsController()
        with patch(
            "barehands_controller.urlopen",
            return_value=FakeResponse(),
        ) as urlopen:
            result = controller.add_card("Plan", "Hello")
        self.assertTrue(result.success)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8794/cmd")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"a": "add_card", "title": "Plan", "body": "Hello"},
        )

    def test_board_state_reads_json(self):
        payload = b'{"items":[{"title":"Plan"}]}'
        controller = BarehandsController()
        with patch(
            "barehands_controller.urlopen",
            return_value=FakeResponse(payload),
        ):
            result = controller.board_state()
        self.assertTrue(result.success)
        self.assertEqual(result.data["items"][0]["title"], "Plan")

    def test_offline_server_fails_without_raising(self):
        controller = BarehandsController()
        with patch(
            "barehands_controller.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = controller.add_card("Plan", "Hello")
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
