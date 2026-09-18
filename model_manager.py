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

    def warmup_coding_model(self) -> bool:
        """Load the coding model into Ollama's resident cache for fast repairs."""
        if not config.PRELOAD_CODING_MODEL:
            return False

        # Keep the warm-up tiny: its purpose is loading the model, not solving
        # anything. The actual repair request uses the full repair prompt later.
        from ollama import chat

        chat(
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
