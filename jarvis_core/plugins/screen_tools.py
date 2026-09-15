"""
JARVIS Screen Tools Plugin - Screen capture, vision, and input control.
"""
import asyncio
import json
import platform
from typing import Any, Dict, List

import pyautogui

from jarvis_core.config.settings import get_settings
from jarvis_core.plugins.base import BasePlugin
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Context, Tool, ToolResult, ToolResultStatus

logger = get_logger(__name__)


class ScreenToolsPlugin(BasePlugin):
    @property
    def manifest(self):
        from jarvis_core.utils.types import PluginManifest
        return PluginManifest(
            name="screen_tools",
            version="1.0.0",
            description="Screen capture, computer vision, and input control",
            author="JARVIS",
            entry_point="screen_tools",
            capabilities=[
                "screen_capture", "screen_analysis",
                "mouse_control", "keyboard_input", "window_detection",
            ],
        )

    def get_tools(self) -> List[Tool]:
        return [
            CaptureScreenTool(),
            ScreenSizeTool(),
            ActiveWindowTool(),
            AnalyzeScreenTool(),
            VerifyScreenTool(),
            MoveMouseTool(),
            ClickScreenTool(),
            DoubleClickTool(),
            ScrollScreenTool(),
            TypeTextTool(),
            PressKeyTool(),
        ]


class _ScreenVisionToolBase(Tool):
    """Base class providing shared vision helpers."""

    def _capture_screenshot(self, context: Context) -> tuple[bool, str, int, int]:
        """Capture a screenshot, return (success, path, width, height)."""
        settings = get_settings()
        screenshot_path = str(settings.vision.screenshot_path)
        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(screenshot_path)
            width, height = screenshot.size
            return True, screenshot_path, width, height
        except Exception as e:
            return False, str(e), 0, 0

    def _vision_chat(
        self, model: str, messages: List[Dict], json_mode: bool = False
    ) -> Dict | None:
        """Call Ollama vision model. Runs in executor since it's sync."""
        from ollama import chat
        options = {"model": model, "messages": messages}
        if json_mode:
            options["format"] = "json"
        try:
            return chat(**options)
        except Exception as e:
            logger.error(f"Vision model error ({model}): {e}")
            return None

    def _extract_json(self, text: str) -> Dict | None:
        """Extract JSON from LLM response text."""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return None
            return None


class CaptureScreenTool(_ScreenVisionToolBase):
    name = "capture_screen"
    description = "Take a screenshot of the current screen"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        success, path, width, height = self._capture_screenshot(context)
        if not success:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=f"Screenshot failed: {path}",
            )
        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"path": path, "width": width, "height": height},
        )


class ScreenSizeTool(Tool):
    name = "screen_size"
    description = "Get the current screen resolution"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        try:
            width, height = pyautogui.size()
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"width": width, "height": height},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class ActiveWindowTool(Tool):
    name = "get_active_window"
    description = "Get the title of the currently focused window"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"window": (
                    pyautogui.getActiveWindow().title
                    if pyautogui.getActiveWindow() else "Unknown"
                )},
            )

        import ctypes
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolResultStatus.SUCCESS,
                    result={"window": "Unknown window"},
                )
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip() or "Unknown window"
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"window": title},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class AnalyzeScreenTool(_ScreenVisionToolBase):
    name = "analyze_screen"
    description = (
        "Describe what is visible on the screen. "
        "Accepts an optional question about the screen."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Question about the screen content",
                "default": "Describe my screen.",
            },
        },
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        settings = get_settings()
        question = arguments.get("question", "Describe my screen.")

        success, screenshot_path, width, height = self._capture_screenshot(context)
        if not success:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=f"Screenshot failed: {screenshot_path}",
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are JARVIS computer vision. Analyze only visible "
                    "information. Identify: applications, browser pages, "
                    "windows, buttons, text, menus, dialogs, videos, icons, "
                    "and clickable elements. Never invent anything."
                ),
            },
            {
                "role": "user",
                "content": question,
                "images": [screenshot_path],
            },
        ]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._vision_chat(settings.models.vision_model, messages)
        )

        if not response:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Vision model failed to respond",
            )

        content = response.get("message", {}).get("content", "").strip()
        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"analysis": content, "screen_size": {"width": width, "height": height}},
        )


