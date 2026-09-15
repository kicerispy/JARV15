"""
JARVIS Critic Agent - Self-evaluation and response critique.
"""
import json
from typing import Any

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context

logger = get_logger(__name__)


CRITIC_PROMPT = """
You are JARVIS's internal critic. Evaluate the quality of a response before it's sent to the user.

Criteria:
1. Accuracy: Is the information factually correct?
2. Completeness: Does it fully address the user's request?
3. Clarity: Is it easy to understand?
4. Tone: Does it match the persona?
5. Safety: Any harmful, misleading, or inappropriate content?
6. Tool usage: Were tools used correctly? Were results properly interpreted?

Return ONLY JSON:
{
  "score": 0.0-1.0,
  "needs_revision": true/false,
  "issues": ["list of specific issues"],
  "suggestions": ["list of improvements"],
  "critical_failure": true/false
}

Be strict but fair. A score below 0.7 should trigger revision.
"""


class CriticAgent(Agent):
    name = "critic"
    description = "Response quality evaluation"

    def __init__(self):
        self._client = None
        self._model = None

    async def initialize(self) -> None:
        from ollama import AsyncClient
        settings = get_settings()
        self._client = AsyncClient(host=settings.models.ollama_host)
        self._model = settings.models.chat_model
        logger.debug("CriticAgent initialized")

    async def shutdown(self) -> None:
        pass

    async def process(self, input_data: Any, context: Context) -> Any:
        response = input_data.get("response", "")
        if not response:
            return {"score": 1.0, "needs_revision": False}

        messages = [
            {"role": "system", "content": CRITIC_PROMPT},
            {"role": "user", "content": f"Evaluate this response:\n\n{response}"},
        ]

        try:
            result = await self._client.chat(
                model=self._model,
                messages=messages,
                format="json",
                options={"temperature": 0.1},
            )

            content = result.get("message", {}).get("content", "")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"Critic returned non-JSON: {content[:200]}")
                return {"score": 0.5, "needs_revision": True, "issues": ["Invalid critic response"]}

        except Exception as e:
            logger.error(f"Critic error: {e}")
            return {"score": 0.8, "needs_revision": False}
