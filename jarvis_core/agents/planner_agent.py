"""
JARVIS Planner Agent - Task decomposition and tool selection.
"""
import json
from typing import Any

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context

logger = get_logger(__name__)


PLANNER_PROMPT = """
You are JARVIS's task planner - an expert software engineer and systems architect.

Your job: convert a user request into a list of tool calls.

If the request needs no tool (a question, chit-chat, opinion, or something you'd just answer in conversation), return an empty list.

Available tools:
{tool_list}

Rules:
1. Return ONLY JSON. No explanation.
2. Every step must use exactly one tool name from the list above.
3. "arguments" must always be an object matching the tool's parameters.
4. For complex requests, break them into multiple steps.
5. Never invent a tool name that isn't in the list.
6. If unsure whether a tool applies, return an empty list instead of guessing.
7. When generating code, include ALL necessary files.
8. Prefer single HTML files for web apps (embed CSS/JS).
9. For multi-file projects, order steps logically (styles before scripts).
10. Consider dependencies between steps - later steps can reference results from earlier steps using {{step_N.result}}.

Output format:
{
  "goal": "brief description of the overall goal",
  "steps": [
    {"tool": "tool_name", "arguments": {...}, "description": "what this step does"},
    ...
  ]
}

Examples:

User: "What's the weather in Chicago?"
Output:
{
  "goal": "check weather",
  "steps": [
    {"tool": "weather", "arguments": {"location": "Chicago"}, "description": "Get current weather for Chicago"}
  ]
}

User: "Create a todo app with HTML, CSS, and JavaScript"
Output:
{
  "goal": "create todo app",
  "steps": [
    {"tool": "write_file", "arguments": {"path": "todo.html", "content": "<!DOCTYPE html>..."}, "description": "Create main HTML file"},
    {"tool": "write_file", "arguments": {"path": "styles.css", "content": "#app { max-width: 400px; }"}, "description": "Create stylesheet"},
    {"tool": "write_file", "arguments": {"path": "app.js", "content": "const app = ...", "description": "Create JavaScript logic"}
  ]
}

User: "Search YouTube for Iron Man trailer"
Output:
{
  "goal": "search youtube",
  "steps": [
    {"tool": "search_website", "arguments": {"site": "youtube", "query": "Iron Man trailer"}, "description": "Search YouTube for Iron Man trailer"}
  ]
}

User: "Tell me a joke"
Output:
{
  "goal": "conversation",
  "steps": []
}
"""


class PlannerAgent(Agent):
    name = "planner"
    description = "Task planning and tool selection"

    def __init__(self):
        self._model = None

    async def initialize(self) -> None:
        from ollama import AsyncClient
        settings = get_settings()
        self._client = AsyncClient(host=settings.models.ollama_host)
        self._model = settings.models.planner_model
        logger.debug("PlannerAgent initialized")

    async def shutdown(self) -> None:
        pass

    async def process(self, input_data: Any, context: Context) -> Any:
        user_input = input_data.get("user_input", "")
        available_tools = input_data.get("available_tools", {})

        if not user_input.strip():
            return []

        tool_list = "\n".join(
            f"{name}: {desc}"
            for name, desc in available_tools.items()
        )

        prompt = PLANNER_PROMPT.format(tool_list=tool_list)

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ]

        try:
            response = await self._client.chat(
                model=self._model,
                messages=messages,
                format="json",
                options={"temperature": 0.1},
            )

            content = response.get("message", {}).get("content", "")
            plan = json.loads(content)

            if not isinstance(plan, dict) or "steps" not in plan:
                logger.warning(f"Invalid plan format: {plan}")
                return []

            steps = plan.get("steps", [])
            validated_steps = []

            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue

                tool_name = step.get("tool")
                arguments = step.get("arguments", {})

                if tool_name not in available_tools:
                    logger.warning(f"Planner selected unknown tool: {tool_name}")
                    continue

                validated_steps.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "description": step.get("description", ""),
                    "call_id": f"call_{i}",
                })

            return validated_steps

        except json.JSONDecodeError as e:
            logger.error(f"Planner returned invalid JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Planner error: {e}")
            return []
