import json

import agent_context
import harness_policy
import skill_catalog
from commands import build_context_and_skill_plan
from tool_registry import (
    AGENT_SKILL_TOOLS,
    CONTEXT_MEMORY_TOOLS,
    JSON_ARGUMENT_TOOLS,
    validate_known_tools,
)


def test_external_tools_are_registered():
    assert {
        "context_backend_status",
        "context_remember",
        "context_recall",
        "context_search",
        "context_read",
    } <= set(CONTEXT_MEMORY_TOOLS)
    assert {
        "skills_status",
        "skills_sync",
        "skills_search",
        "skills_read",
        "harness_review",
    } <= set(AGENT_SKILL_TOOLS)
    assert "context_recall" in JSON_ARGUMENT_TOOLS
    assert "skills_search" in JSON_ARGUMENT_TOOLS
    assert validate_known_tools(CONTEXT_MEMORY_TOOLS) == []
    assert validate_known_tools(AGENT_SKILL_TOOLS) == []


def test_memory_command_routes_deterministically():
    plan = build_context_and_skill_plan("remember that the Unreal project uses port 3000")
    assert plan["steps"][0]["tool"] == "context_remember"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["type"] == "fact"
    assert "port 3000" in payload["content"]


def test_recall_command_routes_deterministically():
    plan = build_context_and_skill_plan("what do you remember about Unreal MCP")
    assert plan["steps"][0]["tool"] == "context_recall"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["query"] == "Unreal MCP"


def test_skill_search_command_routes_deterministically():
    plan = build_context_and_skill_plan("search skills for scientific literature review")
    assert plan["steps"][0]["tool"] == "skills_search"
    payload = json.loads(plan["steps"][0]["argument"])
    assert "literature review" in payload["query"]


def test_skill_source_status_does_not_require_sync():
    status = skill_catalog.status()
    assert status["success"] is True
    assert isinstance(status["sources"], list)


def test_skill_read_rejects_outside_path(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_catalog, "AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    result = skill_catalog.read_skill(str(outside))
    assert result["success"] is False


def test_harness_review_flags_missing_verification_after_mutation():
    result = harness_policy.review_plan(
        [
            {"tool": "browser_fill_element", "argument": "{}"},
            {"tool": "unreal_mcp", "argument": '{"operation":"execute"}'},
        ]
    )
    assert result["success"] is True
    assert result["recommendations"]


def test_local_context_fallback_is_available(monkeypatch):
    class FakeMemory:
        db_path = "fake.db"

        def count(self):
            return 2

    monkeypatch.setattr(agent_context, "_local_memory", lambda: FakeMemory())
    result = agent_context.backend_status(force=True)
    assert result["backends"]["local"]["healthy"] is True
    assert result["backends"]["local"]["memory_count"] == 2



def test_hindsight_context_backend_can_supply_context(monkeypatch):
    monkeypatch.setattr(agent_context, "ADAPTIVE_MEMORY_ENABLED", True)
    monkeypatch.setattr(
        agent_context,
        "_backend_order",
        lambda: ["hindsight", "local"],
    )

    def fake_hindsight(path, payload, timeout=8.0):
        assert "memories/recall" in path
        assert payload["query"] == "Unreal MCP"
        return {"results": ["remembered context"]}

    monkeypatch.setattr(agent_context, "_hindsight_post", fake_hindsight)
    result = agent_context.context("Unreal MCP", limit=3)

    assert result["success"] is True
    assert result["backend"] == "hindsight"
    assert result["context"]["results"] == ["remembered context"]
