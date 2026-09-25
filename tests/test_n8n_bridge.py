import json
import unittest
from unittest.mock import patch

import n8n_bridge


class _FakeResponse:
    status = 200

    def __init__(self, payload=b'{"accepted":true,"message":"Workflow accepted."}'):
        self._payload = payload

    def read(self, *_args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class N8nBridgeTests(unittest.TestCase):

    def test_classifier_routes_workflow_strengths(self):
        cases = {
            "Remind me tomorrow to test the Roblox game": "schedule",
            "Monitor GitHub and notify me when CI fails": "monitor",
            "Email me the GitHub report": "integration",
            "Automate this across multiple services": "orchestration",
            "Open Spotify and play my liked songs": "integration",
        }

        for request, expected in cases.items():
            self.assertEqual(
                n8n_bridge.classify_n8n_request(request),
                expected,
                request,
            )

    def test_classifier_does_not_steal_n8n_explanations(self):
        self.assertIsNone(
            n8n_bridge.classify_n8n_request("What is n8n?")
        )
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "Explain how n8n workflows work"
            )
        )
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "How does n8n handle workflow retries?"
            )
        )


    def test_classifier_does_not_steal_immediate_local_work(self):
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "Inspect my Roblox game and tell me how the project is structured"
            )
        )
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "Search Google for wifi skeleton"
            )
        )


    def test_classifier_routes_spotify_desktop_automation(self):
        self.assertEqual(
            n8n_bridge.classify_n8n_request(
                "Open Spotify and play my liked songs"
            ),
            "integration",
        )

    def test_classifier_prefers_n8n_for_single_service_actions(self):
        cases = {
            "Send an email to my inbox": "integration",
            "Create a GitHub issue for this bug": "integration",
            "Add an event to Google Calendar": "integration",
            "Update my Notion page": "integration",
            "Open Spotify and play my liked songs": "integration",
            "Sync Google Sheets with Airtable": "orchestration",
        }

        for request, expected in cases.items():
            self.assertEqual(
                n8n_bridge.classify_n8n_request(request),
                expected,
                request,
            )

    def test_classifier_keeps_read_only_service_queries_fast(self):
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "Search GitHub for the JARV3 repository"
            )
        )
        self.assertIsNone(
            n8n_bridge.classify_n8n_request(
                "Find a Spotify song by Daft Punk"
            )
        )

    def test_dispatch_is_disabled_by_default(self):
        with patch.object(n8n_bridge, "N8N_ENABLED", False):
            result = n8n_bridge.run_n8n_workflow(
                "Remind me tomorrow to test Roblox",
                "schedule",
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["retryable"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["execution_owner"], "n8n")

    def test_dispatch_prefers_native_mcp_when_enabled(self):
        with patch.object(n8n_bridge, "N8N_ENABLED", True), \
             patch("config.N8N_MCP_ENABLED", True):
            # The config symbol is imported lazily by run_n8n_workflow, so
            # patching the module import boundary keeps this test isolated.
            with patch(
                "n8n_mcp.run_workflow_request",
                return_value={
                    "success": True,
                    "verified": True,
                    "execution_owner": "n8n",
                    "message": "MCP workflow completed.",
                },
            ) as run:
                result = n8n_bridge.run_n8n_workflow(
                    "Run the weather workflow",
                    "orchestration",
                    {"location": "Chicago"},
                )

        self.assertTrue(result["success"])
        run.assert_called_once_with(
            request="Run the weather workflow",
            workflow_class="orchestration",
            context={"location": "Chicago"},
        )

    def test_dispatch_posts_structured_workflow_request(self):
        with patch.object(n8n_bridge, "N8N_ENABLED", True), patch.object(
            n8n_bridge,
            "N8N_BASE_URL",
            "http://127.0.0.1:5678",
        ), patch.object(
            n8n_bridge,
            "N8N_WEBHOOK_PATH",
            "webhook/jarvis-gateway",
        ), patch.object(
            n8n_bridge,
            "N8N_WEBHOOK_TOKEN",
            "",
        ), patch.object(
            n8n_bridge,
            "urlopen",
            return_value=_FakeResponse(),
        ) as mocked_urlopen:
            result = n8n_bridge.run_n8n_workflow(
                "Remind me tomorrow to test Roblox",
                "schedule",
                {"site": "roblox"},
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["execution_owner"], "n8n")

        request = mocked_urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))

        self.assertEqual(body["source"], "JARVIS")
        self.assertEqual(body["workflow_class"], "schedule")
        self.assertEqual(body["request"], "Remind me tomorrow to test Roblox")
        self.assertEqual(body["context"]["site"], "roblox")
        self.assertFalse(
            body["execution_policy"]["allow_local_fallback"]
        )

    def test_remote_dispatch_requires_token(self):
        with patch.object(n8n_bridge, "N8N_ENABLED", True), patch.object(
            n8n_bridge,
            "N8N_BASE_URL",
            "https://n8n.example.com",
        ), patch.object(
            n8n_bridge,
            "N8N_WEBHOOK_TOKEN",
            "",
        ):
            result = n8n_bridge.run_n8n_workflow(
                "Email me the report",
                "integration",
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["retryable"])
        self.assertIn("WEBHOOK_TOKEN", result["message"])


if __name__ == "__main__":
    unittest.main()
