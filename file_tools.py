"""
JARVIS file system tools with input validation.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from logger import logger


IGNORED_LIST_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "jarvis_cuda",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".cache",
    ".eggs",
    ".jarvis_checkpoints",
    "build",
    "dist",
}

IGNORED_LIST_FILE_TOKENS = (
    ".before_",
    ".before-",
    ".backup",
    "_backup",
    ".bak",
    ".broken_",
    ".working_",
)

IGNORED_LIST_RUNTIME_FILES = {
    "input.wav",
    "jarvis_memory.db",
    "conversation_history.json",
    "jarvis_history.json",
    "task_state.json",
}


def _is_discovery_noise(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    return (
        lowered in IGNORED_LIST_RUNTIME_FILES
        or any(token in lowered for token in IGNORED_LIST_FILE_TOKENS)
    )


def _is_ignored_list_entry(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    return (
        lowered in IGNORED_LIST_DIRECTORIES
        or _is_discovery_noise(lowered)
    )


def _sanitize_folder_name(name: str) -> str:
    """Sanitize a single folder/file-name component."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    return name


def _sanitize_relative_filename(filename: str) -> Optional[str]:
    """Sanitize a project-relative filename without destroying its subdirectories."""
    raw = str(filename or "").strip()
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]

    if not parts or any(part == ".." for part in parts):
        return None

    sanitized_parts = [
        _sanitize_folder_name(part)
        for part in parts
    ]

    if any(not part for part in sanitized_parts):
        return None

    return str(Path(*sanitized_parts))


def _resolve_safe_path(
    base_dir: Path,
    relative_path: str,
    allow_outside: bool = False
) -> Optional[Path]:
    """
    Resolve a path relative to base_dir, ensuring it stays within base_dir
    unless allow_outside is True.
    """
    base_dir = base_dir.resolve()
    # Normalize the path to prevent traversal
    clean = relative_path.replace('\\', '/').lstrip('/')
    target = (base_dir / clean).resolve()

    if not allow_outside:
        try:
            target.relative_to(base_dir)
        except ValueError:
            return None

    return target


def create_folder(name: str) -> str:
    """
    Create a folder within the current working directory.
    """
    if not name or not name.strip():
        return "Folder name cannot be empty."

    safe_name = _sanitize_folder_name(name)
    if not safe_name:
        return "Invalid folder name."

    base = Path.cwd()
    path = base / safe_name

    # Ensure the path stays within the working directory
    try:
        path.relative_to(base)
    except ValueError:
        return "I won't create a folder outside the working directory."

    try:
        path.mkdir(parents=True, exist_ok=True)
        return f"Created folder {safe_name}."
    except OSError as e:
        logger.error(f"Failed to create folder: {e}")
        return f"I couldn't create the folder: {e}"


def list_files(folder: str = ".") -> str:
    """
    List files in a folder.
    """
    base = Path.cwd()
    target = _resolve_safe_path(base, folder, allow_outside=True)

    if target is None or not target.exists():
        return f"Folder not found: {folder}"

    if not target.is_dir():
        return f"Not a folder: {folder}"

    try:
        items = sorted(os.listdir(target))
        if not items:
            return "The folder is empty."

        filtered_items = [
            item
            for item in items
            if not _is_ignored_list_entry(item)
        ]

        if not filtered_items:
            return "No relevant project files found."

        result = "Relevant project files:\n"
        for item in filtered_items:
            result += f"- {item}\n"
        return result.strip()
    except OSError as e:
        logger.error(f"Failed to list folder: {e}")
        return f"Error: {e}"


def _normalize_filename_for_search(value: str) -> str:
    """Normalize human/voice-transcribed filenames for conservative matching."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def find_file(filename: str, location: str = ".") -> str:
    """
    Search for a file by name.

    Supports both normal case-insensitive substring matching and a
    conservative normalized-name fallback so spoken punctuation/underscores
    can be omitted without preventing discovery.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."

    base = Path.cwd()
    search_dir = _resolve_safe_path(base, location, allow_outside=True)

    if search_dir is None or not search_dir.exists():
        return f"Search location not found: {location}"

    matches: List[str] = []
    filename_lower = filename.lower()
    normalized_query = _normalize_filename_for_search(filename)

    try:
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [
                name
                for name in dirs
                if not _is_ignored_list_entry(name)
            ]

            for file in files:
                if _is_discovery_noise(file):
                    continue

                lower_file = file.lower()

                if filename_lower in lower_file:
                    matches.append(str(Path(root) / file))
                    continue

                if (
                    normalized_query
                    and normalized_query in _normalize_filename_for_search(file)
                ):
                    matches.append(str(Path(root) / file))
    except OSError as e:
        logger.error(f"File search error: {e}")
        return f"Error searching for files: {e}"

    if matches:
        return "Found:\n" + "\n".join(matches)
    return "No files found."


def open_folder(path: str = ".") -> str:
    """
    Open a folder in File Explorer.
    """
    base = Path.cwd()
    target = _resolve_safe_path(base, path, allow_outside=True)

    if target is None:
        return "Invalid folder path."

    if not target.exists():
        return f"Folder not found: {path}"

    try:
        subprocess.Popen(["explorer", str(target)])
        return "Opening folder."
    except OSError as e:
        logger.error(f"Failed to open folder: {e}")
        return f"Error: {e}"


