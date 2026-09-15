"""
JARVIS File Tools Plugin - File operations.
"""
import shutil
from pathlib import Path
from typing import Any, Dict, List

from jarvis_core.plugins.base import BasePlugin
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Context, Tool, ToolResult, ToolResultStatus

logger = get_logger(__name__)


class FileToolsPlugin(BasePlugin):
    @property
    def manifest(self):
        from jarvis_core.utils.types import PluginManifest
        return PluginManifest(
            name="file_tools",
            version="1.0.0",
            description="File system operations",
            author="JARVIS",
            entry_point="file_tools",
            capabilities=["file_read", "file_write", "file_list", "file_delete", "directory_ops"],
        )

    def get_tools(self) -> List[Tool]:
        return [
            ReadFileTool(),
            WriteFileTool(),
            ListFilesTool(),
            FindFileTool(),
            CreateFolderTool(),
            DeleteFileTool(),
            EditFileTool(),
            OpenFolderTool(),
        ]


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read content from a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        encoding = arguments.get("encoding", "utf-8")

        try:
            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"File not found: {path}",
                )

            content = path.read_text(encoding=encoding)
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path), "content": content, "size": len(content)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write content to a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "Content to write"},
            "overwrite": {"type": "boolean", "default": True},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        content = arguments["content"]
        overwrite = arguments.get("overwrite", True)
        encoding = arguments.get("encoding", "utf-8")

        try:
            if path.exists() and not overwrite:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"File exists and overwrite=False: {path}",
                )

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path), "bytes_written": len(content.encode(encoding))},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class ListFilesTool(Tool):
    name = "list_files"
    description = "List files in a directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern", "default": "**/*"},
            "recursive": {"type": "boolean", "default": True},
        },
        "required": [],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments.get("path", ".")).expanduser()
        pattern = arguments.get("pattern", "**/*")
        recursive = arguments.get("recursive", True)

        try:
            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"Path not found: {path}",
                )

            if recursive:
                files = list(path.glob(pattern))
            else:
                files = list(path.glob(pattern))

            result = []
            for f in files:
                if f.is_file():
                    stat = f.stat()
                    result.append({
                        "name": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"files": result, "count": len(result)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class FindFileTool(Tool):
    name = "find_file"
    description = "Search for a file by name"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "File name or pattern"},
            "path": {"type": "string", "description": "Search root", "default": "."},
        },
        "required": ["name"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        name = arguments["name"]
        path = Path(arguments.get("path", ".")).expanduser()

        try:
            matches = list(path.rglob(f"*{name}*"))
            files = [f for f in matches if f.is_file()]

            result = [{"path": str(f), "name": f.name} for f in files[:50]]

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"matches": result, "count": len(result)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Create a directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create"},
            "parents": {"type": "boolean", "default": True},
            "exist_ok": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        parents = arguments.get("parents", True)
        exist_ok = arguments.get("exist_ok", True)

        try:
            path.mkdir(parents=parents, exist_ok=exist_ok)
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Delete a file or directory"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete"},
            "recursive": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        recursive = arguments.get("recursive", False)

        try:
            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"Path not found: {path}",
                )

            if path.is_dir():
                if recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class EditFileTool(Tool):
    name = "edit_file"
    description = "Edit a file by replacing text"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "old_text": {"type": "string", "description": "Text to replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]

        try:
            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"File not found: {path}",
                )

            content = path.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error="Old text not found in file",
                )

            new_content = content.replace(old_text, new_text)
            path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path), "replacements": content.count(old_text)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class OpenFolderTool(Tool):
    name = "open_folder"
    description = "Open a folder in the system file explorer"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder path to open"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        import subprocess
        path = Path(arguments["path"]).expanduser()

        try:
            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    status=ToolResultStatus.ERROR,
                    error=f"Path not found: {path}",
                )

            subprocess.Popen(["explorer", str(path)])
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"path": str(path)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )
