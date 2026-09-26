from __future__ import annotations

import json

import adaptive_runtime
from tool_registry import ADAPTIVE_RUNTIME_TOOLS, JSON_ARGUMENT_TOOLS


def test_adaptive_runtime_registry_is_known():
    expected = {
        "hindsight_status",
        "hindsight_remember",
        "hindsight_recall",
        "hindsight_reflect",
        "coding_style_review",
        "response_style",
        "magnitude_status",
    }
    assert expected <= set(ADAPTIVE_RUNTIME_TOOLS)
    assert "hindsight_recall" in JSON_ARGUMENT_TOOLS
    assert "coding_style_review" in JSON_ARGUMENT_TOOLS


def test_response_style_is_action_first_and_bounded():
    answer = adaptive_runtime.response_style(
        "Sure, great question! First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence."
    )
    assert not answer.lower().startswith("sure")
    assert len(answer) <= 900
    assert "First sentence." in answer


def test_coding_style_review_flags_overlarge_plan():
    steps = [
        {"tool": "edit_file", "description": "edit"},
        {"tool": "write_file", "description": "create helper"},
    ] * 5
    result = adaptive_runtime.coding_style_review(
        json.dumps({"request": "small fix", "steps": steps})
    )
    assert result["success"] is True
    assert result["lean"] is False
    assert result["concerns"]


def test_magnitude_status_is_nonfatal_when_missing(monkeypatch):
    monkeypatch.setattr(adaptive_runtime.shutil, "which", lambda _: None)
    result = adaptive_runtime.magnitude_status()
    assert result["success"] is True
    assert result["installed"] is False


def test_hindsight_status_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(adaptive_runtime, "ADAPTIVE_MEMORY_ENABLED", False)
    result = adaptive_runtime.hindsight_status()
    assert result["success"] is True
    assert result["enabled"] is False

def test_agent_browser_status_is_nonfatal_when_missing(monkeypatch):
    monkeypatch.setattr(adaptive_runtime.shutil, "which", lambda _: None)
    result = adaptive_runtime.agent_browser_status()
    assert result["success"] is True
    assert result["installed"] is False


def test_agent_browser_action_uses_current_cli_syntax(monkeypatch):
    import adaptive_runtime

    calls = []

    class Result:
        returncode = 0
        stdout = '{"success":true}'
        stderr = ""

    monkeypatch.setattr(
        adaptive_runtime,
        "_agent_browser_executable",
        lambda: "agent-browser",
    )

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(adaptive_runtime.subprocess, "run", fake_run)

    result = adaptive_runtime.agent_browser_action(
        '{"action":"press","key":"Enter"}'
    )
    assert result["success"] is True
    assert calls[-1][:2] == ["agent-browser", "press"]
    assert calls[-1][2] == "Enter"

    result = adaptive_runtime.agent_browser_action(
        '{"action":"scroll","direction":"down","amount":500}'
    )
    assert result["success"] is True
    assert calls[-1][:4] == ["agent-browser", "scroll", "down", "500"]

    result = adaptive_runtime.agent_browser_action(
        '{"action":"get_text","target":"@e1"}'
    )
    assert result["success"] is True
    assert calls[-1][:4] == ["agent-browser", "get", "text", "@e1"]


def test_agent_browser_webmcp_requires_explicit_opt_in(monkeypatch):
    import adaptive_runtime

    monkeypatch.setattr(adaptive_runtime, "_agent_browser_executable", lambda: "agent-browser")
    monkeypatch.setattr(adaptive_runtime, "AGENT_BROWSER_ALLOW_WEBMCP", False)

    result = adaptive_runtime.agent_browser_action(
        '{"action":"webmcp_invoke","tool":"send_email","params":{}}'
    )

    assert result["success"] is False
    assert "disabled" in result["message"].lower()


def test_agent_browser_webmcp_requires_confirmation(monkeypatch):
    import adaptive_runtime

    monkeypatch.setattr(adaptive_runtime, "_agent_browser_executable", lambda: "agent-browser")
    monkeypatch.setattr(adaptive_runtime, "AGENT_BROWSER_ALLOW_WEBMCP", True)

    result = adaptive_runtime.agent_browser_action(
        '{"action":"webmcp_invoke","tool":"send_email","params":{}}'
    )

    assert result["success"] is False
    assert "confirmed=true" in result["message"]


def test_agent_browser_webmcp_discovery_is_read_only(monkeypatch):
    import adaptive_runtime

    calls = []

    class Result:
        returncode = 0
        stdout = '{"tools":[]}'
        stderr = ""

    monkeypatch.setattr(
        adaptive_runtime,
        "_agent_browser_executable",
        lambda: "agent-browser",
    )

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(adaptive_runtime.subprocess, "run", fake_run)

    result = adaptive_runtime.agent_browser_action(
        '{"action":"webmcp_list","target":"search"}'
    )

    assert result["success"] is True
    assert calls[-1][:4] == ["agent-browser", "webmcp", "list", "search"]
