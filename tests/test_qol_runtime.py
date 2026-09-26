from pathlib import Path


def test_screen_vision_module_import_does_not_require_display():
    import importlib
    import sys

    sys.modules.pop("screen_vision", None)
    module = importlib.import_module("screen_vision")

    assert hasattr(module, "_get_pyautogui")


def test_runtime_health_reports_configured_planner_model():
    import config
    import runtime_health

    status = runtime_health.collect_health()
    assert status["models"]["chat"] == config.CHAT_MODEL
    assert status["models"]["planner"] == config.PLANNER_MODEL


def test_active_context_preserves_rich_browser_state():
    from state import ActiveContext

    context = ActiveContext(
        site="youtube",
        last_query="iron man trailer",
        last_tool="browser_click_result",
        page_url="https://www.youtube.com/watch?v=abc",
        page_title="Iron Man Trailer",
        last_result_title="Iron Man Official Trailer",
        last_result_url="https://www.youtube.com/watch?v=abc",
        last_element="Iron Man Official Trailer",
        last_action="browser_click_result",
    )

    snapshot = context.to_dict()

    assert snapshot["site"] == "youtube"
    assert snapshot["last_query"] == "iron man trailer"
    assert snapshot["page_url"].endswith("abc")
    assert snapshot["last_result_title"] == "Iron Man Official Trailer"
    assert snapshot["last_action"] == "browser_click_result"

    context.clear()
    assert context.to_dict()["page_url"] is None
    assert context.to_dict()["last_result_title"] is None


def test_context_resolver_handles_numbered_browser_followups_without_llm():
    from context_resolver import resolve_followup

    active = {
        "site": "youtube",
        "last_query": "wifi skeleton",
        "last_tool": "browser_search_google",
        "last_result": "search complete",
        "page_url": "https://www.youtube.com/results?search_query=wifi+skeleton",
        "page_title": "wifi skeleton - YouTube",
        "last_result_title": "WiFi Skeleton Tutorial",
        "last_result_url": "https://www.youtube.com/watch?v=abc",
        "last_element": "WiFi Skeleton Tutorial",
    }

    assert resolve_followup(
        "click the second result",
        active,
        "",
    ) == "click the second browser result on youtube"

    assert resolve_followup(
        "go back",
        active,
        "",
    ) == "go back in the browser"

    assert resolve_followup(
        "click it",
        active,
        "",
    ) == "click the browser element with visible text 'WiFi Skeleton Tutorial'"


def test_response_pipeline_never_drops_source_words():
    from response_pipeline import clean_for_speech, split_for_speech

    source = (
        "First result title. Second result title. "
        "Third result title. This is the complete browser result."
    )

    cleaned = clean_for_speech(source)
    chunks = split_for_speech(source, max_chars=24)

    assert chunks
    assert "complete browser result" in " ".join(chunks)
    assert cleaned.replace(" ", "") in "".join(chunks).replace(" ", "")


def test_task_memory_records_only_bounded_metadata(tmp_path, monkeypatch):
    import task_memory

    monkeypatch.setattr(
        task_memory,
        "TASK_MEMORY_PATH",
        tmp_path / "task_memory.json",
    )

    assert task_memory.record_task(
        request="open browser",
        goal="open the browser",
        status="completed",
        result="done",
        error="",
        replans=1,
    )

    records = task_memory.get_recent(1)
    assert len(records) == 1
    assert records[0]["request"] == "open browser"
    assert records[0]["status"] == "completed"
    assert records[0]["replans"] == 1

    assert task_memory.format_recent(1).startswith("- completed: open browser")


def test_startup_manager_builds_a_real_run_command():
    import startup_manager

    command = startup_manager._command()

    assert "run_jarvis.py" in command
    assert "--startup" in command


def test_fast_browser_searches_skip_initial_acknowledgement():
    from task_controller import _should_send_initial_acknowledgement

    assert _should_send_initial_acknowledgement(
        "Search Google for wifi skeleton"
    ) is False

    assert _should_send_initial_acknowledgement(
        "Google search for wireless headphones"
    ) is False

    assert _should_send_initial_acknowledgement(
        "Search Bing for JARVIS"
    ) is False

    assert _should_send_initial_acknowledgement(
        "Bing search for Python"
    ) is False

    assert _should_send_initial_acknowledgement(
        "Open a website and investigate the results"
    ) is True


def test_planner_lists_new_reliability_tools():
    import planner

    for name in (
        "browser_click_result",
        "browser_back",
        "startup_status",
        "enable_startup",
        "disable_startup",
        "task_history",
    ):
        assert name in planner.AVAILABLE_TOOLS


def test_screen_adapter_exposes_all_tool_dispatch_functions():
    source = Path("screen_vision.py").read_text(encoding="utf-8")

    for name in (
        "capture_screen",
        "get_screen_size",
        "get_active_window",
        "analyze_screen",
        "move_mouse_to_target",
        "click_screen_target",
        "double_click_screen_target",
        "right_click_screen_target",
        "scroll_screen",
        "verify_screen_state",
        "type_text",
        "press_key",
        "wait_for_change",
    ):
        assert f"def {name}" in source


