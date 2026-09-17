"""Best-effort synchronization between JARVIS lifecycle states and barehands."""

from __future__ import annotations

import os

from barehands_controller import BarehandsController
from logger import logger


def set_barehands_state(state: str) -> None:
    """Update the optional barehands ring without affecting JARVIS execution."""
    try:
        state_dir = os.environ.get("BAREHANDS_DIR", "").strip()
        if not state_dir:
            return
        result = BarehandsController(state_dir=state_dir).set_state(state)
        if not result.success:
            logger.debug(f"JARVIS: barehands state sync skipped: {result.error}")
    except Exception as exc:
        logger.debug(f"JARVIS: barehands state sync failed: {exc}")
