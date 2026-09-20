import unittest


class BrowserCDPConfigTests(unittest.TestCase):

    def test_controller_requests_tcp_cdp_and_keeps_playwright_pipe(self):
        from pathlib import Path

        source = Path("browser_controller.py").read_text(encoding="utf-8")
        self.assertIn(
            'JARVIS_CDP_PORT = int(os.getenv("JARVIS_CDP_PORT", "9222"))',
            source,
        )
        self.assertIn(
            'f"--remote-debugging-port={JARVIS_CDP_PORT}"',
            source,
        )
        self.assertNotIn(
            'ignore_default_args=["--remote-debugging-pipe"]',
            source,
        )


if __name__ == "__main__":
    unittest.main()
