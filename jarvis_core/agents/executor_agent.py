"""
JARVIS Executor Agent - Tool execution with verification and recovery.
"""
import asyncio
import time
from typing import Any, Dict, List

from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context, Tool, ToolCall, ToolResult, ToolResultStatus

logger = get_logger(__name__)


class ExecutorAgent(Agent):
    name = "executor"
    description = "Tool execution with verification and error recovery"

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._max_retries = 2
        self._retry_delay = 1.0

    async def initialize(self) -> None:
        logger.debug("ExecutorAgent initialized")

    async def shutdown(self) -> None:
        pass

    def register_tools(self, tools: Dict[str, Tool]) -> None:
        self._tools = tools

    async def process(self, input_data: Any, context: Context) -> Any:
        action = input_data.get("action", "execute")

        if action == "execute":
            return await self._execute_tool(input_data, context)
        elif action == "execute_plan":
            return await self._execute_plan(input_data, context)
        elif action == "verify":
            return await self._verify_result(input_data, context)
        else:
            return ToolResult(
                call_id=input_data.get("call_id", "unknown"),
                tool_name=input_data.get("tool_name", "unknown"),
                status=ToolResultStatus.ERROR,
                error=f"Unknown executor action: {action}",
            )

    async def _execute_tool(self, input_data: Any, context: Context) -> ToolResult:
        tool_name = input_data.get("tool_name")
        arguments = input_data.get("arguments", {})
        call_id = input_data.get("call_id", f"call_{int(time.time() * 1000)}")

        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                status=ToolResultStatus.ERROR,
                error=f"Tool not found: {tool_name}",
            )

        for attempt in range(self._max_retries + 1):
            start_time = time.time()
            try:
                result = await tool.execute(arguments, context)
                result.call_id = call_id
                result.execution_time_ms = (time.time() - start_time) * 1000

                if result.status == ToolResultStatus.SUCCESS:
                    return result
                elif result.status == ToolResultStatus.PARTIAL and attempt == self._max_retries:
                    return result

            except Exception as e:
                logger.warning(f"Tool {tool_name} attempt {attempt + 1} failed: {e}")
                if attempt == self._max_retries:
                    return ToolResult(
                        call_id=call_id,
                        tool_name=tool_name,
                        status=ToolResultStatus.ERROR,
                        error=str(e),
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )

            await asyncio.sleep(self._retry_delay * (attempt + 1))

        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolResultStatus.ERROR,
            error="Max retries exceeded",
        )

    async def _execute_plan(self, input_data: Any, context: Context) -> List[ToolResult]:
        steps = input_data.get("steps", [])
        results = []

        for step in steps:
            tool_call = ToolCall(
                tool_name=step.get("tool", ""),
                arguments=step.get("arguments", {}),
                call_id=step.get("call_id", f"call_{len(results)}"),
            )
            result = await self._execute_tool({
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.arguments,
                "call_id": tool_call.call_id,
            }, context)
            results.append(result)

            if result.status == ToolResultStatus.ERROR:
                break

        return results

    async def _verify_result(self, input_data: Any, context: Context) -> Dict[str, Any]:
        tool_name = input_data.get("tool_name")
        result = input_data.get("result")
        expected = input_data.get("expected", "")

        if not tool_name or result is None:
            return {"verified": False, "confidence": 0.0, "reason": "Missing tool or result"}

        if expected:
            logger.debug(f"Verification expected: {expected}")

        if isinstance(result, dict):
            if result.get("success", True) and result.get("verified", True):
                return {"verified": True, "confidence": 1.0, "reason": "Tool reported success"}
            if not result.get("success", True):
                return {"verified": False, "confidence": 0.0, "reason": result.get("error", "Tool reported failure")}

        return {"verified": True, "confidence": 0.8, "reason": "Basic verification passed"}
