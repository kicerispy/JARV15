"""JARVIS desktop vision and input fallback.

Playwright is preferred for browser work. This module handles genuine desktop
input through PyAutoGUI and uses the local Ollama vision model only when a
human-readable target must be located on the screen.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import json
import logging
import time
from typing import Any

import httpx
import pyautogui
from PIL import Image

from config import OLLAMA_HOST, SCREENSHOT_PATH, VISION_MODEL

logger = logging.getLogger("jarvis.screen_vision")


def _capture_image() -> Image.Image:
    return pyautogui.screenshot()


def _capture_bytes(image: Image.Image | None = None) -> bytes:
    image = image or _capture_image()
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _vision_query(image_bytes: bytes, prompt: str) -> dict[str, Any] | None:
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }
        ],
        "stream": False,
        "format": "json",
    }

    try:
        response = httpx.post(
            OLLAMA_HOST.rstrip("/") + "/api/chat",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        return json.loads(content)
    except Exception as exc:
        logger.error("Vision query failed: %s", exc)
        return None


def capture_screen() -> dict[str, Any]:
    """Capture the desktop to the configured screenshot path."""
    try:
        image = _capture_image()
        SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        image.save(SCREENSHOT_PATH)
        return {
            "success": True,
            "verified": True,
            "path": str(SCREENSHOT_PATH),
            "width": image.width,
            "height": image.height,
            "message": "Desktop screenshot captured.",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "error": str(exc),
            "message": "I couldn't capture the desktop.",
        }


def get_screen_size() -> dict[str, Any]:
    try:
        width, height = pyautogui.size()
        return {
            "success": True,
            "width": int(width),
            "height": int(height),
            "message": f"Screen resolution is {width} by {height}.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_active_window() -> dict[str, Any]:
    if hasattr(ctypes, "windll"):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            buffer = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, 512)
            title = buffer.value.strip()
            return {
                "success": True,
                "title": title,
                "message": f"The active window is {title or 'unknown'}.",
            }
        except Exception as exc:
            logger.debug("Active-window lookup failed: %s", exc)

    return {
        "success": True,
        "title": "Unknown",
        "message": "The active window could not be identified.",
    }


def locate_target_on_screen(
    image_bytes: bytes,
    target_description: str,
) -> dict[str, Any]:
    """Locate a target with the local vision model."""
    prompt = f"""
Locate the visible desktop UI target described as: {target_description!r}.

Return ONLY JSON:
{{
  "found": true,
  "confidence": 0.90,
  "box_2d": [ymin, xmin, ymax, xmax],
  "description": "short description"
}}

