"""
Tests for JARVIS SelfImprovementAgent.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis_core.agents.self_improvement_agent import (
    ImprovementSuggestion,
    SelfImprovementAgent,
)
from jarvis_core.config.settings import PersonaConfig, SelfImprovementConfig, Settings
from jarvis_core.utils.types import Context


def _make_context():
    return Context(conversation_id="test-conv", user_id="test-user")


def _make_settings(enabled=True):
    settings = Settings()
    settings.self_improvement = SelfImprovementConfig(
        enabled=enabled,
        evaluation_interval_minutes=0,
    )
    settings.persona = PersonaConfig(
        name="professional", formality=0.8, verbosity=0.4, humor=0.1,
        jargon=0.6, response_style="concise",
    )
    return settings


@pytest.fixture
def agent():
    a = SelfImprovementAgent()
    a._settings = _make_settings()
    a._model = "test-model"
    return a


class TestImprovementSuggestion:
    def test_to_dict_contains_all_fields(self):
        s = ImprovementSuggestion(
            id="test-1",
            category="persona",
            change_type="adjust",
            target="persona.verbosity",
            current_value=0.4,
            suggested_value=0.6,
            confidence=0.85,
            rationale="User seems to want more detail",
            auto_applicable=True,
        )
        d = s.to_dict()
        assert d["id"] == "test-1"
        assert d["category"] == "persona"
        assert d["confidence"] == 0.85
        assert d["auto_applicable"] is True
        assert "timestamp" in d


class TestMetricCollection:
    @pytest.mark.asyncio
    async def test_on_task_completed_appends_metric(self, agent):
        task_data = {
            "task_id": "abc123",
            "status": "completed",
            "description": "Fix bug",
            "steps": [{"tool_name": "read"}, {"tool_name": "edit"}],
            "results": [{"tool_name": "read", "status": "success"}],
            "error": None,
            "completed_at": "2025-01-01T00:00:00",
        }
        await agent._on_task_completed("task_completed", {"task": task_data})
        assert len(agent._metrics_buffer) == 1
        m = agent._metrics_buffer[0]
        assert m["type"] == "task"
        assert m["task_id"] == "abc123"
        assert m["status"] == "completed"
        assert m["num_steps"] == 2
        assert m["num_results"] == 1

    @pytest.mark.asyncio
    async def test_on_response_generated_appends_metric(self, agent):
        data = {"response": "Hello there", "context_id": "conv-1"}
        await agent._on_response_generated("response_generated", data)
        assert len(agent._metrics_buffer) == 1
        assert agent._metrics_buffer[0]["type"] == "response"
        assert agent._metrics_buffer[0]["context_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_trim_buffer_caps_history(self, agent):
        agent._settings.self_improvement.max_metric_history = 3
        for i in range(10):
            agent._metrics_buffer.append({"type": "test", "idx": i})
        agent._trim_buffer()
        assert len(agent._metrics_buffer) == 3
        assert agent._metrics_buffer[0]["idx"] == 7


class TestProcessActions:
    @pytest.mark.asyncio
    async def test_process_status_returns_info(self, agent):
        ctx = _make_context()
        result = await agent.process({"action": "status"}, ctx)
        assert result["enabled"] is True
        assert result["metrics_count"] == 0
        assert result["suggestion_count"] == 0
        assert result["last_evaluation"] is None

    @pytest.mark.asyncio
    async def test_process_unknown_action(self, agent):
        ctx = _make_context()
        result = await agent.process({"action": "bogus"}, ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_process_apply_without_suggestion_id(self, agent):
        ctx = _make_context()
        result = await agent.process({"action": "apply"}, ctx)
        assert result["error"] == "suggestion_id required for apply action"

    @pytest.mark.asyncio
    async def test_process_apply_not_found(self, agent):
        ctx = _make_context()
        result = await agent.process({"action": "apply", "suggestion_id": "nope"}, ctx)
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_process_get_suggestions(self, agent):
        ctx = _make_context()
        agent._suggestions = [
            ImprovementSuggestion(
                id="s1", category="persona", change_type="adjust",
                target="persona.verbosity", current_value=0.4, suggested_value=0.6,
                confidence=0.85, rationale="test",
            )
        ]
        result = await agent.process({"action": "get_suggestions", "limit": 5}, ctx)
        assert result["total"] == 1
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["id"] == "s1"


class TestApplySuggestion:
    @pytest.mark.asyncio
    async def test_apply_persona_formality(self, agent):
        suggestion = ImprovementSuggestion(
            id="s1", category="persona", change_type="adjust",
            target="persona.formality", current_value=0.8, suggested_value=0.9,
            confidence=0.8, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.formality == 0.9

    @pytest.mark.asyncio
    async def test_apply_persona_verbosity(self, agent):
        suggestion = ImprovementSuggestion(
            id="s2", category="persona", change_type="adjust",
            target="persona.verbosity", current_value=0.4, suggested_value=0.6,
            confidence=0.8, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.verbosity == 0.6

    @pytest.mark.asyncio
    async def test_apply_persona_humor(self, agent):
        suggestion = ImprovementSuggestion(
            id="s3", category="persona", change_type="adjust",
            target="persona.humor", current_value=0.1, suggested_value=0.3,
            confidence=0.8, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.humor == 0.3

    @pytest.mark.asyncio
    async def test_apply_persona_jargon(self, agent):
        suggestion = ImprovementSuggestion(
            id="s4", category="persona", change_type="adjust",
            target="persona.jargon", current_value=0.6, suggested_value=0.8,
            confidence=0.8, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.jargon == 0.8

    @pytest.mark.asyncio
    async def test_apply_persona_response_style(self, agent):
        suggestion = ImprovementSuggestion(
            id="s5", category="persona", change_type="adjust",
            target="persona.response_style", current_value="concise", suggested_value="detailed",
            confidence=0.8, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.response_style == "detailed"

    @pytest.mark.asyncio
    async def test_apply_non_persona_skipped(self, agent):
        suggestion = ImprovementSuggestion(
            id="s6", category="workflow", change_type="replace",
            target="tool:planner", current_value="A", suggested_value="B",
            confidence=0.9, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.formality == 0.8

    @pytest.mark.asyncio
    async def test_apply_invalid_value_does_not_crash(self, agent):
        suggestion = ImprovementSuggestion(
            id="s7", category="persona", change_type="adjust",
            target="persona.formality", current_value=0.8, suggested_value="not_a_number",
            confidence=0.9, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)
        assert agent._settings.persona.formality == 0.8


class TestRunEvaluationCycle:
    @pytest.mark.asyncio
    async def test_evaluate_with_no_metrics_returns_empty(self, agent):
        ctx = _make_context()
        result = await agent.process({"action": "evaluate"}, ctx)
        assert result["count"] == 0
        assert result["suggestions"] == []

    @pytest.mark.asyncio
    async def test_evaluate_with_mocked_llm(self, agent):
        ctx = _make_context()
        agent._metrics_buffer.append({"type": "task", "status": "completed"})
        agent._client = MagicMock()
        mock_result = {
            "message": {
                "content": json.dumps([
                    {
                        "category": "persona",
                        "change_type": "adjust",
                        "target": "persona.verbosity",
                        "current_value": 0.4,
                        "suggested_value": 0.6,
                        "confidence": 0.85,
                        "rationale": "User asks for more detail",
                        "auto_applicable": True,
                    }
                ])
            }
        }
        agent._client.chat = AsyncMock(return_value=mock_result)

        result = await agent.process({"action": "evaluate"}, ctx)
        assert result["count"] == 1
        assert result["suggestions"][0]["category"] == "persona"
        assert result["suggestions"][0]["target"] == "persona.verbosity"
        assert len(agent._metrics_buffer) == 0

    @pytest.mark.asyncio
    async def test_evaluate_invalid_json_returns_empty(self, agent):
        ctx = _make_context()
        agent._metrics_buffer.append({"type": "task", "status": "completed"})
        agent._client = MagicMock()
        mock_result = {
            "message": {"content": "this is not json"}
        }
        agent._client.chat = AsyncMock(return_value=mock_result)

        result = await agent.process({"action": "evaluate"}, ctx)
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_evaluate_skips_auto_apply_below_threshold(self, agent):
        ctx = _make_context()
        agent._metrics_buffer.append({"type": "task", "status": "completed"})
        agent._client = MagicMock()
        mock_result = {
            "message": {
                "content": json.dumps([
                    {
                        "category": "persona",
                        "change_type": "adjust",
                        "target": "persona.formality",
                        "current_value": 0.8,
                        "suggested_value": 0.7,
                        "confidence": 0.5,
                        "rationale": "Low confidence test",
                        "auto_applicable": True,
                    }
                ])
            }
        }
        agent._client.chat = AsyncMock(return_value=mock_result)

        result = await agent.process({"action": "evaluate"}, ctx)
        assert result["count"] == 1
        assert agent._settings.persona.formality == 0.8


class TestApplyViaProcess:
    @pytest.mark.asyncio
    async def test_apply_valid_suggestion_id(self, agent):
        ctx = _make_context()
        suggestion = ImprovementSuggestion(
            id="app-s1", category="persona", change_type="adjust",
            target="persona.formality", current_value=0.8, suggested_value=0.9,
            confidence=0.9, rationale="test", auto_applicable=True,
        )
        agent._suggestions.append(suggestion)

        result = await agent.process({"action": "apply", "suggestion_id": "app-s1"}, ctx)
        assert "applied" in result
        assert agent._settings.persona.formality == 0.9


class TestInitializeShutdown:
    @pytest.mark.asyncio
    async def test_initialize_when_disabled(self):
        a = SelfImprovementAgent()
        disabled_settings = _make_settings(enabled=False)
        with patch(
            "jarvis_core.agents.self_improvement_agent.get_settings",
            return_value=disabled_settings,
        ):
            await a.initialize()
        assert a._client is None

    @pytest.mark.asyncio
    async def test_shutdown_unsubscribe(self):
        a = SelfImprovementAgent()
        a._settings = _make_settings(enabled=True)
        a._client = MagicMock()
        a._model = "test"
        a._event_bus = MagicMock()
        a._event_bus.subscribe = AsyncMock()
        a._event_bus.unsubscribe = AsyncMock()
        a._subscribed = True
        await a.shutdown()
        assert a._event_bus.unsubscribe.call_count == 3


class TestUserFeedback:
    @pytest.mark.asyncio
    async def test_classify_positive_feedback(self, agent):
        agent._settings = _make_settings()
        assert agent._classify_feedback("That was good, thanks!") == "positive"

    @pytest.mark.asyncio
    async def test_classify_negative_feedback(self, agent):
        agent._settings = _make_settings()
        assert agent._classify_feedback("That was bad and wrong") == "negative"

    @pytest.mark.asyncio
    async def test_classify_neutral_feedback(self, agent):
        agent._settings = _make_settings()
        assert agent._classify_feedback("interesting") == "neutral"

    @pytest.mark.asyncio
    async def test_record_feedback_action(self, agent):
        ctx = _make_context()
        agent._settings = _make_settings()
        result = await agent.process(
            {"action": "record_feedback", "feedback": "good job"}, ctx
        )
        assert result["recorded"] is True
        assert result["sentiment"] == "positive"
        assert len(agent._metrics_buffer) == 1

    @pytest.mark.asyncio
    async def test_on_user_feedback_event(self, agent):
        agent._settings = _make_settings()
        await agent._on_user_feedback("user_feedback", {"feedback": "terrible work"})
        assert len(agent._metrics_buffer) == 1
        assert agent._metrics_buffer[0]["sentiment"] == "negative"

    @pytest.mark.asyncio
    async def test_status_includes_sentiment_breakdown(self, agent):
        ctx = _make_context()
        agent._settings = _make_settings()
        await agent._on_user_feedback("user_feedback", {"feedback": "good"})
        await agent._on_user_feedback("user_feedback", {"feedback": "bad"})
        result = await agent.process({"action": "status"}, ctx)
        assert result["sentiment_breakdown"]["positive"] == 1
        assert result["sentiment_breakdown"]["negative"] == 1


class TestSuggestionPersistence:
    @pytest.mark.asyncio
    async def test_apply_persists_to_file(self, agent, tmp_path, monkeypatch):
        agent._settings = _make_settings()
        agent._settings.memory.profile_path = tmp_path / "sub" / "profile.json"

        suggestion = ImprovementSuggestion(
            id="pers-1", category="persona", change_type="adjust",
            target="persona.formality", current_value=0.8, suggested_value=0.9,
            confidence=0.9, rationale="test", auto_applicable=True,
        )
        agent._suggestions.append(suggestion)
        agent._save_persisted_suggestions()

        suggestion_path = agent._suggestion_path()
        assert suggestion_path.exists()
        loaded = json.loads(suggestion_path.read_text())
        assert len(loaded) == 1
        assert loaded[0]["id"] == "pers-1"

    @pytest.mark.asyncio
    async def test_load_persisted_suggestions(self, agent, tmp_path):
        agent._settings = _make_settings()
        agent._settings.memory.profile_path = tmp_path / "sub" / "profile.json"

        suggestion = ImprovementSuggestion(
            id="load-1", category="persona", change_type="adjust",
            target="persona.verbosity", current_value=0.4, suggested_value=0.6,
            confidence=0.85, rationale="persisted test",
        )
        agent._suggestions.append(suggestion)
        agent._save_persisted_suggestions()

        agent._suggestions.clear()
        agent._load_persisted_suggestions()
        assert len(agent._suggestions) == 1
        assert agent._suggestions[0].id == "load-1"
        assert agent._suggestions[0].target == "persona.verbosity"

    @pytest.mark.asyncio
    async def test_load_persisted_suggestions_no_file(self, agent, tmp_path):
        agent._settings = _make_settings()
        agent._settings.memory.profile_path = tmp_path / "nonexistent" / "profile.json"
        agent._load_persisted_suggestions()
        assert agent._suggestions == []


class TestProfileJsonSync:
    @pytest.mark.asyncio
    async def test_sync_persona_formality(self, agent, tmp_path):
        agent._settings = _make_settings()
        profile = {
            "preferences": {
                "persona_traits": {"formality": 0.8, "wit": 0.4, "technical_depth": 0.7}
            }
        }
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        agent._settings.memory.profile_path = profile_path

        agent._sync_to_profile_json("persona.formality", 0.9)
        updated = json.loads(profile_path.read_text())
        assert updated["preferences"]["persona_traits"]["formality"] == 0.9

    @pytest.mark.asyncio
    async def test_sync_persona_humor_to_wit(self, agent, tmp_path):
        agent._settings = _make_settings()
        profile = {"preferences": {"persona_traits": {"wit": 0.3}}}
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        agent._settings.memory.profile_path = profile_path

        agent._sync_to_profile_json("persona.humor", 0.5)
        updated = json.loads(profile_path.read_text())
        assert updated["preferences"]["persona_traits"]["wit"] == 0.5

    @pytest.mark.asyncio
    async def test_sync_persona_jargon_to_technical_depth(self, agent, tmp_path):
        agent._settings = _make_settings()
        profile = {"preferences": {"persona_traits": {"technical_depth": 0.6}}}
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        agent._settings.memory.profile_path = profile_path

        agent._sync_to_profile_json("persona.jargon", 0.8)
        updated = json.loads(profile_path.read_text())
        assert updated["preferences"]["persona_traits"]["technical_depth"] == 0.8

    @pytest.mark.asyncio
    async def test_sync_unknown_target_skipped(self, agent, tmp_path):
        agent._settings = _make_settings()
        profile = {"preferences": {"persona_traits": {"formality": 0.8}}}
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        agent._settings.memory.profile_path = profile_path
        original = profile_path.read_text()

        agent._sync_to_profile_json("persona.response_style", "concise")
        assert profile_path.read_text() == original

    @pytest.mark.asyncio
    async def test_sync_no_profile_file(self, agent, tmp_path):
        agent._settings = _make_settings()
        agent._settings.memory.profile_path = tmp_path / "nonexistent.json"
        agent._sync_to_profile_json("persona.formality", 0.5)
        assert not (tmp_path / "nonexistent.json").exists()

    @pytest.mark.asyncio
    async def test_apply_suggestion_syncs_profile(self, agent, tmp_path):
        agent._settings = _make_settings()
        profile = {"preferences": {"persona_traits": {"formality": 0.85}}}
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        agent._settings.memory.profile_path = profile_path

        suggestion = ImprovementSuggestion(
            id="sync-1", category="persona", change_type="adjust",
            target="persona.formality", current_value=0.85, suggested_value=0.9,
            confidence=0.9, rationale="test", auto_applicable=True,
        )
        await agent._apply_suggestion(suggestion)

        updated = json.loads(profile_path.read_text())
        assert updated["preferences"]["persona_traits"]["formality"] == 0.9
        assert agent._settings.persona.formality == 0.9
