import json

from commands import (
    build_gods_eye_plan,
    build_integration_health_plan,
    build_screen_memory_plan,
)
from integration_health import integration_health
from tool_registry import (
    GODS_EYE_TOOLS,
    SCREEN_MEMORY_TOOLS,
    SYSTEM_HEALTH_TOOLS,
    ROBLOX_MCP_TOOLS,
    validate_known_tools,
)


def test_completion_tool_families_are_registered():
    expected_gods_eye = {
        "gods_eye_status",
        "gods_eye_setup",
        "gods_eye_start",
        "gods_eye_open",
        "gods_eye_stop",
        "gods_eye_contacts",
        "gods_eye_vessels",
        "gods_eye_satellites",
        "gods_eye_launches",
        "gods_eye_cameras",
        "gods_eye_radio",
        "gods_eye_transit",
    }
    assert expected_gods_eye <= set(GODS_EYE_TOOLS)
    assert set(SCREEN_MEMORY_TOOLS) == {
        "screen_memory_setup",
        "screen_memory_status",
        "screen_memory_search",
        "screen_memory_recent",
    }
    assert SYSTEM_HEALTH_TOOLS == {"integration_health"}
    assert {"roblox_mcp_status", "roblox_mcp_setup"} <= set(ROBLOX_MCP_TOOLS)
    assert validate_known_tools(
        set(GODS_EYE_TOOLS)
        | set(SCREEN_MEMORY_TOOLS)
        | set(SYSTEM_HEALTH_TOOLS)
    ) == []


def test_integration_health_local_sweep_has_structured_components():
    result = integration_health('{"include_optional": false, "probe": false}')
    assert result["success"] is True
    assert result["verified"] is True
    assert result["tool"] == "integration_health"
    assert result["components"]
    names = {item["name"] for item in result["components"]}
    assert {"Ollama", "Browser", "Anipy", "Unreal MCP", "n8n"} <= names
    assert "registry_counts" in result


def test_integration_health_route():
    plan = build_integration_health_plan("what tools are working right now")
    assert plan == {
        "steps": [{"tool": "integration_health", "argument": ""}]
    }


def test_gods_eye_routes():
    assert build_gods_eye_plan("check God's Eye View status") == {
        "steps": [{"tool": "gods_eye_status", "argument": ""}]
    }
    assert build_gods_eye_plan("start God's Eye View") == {
        "steps": [{"tool": "gods_eye_start", "argument": ""}]
    }
    assert build_gods_eye_plan("show God's Eye View aircraft") == {
        "steps": [{"tool": "gods_eye_contacts", "argument": ""}]
    }


def test_screen_memory_routes():
    assert build_screen_memory_plan("setup screen memory") == {
        "steps": [{"tool": "screen_memory_setup", "argument": ""}]
    }
    assert build_screen_memory_plan("screen memory status") == {
        "steps": [{"tool": "screen_memory_status", "argument": ""}]
    }

    plan = build_screen_memory_plan("search screen memory for Unreal")
    assert plan["steps"][0]["tool"] == "screen_memory_search"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["query"] == "Unreal"


def test_roblox_setup_routes_deterministically():
    from commands import build_roblox_mcp_plan

    assert build_roblox_mcp_plan("check Roblox MCP status") == {
        "steps": [{"tool": "roblox_mcp_status", "argument": ""}]
    }
    assert build_roblox_mcp_plan("setup Roblox MCP") == {
        "steps": [{"tool": "roblox_mcp_setup", "argument": ""}]
    }


def test_integration_health_reports_degraded_and_unavailable_counts(monkeypatch):
    import integration_health as health

    monkeypatch.setattr(health, "_ollama_component", lambda: health._component("Ollama", "READY", "ok"))
    monkeypatch.setattr(health, "_browser_component", lambda: health._component("Browser", "READY", "ok"))
    monkeypatch.setattr(health, "_browser_agent_component", lambda: health._component("Browser Agent", "READY", "ok"))
    monkeypatch.setattr(health, "_anipy_component", lambda: health._component("Anipy", "READY", "ok"))
    monkeypatch.setattr(health, "_memory_component", lambda: health._component("Memory", "DEGRADED", "fallback"))
    monkeypatch.setattr(health, "_skills_component", lambda: health._component("Agent Skills", "READY", "ok"))
    monkeypatch.setattr(health, "_unreal_component", lambda: health._component("Unreal MCP", "NOT_READY", "not ready"))
    monkeypatch.setattr(health, "_roblox_component", lambda: health._component("Roblox MCP", "OFFLINE", "offline"))
    monkeypatch.setattr(health, "_n8n_component", lambda: health._component("n8n", "READY", "ok"))

    result = health.integration_health('{"include_optional": false}')
    assert result["status"] == "DEGRADED"
    assert result["counts"]["DEGRADED"] == 1
    assert result["counts"]["NOT_READY"] == 1
    assert result["counts"]["OFFLINE"] == 1


def test_roblox_health_reads_top_level_plugin_state(monkeypatch):
    import integration_health as health
    from tool_result import ToolResult

    monkeypatch.setattr(
        health,
        "_probe_socket",
        lambda url: (True, "127.0.0.1:58741 reachable"),
    )
    monkeypatch.setattr(
        health,
        "roblox_mcp_status",
        lambda argument="": ToolResult(
            success=True,
            tool="roblox_mcp_status",
            data={
                "health": {
                    "status": "ok",
                    "pluginConnected": True,
                    "instanceCount": 1,
                },
                "status": {
                    "pluginConnected": True,
                    "mcpServerActive": True,
                    "instanceCount": 1,
                },
            },
        ),
    )

    result = health._roblox_component()

    assert result["status"] == "READY"
    assert "plugin is connected" in result["message"]