def test_browser_click_result_dispatch_does_not_hit_json_scope_error(monkeypatch):
    import browser_controller
    import tools

    calls = {}

    def fake_click_result(index=1, site="", query=""):
        calls.update(index=index, site=site, query=query)
        return {"success": True, "verified": True}

    monkeypatch.setattr(browser_controller, "browser_click_result", fake_click_result)

    result = tools.run_browser_tool(
        "browser_click_result",
        '{"index":2,"site":"google","query":"JARVIS"}',
    )

    assert result.success is True
    assert calls == {
        "index": 2,
        "site": "google",
        "query": "JARVIS",
    }

    calls.clear()
    result = tools.run_browser_tool(
        "browser_click_result",
        '{"number":2,"site":"google","query":"JARVIS"}',
    )

    assert result.success is True
    assert calls["index"] == 2


def test_browser_dom_dispatch_accepts_llm_python_dict_syntax(monkeypatch):
    import browser_controller
    import tools

    calls = {}

    def fake_find_element(selector="", text="", role=""):
        calls.update(selector=selector, text=text, role=role)
        return {"success": True, "verified": True}

    monkeypatch.setattr(browser_controller, "browser_find_element", fake_find_element)

    result = tools.run_browser_tool(
        "browser_find_element",
        "{'role': 'organic-result'}",
    )

    assert result.success is True
    assert calls == {
        "selector": "",
        "text": "",
        "role": "organic-result",
    }


def test_planner_canonicalizes_python_literal_browser_arguments():
    from planner import validate_plan

    plan = validate_plan({
        "goal": "inspect browser results",
        "steps": [{
            "tool": "browser_find_element",
            "argument": "{'role': 'organic-result'}",
        }],
    })

    assert plan["steps"][0]["argument"] == '{"role":"organic-result"}'


def test_browser_result_format_is_specific():
    from tool_executor import format_browser_result

    message = format_browser_result(
        "browser_click_result",
        {
            "success": True,
            "verified": True,
            "index": 2,
            "result_title": "JARVIS Browser Automation",
        },
    )

    assert message == "Opened result 2: JARVIS Browser Automation."


def test_browser_search_and_click_summaries_are_concise():
    from tool_executor import format_browser_result

    assert format_browser_result(
        "browser_search_google",
        {
            "success": True,
            "verified": True,
            "title": "JARVIS browser automation - Google Search",
            "url": "https://www.google.com/search?q=JARVIS+browser+automation",
        },
    ) == "Google search complete."

    assert format_browser_result(
        "browser_click_result",
        {
            "success": True,
            "verified": True,
            "index": 2,
            "result_title": "Awesome Browser Automation\n\nGitHub\nhttps://github.com/example",
        },
    ) == "Opened result 2: Awesome Browser Automation GitHub https://github.com/example."


def test_task_completion_summaries_are_natural_and_concise():
    from tool_executor import _spoken_execution_summary

    assert _spoken_execution_summary(
        "search_website",
        "Searching Google for Wi-Fi Skeleton.",
    ) == "Google search complete."

    assert _spoken_execution_summary(
        "browser_search_google",
        "Google search action completed. Title: Wi-Fi Skeleton - Google Search URL: https://google.com",
    ) == "Google search complete."

    assert _spoken_execution_summary(
        "read_file",
        "long source file contents ...",
    ) == "I inspected the relevant source file."

    assert _spoken_execution_summary(
        "write_file",
        "Wrote 1 file successfully.",
    ) == "The file is written."

    assert _spoken_execution_summary(
        "open_program",
        "Program launched successfully.",
    ) == "The application is open."

    assert _spoken_execution_summary(
        "unknown_tool",
        "Tool completed.",
    ) == "Done."


def test_task_state_tracks_completion_speech_delivery():
    from state import TaskState

    task_state = TaskState()
    task_state.prepare("test task", 1)
    assert task_state.was_completion_spoken() is False

    task_state.mark_completion_spoken()
    assert task_state.was_completion_spoken() is True

    task_state.start("test task", 1)
    assert task_state.was_completion_spoken() is False


def test_search_website_returns_concise_completion_message(monkeypatch):
    import tools
    import browser_controller
    monkeypatch.setattr(
        browser_controller,
        "browser_goto",
        lambda url: {"success": True},
    )

    assert tools.search_website("google", "Wi-Fi Skeleton") == (
        "Google search complete."
    )


def test_tts_status_exposes_runtime_provider():
    source = Path("voice.py").read_text(encoding="utf-8-sig")

    assert '"provider": "CUDA" if _using_cuda else "CPU"' in source
    assert '"onnx_providers"' in source

def test_background_memory_analysis_skips_software_tasks():
    import main

    assert main.should_run_background_memory_analysis(
        "diagnose and repair the bug in browser_controller.py"
    ) is False

    assert main.should_run_background_memory_analysis(
        "add a new feature to JARVIS"
    ) is False

    assert main.should_run_background_memory_analysis(
        "what is the weather today?"
    ) is True



def test_browser_title_speech_uses_task_goal():
    from tool_executor import _spoken_execution_summary
    from tool_result import ToolResult

    result = ToolResult(
        success=True,
        tool="browser_page_info",
        data={
            "success": True,
            "verified": True,
            "title": "Example Domain",
            "url": "https://example.com/",
        },
    )

    assert _spoken_execution_summary(
        "browser_page_info",
        'Browser page inspected. Title: Example Domain URL: https://example.com/',
        result,
        "What's the page title of example.com?",
    ) == 'The page title is "Example Domain".'



def test_planner_exposes_platform_autonomy_tools():
    import planner

    for name in (
        "jarvis_doctor",
        "jarvis_quickcheck",
        "healing_hints",
        "tool_health",
        "code_index_rebuild",
        "autonomy_status",
        "strategy_history",
        "regression_status",
    ):
        assert name in planner.AVAILABLE_TOOLS
