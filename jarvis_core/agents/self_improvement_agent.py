"""
JARVIS Self-Improvement Agent - Meta-learning and persona/workflow tuning.

Collects performance metrics from task completions and response events,
then periodically evaluates them to suggest or auto-apply improvements
to JARVIS's persona, workflows, and tool usage patterns.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context, get_event_bus

logger = get_logger(__name__)


@dataclass
class ImprovementSuggestion:
    id: str
    category: str
    change_type: str
    target: str
    current_value: Any
    suggested_value: Any
    confidence: float
    rationale: str
    auto_applicable: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "change_type": self.change_type,
            "target": self.target,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "auto_applicable": self.auto_applicable,
            "timestamp": self.timestamp.isoformat(),
        }


SELF_IMPROVEMENT_PROMPT = """
You are JARVIS's self-improvement analyst. Analyze the collected performance
metrics and conversation data below to identify optimization opportunities.

Your task is to produce specific, actionable suggestions for improving JARVIS's
persona, workflow efficiency, and overall effectiveness. Focus on:

1. Persona tuning: Adjust formality, verbosity, humor, jargon, or response_style
   based on user engagement signals and response quality scores.
2. Workflow optimization: Identify tools or agent steps that consistently fail
   or underperform, suggesting reordering or replacement.
3. Response quality: Spot patterns in low-scoring responses from the CriticAgent
   and suggest improvements to the reasoner or planner prompts.

Output format - a JSON array of suggestion objects:
[
  {
    "category": "persona" | "workflow" | "quality",
    "change_type": "adjust" | "replace" | "add_prompt_hint",
    "target": "persona.verbosity" | "tool:tool_name" | "agent:agent_role",
    "current_value": "<current value>",
    "suggested_value": "<suggested value>",
    "confidence": 0.0-1.0,
    "rationale": "why this change would help",
    "auto_applicable": true or false
  }
]

