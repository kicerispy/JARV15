"""
JARVIS System Tools Plugin - System operations.
"""
import asyncio
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import psutil

from jarvis_core.plugins.base import BasePlugin
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Tool, ToolResult, ToolResultStatus, Context

logger = get_logger(__name__)


class SystemToolsPlugin(BasePlugin):
    @property
    def manifest(self):
        from jarvis_core.utils.types import PluginManifest
        return PluginManifest(
            name="system_tools",
            version="1.0.0",
            description="System monitoring and operations",
            author="JARVIS",
            entry_point="system_tools",
            capabilities=["system_info", "process_management", "shell_exec"],
        )

    def get_tools(self) -> List[Tool]:
        return [
            SystemStatusTool(),
            ShellExecTool(),
            OpenProgramTool(),
            OpenWebsiteTool(),
            CurrentTimeTool(),
            CurrentDateTool(),
            WaitTool(),
        ]


class SystemStatusTool(Tool):
    name = "system_status"
    description = "Get system status (CPU, RAM, disk, network)"
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            net = psutil.net_io_counters()

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={
                    "cpu_percent": cpu,
                    "ram_percent": ram.percent,
                    "ram_used_gb": round(ram.used / (1024**3), 2),
                    "ram_total_gb": round(ram.total / (1024**3), 2),
                    "disk_percent": disk.percent,
                    "disk_used_gb": round(disk.used / (1024**3), 2),
                    "disk_total_gb": round(disk.total / (1024**3), 2),
                    "net_sent_mb": round(net.bytes_sent / (1024**2), 2),
                    "net_recv_mb": round(net.bytes_recv / (1024**2), 2),
                    "platform": platform.platform(),
                    "boot_time": psutil.boot_time(),
                },
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class ShellExecTool(Tool):
    name = "shell_exec"
    description = "Execute a shell command"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "cwd": {"type": "string", "description": "Working directory", "default": "."},
            "timeout": {"type": "integer", "default": 30},
        },
        "required": ["command"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        command = arguments["command"]
        cwd = Path(arguments.get("cwd", ".")).expanduser()
        timeout = arguments.get("timeout", 30)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"Command timed out after {timeout}s",
                )

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS if process.returncode == 0 else ToolResultStatus.ERROR,
                result={
                    "returncode": process.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace")[:5000],
                    "stderr": stderr.decode("utf-8", errors="replace")[:5000],
                },
                error=stderr.decode("utf-8", errors="replace")[:1000] if process.returncode != 0 else None,
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


PROGRAM_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "edge": "msedge.exe",
    "discord": "Discord.exe",
    "spotify": "Spotify.exe",
    "steam": "steam.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
}


class OpenProgramTool(Tool):
    name = "open_program"
    description = "Launch a desktop application"
    parameters = {
        "type": "object",
        "properties": {
            "program": {"type": "string", "description": "Program name"},
        },
        "required": ["program"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        program = arguments["program"].lower().strip()

        try:
            if program in {"chrome", "google chrome"}:
                chrome_paths = [
                    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                ]
                for p in chrome_paths:
                    expanded = os.path.expandvars(p)
                    if os.path.exists(expanded):
                        subprocess.Popen([expanded])
                        return ToolResult(
                            call_id="",
                            tool_name=self.name,
                            status=ToolResultStatus.SUCCESS,
                            result={"program": "Chrome"},
                        )
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error="Chrome not found",
                )

            executable = PROGRAM_ALIASES.get(program)
            if not executable:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"Unknown program: {program}",
                )

            subprocess.Popen([executable])
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"program": program},
            )
        except FileNotFoundError:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=f"Program not found: {program}",
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class OpenWebsiteTool(Tool):
    name = "open_website"
    description = "Open a website in the default browser"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL or site name"},
        },
        "required": ["url"],
    }

    WEBSITE_URLS = {
        "youtube": "https://www.youtube.com/",
        "google": "https://www.google.com/",
        "amazon": "https://www.amazon.com/",
        "reddit": "https://www.reddit.com/",
        "github": "https://github.com/",
        "stackoverflow": "https://stackoverflow.com/",
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        import webbrowser
        url = arguments["url"].strip()

        try:
            if not (url.startswith("http://") or url.startswith("https://")):
                site = url.lower()
                url = self.WEBSITE_URLS.get(site, f"https://{url}")

            webbrowser.open(url)
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"url": url},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class CurrentTimeTool(Tool):
    name = "current_time"
    description = "Get current time"
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {"type": "string", "description": "Timezone (e.g., 'America/Chicago')"},
        },
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = arguments.get("timezone")
        try:
            if tz:
                now = datetime.now(ZoneInfo(tz))
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.SUCCESS,
                    result={"time": now.strftime("%I:%M %p"), "timezone": tz},
                )
            else:
                now = datetime.now()
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.SUCCESS,
                    result={"time": now.strftime("%I:%M %p"), "timezone": "local"},
                )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class CurrentDateTool(Tool):
    name = "current_date"
    description = "Get current date"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from datetime import datetime
        now = datetime.now()
        return ToolResult(
            call_id="",
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"date": now.strftime("%A, %B %d, %Y")},
        )


class WaitTool(Tool):
    name = "wait"
    description = "Wait for specified seconds"
    parameters = {
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "Seconds to wait"},
        },
        "required": ["seconds"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        seconds = max(0, min(float(arguments["seconds"]), 30))
        await asyncio.sleep(seconds)
        return ToolResult(
            call_id="",
            tool_name=self.name,
            status=ToolResultStatus.SUCCESS,
            result={"waited": seconds},
        )


