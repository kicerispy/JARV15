"""Centralized model roles and Ollama generation settings for JARVIS."""

from __future__ import annotations

from dataclasses import dataclass

import config


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelManager:
    """Single source of truth for JARVIS model roles and chat settings."""

    chat_model: str = config.CHAT_MODEL
    planner_model: str = config.PLANNER_MODEL
    coding_model: str = config.CODING_MODEL
    coding_fallback_model: str = config.CODING_FALLBACK_MODEL

    chat_think: bool = config.CHAT_THINK
    chat_num_gpu: int = config.CHAT_NUM_GPU
    chat_num_predict: int = config.CHAT_NUM_PREDICT

    coding_num_ctx: int = config.CODING_NUM_CTX

    def generate(
        self,
        *,
        model: str,
        messages: list,
        format: str | None = None,
        options: dict | None = None,
        keep_alive=None,
        think: bool | None = None,
    ):
        """Execute one Ollama chat request through the centralized model layer."""
        from ollama import chat
        kwargs = {"model": model, "messages": messages}
        if format is not None:
            kwargs["format"] = format
        if options is not None:
            kwargs["options"] = options
        if keep_alive is not None:
            kwargs["keep_alive"] = keep_alive
        if think is not None:
            kwargs["think"] = think
        return chat(**kwargs)

    def chat(self, messages: list):
        """Generate a normal conversational response using the chat model."""
        return self.generate(
            model=self.chat_model,
            messages=messages,
            options={"num_gpu": self.chat_num_gpu, "num_predict": self.chat_num_predict},
            think=self.chat_think,
        )

    def planner(self, messages: list, *, format: str = "json"):
        """Generate a planner response using the configured planner model."""
        return self.generate(model=self.planner_model, messages=messages, format=format)

    def coding(self, messages: list, *, format: str = "json", options: dict | None = None, model: str | None = None):
        """Generate a coding/repair response with optional model override."""
        return self.generate(
            model=model or self.coding_model,
            messages=messages,
            format=format,
            options=options or {"temperature": 0, "num_predict": 240, "num_ctx": self.coding_num_ctx},
            keep_alive=config.CODING_MODEL_KEEP_ALIVE,
        )

    def warmup_coding_model(self) -> bool:
        """Load the coding model into Ollama's resident cache for fast repairs."""
        if not config.PRELOAD_CODING_MODEL:
            return False

        # Keep the warm-up tiny: its purpose is loading the model, not solving
        # anything. The actual repair request uses the full repair prompt later.
        self.generate(
            model=self.coding_model,
            messages=[
                {
                    "role": "user",
                    "content": "Initialize the coding model. Respond with OK.",
                }
            ],
            options={
                "temperature": 0,
                "num_predict": 1,
                "num_ctx": self.coding_num_ctx,
            },
            keep_alive=config.CODING_MODEL_KEEP_ALIVE,
        )
        return True
