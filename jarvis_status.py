"""
JARVIS system status monitoring.
"""
import time
from typing import Dict, Any

import psutil

from logger import logger


_start_time = time.time()


def get_status(model: str = "unknown") -> str:
    """
    Get JARVIS's current status including system metrics.

    Args:
        model: The name of the current LLM model.

    Returns:
        A formatted status string.
    """
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        uptime = int(time.time() - _start_time)

        return f"""
JARVIS Status:

Model: {model}

CPU: {cpu}%

RAM: {ram.percent}%

Uptime: {uptime} seconds
"""
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        return "I couldn't retrieve the system status."