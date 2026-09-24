import unittest
from pathlib import Path
from unittest import mock

class N8NAutostartTests(unittest.TestCase):
    def test_disabled_does_not_launch(self):
        import config, n8n_autostart
        with mock.patch.object(config, "N8N_ENABLED", False):
            with mock.patch.object(n8n_autostart, "_launch_process") as launch:
                result = n8n_autostart.ensure_n8n_started()
        self.assertFalse(result["success"])
        launch.assert_not_called()

    def test_configured_off_does_not_launch(self):
        import config, n8n_autostart
        with mock.patch.object(config, "N8N_ENABLED", True):
            with mock.patch.object(config, "N8N_AUTOSTART", False):
                with mock.patch.object(n8n_autostart, "_launch_process") as launch:
                    result = n8n_autostart.ensure_n8n_started()
        self.assertTrue(result["success"])
        self.assertFalse(result["started"])
        launch.assert_not_called()

    def test_existing_listener_is_not_duplicated(self):
        import config, n8n_autostart
        with mock.patch.object(config, "N8N_ENABLED", True),              mock.patch.object(config, "N8N_AUTOSTART", True),              mock.patch.object(n8n_autostart, "_is_windows", return_value=True),              mock.patch.object(n8n_autostart, "n8n_port_open", return_value=True),              mock.patch.object(n8n_autostart, "_launch_process") as launch:
            result = n8n_autostart.ensure_n8n_started()
        self.assertTrue(result["success"])
        self.assertFalse(result["started"])
        launch.assert_not_called()

    def test_missing_npx_fails_cleanly(self):
        import config, n8n_autostart
        with mock.patch.object(config, "N8N_ENABLED", True),              mock.patch.object(config, "N8N_AUTOSTART", True),              mock.patch.object(n8n_autostart, "_is_windows", return_value=True),              mock.patch.object(n8n_autostart, "n8n_port_open", return_value=False),              mock.patch.object(n8n_autostart, "_npx_path", return_value=None):
            result = n8n_autostart.ensure_n8n_started()
        self.assertFalse(result["success"])

    def test_launch_uses_call_for_npx_cmd_paths_with_spaces(self):
        import config, n8n_autostart
        fake_file = mock.Mock()
        fake = mock.Mock()
        fake.pid = 4242
        fake.poll.return_value = None
        with mock.patch.object(config, "N8N_ENABLED", True), \\
             mock.patch.object(config, "N8N_AUTOSTART", True), \\
             mock.patch.object(n8n_autostart, "_is_windows", return_value=True), \\
             mock.patch.object(n8n_autostart, "n8n_port_open", return_value=False), \\
             mock.patch.object(n8n_autostart, "_npx_path", return_value=r"C:\\Program Files\\nodejs\\npx.cmd"), \\
             mock.patch.object(n8n_autostart.n8n_log_path, "__call__") as unused, \\
             mock.patch("n8n_autostart.n8n_log_path", return_value=Path(config.BASE_DIR) / ".jarvis_runtime" / "test-n8n.log"), \\
             mock.patch.object(Path, "open", return_value=fake_file), \\
             mock.patch.object(n8n_autostart.subprocess, "Popen", return_value=fake) as popen:
            result = n8n_autostart.ensure_n8n_started(timeout=0.5, poll_interval=0.1)

        self.assertTrue(result["success"])
        args = popen.call_args.args[0]
        self.assertEqual(args[:3], [args[0], "/d", "/c"])
        self.assertIn(r'call "C:\\Program Files\\nodejs\\npx.cmd" --yes n8n@2.40.5', args[3])
        self.assertNotIn("/s", args)

    def test_background_launch_returns_without_waiting(self):
        import config, n8n_autostart
        fake = mock.Mock()
        fake.pid = 4242
        fake.poll.return_value = None
        with mock.patch.object(config, "N8N_ENABLED", True),              mock.patch.object(config, "N8N_AUTOSTART", True),              mock.patch.object(n8n_autostart, "_is_windows", return_value=True),              mock.patch.object(n8n_autostart, "n8n_port_open", return_value=False),              mock.patch.object(n8n_autostart, "_launch_process", return_value=fake),              mock.patch.object(n8n_autostart.threading, "Thread") as thread:
            result = n8n_autostart.ensure_n8n_started()
        self.assertTrue(result["success"])
        self.assertTrue(result["started"])
        self.assertEqual(result["pid"], 4242)
        thread.assert_called_once()

if __name__ == "__main__":
    unittest.main()
