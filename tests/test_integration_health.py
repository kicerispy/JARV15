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
        "screen_memory_status",
        "screen_memory_search",
        "screen_memory_recent",
    }
    assert SYSTEM_HEALTH_TOOLS == {"integration_health"}
    assert validate_known_tools(
        set(GODS_EYE_TOOLS)
        | set(SCREEN_MEMORY_TOOLS)
        | set(SYSTEM_HEALTH_TOOLS)
    ) == []


def test_integration_health_local_sweep_has_structured_components():
    result = integration_health('{"include_optional": false}')
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
    assert build_screen_memory_plan("screen memory status") == {
        "steps": [{"tool": "screen_memory_status", "argument": ""}]
    }

    plan = build_screen_memory_plan("search screen memory for Unreal")
    assert plan["steps"][0]["tool"] == "screen_memory_search"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["query"] == "Unreal"