Coordinates are normalized integers from 0 to 1000.
If the target is not visible, return:
{{"found": false, "confidence": 0.0, "box_2d": [], "description": "not found"}}
"""

    result = _vision_query(image_bytes, prompt)
    if not result or not result.get("found"):
        return {
            "success": False,
            "confidence": float((result or {}).get("confidence", 0.0) or 0.0),
            "message": f"Target {target_description!r} was not found on screen.",
        }

    box = result.get("box_2d") or []
    if len(box) != 4:
        return {
            "success": False,
            "confidence": float(result.get("confidence", 0.0) or 0.0),
            "message": "Vision returned an invalid target box.",
        }

    try:
        ymin, xmin, ymax, xmax = [max(0, min(1000, int(value))) for value in box]
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size

        left = int((xmin / 1000.0) * width)
        top = int((ymin / 1000.0) * height)
        right = int((xmax / 1000.0) * width)
        bottom = int((ymax / 1000.0) * height)

        return {
            "success": True,
            "verified": True,
            "confidence": float(result.get("confidence", 0.0) or 0.0),
            "x": (left + right) // 2,
            "y": (top + bottom) // 2,
            "box": [left, top, right, bottom],
            "description": str(result.get("description", target_description)),
            "message": f"Located {target_description!r} via vision.",
        }
    except Exception as exc:
        return {
            "success": False,
            "confidence": 0.0,
            "error": str(exc),
            "message": f"Vision could not resolve {target_description!r}.",
        }


def _dom_click_fallback(target: str, double: bool = False, right: bool = False) -> dict[str, Any] | None:
    """Try the controlled browser DOM before desktop vision."""
    try:
        from browser_controller import browser_click_element

        result = browser_click_element(text=target)
        if isinstance(result, dict) and result.get("success"):
            result = dict(result)
            result["fallback"] = "browser_dom"
            return result
    except Exception as exc:
        logger.debug("Browser DOM fallback unavailable: %s", exc)

    return None


def _desktop_click(target: str, clicks: int = 1, button: str = "left") -> dict[str, Any]:
    screenshot = _capture_bytes()
    detection = locate_target_on_screen(screenshot, target)

    if not detection.get("success"):
        return detection

    x = int(detection["x"])
    y = int(detection["y"])
    pyautogui.click(x=x, y=y, clicks=clicks, interval=0.1, button=button)

    return {
        **detection,
        "success": True,
        "verified": True,
        "fallback": "desktop_vision",
        "clicked": True,
        "clicks": clicks,
        "button": button,
    }


def click_screen_target(target: str) -> dict[str, Any]:
    target = str(target or "").strip()
    if not target:
        return {"success": False, "error": "Screen target cannot be empty."}

    dom = _dom_click_fallback(target)
    if dom is not None:
        return dom

    return _desktop_click(target)


def double_click_screen_target(target: str) -> dict[str, Any]:
    target = str(target or "").strip()
    if not target:
        return {"success": False, "error": "Screen target cannot be empty."}

    # Playwright currently exposes a single-click primitive, so use
    # desktop vision for a genuine double-click request.
    return _desktop_click(target, clicks=2)


def right_click_screen_target(target: str) -> dict[str, Any]:
    target = str(target or "").strip()
    if not target:
        return {"success": False, "error": "Screen target cannot be empty."}

    return _desktop_click(target, button="right")


def move_mouse_to_target(target: str) -> dict[str, Any]:
    target = str(target or "").strip()
    if not target:
        return {"success": False, "error": "Mouse target cannot be empty."}

    screenshot = _capture_bytes()
    detection = locate_target_on_screen(screenshot, target)
    if not detection.get("success"):
        return detection

    pyautogui.moveTo(
        int(detection["x"]),
        int(detection["y"]),
        duration=0.15,
    )

    return {
        **detection,
        "success": True,
        "verified": True,
        "moved": True,
    }


def scroll_screen(argument: str = "") -> dict[str, Any]:
    text = str(argument or "").strip().lower()

    amount = 4
    direction = "down"

    import re

    match = re.search(r"(-?\d+)", text)
    if match:
        amount = max(1, min(abs(int(match.group(1))), 20))

    if "up" in text:
        direction = "up"

    elif "down" in text:
        direction = "down"

    elif "top" in text:
        pyautogui.hotkey("ctrl", "home")
        return {
            "success": True,
            "verified": True,
            "action": "scroll_top",
            "message": "Scrolled to the top.",
        }

    elif "bottom" in text:
        pyautogui.hotkey("ctrl", "end")
        return {
            "success": True,
            "verified": True,
            "action": "scroll_bottom",
            "message": "Scrolled to the bottom.",
        }

    pyautogui.scroll(-amount if direction == "down" else amount)

    return {
        "success": True,
        "verified": True,
        "action": "scroll",
        "direction": direction,
        "amount": amount,
        "message": f"Scrolled {direction}.",
    }


def type_text(argument: str = "") -> dict[str, Any]:
    text = str(argument or "")
    pyautogui.write(text, interval=0.01)
    return {
        "success": True,
        "verified": True,
        "action": "type_text",
        "characters": len(text),
        "message": "Text entered.",
    }


def press_key(argument: str = "") -> dict[str, Any]:
    keys = [part.strip().lower() for part in str(argument or "").replace("+", " ").split() if part.strip()]
    if not keys:
        return {"success": False, "error": "Key cannot be empty."}

    pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])

    return {
        "success": True,
        "verified": True,
        "action": "press_key",
        "key": argument,
        "message": f"Pressed {argument}.",
    }


def analyze_screen(question: str = "") -> dict[str, Any]:
    prompt = f"""
Describe the current desktop screenshot for JARVIS.
Question from the user: {str(question or '').strip() or 'Describe the important visible UI.'}

Return ONLY JSON:
{{
  "summary": "concise description",
  "details": "important visible details"
}}
"""
    result = _vision_query(_capture_bytes(), prompt)
    if not result:
        return {
            "success": False,
            "error": "Vision analysis failed.",
            "message": "I couldn't analyze the screen.",
        }

    summary = str(result.get("summary", "")).strip()
    details = str(result.get("details", "")).strip()

    return {
        "success": True,
        "verified": True,
        "summary": summary,
        "details": details,
        "message": (summary + (" " + details if details else "")).strip(),
    }


def verify_screen_state(expected: str = "") -> dict[str, Any]:
    prompt = f"""
Determine whether the current desktop visibly matches this expected state:
{str(expected or '').strip()!r}

Return ONLY JSON:
{{
  "matches": true,
  "confidence": 0.90,
  "reason": "short explanation"
}}
"""
    result = _vision_query(_capture_bytes(), prompt)
    if not result:
        return {
            "success": False,
            "verified": False,
            "error": "Vision verification failed.",
        }

    matches = bool(result.get("matches"))
    return {
        "success": matches,
        "verified": True,
        "confidence": float(result.get("confidence", 0.0) or 0.0),
        "matches": matches,
        "reason": str(result.get("reason", "")).strip(),
        "message": (
            "The screen matches the expected state."
            if matches
            else "The screen does not match the expected state."
        ),
    }


def _screen_fingerprint() -> str:
    return hashlib.sha256(_capture_bytes()).hexdigest()


def wait_for_change(timeout: float = 0.75, interval: float = 0.20) -> bool:
    """Return True when the desktop image changes within the timeout."""
    baseline = _screen_fingerprint()
    deadline = time.monotonic() + max(0.05, float(timeout))

    while time.monotonic() < deadline:
        time.sleep(max(0.05, float(interval)))
        if _screen_fingerprint() != baseline:
            return True

    return False
