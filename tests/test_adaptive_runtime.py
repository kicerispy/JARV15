from __future__ import annotations

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
        '{"request":"small fix","steps":' + repr(steps).replace("'", '"') + '}'
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