class VerifyScreenTool(_ScreenVisionToolBase):
    name = "verify_screen"
    description = "Verify that the screen matches an expected state."
    parameters = {
        "type": "object",
        "properties": {
            "expected": {"type": "string", "description": "Description of the expected screen state"},
        },
        "required": ["expected"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        settings = get_settings()
        expected = arguments.get("expected", "")

        success, screenshot_path, _, _ = self._capture_screenshot(context)
        if not success:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=f"Screenshot failed: {screenshot_path}",
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are JARVIS verification system. Check whether an "
                    "action succeeded. Only answer JSON: "
                    '{"success": true/false, "confidence": 0.0-1.0, '
                    '"reason": "what changed"}. Do not guess.'
                ),
            },
            {
                "role": "user",
                "content": f"Verify the screen matches: {expected}",
                "images": [screenshot_path],
            },
        ]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._vision_chat(settings.models.verify_model, messages, json_mode=True)
        )

        if not response:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Vision model failed to respond",
            )

        content = response.get("message", {}).get("content", "")
        data = self._extract_json(content)

        if not data:
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Could not parse verification response",
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={
                "verified": data.get("success", False),
                "confidence": data.get("confidence", 0.0),
                "reason": data.get("reason", ""),
            },
        )


class MoveMouseTool(_ScreenVisionToolBase):
    name = "move_mouse"
    description = "Move the mouse cursor to a target described in the argument."
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Description of the on-screen target"},
        },
        "required": ["target"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import move_mouse_to_target
        target = arguments.get("target", "")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: move_mouse_to_target(target))
        return self._wrap_result(result)

    def _wrap_result(self, result: Dict) -> ToolResult:
        if result.get("success"):
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result=result,
            )
        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.ERROR,
            error=result.get("message", "Unknown error"),
        )


class ClickScreenTool(MoveMouseTool):
    name = "click_screen"
    description = "Click an on-screen target described in the argument."

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import click_screen_target
        target = arguments.get("target", "")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: click_screen_target(target))
        return self._wrap_result(result)


class DoubleClickTool(MoveMouseTool):
    name = "double_click_screen"
    description = "Double-click an on-screen target described in the argument."

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import double_click_screen_target
        target = arguments.get("target", "")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: double_click_screen_target(target))
        return self._wrap_result(result)


class ScrollScreenTool(Tool):
    name = "scroll_screen"
    description = (
        "Scroll the screen. Argument specifies direction and "
        "optional amount (e.g., 'down', 'up 3')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "description": "Direction to scroll: up or down"},
            "amount": {"type": "integer", "description": "Number of scroll units", "default": 5},
        },
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import scroll_screen
        direction = arguments.get("direction", "down")
        amount = arguments.get("amount", 5)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: scroll_screen(direction, amount))
        if result.get("success"):
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result=result,
            )
        return ToolResult(
            tool_name=self.name, status=ToolResultStatus.ERROR,
            error=result.get("message", "Scroll failed"),
        )


class TypeTextTool(Tool):
    name = "type_text"
    description = "Type text at the current cursor position."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import type_text
        text = arguments.get("text", "")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: type_text(text))
        if result.get("success"):
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result=result,
            )
        return ToolResult(
            tool_name=self.name, status=ToolResultStatus.ERROR,
            error=result.get("message", "Typing failed"),
        )


class PressKeyTool(Tool):
    name = "press_key"
    description = (
        "Press a keyboard key or hotkey. Keys: enter, escape, tab, "
        "space, backspace, delete, up, down, left, right, "
        "or combos like 'ctrl+c'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key or key combination to press"},
        },
        "required": ["key"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from screen_vision import press_key
        key = arguments.get("key", "")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: press_key(key))
        if result.get("success"):
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result=result,
            )
        return ToolResult(
            tool_name=self.name, status=ToolResultStatus.ERROR,
            error=result.get("message", "Key press failed"),
        )
