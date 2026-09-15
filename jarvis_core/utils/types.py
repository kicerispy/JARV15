"""
JARVIS Core Types - Shared types, protocols, and base classes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


@dataclass
class Message:
    role: MessageRole
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=MessageRole(data["role"]),
            content=data["content"],
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            message_id=data.get("message_id", str(uuid.uuid4())),
        )


@dataclass
class ToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "call_id": self.call_id,
        }


@dataclass
class ToolResult:
    call_id: str
    tool_name: str
    status: ToolResultStatus
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class Task:
    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    steps: List[ToolCall] = field(default_factory=list)
    results: List[ToolResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "results": [r.to_dict() for r in self.results],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class Context:
    conversation_id: str
    user_id: str
    active_task: Optional[Task] = None
    recent_messages: List[Message] = field(default_factory=list)
    working_memory: Dict[str, Any] = field(default_factory=dict)
    long_term_memory_ids: List[str] = field(default_factory=list)
    screen_context: Optional[Dict[str, Any]] = None
    active_window: Optional[str] = None
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: Dict[str, Any]

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        ...


class ToolProvider(Protocol):
    def get_tools(self) -> List[Tool]:
        ...

    async def initialize(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...


class Agent(Protocol):
    name: str
    description: str

    async def process(self, input_data: Any, context: Context) -> Any:
        ...

    async def initialize(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...


class MemoryStore(Protocol):
    async def store(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> str:
        ...

    async def retrieve(self, key: str) -> Optional[Any]:
        ...

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        ...

    async def delete(self, key: str) -> bool:
        ...

    async def initialize(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    author: str
    entry_point: str
    dependencies: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)


class Plugin(Protocol):
    manifest: PluginManifest

    async def initialize(self, config: Dict[str, Any]) -> None:
        ...

    async def shutdown(self) -> None:
        ...

    def get_tools(self) -> List[Tool]:
        ...

    def get_agents(self) -> List[Agent]:
        ...


EventCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[EventCallback]] = {}

    async def subscribe(self, event_type: str, callback: EventCallback) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def unsubscribe(self, event_type: str, callback: EventCallback) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)

    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    await callback(event_type, data)
                except Exception:
                    pass

    async def publish_sync(self, event_type: str, data: Dict[str, Any]) -> None:
        await self.publish(event_type, data)


_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
