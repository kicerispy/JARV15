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
