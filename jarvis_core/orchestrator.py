"""
JARVIS Conversation Orchestrator - Multi-agent conversation management.
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import (
    Agent,
    Context,
    Message,
    MessageRole,
    Task,
    TaskStatus,
    Tool,
    ToolCall,
    ToolProvider,
    ToolResult,
    ToolResultStatus,
    get_event_bus,
)

logger = get_logger(__name__)


class AgentRole(str, Enum):
    PLANNER = "planner"
    REASONER = "reasoner"
    PERSONA = "persona"
    MEMORY = "memory"
    CRITIC = "critic"
    EXECUTOR = "executor"
    SELF_IMPROVEMENT = "self_improvement"


@dataclass
class AgentState:
    agent: Agent
    role: AgentRole
    enabled: bool = True
    last_active: datetime = field(default_factory=datetime.now)
    metrics: Dict[str, float] = field(default_factory=dict)


class ConversationOrchestrator:
    def __init__(self):
        self.agents: Dict[AgentRole, AgentState] = {}
        self.tool_providers: List[ToolProvider] = []
        self.tools: Dict[str, Tool] = {}
        self.context: Optional[Context] = None
        self.event_bus = get_event_bus()
        self._running = False
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._background_tasks: List[asyncio.Task] = []

    async def initialize(self) -> None:
        logger.info("Initializing Conversation Orchestrator")
        await self._register_default_agents()
        await self._register_default_tools()
        self._running = True
        self._background_tasks.append(asyncio.create_task(self._process_queue()))
        logger.info("Conversation Orchestrator initialized")

    async def shutdown(self) -> None:
        logger.info("Shutting down Conversation Orchestrator")
        self._running = False
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        for provider in self.tool_providers:
            await provider.shutdown()
        for state in self.agents.values():
            await state.agent.shutdown()
        logger.info("Conversation Orchestrator shutdown complete")

    async def _register_default_agents(self) -> None:
        from jarvis_core.agents.critic_agent import CriticAgent
        from jarvis_core.agents.executor_agent import ExecutorAgent
        from jarvis_core.agents.memory_agent import MemoryAgent
        from jarvis_core.agents.persona_agent import PersonaAgent
        from jarvis_core.agents.planner_agent import PlannerAgent
        from jarvis_core.agents.reasoner_agent import ReasonerAgent
        from jarvis_core.agents.self_improvement_agent import SelfImprovementAgent

        agents = [
            (AgentRole.PLANNER, PlannerAgent()),
            (AgentRole.REASONER, ReasonerAgent()),
            (AgentRole.PERSONA, PersonaAgent()),
            (AgentRole.MEMORY, MemoryAgent()),
            (AgentRole.CRITIC, CriticAgent()),
            (AgentRole.EXECUTOR, ExecutorAgent()),
            (AgentRole.SELF_IMPROVEMENT, SelfImprovementAgent()),
        ]

        for role, agent in agents:
            await agent.initialize()
            self.agents[role] = AgentState(agent=agent, role=role)
            logger.debug(f"Registered agent: {role.value}")

    async def _register_default_tools(self) -> None:
        from jarvis_core.plugins.code_tools import CodeToolsPlugin
        from jarvis_core.plugins.file_tools import FileToolsPlugin
        from jarvis_core.plugins.screen_tools import ScreenToolsPlugin
        from jarvis_core.plugins.system_tools import SystemToolsPlugin
        from jarvis_core.plugins.web_tools import WebToolsPlugin

        providers = [
            FileToolsPlugin(),
            WebToolsPlugin(),
            SystemToolsPlugin(),
            ScreenToolsPlugin(),
            CodeToolsPlugin(),
        ]

        for provider in providers:
            await provider.initialize()
            self.tool_providers.append(provider)
            for tool in provider.get_tools():
                self.tools[tool.name] = tool
                logger.debug(f"Registered tool: {tool.name}")

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def register_agent(self, role: AgentRole, agent: Agent) -> None:
        asyncio.create_task(agent.initialize())
        self.agents[role] = AgentState(agent=agent, role=role)
        logger.info(f"Registered custom agent: {role.value}")

    async def trigger_self_evaluation(self) -> Dict[str, Any]:
        state = self.agents.get(AgentRole.SELF_IMPROVEMENT)
        if not state or not state.enabled:
            return {"error": "SelfImprovementAgent not available"}
        result = await state.agent.process({"action": "evaluate"}, self.context or Context(
            conversation_id="self-improvement", user_id="system"
        ))
        state.last_active = datetime.now()
        return result

    async def get_self_improvement_status(self) -> Dict[str, Any]:
        state = self.agents.get(AgentRole.SELF_IMPROVEMENT)
        if not state or not state.enabled:
            return {"error": "SelfImprovementAgent not available"}
        result = await state.agent.process({"action": "status"}, self.context or Context(
            conversation_id="self-improvement", user_id="system"
        ))
        return result

    async def record_user_feedback(self, feedback: str) -> None:
        """Publish a user_feedback event for the SelfImprovementAgent to collect."""
        if not feedback:
            return
        settings = get_settings()
        if not settings.self_improvement.feedback_enabled:
            return
        await self.event_bus.publish("user_feedback", {"feedback": feedback})

    async def process_message(self, user_input: str, context: Context) -> AsyncGenerator[str, None]:
        self.context = context
        corr_id = str(uuid.uuid4())[:8]
        set_correlation_id(corr_id)

        try:
            user_message = Message(role=MessageRole.USER, content=user_input)
            context.recent_messages.append(user_message)

            await self.event_bus.publish("message_received", {"message": user_message.to_dict()})

            plan = await self._plan(user_input, context)
            if not plan:
                async for chunk in self._converse(user_input, context):
                    yield chunk
                return

            async for chunk in self._execute_plan(plan, context):
                yield chunk

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            yield f"I encountered an error: {str(e)}"
        finally:
            set_correlation_id(None)

    async def _plan(self, user_input: str, context: Context) -> Optional[List[ToolCall]]:
        planner_state = self.agents.get(AgentRole.PLANNER)
        if not planner_state or not planner_state.enabled:
            return None

        try:
            plan = await planner_state.agent.process({
                "user_input": user_input,
                "context": context,
                "available_tools": {name: tool.description for name, tool in self.tools.items()},
            }, context)

            if plan and isinstance(plan, list):
                for step in plan:
                    planner_state.last_active = datetime.now()
                return plan
        except Exception as e:
            logger.error(f"Planner error: {e}")

        return None

    async def _execute_plan(self, plan: List[ToolCall], context: Context) -> AsyncGenerator[str, None]:
        executor_state = self.agents.get(AgentRole.EXECUTOR)
        if not executor_state:
            yield "Executor agent not available"
            return

        task = Task(
            task_id=str(uuid.uuid4()),
            description=f"Execute plan with {len(plan)} steps",
            steps=plan,
            status=TaskStatus.RUNNING,
        )
        context.active_task = task

        for i, step in enumerate(plan):
            if task.status == TaskStatus.CANCELLED:
                yield "Task cancelled"
                break

            yield f"Step {i+1}/{len(plan)}: {step.tool_name}"

            tool = self.tools.get(step.tool_name)
            if not tool:
                error_result = ToolResult(
                    call_id=step.call_id,
                    tool_name=step.tool_name,
                    status=ToolResultStatus.ERROR,
                    error=f"Unknown tool: {step.tool_name}",
                )
                task.results.append(error_result)
                continue

            try:
                result = await tool.execute(step.arguments, context)
                task.results.append(result)
                planner_state = self.agents.get(AgentRole.PLANNER)
                if planner_state:
                    await planner_state.agent.process({"tool_result": result.to_dict()}, context)

                if result.status == ToolResultStatus.ERROR:
                    task.status = TaskStatus.FAILED
                    task.error = result.error
                    yield f"Step failed: {result.error}"
                    break

                yield str(result.result) if result.result else "Done"

            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                error_result = ToolResult(
                    call_id=step.call_id,
                    tool_name=step.tool_name,
                    status=ToolResultStatus.ERROR,
                    error=str(e),
                )
                task.results.append(error_result)

        task.status = TaskStatus.COMPLETED if task.status != TaskStatus.FAILED else TaskStatus.FAILED
        task.completed_at = datetime.now()
        context.active_task = None

        await self.event_bus.publish("task_completed", {"task": task.to_dict()})

    async def _converse(self, user_input: str, context: Context) -> AsyncGenerator[str, None]:
        reasoner_state = self.agents.get(AgentRole.REASONER)
        persona_state = self.agents.get(AgentRole.PERSONA)
        memory_state = self.agents.get(AgentRole.MEMORY)
        critic_state = self.agents.get(AgentRole.CRITIC)

        memory_context = ""
        if memory_state:
            memories = await memory_state.agent.process({"query": user_input}, context)
            if memories:
                memory_context = f"\nRelevant memories:\n{memories}"

        system_prompt = self._build_system_prompt(context, memory_context)

        messages = [Message(role=MessageRole.SYSTEM, content=system_prompt)]
        messages.extend(context.recent_messages[-10:])
        messages.append(Message(role=MessageRole.USER, content=user_input))

        full_response = ""
        if reasoner_state:
            async for chunk in self._stream_reasoning(reasoner_state, messages, context):
                full_response += chunk
                yield chunk

        if critic_state:
            critique = await critic_state.agent.process({
                "response": full_response,
                "context": context,
            }, context)
            if critique and critique.get("needs_revision"):
                revised_messages = messages + [Message(role=MessageRole.ASSISTANT, content=full_response)]
                full_response = ""
                async for chunk in self._stream_reasoning(reasoner_state, revised_messages, context):
                    full_response += chunk
                    yield chunk

        if persona_state:
            styled = await persona_state.agent.process({
                "response": full_response,
                "context": context,
            }, context)
            if styled:
                full_response = styled

        context.recent_messages.append(Message(role=MessageRole.ASSISTANT, content=full_response))

        await self.event_bus.publish("response_generated", {
            "response": full_response,
            "context_id": context.conversation_id,
        })

    async def _stream_reasoning(
        self, agent_state: AgentState, messages: List[Message], context: Context
    ) -> AsyncGenerator[str, None]:
        try:
            result = await agent_state.agent.process({
                "messages": [m.to_dict() for m in messages],
                "tools": {name: tool.description for name, tool in self.tools.items()},
            }, context)

            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if isinstance(content, str):
                    for chunk in self._chunk_text(content):
                        yield chunk
                else:
                    yield str(content)
            else:
                yield str(result)
        except Exception as e:
            logger.error(f"Reasoning error: {e}")
            yield f"I encountered an error while thinking: {str(e)}"

    def _chunk_text(self, text: str, chunk_size: int = 50) -> List[str]:
        words = text.split()
        chunks = []
        current = []
        current_len = 0

        for word in words:
            if current_len + len(word) + 1 > chunk_size and current:
                chunks.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += len(word) + 1

        if current:
            chunks.append(" ".join(current))
        return chunks

    def _build_system_prompt(self, context: Context, memory_context: str) -> str:
        settings = get_settings()
        persona = settings.persona

        prompt_parts = [
            "You are JARVIS, a personal AI assistant and software engineering expert.",
            f"Persona: {persona.name} (formality: {persona.formality}, verbosity: {persona.verbosity}, humor: {persona.humor})",
            f"Response style: {persona.response_style}",
            f"User: {context.user_preferences.get('name', 'User')}",
        ]

        if memory_context:
            prompt_parts.append(memory_context)

        if context.active_window:
            prompt_parts.append(f"Active window: {context.active_window}")

        if context.screen_context:
            prompt_parts.append(f"Screen context: {context.screen_context}")

        prompt_parts.extend([
            "Keep answers concise unless the user asks for more detail.",
            "Address the user naturally when appropriate.",
            "Use saved memories and recent conversation context when relevant.",
            "Do not pretend to have completed an action unless a tool actually completed it.",
            "When a tool has completed an action, treat that result as part of the conversation context.",
            "You can help with software engineering tasks across multiple languages.",
        ])

        return "\n\n".join(prompt_parts)

    async def _process_queue(self) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
                await self._handle_queued_task(item)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue processing error: {e}")

    async def _handle_queued_task(self, item: Dict[str, Any]) -> None:
        pass


def set_correlation_id(corr_id: Optional[str]) -> None:
    from jarvis_core.utils.logging import set_correlation_id as _set
    _set(corr_id)
