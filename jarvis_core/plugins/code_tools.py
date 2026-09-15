"""
JARVIS Code Tools Plugin - Code generation and file writing.
"""
import re
from typing import Any, Dict, List

from ollama import AsyncClient

from jarvis_core.config.settings import get_settings
from jarvis_core.plugins.base import BasePlugin
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Context, Tool, ToolResult, ToolResultStatus

logger = get_logger(__name__)


CODE_PATTERNS = [
    r"\b(create|make|build|write|generate)\b.*\b(code|script|program|game|app|application|website|webpage|html|python|javascript|js|file|lua|roblox)\b",
    r"\b(write|create)\b.*\b\d+\s*(file|script|program)\b",
    r"\b(flay|snake|tic\s*tac\s*toe|pong|browser\s*game)\b",
    r"\bhtml\b.*\bcss\b.*\bjavascript\b",
    r"\bpython\b.*\bscript\b",
    r"\broblox\b.*\b(script|game|model|part|tool|gui)\b",
    r"\blua\b.*\b(script|roblox|game)\b",
]


class CodeToolsPlugin(BasePlugin):
    @property
    def manifest(self):
        from jarvis_core.utils.types import PluginManifest
        return PluginManifest(
            name="code_tools",
            version="1.0.0",
            description="Code generation and file writing",
            author="JARVIS",
            entry_point="code_tools",
            capabilities=["code_generation", "file_writing", "language_support"],
        )

    def get_tools(self) -> List[Tool]:
        return [
            GenerateCodeTool(),
            ExtractFilenameTool(),
            IsCodeRequestTool(),
        ]


class GenerateCodeTool(Tool):
    name = "generate_code"
    description = (
        "Generate complete, working code based on a user's request. "
        "Specify language or let JARVIS infer it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "The user's coding request"},
            "language": {
                "type": "string",
                "description": "Target language (auto-inferred if omitted)",
                "default": "auto",
            },
            "filename": {
                "type": "string",
                "description": "Output filename (auto-generated if omitted)",
                "default": "",
            },
        },
        "required": ["request"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from code_gen import extract_filename

        request = arguments.get("request", "")
        language = arguments.get("language", "auto")
        filename = arguments.get("filename", "")

        if not request.strip():
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Request cannot be empty",
            )

        if not filename:
            filename = extract_filename(request)

        is_roblox = "roblox" in request.lower() or "lua" in request.lower()

        if is_roblox:
            prompt = f"""You are an expert Roblox Lua developer. Generate complete, working Roblox Lua code for the following request.

User request: {request}

Requirements:
1. Use proper Roblox API: game:GetService(), Instance.new(), workspace, etc.
2. For Script: use .Touched events, tweens, remote events
3. For LocalScript: use player local scripts, GUI, camera
4. Use proper indentation and comments
5. Handle edge cases (parts touching, player respawning)
6. Return ONLY the Lua code, no markdown blocks, no explanations

Generate the Roblox Lua code now:"""
        else:
            language_hint = ""
            if language != "auto" and language:
                language_hint = f"Target language: {language}. "
            prompt = f"""You are an expert software engineer. Generate complete, working, production-ready code.

{language_hint}User request: {request}

Requirements:
1. Generate COMPLETE, WORKING code that actually runs
2. Include ALL necessary HTML, CSS, and JavaScript in a single file if it's a web app
3. Use modern, clean code with comments
4. Make it visually appealing and functional
5. For games, include collision detection, scoring, and game states
6. Return ONLY the code, no explanations before or after
7. Start with the first line of actual code (no markdown code blocks)

Generate the code now:"""

        settings = get_settings()
        try:
            client = AsyncClient(host=settings.models.ollama_host)
            response = await client.chat(
                model=settings.models.chat_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3},
            )

            code = response.get("message", {}).get("content", "").strip()
            code = re.sub(r'^```(?:html|javascript|python|js|lua)?\n', '', code)
            code = re.sub(r'\n```$', '', code)
            code = re.sub(r'^```(?:html|javascript|python|js|lua)?$', '', code)
            code = code.strip()

            if not code:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error="Code generation produced empty output",
                )

            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={
                    "filename": filename, "code": code,
                    "is_roblox": is_roblox, "language": language,
                },
            )

        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class ExtractFilenameTool(Tool):
    name = "extract_filename"
    description = "Extract a filename from a user's coding request text."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "User request text to extract filename from"},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from code_gen import extract_filename
        text = arguments.get("text", "")
        filename = extract_filename(text)
        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"filename": filename},
        )


class IsCodeRequestTool(Tool):
    name = "is_code_request"
    description = "Check if a user's message is a code generation request."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "User message to check"},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from code_gen import is_code_request
        text = arguments.get("text", "")
        is_code = is_code_request(text)
        return ToolResult(
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"is_code_request": is_code},
        )
