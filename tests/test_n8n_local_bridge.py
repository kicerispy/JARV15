import json
import unittest
from unittest import mock
from urllib.request import Request, urlopen


class N8NLocalBridgeTests(unittest.TestCase):

    def setUp(self):
        import config
        import n8n_local_bridge

        self.bridge = n8n_local_bridge
        self.original_enabled = config.N8N_ENABLED
        self.original_port = getattr(config, "N8N_LOCAL_ACTION_PORT", 8765)
        self.original_token = getattr(config, "N8N_WEBHOOK_TOKEN", "")

        config.N8N_ENABLED = True
        config.N8N_LOCAL_ACTION_PORT = 28765
        config.N8N_WEBHOOK_TOKEN = ""
        self.bridge.stop_local_action_server()

    def tearDown(self):
        import config

        self.bridge.stop_local_action_server()
        config.N8N_ENABLED = self.original_enabled
        config.N8N_LOCAL_ACTION_PORT = self.original_port
        config.N8N_WEBHOOK_TOKEN = self.original_token

    def _post(self, payload, token=None):
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-JARVIS-N8N-TOKEN"] = token

        request = Request(
            self.bridge.local_action_url(),
            data=body,
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_gateway_starts_loopback_only(self):
        self.assertTrue(self.bridge.start_local_action_server())

        with urlopen(self.bridge.local_action_health_url(), timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["success"])
        self.assertTrue(payload["loopback_only"])
        self.assertIn("open_program", payload["actions"])

    def test_unknown_action_is_rejected(self):
        self.bridge.start_local_action_server()

        status, payload = self._post({
            "action": "run_shell",
            "arguments": {"command": "whoami"},
        })

        self.assertEqual(status, 400)
        self.assertFalse(payload["success"])

    def test_browser_url_validation(self):
        from n8n_local_bridge import _browser_goto

        self.assertFalse(_browser_goto("file:///C:/Windows/win.ini")["success"])
        self.assertFalse(_browser_goto("javascript:alert(1)")["success"])

    def test_program_launch_uses_existing_allowlist(self):
        import n8n_local_bridge

        with mock.patch("tools.open_program", return_value="Opening Spotify."):
            result = n8n_local_bridge._open_program("spotify")

        self.assertTrue(result["success"])
        self.assertEqual(result["program"], "spotify")

    def test_spotify_liked_songs_action_avoids_toggle_when_already_playing(self):
        import n8n_local_bridge

        with mock.patch("tools.open_program", return_value="Opening Spotify."):
            with mock.patch("screen_vision.press_key", return_value={"success": True}) as press:
                with mock.patch(
                    "screen_vision.verify_screen_state",
                    side_effect=[
                        {"success": True, "verified": True},
                        {"success": True, "verified": True},
                    ],
                ):
                    with mock.patch("time.sleep"):
                        result = n8n_local_bridge._spotify_play_liked_songs()

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["playback_verified"])
        self.assertEqual(press.call_count, 1)
        press.assert_called_once_with("alt shift s")

    def test_spotify_liked_songs_action_starts_playback_when_paused(self):
        import n8n_local_bridge

        with mock.patch("tools.open_program", return_value="Opening Spotify."):
            with mock.patch(
                "screen_vision.press_key",
                return_value={"success": True},
            ) as press:
                with mock.patch(
                    "screen_vision.verify_screen_state",
                    side_effect=[
                        {"success": True, "verified": True},
                        {"success": False, "verified": True},
                        {"success": True, "verified": True},
                    ],
                ):
                    with mock.patch("time.sleep"):
                        result = n8n_local_bridge._spotify_play_liked_songs()

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["playback_verified"])
        self.assertEqual(press.call_count, 2)
        self.assertEqual(press.call_args_list[0].args, ("alt shift s",))
        self.assertEqual(press.call_args_list[1].args, ("space",))

    def test_token_is_required_when_configured(self):
        import config

        config.N8N_WEBHOOK_TOKEN = "secret-token"
        self.bridge.start_local_action_server()

        body = json.dumps({"action": "get_screen_size", "arguments": {}}).encode("utf-8")
        request = Request(
            self.bridge.local_action_url(),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(Exception):
            urlopen(request, timeout=3)

        request = Request(
            self.bridge.local_action_url(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-JARVIS-N8N-TOKEN": "secret-token",
            },
            method="POST",
        )

        with mock.patch(
            "screen_vision.get_screen_size",
            return_value={
                "success": True,
                "width": 1920,
                "height": 1080,
            },
        ):
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["success"])
        self.assertEqual(payload["width"], 1920)


if __name__ == "__main__":
    unittest.main()
