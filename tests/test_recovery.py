"""Integration tests for Healing Kernel decisions inside recovery.py."""

import recovery
from tool_result import ToolResult


class FakeRecoveryModelManager:
    def __init__(self, callback):
        self._callback = callback

    def recovery(self, messages, format="json"):
        return self._callback(messages, format=format)


def test_transient_exception_retries_without_recovery_model(monkeypatch):
    calls = {"run": 0, "model": 0}

    def fake_recovery(*args, **kwargs):
        calls["model"] += 1
        raise AssertionError("transient transport errors should not call the model")

    def run_tool(tool_name, argument):
        calls["run"] += 1
        if calls["run"] == 1:
            raise TimeoutError("request timed out")
        return ToolResult(
            success=True,
            tool=tool_name,
            data={"ok": True},
        )

    monkeypatch.setattr(
        recovery,
        "MODEL_MANAGER",
        FakeRecoveryModelManager(fake_recovery),
    )

    result = recovery.retry_with_recovery(
        "web_search",
        "wifi skeleton",
        run_tool,
        max_attempts=2,
    )

    assert result["success"] is True
    assert result["attempts"] == 2
    assert calls["model"] == 0


def test_browser_drift_escalates_without_argument_rewrite(monkeypatch):
    calls = {"run": 0, "model": 0}

    def fake_recovery(*args, **kwargs):
        calls["model"] += 1
        raise AssertionError("browser drift belongs to Agent Core replanning")

    def run_tool(tool_name, argument):
        calls["run"] += 1
        return ToolResult(
            success=False,
            tool=tool_name,
            error="No such element: Downloads",
            retryable=True,
        )

    monkeypatch.setattr(
        recovery,
        "MODEL_MANAGER",
        FakeRecoveryModelManager(fake_recovery),
    )

    result = recovery.retry_with_recovery(
        "browser_click_element",
        "Downloads",
        run_tool,
        max_attempts=3,
    )

    assert result["success"] is False
    assert result["attempts"] == 1
    assert calls["run"] == 1
    assert calls["model"] == 0


def test_invalid_argument_can_use_recovery_model_even_when_tool_marks_failure_nonretryable(monkeypatch):
    seen = []

    def fake_recovery(messages, format="json"):
        seen.append(messages[0]["content"])
        return {
            "message": {
                "content": (
                    '{"can_fix": true,'
                    '"new_argument": "Belvidere, IL",'
                    '"explanation": "Normalized the location."}'
                )
            }
        }

    def run_tool(tool_name, argument):
        if argument == "Belvidere":
            return ToolResult(
                success=False,
                tool=tool_name,
                error="invalid argument: location must include region",
                retryable=False,
            )

        return ToolResult(
            success=True,
            tool=tool_name,
            data={"location": argument},
        )

    monkeypatch.setattr(
        recovery,
        "MODEL_MANAGER",
        FakeRecoveryModelManager(fake_recovery),
    )

    result = recovery.retry_with_recovery(
        "weather",
        "Belvidere",
        run_tool,
        max_attempts=2,
    )

    assert result["success"] is True
    assert result["attempts"] == 2
    assert len(seen) == 1


def test_code_regression_escalates_to_agent_core(monkeypatch):
    called = {"model": 0}

    def fake_recovery(*args, **kwargs):
        called["model"] += 1
        raise AssertionError("code regressions should enter source-repair workflow")

    def run_tool(tool_name, argument):
        return ToolResult(
            success=False,
            tool=tool_name,
            error="SyntaxError: invalid syntax in browser_controller.py",
            retryable=True,
        )

    monkeypatch.setattr(
        recovery,
        "MODEL_MANAGER",
        FakeRecoveryModelManager(fake_recovery),
    )

    result = recovery.retry_with_recovery(
        "code_test",
        '{"mode":"compile","path":"browser_controller.py"}',
        run_tool,
        max_attempts=3,
    )

    assert result["success"] is False
    assert result["attempts"] == 1
    assert called["model"] == 0
