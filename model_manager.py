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

    chat_think: bool = config.CHAT_THINK
    chat_num_gpu: int = config.CHAT_NUM_GPU
    chat_num_predict: int = config.CHAT_NUM_PREDICT
