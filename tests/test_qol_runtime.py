import json
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



def test_platform_diagnostics_routes_are_deterministic():
    from commands import build_platform_diagnostics_plan

    assert build_platform_diagnostics_plan("jarvis doctor")["steps"][0]["tool"] == "jarvis_doctor"
    assert build_platform_diagnostics_plan("tool health")["steps"][0]["tool"] == "tool_health"
    assert build_platform_diagnostics_plan("rebuild code index")["steps"][0]["tool"] == "code_index_rebuild"
    assert build_platform_diagnostics_plan("strategy history for browser search")["steps"][0]["tool"] == "strategy_history"

def test_tool_dispatch_does_not_shadow_n8n_registry(monkeypatch):
    import n8n_bridge
    import tools

    monkeypatch.setattr(
        n8n_bridge,
        "n8n_status",
        lambda: {"success": True, "verified": True, "message": "n8n ready"},
    )

    result = tools.run_tool("n8n_status")

    assert result.success is True
    assert result.data["message"] == "n8n ready"

    capabilities = tools.run_tool("jarvis_capabilities")

    assert capabilities.success is True


def test_model_manager_lists_local_ollama_models(monkeypatch):
    from types import SimpleNamespace

    import model_manager
    import ollama

    monkeypatch.setattr(
        ollama,
        "list",
        lambda: SimpleNamespace(
            models=[
                SimpleNamespace(model="qwen3.5:9b", size=123, details=None),
                SimpleNamespace(model="qwen3-coder:14b", size=456, details=None),
            ]
        ),
    )

    models = model_manager.ModelManager().list_local_models()

    assert [item["name"] for item in models] == [
        "qwen3.5:9b",
        "qwen3-coder:14b",
    ]


def test_doctor_reports_health_state_without_becoming_a_failed_tool(monkeypatch):
    import jarvis_doctor

    monkeypatch.setattr(
        jarvis_doctor.runtime_health,
        "collect_health",
        lambda: {"overall": "DEGRADED", "ollama": True},
    )
    monkeypatch.setattr(
        jarvis_doctor,
        "_check_models",
        lambda: {
            "reachable": True,
            "available_count": 1,
            "available_models": ["qwen3.5:9b"],
            "missing_configured_models": {},
        },
    )
    monkeypatch.setattr(jarvis_doctor, "healing_status", lambda: {"events": 0})
    monkeypatch.setattr(
        jarvis_doctor,
        "autonomy_memory_status",
        lambda: {"episodes": 0},
    )
    monkeypatch.setattr(jarvis_doctor, "memory_status", lambda: {"records": 0})
    monkeypatch.setattr(jarvis_doctor, "tool_health_status", lambda limit=12: {"tool_count": 1})
    monkeypatch.setattr(
        jarvis_doctor,
        "_git_snapshot",
        lambda base: {"available": True, "tracked_worktree_clean": True},
    )

    result = jarvis_doctor.run_doctor()

    assert result["success"] is True
    assert result["healthy"] is False
    assert result["failures"]


def test_quickcheck_reports_degraded_state_without_becoming_a_failed_tool(monkeypatch):
    import qol_tools

    monkeypatch.setattr(
        qol_tools.runtime_health,
        "collect_health",
        lambda: {
            "overall": "DEGRADED",
            "ollama": True,
            "whisper": True,
            "piper": True,
        },
    )
    monkeypatch.setattr(qol_tools, "memory_status", lambda: {"records": 2})
    monkeypatch.setattr(qol_tools, "healing_status", lambda: {"events": 1})
    monkeypatch.setattr(
        qol_tools,
        "tool_health_status",
        lambda limit=8: {
            "tool_count": 3,
            "degraded_tools": [{"tool": "example_tool"}],
        },
    )
    monkeypatch.setattr(
        qol_tools,
        "resource_status",
        lambda: {"success": True, "verified": True},
    )

    result = qol_tools.jarvis_quickcheck()

    assert result["success"] is True
    assert result["healthy"] is False
    assert result["overall"] == "DEGRADED"
    assert result["tool_health"]["degraded"] == ["example_tool"]


def test_n8n_mcp_diagnostic_routes_are_deterministic():
    from commands import build_platform_diagnostics_plan

    assert build_platform_diagnostics_plan("check n8n MCP status") == {
        "steps": [{"tool": "n8n_mcp_status", "argument": ""}]
    }
    assert build_platform_diagnostics_plan("list n8n MCP tools") == {
        "steps": [{"tool": "n8n_mcp_list_tools", "argument": ""}]
    }


