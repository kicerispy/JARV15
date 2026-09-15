"""
JARVIS centralized logging.
"""
import logging
import os
from typing import Optional

LOG_LEVEL = os.environ.get("JARVIS_LOG_LEVEL", "INFO").upper()


class JarvisFormatter(logging.Formatter):
    """Consistent JARVIS log formatting."""

    def format(self, record: logging.LogRecord) -> str:
        return f"[JARVIS] {record.getMessage()}"


def setup_logging(
    name: str = "JARVIS",
    level: Optional[str] = None,
) -> logging.Logger:
    """Configure and return the JARVIS logger."""

    logger = logging.getLogger(name)

    # Prevent messages from being printed again by the root logger.
    logger.propagate = False

    # Avoid adding another handler if setup_logging() is called again.
    if not any(getattr(handler, "_jarvis_handler", False)
               for handler in logger.handlers):

        handler = logging.StreamHandler()
        handler._jarvis_handler = True

        handler.setFormatter(JarvisFormatter())
        logger.addHandler(handler)

    effective_level = level or LOG_LEVEL
    logger.setLevel(effective_level)

    return logger


# Default application logger.
logger = setup_logging()