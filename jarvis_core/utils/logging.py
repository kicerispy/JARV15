"""
JARVIS Logging Utility - Structured, async-safe logging.
"""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional

from jarvis_core.config.settings import get_settings

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": _correlation_id.get(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "thread", "threadName",
                "exc_info", "exc_text", "stack_info"
            }:
                log_data[key] = value

        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        corr_id = _correlation_id.get()
        corr_str = f" [{corr_id[:8]}]" if corr_id else ""
        return f"{color}[{record.levelname}]{self.RESET}{corr_str} {record.getMessage()}"


def setup_logging(log_level: Optional[str] = None, log_file: Optional[Path] = None) -> logging.Logger:
    settings = get_settings()
    level = getattr(logging, (log_level or settings.log_level).upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ConsoleFormatter())
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    if log_file or settings.debug:
        log_path = log_file or (Path.home() / ".jarvis" / "logs" / "jarvis.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(StructuredFormatter())
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("ollama").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def set_correlation_id(corr_id: Optional[str]) -> None:
    _correlation_id.set(corr_id)


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


class LogContext:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.old_values = {}

    def __enter__(self):
        logger = logging.getLogger()
        for key, value in self.kwargs.items():
            self.old_values[key] = getattr(logger, key, None)
            setattr(logger, key, value)
        return self

    def __exit__(self, *args):
        logger = logging.getLogger()
        for key, value in self.old_values.items():
            if value is None:
                delattr(logger, key)
            else:
                setattr(logger, key, value)
