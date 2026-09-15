"""
JARVIS Reasoner Agent - Chain-of-thought reasoning for complex queries.
"""
from typing import Any

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context

logger = get_logger(__name__)


REASONER_PROMPT = """
You are JARVIS's reasoning engine. Think step-by-step through complex problems.

Guidelines:
1. Break down the problem into clear steps
2. Show your reasoning explicitly
3. Consider multiple perspectives
4. Verify your conclusions
5. Be concise but thorough
6. If you need tools, indicate which ones and why

For coding tasks:
- Analyze requirements
- Design architecture
- Consider edge cases
- Plan implementation steps
- Suggest testing approach

For analysis tasks:
- Identify key factors
- Weigh evidence
- Draw logical conclusions
- Note uncertainties

Format your response as natural language reasoning, not JSON.
"""


class ReasonerAgent(Agent):
    name = "reasoner"
    description = "Chain-of-thought reasoning and problem solving"

    def __init__(self):
        self._client = None
        self._model = None

    async def initialize(self) -> None:
        from ollama import AsyncClient
        settings = get_settings()
        self._client = AsyncClient(host=settings.models.ollama_host)
        self._model = settings.models.chat_model
        logger.debug("ReasonerAgent initialized")

    async def shutdown(self) -> None:
        pass

    async def process(self, input_data: Any, context: Context) -> Any:
        messages = input_data.get("messages", [])
        tools = input_data.get("tools", {})

        if isinstance(messages[0], dict) and "role" in messages[0]:
            pass
        else:
            messages = [m.to_dict() if hasattr(m, 'to_dict') else m for m in messages]

        system_msg = {"role": "system", "content": REASONER_PROMPT}
        if tools:
            tool_list = "\n".join(f"{name}: {desc}" for name, desc in tools.items())
            system_msg["content"] += f"\n\nAvailable tools:\n{tool_list}"

        all_messages = [system_msg] + messages

        try:
            response = await self._client.chat(
                model=self._model,
                messages=all_messages,
                options={"temperature": 0.3},
            )

            return {
                "content": response.get("message", {}).get("content", ""),
                "reasoning": True,
            }

        except Exception as e:
            logger.error(f"Reasoner error: {e}")
            return {"content": f"I encountered an error while reasoning: {str(e)}", "reasoning": False}
