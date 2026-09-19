"""Centralized model roles and Ollama generation settings for JARVIS."""

from __future__ import annotations

import time
from dataclasses import dataclass

import config
from logger import logger


class ModelGenerationError(RuntimeError):
    """Raised when centralized Ollama generation cannot produce a usable response."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 1,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.attempts = max(1, int(attempts))
        self.retryable = bool(retryable)


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _response_content(response) -> str:
    """Return assistant text from either an Ollama mapping or ChatResponse object."""
    if response is None:
        return ""

    if isinstance(response, dict):
        message = response.get("message")
    else:
        message = getattr(response, "message", None)

    if message is None:
        return ""

    if isinstance(message, dict):
        return str(message.get("content") or "").strip()

    return str(getattr(message, "content", "") or "").strip()


def _is_transient_generation_error(exc: BaseException) -> bool:
    """Identify failures that are usually safe to retry once."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True

    text = f"{type(exc).__name__}: {exc}".lower()

    transient_markers = (
        "connection",
        "connecterror",
        "readtimeout",
        "timeout",
        "timed out",
        "server disconnected",
        "connection reset",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        " 502",
        " 503",
        " 504",
    )

    return any(marker in text for marker in transient_markers)


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

    generation_max_attempts: int = config.OLLAMA_GENERATION_MAX_ATTEMPTS
    generation_retry_delay: float = config.OLLAMA_GENERATION_RETRY_DELAY

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
        """
        Execute one Ollama chat request through the centralized model layer.

        Transient transport failures and unusable/empty model responses receive
        a small bounded retry. Deterministic failures are surfaced immediately.
        """
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

        max_attempts = max(
            1,
            int(self.generation_max_attempts),
        )
        retry_delay = max(
            0.0,
            float(self.generation_retry_delay),
        )

        last_error: BaseException | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = chat(**kwargs)

                if not _response_content(response):
                    last_error = ModelGenerationError(
                        "Ollama returned an empty or malformed chat response.",
                        attempts=attempt,
                        retryable=True,
                    )
                else:
                    if attempt > 1:
                        logger.info(
                            "JARVIS MODEL: generation recovered on "
                            f"attempt {attempt}/{max_attempts}."
                        )
                    return response

            except Exception as exc:
                last_error = exc

                if not _is_transient_generation_error(exc):
                    raise ModelGenerationError(
                        f"Ollama generation failed: {exc}",
                        attempts=attempt,
                        retryable=False,
                    ) from exc

                logger.warning(
                    "JARVIS MODEL: transient generation failure "
                    f"(attempt {attempt}/{max_attempts}): {exc}"
                )

            if attempt >= max_attempts:
                break

            if retry_delay:
                time.sleep(
                    retry_delay * attempt
                )

        if isinstance(last_error, ModelGenerationError):
            raise ModelGenerationError(
                str(last_error),
                attempts=max_attempts,
                retryable=True,
            ) from last_error

        raise ModelGenerationError(
            f"Ollama generation failed: {last_error or 'unknown error'}",
            attempts=max_attempts,
            retryable=True,
        ) from last_error

    def chat(self, messages: list):
        """Generate a normal conversational response using the chat model."""
        return self.generate(
            model=self.chat_model,
            messages=messages,
            options={
                "num_gpu": self.chat_num_gpu,
                "num_predict": self.chat_num_predict,
            },
            think=self.chat_think,
        )

    def planner(self, messages: list, *, format: str = "json"):
        """Generate a bounded, deterministic planner response."""
        return self.generate(
            model=self.planner_model,
            messages=messages,
            format=format,
            options={
                "temperature": 0,
                "num_predict": config.PLANNER_NUM_PREDICT,
            },
            keep_alive=config.PLANNER_MODEL_KEEP_ALIVE,
            think=False,
        )

    def recovery(self, messages: list, *, format: str = "json"):
        """Generate a bounded recovery-analysis response using the chat model."""
        return self.generate(
            model=self.chat_model,
            messages=messages,
            format=format,
            options={
                "temperature": 0.0,
                "num_gpu": self.chat_num_gpu,
                "num_predict": 180,
            },
            think=False,
        )

    def coding(
        self,
        messages: list,
        *,
        format: str = "json",
        options: dict | None = None,
        model: str | None = None,
    ):
        """Generate a coding/repair response with optional model override."""
        return self.generate(
            model=model or self.coding_model,
            messages=messages,
            format=format,
            options=options or {
                "temperature": 0,
                "num_predict": 240,
                "num_ctx": self.coding_num_ctx,
            },
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
