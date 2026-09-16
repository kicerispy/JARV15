from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """
    Normalized result returned by JARVIS tools.

    This gives every tool the same result contract while
    preserving the original raw result in `data`.
    """

    success: bool
    tool: str
    data: Any = None
    error: str | None = None
    retryable: bool = False
    observation: dict | None = None

    def __bool__(self) -> bool:
        return self.success

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "retryable": self.retryable,
            "observation": self.observation,
        }

    def __str__(self) -> str:
        if self.success:
            return str(self.data if self.data is not None else "done")

        return self.error or f"{self.tool} failed"
