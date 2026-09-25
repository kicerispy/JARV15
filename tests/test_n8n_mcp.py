import json
import unittest
from unittest.mock import patch

import n8n_mcp


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeResponse:
    def __init__(self, payload, content_type="application/json", session_id=""):
        self._payload = payload
        self.headers = _FakeHeaders({"Content-Type": content_type})
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id

    def read(self, *_args):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class N8nMcpTests(unittest.TestCase):

    def setUp(self):
        n8n_mcp._SESSION_ID = None
        n8n_mcp._REQUEST_ID = 0
        n8n_mcp._TOOL_CACHE = {"expires_at": 0.0, "tools": []}

    def test_sse_parser_reads_first_json_event(self):
        raw = (
            "event: message\\n"
            "data: {\"jsonrpc\":\"2.0\",\"result\":{\"ok\":true}}\\n"
            "\\n"
        )

        parsed = n8n_mcp._parse_sse(raw)

        self.assertTrue(parsed["result"]["ok"])

    def test_initialize_sends_protocol_and_preserves_session(self):
        responses = [
            _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                    },
                },
                session_id="session-123",
            ),
            _FakeResponse({}),
        ]

        with patch.object(n8n_mcp, "N8N_MCP_ENABLED", True), \
             patch.object(n8n_mcp, "N8N_MCP_URL", "http://127.0.0.1:5678/mcp-server/http"), \
             patch.object(n8n_mcp, "_token", return_value="secret-token"), \
             patch.object(
                 n8n_mcp,
                 "urlopen",
                 side_effect=responses,
             ) as mocked:
            result = n8n_mcp.initialize()

        self.assertEqual(
            result["protocolVersion"],
            "2025-03-26",
        )
        self.assertEqual(
            n8n_mcp._SESSION_ID,
            "session-123",
        )

        first_request = mocked.call_args_list[0].args[0]
        self.assertEqual(
            first_request.get_header("Authorization"),
            "Bearer secret-token",
        )
        self.assertEqual(
            first_request.get_header("Mcp-protocol-version"),
            "2025-03-26",
        )

    def test_call_tool_parses_text_json_result(self):
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"data":[{"id":"123","name":"Weather"}]}',
                    }
                ],
                "isError": False,
            },
        }

        with patch.object(
            n8n_mcp,
            "_rpc",
            side_effect=[
                {
                    "tools": [
                        {
                            "name": "search_workflows",
                            "description": "Search workflows",
                            "inputSchema": {},
                        }
                    ]
                },
                {
                    "content": tool_response["result"]["content"],
                    "isError": False,
                },
            ],
        ):
            result = n8n_mcp.call_tool(
                "search_workflows",
                {"query": "weather"},
            )

        self.assertTrue(result["success"])
        self.assertEqual(
            result["data"]["data"][0]["name"],
            "Weather",
        )

    def test_status_fails_closed_without_token(self):
        with patch.object(n8n_mcp, "N8N_MCP_ENABLED", True), \
             patch.object(n8n_mcp, "_token", return_value=""):
            result = n8n_mcp.status()

        self.assertFalse(result["success"])
        self.assertIn("token", result["message"].lower())

    def test_run_workflow_request_selects_mcp_workflow_and_polls(self):
        tool_calls = [
            {
                "success": True,
                "data": {
                    "data": [
                        {
                            "id": "42",
                            "name": "Weather Research",
                            "description": "Search weather and summarize it",
                            "active": True,
                            "availableInMCP": True,
                            "updatedAt": "2026-09-25T00:00:00Z",
                        }
                    ]
                },
            },
            {
                "success": True,
                "data": {
                    "workflow": {
                        "id": "42",
                        "name": "Weather Research",
                        "active": True,
                        "canExecute": True,
                    },
                    "triggerInfo": "Webhook trigger",
                },
            },
            {
                "success": True,
                "data": {
                    "executionId": "9001",
                    "status": "started",
                },
            },
            {
                "success": True,
                "data": {
                    "execution": {
                        "id": "9001",
                        "workflowId": "42",
                        "status": "success",
                    },
                    "data": {
                        "result": "72F and sunny",
                    },
                },
            },
        ]

        # Supply a detailed execution workflow shape on the second call.
        tool_calls[1]["data"]["workflow"]["nodes"] = [
            {
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
            }
        ]

        def fake_call_tool(name, arguments=None):
            return tool_calls.pop(0)

        with patch.object(n8n_mcp, "call_tool", side_effect=fake_call_tool), \
             patch.object(n8n_mcp.time, "sleep"):
            result = n8n_mcp.run_workflow_request(
                "Chicago weather today",
                "orchestration",
                {"location": "Chicago"},
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["execution_id"], "9001")
        self.assertEqual(result["data"]["result"], "72F and sunny")

    def test_run_workflow_request_refuses_unpublished_non_manual_workflow(self):
        calls = [
            {
                "success": True,
                "data": {
                    "data": [
                        {
                            "id": "7",
                            "name": "Email Workflow",
                            "description": "Send report by email",
                            "active": False,
                            "availableInMCP": True,
                            "updatedAt": "2026-09-25T00:00:00Z",
                        }
                    ]
                },
            },
            {
                "success": True,
                "data": {
                    "workflow": {
                        "id": "7",
                        "name": "Email Workflow",
                        "active": False,
                        "canExecute": True,
                        "nodes": [
                            {
                                "name": "Webhook",
                                "type": "n8n-nodes-base.webhook",
                            }
                        ],
                    }
                },
            },
        ]

        with patch.object(n8n_mcp, "call_tool", side_effect=lambda *args, **kwargs: calls.pop(0)):
            result = n8n_mcp.run_workflow_request(
                "Email me the report",
                "integration",
            )

        self.assertFalse(result["success"])
        self.assertIn("publish", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
