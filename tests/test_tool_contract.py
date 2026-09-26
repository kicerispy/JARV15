import json


def test_full_planner_tool_contract_is_registered():
    from planner import AVAILABLE_TOOLS
    from tool_registry import registry_contract_report, validate_known_tools

    report = registry_contract_report(AVAILABLE_TOOLS.keys())

    assert report["healthy"] is True
    assert report["planner_missing_from_registry"] == []
    assert validate_known_tools(set(AVAILABLE_TOOLS)) == []


def test_tool_contract_audit_is_directly_executable():
    from tool_registry import tool_contract_audit

    result = tool_contract_audit()

    assert result["success"] is True
    assert result["verified"] is True
    assert result["tool"] == "tool_contract_audit"
    assert result["healthy"] is True
    assert result["planner_missing_from_registry"] == []


def test_contract_report_allows_dynamic_mcp_tool_names():
    from tool_registry import registry_contract_report

    report = registry_contract_report(
        {
            "browser_connect",
            "roblox__get_place_info",
            "n8n_mcp__search_workflows",
        }
    )

    assert report["planner_missing_from_registry"] == []


def test_tool_contract_audit_dispatcher_path():
    from tools import run_tool

    result = run_tool("tool_contract_audit", "")

    if hasattr(result, "data"):
        data = result.data
    else:
        data = result

    assert isinstance(data, dict)
    assert data["healthy"] is True
