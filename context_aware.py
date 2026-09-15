"""
JARVIS context-aware conversation - smarter responses with user/project context.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from ollama import chat

from config import CHAT_MODEL, PROFILE_PATH
from logger import logger


class JarvisContext:
    """Builds rich context for smarter conversations."""

    def __init__(self):
        self._profile = self._load_profile()
        self._project_info = self._analyze_project()

    def _load_profile(self) -> Dict[str, Any]:
        """Load user profile."""
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"name": "User"}

    def _analyze_project(self) -> Dict[str, Any]:
        """Analyze the current project structure."""
        info = {
            "files": [],
            "file_count": 0,
            "languages": set(),
            "has_tests": False,
            "has_config": False,
        }

        excluded_dirs = {"__pycache__", ".git", "jarvis_cuda", "venv", ".venv", "node_modules", ".eggs", "build", "dist", ".pytest_cache", ".mypy_cache"}

        try:
            for path in Path(".").rglob("*"):
                if not path.is_file():
                    continue
                parts = set(path.parts)
                if parts & excluded_dirs:
                    continue
                info["files"].append(str(path))
                info["file_count"] += 1

                ext = path.suffix.lower()
                if ext in (".py",):
                    info["languages"].add("Python")
                elif ext in (".js", ".ts", ".jsx", ".tsx"):
                    info["languages"].add("JavaScript/TypeScript")
                elif ext in (".html",):
                    info["languages"].add("HTML")
                elif ext in (".lua",):
                    info["languages"].add("Lua")
                elif ext in (".md",):
                    pass
                elif ext in (".json", ".toml", ".yaml", ".yml"):
                    info["has_config"] = True

                if "test" in path.name.lower():
                    info["has_tests"] = True

        except Exception as e:
            logger.warning(f"Project analysis failed: {e}")

        info["languages"] = list(info["languages"])
        return info

    def build_context_string(self) -> str:
        """Build a context string for the LLM."""
        parts = []

        # User info
        parts.append(f"User name: {self._profile.get('name', 'User')}")
        if self._profile.get("preferences"):
            prefs = self._profile["preferences"]
            if prefs.get("response_style"):
                parts.append(f"Preferred response style: {prefs['response_style']}")
            if prefs.get("interests"):
                parts.append(f"Interests: {', '.join(prefs['interests'])}")

        # Project info
        parts.append(f"\nProject: {self._project_info['file_count']} files")
        parts.append(f"Languages: {', '.join(self._project_info['languages']) or 'None detected'}")
        parts.append(f"Has tests: {self._project_info['has_tests']}")
        parts.append(f"Has config: {self._project_info['has_config']}")

        return "\n".join(parts)

    def get_response_style(self) -> str:
        """Get the user's preferred response style."""
        return self._profile.get("preferences", {}).get("response_style", "balanced")

    def refresh(self):
        """Refresh the context (call after file changes)."""
        self._project_info = self._analyze_project()


def generate_smart_response(
    user_input: str,
    conversation_history: List[Dict[str, str]],
    memories: List[str],
    context: JarvisContext
) -> str:
    """
    Generate a smarter response using rich context.

    Args:
        user_input: The user's message.
        conversation_history: Recent conversation.
        memories: Saved memories.
        context: Jarvis context with user/project info.

    Returns:
        Generated response.
    """
    context_str = context.build_context_string()
    memory_str = "\n".join(f"- {m}" for m in memories[:10]) if memories else "No saved memories."

    # Build conversation history
    history_str = ""
    for msg in conversation_history[-10:]:
        history_str += f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')}\n"

    response_style = context.get_response_style()
    style_instructions = {
        "brief": "Be very concise. Use bullet points. Maximum 3 sentences.",
        "detailed": "Provide thorough explanations with examples.",
        "balanced": "Be clear and helpful. Balance detail with brevity.",
    }.get(response_style, "Be clear and helpful.")

    prompt = f"""You are JARVIS, a personal AI assistant and software engineering expert.

{style_instructions}

CONTEXT:
{context_str}

MEMORIES:
{memory_str}

RECENT CONVERSATION:
{history_str}

USER: {user_input}

Respond as JARVIS:"""

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.7}
        )
        return response.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"Smart response generation failed: {e}")
        return "I encountered an error while processing that."
