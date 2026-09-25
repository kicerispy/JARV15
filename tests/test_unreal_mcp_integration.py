import json

from commands import build_unreal_mcp_plan
from tool_registry import UNREAL_MCP_TOOLS, JSON_ARGUMENT_TOOLS, validate_known_tools
from unreal_mcp import (
    UNREAL_MCP_PROTOCOL_VERSION,
    UnrealMcpClient,
    _frames,
    _parse_gateway,
)


class FakeResponse:
    def __init__(self, content_type, lines):
        self.headers = {"Content-Type": content_type}
        self._lines = lines
        self.text = ""

    def iter_lines(self, decode_unicode=True):
        return self._lines


def test_unreal_mcp_tools_are_registered():
    assert {
        "unreal_mcp",
        "unreal_mcp_status",
        "unreal_mcp_setup",
    } <= set(UNREAL_MCP_TOOLS)
    assert "unreal_mcp" in JSON_ARGUMENT_TOOLS
    assert validate_known_tools(UNREAL_MCP_TOOLS) == []


def test_unreal_mcp_status_routes_deterministically():
    assert build_unreal_mcp_plan("check Unreal MCP status") == {
        "steps": [{"tool": "unreal_mcp_status", "argument": ""}]
    }


def test_unreal_mcp_search_route_builds_upstream_gateway_call():
    plan = build_unreal_mcp_plan("search Unreal for spawning an actor")
    assert plan["steps"][0]["tool"] == "unreal_mcp"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload == {
        "operation": "search",
        "query": "spawning an actor",
    }


def test_unreal_mcp_describe_route_builds_upstream_gateway_call():
    plan = build_unreal_mcp_plan(
        "describe Unreal capability manage_asset.import_asset"
    )
    assert plan["steps"][0]["tool"] == "unreal_mcp"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload == {
        "operation": "describe",
        "capability": "manage_asset.import_asset",
    }


def test_unreal_mcp_raw_json_is_forwarded_without_rewriting():
    raw = json.dumps({
        "operation": "execute",
        "capability": "control_actor.spawn",
        "params": {"classPath": "/Script/Engine.StaticMeshActor"},
    })
    plan = build_unreal_mcp_plan(f"unreal mcp {raw}")
    assert plan["steps"][0]["tool"] == "unreal_mcp"
    assert json.loads(plan["steps"][0]["argument"]) == json.loads(raw)


def test_unreal_mcp_gateway_payload_validation():
    payload = _parse_gateway(
        '{"operation":"search","query":"spawn actor"}'
    )
    assert payload["operation"] == "search"

    try:
        _parse_gateway('{"operation":"not-valid"}')
    except ValueError as exc:
        assert "search, describe, execute, or configure" in str(exc)
    else:
        raise AssertionError("Invalid gateway operation was accepted.")


def test_unreal_mcp_sse_parser_handles_fragmented_events():
    response = FakeResponse(
        "text/event-stream",
        [
            'event: message',
            'data: {"jsonrpc":"2.0",',
            'data: "id":1001,"result":{"ok":true}}',
            '',
        ],
    )
    frames = _frames(response)
    assert frames == [
        {
            "jsonrpc": "2.0",
            "id": 1001,
            "result": {"ok": True},
        }
    ]


def test_unreal_mcp_client_uses_native_protocol_version():
    client = UnrealMcpClient()
    assert client.protocol_version == UNREAL_MCP_PROTOCOL_VERSION
    headers = client.headers(session=False, protocol=False)
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json, text/event-stream"




def test_unreal_mcp_project_path_accepts_uproject_file(monkeypatch, tmp_path):
    import config
    import unreal_mcp

    project_dir = tmp_path / "FGH"
    project_dir.mkdir()
    project_file = project_dir / "FGH.uproject"
    project_file.write_text("{}", encoding="utf-8")

    token_path = project_dir / "Saved" / "MCP" / "capability-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("test-token", encoding="utf-8")

    monkeypatch.setattr(config, "UNREAL_MCP_PROJECT_PATH", str(project_file))
    monkeypatch.setattr(config, "UNREAL_MCP_TOKEN", "")
    monkeypatch.setattr(config, "UNREAL_MCP_TOKEN_FILE", "")

    token, source = unreal_mcp.capability_token()

    assert token == "test-token"
    assert source == f"file:{token_path.resolve()}"