Be conservative with confidence scores. Only suggest changes you can justify
from the data. Return ONLY the JSON array, no explanatory text.
"""


class SelfImprovementAgent(Agent):
    name = "self_improvement"
    description = "Meta-learning and persona/workflow tuning agent"

    def __init__(self):
        self._client = None
        self._model = None
        self._settings = None
        self._metrics_buffer: list[dict[str, Any]] = []
        self._suggestions: list[ImprovementSuggestion] = []
        self._last_evaluation: datetime | None = None
        self._event_bus = None
        self._subscribed = False
        self._evaluation_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        from ollama import AsyncClient

        self._settings = get_settings()
        if not self._settings.self_improvement.enabled:
            logger.info("SelfImprovementAgent disabled in config")
            return

        self._client = AsyncClient(host=self._settings.models.ollama_host)
        self._model = self._settings.models.chat_model
        self._event_bus = get_event_bus()

        await self._event_bus.subscribe("task_completed", self._on_task_completed)
        await self._event_bus.subscribe("response_generated", self._on_response_generated)
        await self._event_bus.subscribe("user_feedback", self._on_user_feedback)
        self._subscribed = True

        self._load_persisted_suggestions()
        logger.debug("SelfImprovementAgent initialized")
        self._start_background_evaluation()

    async def shutdown(self) -> None:
        if self._evaluation_task:
            self._evaluation_task.cancel()
        if self._subscribed and self._event_bus:
            await self._event_bus.unsubscribe("task_completed", self._on_task_completed)
            await self._event_bus.unsubscribe("response_generated", self._on_response_generated)
            await self._event_bus.unsubscribe("user_feedback", self._on_user_feedback)
            self._subscribed = False

    def _start_background_evaluation(self):
        async def _loop():
            while True:
                interval = self._settings.self_improvement.evaluation_interval_minutes * 60
                await asyncio.sleep(interval)
                try:
                    await self._run_evaluation_cycle()
                except Exception as e:
                    logger.error(
                        f"Self-improvement evaluation cycle error: {e}", exc_info=True
                    )

        self._evaluation_task = asyncio.create_task(_loop())

    async def _on_task_completed(self, event_type: str, data: dict[str, Any]) -> None:
        task_data = data.get("task", {})
        metric = {
            "type": "task",
            "task_id": task_data.get("task_id", ""),
            "status": task_data.get("status", ""),
            "description": task_data.get("description", ""),
            "num_steps": len(task_data.get("steps", [])),
            "num_results": len(task_data.get("results", [])),
            "error": task_data.get("error"),
            "timestamp": task_data.get("completed_at", datetime.now().isoformat()),
        }
        self._metrics_buffer.append(metric)
        self._trim_buffer()

    async def _on_response_generated(self, event_type: str, data: dict[str, Any]) -> None:
        metric = {
            "type": "response",
            "response": data.get("response", "")[:500],
            "context_id": data.get("context_id", ""),
            "timestamp": datetime.now().isoformat(),
        }
        self._metrics_buffer.append(metric)
        self._trim_buffer()

    async def _on_user_feedback(self, event_type: str, data: dict[str, Any]) -> None:
        feedback = data.get("feedback", "").lower().strip()
        if not self._settings.self_improvement.feedback_enabled:
            return

        sentiment = self._classify_feedback(feedback)
        metric = {
            "type": "feedback",
            "feedback": feedback[:300],
            "sentiment": sentiment,
            "timestamp": datetime.now().isoformat(),
        }
        self._metrics_buffer.append(metric)
        self._trim_buffer()
        logger.debug(f"Recorded user feedback (sentiment={sentiment})")

    def _classify_feedback(self, text: str) -> str:
        lower = text.lower()
        positive = any(kw in lower for kw in ["good", "thanks", "perfect", "great", "excellent"])
        negative = any(kw in lower for kw in ["bad", "wrong", "terrible", "awful", "worst"])
        if positive and negative:
            return "mixed"
        if positive:
            return "positive"
        if negative:
            return "negative"
        return "neutral"

    def _load_persisted_suggestions(self) -> None:
        path = self._suggestion_path()
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.loads(f.read())
            for item in data:
                s = ImprovementSuggestion(
                    id=item["id"], category=item["category"],
                    change_type=item["change_type"], target=item["target"],
                    current_value=item["current_value"],
                    suggested_value=item["suggested_value"],
                    confidence=item["confidence"], rationale=item["rationale"],
                    auto_applicable=item.get("auto_applicable", False),
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                )
                self._suggestions.append(s)
            logger.debug(f"Loaded {len(self._suggestions)} persisted suggestions")
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.debug(f"Could not load persisted suggestions: {e}")

    def _save_persisted_suggestions(self) -> None:
        path = self._suggestion_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [s.to_dict() for s in self._suggestions[-100:]]
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))

    def _suggestion_path(self) -> Path:
        return self._settings.memory.profile_path.parent / "self_improvement_suggestions.json"

    def _trim_buffer(self) -> None:
        max_size = self._settings.self_improvement.max_metric_history
        if len(self._metrics_buffer) > max_size:
            self._metrics_buffer = self._metrics_buffer[-max_size:]

    async def _run_evaluation_cycle(self) -> list[ImprovementSuggestion]:
        if not self._metrics_buffer:
            logger.debug("Self-improvement: no metrics to evaluate")
            return []

        metrics_json = json.dumps(self._metrics_buffer, indent=2)
        persona = self._settings.persona

        user_input = (
            f"Metrics data:\n{metrics_json}\n\n"
            f"Current persona: {persona.name} "
            f"(formality={persona.formality}, verbosity={persona.verbosity}, "
            f"humor={persona.humor}, jargon={persona.jargon}, "
            f"style={persona.response_style})\n\n"
        )

        messages = [
            {"role": "system", "content": SELF_IMPROVEMENT_PROMPT},
            {"role": "user", "content": user_input},
        ]

        try:
            result = await self._client.chat(
                model=self._model,
                messages=messages,
                format="json",
                options={"temperature": 0.3},
            )

            content = result.get("message", {}).get("content", "")
            suggestions_data = json.loads(content)

            new_suggestions: list[ImprovementSuggestion] = []
            for i, s in enumerate(suggestions_data):
                suggestion = ImprovementSuggestion(
                    id=f"sugg-{datetime.now().strftime('%Y%m%d%H%M%S')}-{i}",
                    category=s.get("category", "quality"),
                    change_type=s.get("change_type", "adjust"),
                    target=s.get("target", ""),
                    current_value=s.get("current_value", ""),
                    suggested_value=s.get("suggested_value", ""),
                    confidence=float(s.get("confidence", 0.5)),
                    rationale=s.get("rationale", ""),
                    auto_applicable=bool(s.get("auto_applicable", False)),
                )
                new_suggestions.append(suggestion)

                threshold = self._settings.self_improvement.confidence_threshold
                auto_apply = self._settings.self_improvement.auto_apply_trait_changes

                if (
                    suggestion.auto_applicable
                    and suggestion.confidence >= threshold
                    and auto_apply
                ):
                    await self._apply_suggestion(suggestion)

                self._suggestions.append(suggestion)

            self._last_evaluation = datetime.now()
            self._metrics_buffer.clear()
            self._save_persisted_suggestions()

            logger.info(
                f"Self-improvement cycle: {len(new_suggestions)} suggestions generated"
            )
            return new_suggestions

        except json.JSONDecodeError as e:
            logger.warning(f"Self-improvement: invalid JSON from model: {e}")
            return []
        except Exception as e:
            logger.error(f"Self-improvement evaluation error: {e}")
            return []

    async def _apply_suggestion(self, suggestion: ImprovementSuggestion) -> None:
        if suggestion.category != "persona":
            logger.debug(f"Skipping non-persona auto-apply: {suggestion.category}")
            return

        try:
            target = suggestion.target
            value = suggestion.suggested_value

            if target == "persona.formality":
                self._settings.persona.formality = float(value)
            elif target == "persona.verbosity":
                self._settings.persona.verbosity = float(value)
            elif target == "persona.humor":
                self._settings.persona.humor = float(value)
            elif target == "persona.jargon":
                self._settings.persona.jargon = float(value)
            elif target == "persona.response_style":
                self._settings.persona.response_style = str(value)
            else:
                logger.debug(f"Cannot auto-apply unknown target: {target}")
                return

            logger.info(
                f"Auto-applied {target} = {value} "
                f"(confidence={suggestion.confidence:.2f})"
            )

            if hasattr(self._settings, "save"):
                config_dir = self._settings.memory.profile_path.parent
                config_dir.mkdir(parents=True, exist_ok=True)
                self._settings.save(config_dir / "self_improvement.yaml")

            self._sync_to_profile_json(target, value)

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to apply persona suggestion: {e}")

    def _sync_to_profile_json(self, target: str, value: Any) -> None:
        """Sync persona changes to the legacy profile.json persona_traits."""
        try:
            profile_path = self._settings.memory.profile_path
            if not profile_path.exists():
                return

            with open(profile_path, encoding="utf-8") as f:
                profile = json.load(f)

            traits = profile.setdefault("preferences", {}).setdefault("persona_traits", {})

            trait_map = {
                "persona.formality": "formality",
                "persona.humor": "wit",
                "persona.jargon": "technical_depth",
            }

            legacy_key = trait_map.get(target)
            if legacy_key:
                traits[legacy_key] = float(value)
                with open(profile_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(profile, indent=2))
                logger.debug(f"Synced {target} -> persona_traits.{legacy_key}")
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.debug(f"Could not sync to profile.json: {e}")

    async def process(self, input_data: Any, context: Context) -> Any:
        action = input_data.get("action", "status")

        if action == "status":
            last_eval = (
                self._last_evaluation.isoformat()
                if self._last_evaluation
                else None
            )
            feedback_metrics = [
                m for m in self._metrics_buffer if m.get("type") == "feedback"
            ]
            sentiment_counts: dict[str, int] = {}
            for m in feedback_metrics:
                sentiment = m.get("sentiment", "neutral")
                sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

            return {
                "last_evaluation": last_eval,
                "metrics_count": len(self._metrics_buffer),
                "suggestion_count": len(self._suggestions),
                "enabled": self._settings.self_improvement.enabled if self._settings else False,
                "sentiment_breakdown": sentiment_counts,
                "suggestions": [s.to_dict() for s in self._suggestions[-10:]],
            }

        elif action == "evaluate":
            suggestions = await self._run_evaluation_cycle()
            return {"suggestions": [s.to_dict() for s in suggestions], "count": len(suggestions)}

        elif action == "apply":
            suggestion_id = input_data.get("suggestion_id")
            if not suggestion_id:
                return {"error": "suggestion_id required for apply action"}

            suggestion = next((s for s in self._suggestions if s.id == suggestion_id), None)
            if not suggestion:
                return {"error": f"Suggestion '{suggestion_id}' not found"}

            await self._apply_suggestion(suggestion)
            return {"applied": suggestion.to_dict()}

        elif action == "get_suggestions":
            limit = input_data.get("limit", 10)
            recent = self._suggestions[-limit:] if limit else self._suggestions
            return {
                "suggestions": [s.to_dict() for s in recent],
                "total": len(self._suggestions),
            }

        elif action == "record_feedback":
            feedback = input_data.get("feedback", "")
            sentiment = self._classify_feedback(feedback)
            metric = {
                "type": "feedback",
                "feedback": feedback[:300],
                "sentiment": sentiment,
                "timestamp": datetime.now().isoformat(),
            }
            self._metrics_buffer.append(metric)
            self._trim_buffer()
            return {
                "recorded": True,
                "sentiment": sentiment,
                "metrics_buffer_size": len(self._metrics_buffer),
            }

        return {"error": f"Unknown action: {action}"}