def write_file(
    filename: str,
    content: str,
    folder: str = ".",
    overwrite: bool = False
) -> str:
    """
    Write content to a file.

    Args:
        filename: Name of the file to write.
        content: Content to write to the file.
        folder: Folder to write to (default: current directory).
        overwrite: Whether to overwrite existing files.

    Returns:
        Status message.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."

    if content is None:
        return "Content cannot be None."

    base = Path.cwd()
    target_dir = _resolve_safe_path(base, folder, allow_outside=True)

    if target_dir is None:
        return "Invalid folder path."

    if not target_dir.exists():
        return f"Folder not found: {folder}"

    if not target_dir.is_dir():
        return f"Not a folder: {folder}"

    # Sanitize filename while preserving nested project-relative paths.
    safe_name = _sanitize_relative_filename(filename)
    if not safe_name:
        return "Invalid filename."

    target = _resolve_safe_path(
        target_dir,
        safe_name,
        allow_outside=False,
    )
    if target is None:
        return "Invalid filename."

    # Check if file exists
    if target.exists() and not overwrite:
        return f"File '{safe_name}' already exists. Use overwrite=True to replace it."

    try:
        # Create parent directories if needed
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Wrote {len(content)} bytes to {safe_name}."
    except OSError as e:
        logger.error(f"Failed to write file: {e}")
        return f"I couldn't write the file: {e}"


def read_file(filename: str, folder: str = ".") -> str:
    """
    Read content from a file.

    Args:
        filename: Name of the file to read.
        folder: Folder containing the file.

    Returns:
        File content or error message.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."

    base = Path.cwd()
    target_dir = _resolve_safe_path(base, folder, allow_outside=True)

    if target_dir is None:
        return "Invalid folder path."

    safe_name = _sanitize_relative_filename(filename)
    if not safe_name:
        return "Invalid filename."

    target = _resolve_safe_path(
        target_dir,
        safe_name,
        allow_outside=False,
    )
    if target is None:
        return "Invalid filename."

    if not target.exists():
        return f"File not found: {safe_name}"

    if not target.is_file():
        return f"Not a file: {safe_name}"

    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except OSError as e:
        logger.error(f"Failed to read file: {e}")
        return f"Error reading file: {e}"


def edit_file(
    filename: str,
    old_text: str,
    new_text: str,
    folder: str = "."
) -> str:
    """
    Edit a file by replacing old_text with new_text.

    Args:
        filename: Name of the file to edit.
        old_text: Text to find and replace.
        new_text: Text to replace with.
        folder: Folder containing the file.

    Returns:
        Status message.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."

    if not old_text:
        return "old_text cannot be empty."

    base = Path.cwd()
    target_dir = _resolve_safe_path(base, folder, allow_outside=True)

    if target_dir is None:
        return "Invalid folder path."

    safe_name = _sanitize_relative_filename(filename)
    if not safe_name:
        return "Invalid filename."

    target = _resolve_safe_path(
        target_dir,
        safe_name,
        allow_outside=False,
    )
    if target is None:
        return "Invalid filename."

    if not target.exists():
        return f"File not found: {safe_name}"

    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        if old_text not in content:
            return f"old_text not found in {safe_name}."

        count = content.count(old_text)
        new_content = content.replace(old_text, new_text)

        with open(target, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Replaced {count} occurrence(s) in {safe_name}."
    except OSError as e:
        logger.error(f"Failed to edit file: {e}")
        return f"I couldn't edit the file: {e}"


def delete_file(filename: str, folder: str = ".") -> str:
    """
    Delete a file.

    Args:
        filename: Name of the file to delete.
        folder: Folder containing the file.

    Returns:
        Status message.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."

    base = Path.cwd()
    target_dir = _resolve_safe_path(base, folder, allow_outside=True)

    if target_dir is None:
        return "Invalid folder path."

    safe_name = _sanitize_relative_filename(filename)
    if not safe_name:
        return "Invalid filename."

    target = _resolve_safe_path(
        target_dir,
        safe_name,
        allow_outside=False,
    )
    if target is None:
        return "Invalid filename."

    if not target.exists():
        return f"File not found: {safe_name}"

    if not target.is_file():
        return f"Not a file: {safe_name}"

    try:
        target.unlink()
        return f"Deleted {safe_name}."
    except OSError as e:
        logger.error(f"Failed to delete file: {e}")
        return f"I couldn't delete the file: {e}"


def list_files_detailed(folder: str = ".") -> str:
    """
    List files with detailed information (size, modified date).

    Args:
        folder: Folder to list.

    Returns:
        Formatted file listing.
    """
    base = Path.cwd()
    target = _resolve_safe_path(base, folder, allow_outside=True)

    if target is None or not target.exists():
        return f"Folder not found: {folder}"

    if not target.is_dir():
        return f"Not a folder: {folder}"

    try:
        items = sorted(os.listdir(target))
        if not items:
            return "The folder is empty."

        result = "Files in {}:\n".format(folder)
        for item in items:
            item_path = target / item
            if item_path.is_file():
                size = item_path.stat().st_size
                result += f"  {item} ({size} bytes)\n"
            else:
                result += f"  {item}/ (folder)\n"
        return result.strip()
    except OSError as e:
        logger.error(f"Failed to list folder: {e}")
        return f"Error: {e}"