def test_diagnostic_answer_composer_is_concise():
    from types import SimpleNamespace

    from answer_composer import compose_task_answer

    task = SimpleNamespace(
        request="check memory status",
        planner_result=None,
        evidence=[
            {
                "tool": "context_backend_status",
                "success": True,
                "verified": True,
                "data": {
                    "success": True,
                    "verified": True,
                    "selected_backend": "local",
                    "message": "Context memory backend 'local' is available.",
                },
            }
        ],
    )

    answer = compose_task_answer(
        task.request,
        task,
        active_context={},
    )

    assert answer == "Context memory backend 'local' is available."


def test_resilience_health_clears_active_degradation_after_success(tmp_path, monkeypatch):
    import resilience_kernel

    monkeypatch.setattr(
        resilience_kernel,
        "_HEALTH_PATH",
        tmp_path / "tool_health.json",
    )
    monkeypatch.setattr(
        resilience_kernel,
        "_MEMORY_DIR",
        tmp_path,
    )

    runtime = resilience_kernel.RuntimeResilience()
    runtime.record("example_tool", success=False, error="temporary")
    runtime.record("example_tool", success=True)

    status = runtime.snapshot()

    assert status["degraded_tools"] == []
    assert status["historical_failures"][0]["tool"] == "example_tool"


def test_response_pipeline_does_not_speak_parenthetical_plural_markers():
    from response_pipeline import clean_for_speech

    cleaned = clean_for_speech(
        "I found 4 model(s) and 3 tool(s)."
    )

    assert cleaned == "I found 4 models and 3 tools."
    assert "comma s" not in cleaned.lower()


def test_code_index_status_has_a_compact_speech_answer():
    from types import SimpleNamespace
    from answer_composer import compose_task_answer

    task = SimpleNamespace(
        request="code index status",
        planner_result=None,
        evidence=[
            {
                "tool": "code_index_status",
                "success": True,
                "verified": True,
                "data": {
                    "success": True,
                    "verified": True,
                    "indexed_files": 792,
                    "path": r"C:\Users\Jordan\.jarvis_autonomy\code_index.sqlite3",
                    "fts5": True,
                },
            }
        ],
    )

    assert compose_task_answer(
        task.request,
        task,
        active_context={},
    ) == "The local code index contains 792 indexed files."


def test_n8n_mcp_negotiates_modern_protocol_and_lists_tools(monkeypatch):
    import n8n_mcp

    class FakeResponse:
        def __init__(self, payload, headers=None):
            self.payload = payload
            self.headers = headers or {}
            self.status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=None):
            return json.dumps(self.payload).encode("utf-8")

    calls = []

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        calls.append((request, body))
        if body["method"] == "server/discover":
            return FakeResponse({
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {"tools": {"listChanged": False}},
                },
            })
        return FakeResponse({
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "tools": [
                    {"name": "execute_workflow", "description": "Run a workflow", "inputSchema": {}},
                    {"name": "search_workflows", "description": "Find workflows", "inputSchema": {}},
                ]
            },
        })

    monkeypatch.setattr(n8n_mcp, "_PROTOCOL_MODE", "unknown")
    monkeypatch.setattr(n8n_mcp, "_NEGOTIATED_PROTOCOL_VERSION", "")
    monkeypatch.setattr(n8n_mcp, "_SESSION_ID", None)
    monkeypatch.setattr(n8n_mcp, "_TOOL_CACHE", {"expires_at": 0.0, "tools": []})
    monkeypatch.setattr(n8n_mcp, "N8N_MCP_ENABLED", True)
    monkeypatch.setattr(n8n_mcp, "N8N_MCP_URL", "http://127.0.0.1:5678/mcp-server/http")
    monkeypatch.setattr(n8n_mcp, "N8N_MCP_TOKEN", "test-token")
    monkeypatch.setattr(n8n_mcp, "urlopen", fake_urlopen)

    tools = n8n_mcp.list_tools(force=True)

    assert [item["name"] for item in tools] == [
        "execute_workflow",
        "search_workflows",
    ]
    assert n8n_mcp._PROTOCOL_MODE == "modern"
    first_headers = {key.lower(): value for key, value in calls[0][0].header_items()}
    second_headers = {key.lower(): value for key, value in calls[1][0].header_items()}
    assert first_headers["mcp-method"] == "server/discover"
    assert first_headers["mcp-protocol-version"] == "2026-07-28"
    assert second_headers["mcp-method"] == "tools/list"
