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


def test_browser_agent_setup_is_not_a_browser_action():
    from tool_registry import BROWSER_TOOLS

    assert "browser_agent_setup" not in BROWSER_TOOLS


def test_project_discovery_ignores_browser_agent_worker_venv(tmp_path):
    import project_fs

    root = tmp_path
    (root / ".browser_agent_venv" / "bin").mkdir(parents=True)
    (root / ".browser_agent_venv" / "bin" / "browser").write_text("", encoding="utf-8")
    (root / "browser_controller.py").write_text("", encoding="utf-8")

    discovered = {
        path.relative_to(root).as_posix()
        for path in project_fs.iter_project_files(root)
    }

    assert "browser_controller.py" in discovered
    assert ".browser_agent_venv/bin/browser" not in discovered
