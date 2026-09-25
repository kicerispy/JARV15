
import json

import roblox_mcp


def test_parse_tool_argument():
    payload, error = roblox_mcp._parse_tool_argument(
        '{"instancePath":"game.Workspace"}'
    )

    assert error is None
    assert payload == {
        "instancePath": "game.Workspace",
    }


def test_parse_tool_argument_rejects_non_object():
    payload, error = roblox_mcp._parse_tool_argument(
        '["bad"]'
    )

    assert payload is None
    assert "JSON object" in error


def test_planner_tool_descriptions_are_prefixed(monkeypatch):
    monkeypatch.setattr(
        roblox_mcp,
        "discover_roblox_tools",
        lambda force=False: {
            "get_place_info": {
                "name": "get_place_info",
                "description": "Get place info",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            }
        },
    )

    result = roblox_mcp.get_roblox_planner_tool_descriptions()

    assert "roblox__get_place_info" in result
    assert "Get place info" in result["roblox__get_place_info"]
    assert '"type":"object"' in result["roblox__get_place_info"]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_plugin_connection_timeout_is_not_retryable(monkeypatch):
    monkeypatch.setattr(
        roblox_mcp,
        "discover_roblox_tools",
        lambda force=False: {
            "get_place_info": {
                "name": "get_place_info",
                "description": "Get place info",
                "input_schema": {"type": "object"},
            }
        },
    )

    def fake_post(url, **kwargs):
        return FakeResponse(
            {
                "message": "Studio plugin connection timeout. Make sure the Roblox Studio plugin is running and activated."
            },
            status_code=500,
        )

    monkeypatch.setattr(
        roblox_mcp.requests,
        "post",
        fake_post,
    )

    result = roblox_mcp.run_roblox_tool(
        "get_place_info",
        "{}",
    )

    assert result.success is False
    assert result.retryable is False
    assert "plugin connection timeout" in str(result.error).lower()


def test_run_roblox_tool_uses_direct_json_route(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        roblox_mcp,
        "discover_roblox_tools",
        lambda force=False: {
            "get_place_info": {
                "name": "get_place_info",
                "description": "Get place info",
                "input_schema": {"type": "object"},
            }
        },
    )

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["timeout"] = kwargs["timeout"]

        return FakeResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"placeName":"Place2"}',
                    }
                ]
            }
        )

    monkeypatch.setattr(
        roblox_mcp.requests,
        "post",
        fake_post,
    )

    result = roblox_mcp.run_roblox_tool(
        "get_place_info",
        "{}",
    )

    assert result.success is True
    assert captured["url"].endswith(
        "/mcp/get_place_info"
    )
    assert captured["json"] == {}


def test_roblox_mcp_setup_uses_npx_when_server_is_offline(monkeypatch):
    calls = {}

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(
        roblox_mcp,
        "roblox_mcp_status",
        lambda argument="": roblox_mcp.ToolResult(
            success=False,
            tool="roblox_mcp_status",
            error="connection refused",
            retryable=True,
        ),
    )
    monkeypatch.setattr(
        roblox_mcp.shutil,
        "which",
        lambda name: "C:/node/npx.cmd" if name == "npx.cmd" else None,
    )

    def fake_popen(command, **kwargs):
        calls["command"] = command
        return FakeProcess()

    monkeypatch.setattr(roblox_mcp.subprocess, "Popen", fake_popen)

    checks = iter([
        roblox_mcp.ToolResult(
            success=False,
            tool="roblox_mcp_status",
            error="still starting",
            retryable=True,
        ),
        roblox_mcp.ToolResult(
            success=True,
            tool="roblox_mcp_status",
            data={"server_url": roblox_mcp.ROBLOX_MCP_URL},
            observation={},
        ),
    ])
    monkeypatch.setattr(roblox_mcp, "roblox_mcp_status", lambda argument="": next(checks))

    result = roblox_mcp.roblox_mcp_setup()

    assert result.success is True
    assert calls["command"][:2] == ["C:/node/npx.cmd", "-y"]
    assert calls["command"][2] == "robloxstudio-mcp@latest"
