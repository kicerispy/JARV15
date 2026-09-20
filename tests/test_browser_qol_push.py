from pathlib import Path


def test_browser_controller_exposes_navigation_and_tab_qol_tools():
    source = Path("browser_controller.py").read_text(encoding="utf-8")
    for name in (
        "browser_refresh",
        "browser_forward",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_current_tab",
        "browser_close_tab",
        "browser_get_links",
        "browser_open_link",
    ):
        assert f"def {name}" in source


def test_browser_controller_keeps_playwright_native_cdp_pipe():
    source = Path("browser_controller.py").read_text(encoding="utf-8")
    assert 'f"--remote-debugging-port={JARVIS_CDP_PORT}"' in source
    assert 'ignore_default_args=["--remote-debugging-pipe"]' not in source


def test_planner_registers_browser_qol_tools():
    import planner

    for name in (
        "browser_refresh",
        "browser_forward",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_current_tab",
        "browser_close_tab",
        "browser_get_links",
        "browser_open_link",
        "browser_scroll",
    ):
        assert name in planner.AVAILABLE_TOOLS


def test_browser_qol_tools_use_json_arguments_when_needed():
    import planner

    for name in (
        "browser_switch_tab",
        "browser_close_tab",
        "browser_get_links",
        "browser_open_link",
        "browser_scroll",
    ):
        assert name in planner.JSON_ARGUMENT_TOOLS


def test_browser_agent_has_deterministic_title_fast_path():
    source = Path("browser_agent.py").read_text(encoding="utf-8")
    assert "_is_page_title_request" in source
    assert "_extract_explicit_url" in source
    assert '"mode": "deterministic_browser_fast_path"' in source


def test_browser_agent_worker_uses_valid_history_floor():
    source = Path("browser_agent_worker.py").read_text(encoding="utf-8")
    assert "max_history_items=8" in source
    assert "max_history_items=3" not in source


def test_coding_warmup_can_be_deferred():
    import config
    source = Path("main.py").read_text(encoding="utf-8")
    assert "CODING_MODEL_WARMUP_DELAY_SECONDS" in source
    assert "Coding model warm-up deferred" in source
    assert hasattr(config, "CODING_MODEL_WARMUP_DELAY_SECONDS")



def test_browser_registry_is_shared_by_planner_dispatcher_and_executor():
    import planner
    import tools
    import tool_executor
    from tool_registry import BROWSER_TOOLS

    assert tools.BROWSER_TOOLS == BROWSER_TOOLS
    assert tool_executor.BROWSER_TOOLS == BROWSER_TOOLS
    assert planner.BROWSER_TOOLS == BROWSER_TOOLS


def test_pyproject_uses_flat_module_metadata():
    import tomllib

    payload = tomllib.loads(
        open("pyproject.toml", "rb").read().decode("utf-8")
    )
    tool = payload["tool"]["setuptools"]

    assert "packages" not in tool
    assert "tool_registry" in tool["py-modules"]
    assert "tool_result" in tool["py-modules"]
