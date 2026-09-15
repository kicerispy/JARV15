"""
JARVIS task planner - converts user requests into tool calls.
"""
import json
from typing import Any, Dict, List, Optional

from ollama import chat

from config import PLANNER_MODEL
from logger import logger

# ==========================================================
# Available Tools
# ==========================================================

AVAILABLE_TOOLS: Dict[str, str] = {
    "weather": "Get current weather. argument = location, or empty for default.",
    "current_time": "Get current time. argument = timezone/city, or empty for local.",
    "current_date": "Get today's date. argument = empty.",
    "wait": "Wait N seconds. argument = number of seconds.",
    "open_website": "Open a website in the browser. argument = site name or URL.",
    "search_website": "Search a specific site. argument = 'site|query', e.g. 'youtube|iron man trailer'.",
    "open_program": "Launch a desktop application. argument = program name, e.g. 'notepad', 'chrome'.",
    "system_status": "Report CPU/RAM usage. argument = empty.",
    "create_folder": "Create a folder. argument = folder name.",
    "list_files": "List files in a folder. argument = folder path, or empty for current folder.",
    "find_file": "Search for a file by name. argument = filename.",
    "open_folder": "Open a folder in File Explorer. argument = folder path.",
    "write_file": "Write content to a file. argument = 'filename|||content' format.",
    "read_file": "Read content from a file. argument = filename.",
    "edit_file": "Edit a file by replacing text. argument = 'filename|||old_text|||new_text'.",
    "delete_file": "Delete a file. argument = filename.",
    "web_search": "Search the web for information. argument = search query.",
    "jarvis_status": "Report JARVIS's own status/uptime. argument = empty.",
    "capture_screen": "Take a screenshot. argument = empty.",
    "screen_size": "Get screen resolution. argument = empty.",
    "get_active_window": "Get the currently focused window. argument = empty.",
    "analyze_screen": "Describe what's on screen. argument = optional question about the screen.",
    "move_mouse": "Move the mouse to an on-screen target. argument = description of the target.",
    "click_screen": "Click an on-screen target. argument = description of the target.",
    "double_click_screen": "Double-click an on-screen target. argument = description of the target.",
    "scroll_screen": "Scroll the screen. argument = direction/amount, e.g. 'down', 'up 3'.",
    "verify_screen": "Verify the screen matches an expected state. argument = description of expected state.",
    "type_text": "Type text at the current cursor/focus. argument = the text to type.",
    "press_key": "Press a keyboard key or combo. argument = key name, e.g. 'enter', 'ctrl+c'.",
}


# ==========================================================
# Planner Prompt
# ==========================================================

def _planner_prompt() -> str:
    """Build the planner prompt with available tools."""
    tool_list = "\n".join(
        f"{name}: {desc}"
        for name, desc in AVAILABLE_TOOLS.items()
    )
    return f"""
You are JARVIS's task planner — an expert software engineer and systems architect.

Your job: convert a user request into a list of tool calls.

If the request needs no tool (a question, chit-chat, opinion,
or something you'd just answer in conversation), return an
empty steps list.

Available tools:

{tool_list}

Rules:

1. Return ONLY JSON. No explanation.
2. Every step must use exactly one tool name from the list above.
3. "argument" must always be a string (use "" if the tool needs none).
4. For complex requests, break them into multiple steps.
   Example: "Create a todo app" -> write index.html, write styles.css, write app.js
5. Never invent a tool name that isn't in the list.
6. If unsure whether a tool applies, return an empty steps list
   instead of guessing.
7. When generating code, include ALL necessary files.
8. Prefer single HTML files for web apps (embed CSS/JS).
9. For multi-file projects, order steps logically (styles before scripts).

Multi-Step Examples:

User:
Create a todo app with HTML, CSS, and JavaScript

Output:
{{
"goal": "create todo app",
"steps": [
  {{"tool": "write_file", "argument": "todo.html|||<!DOCTYPE html>\\n<html>\\n<head>\\n<title>Todo App</title>\\n<link rel=\"stylesheet\" href=\"styles.css\">\\n</head>\\n<body>\\n<div id=\"app\">\\n<input id=\"new-todo\" type=\"text\">\\n<button id=\"add-btn\">Add</button>\\n<ul id=\"todo-list\"></ul>\\n</body>\\n</html>"}},
  {{"tool": "write_file", "argument": "styles.css|||#app {{ max-width: 400px; margin: 50px auto; padding: 20px; }}\\n.todo-item {{ padding: 10px; border: 1px solid #ccc; margin: 5px 0; }}"}}
]
}}

User:
Set up a Python project with a main script and requirements file

Output:
{{
"goal": "create python project",
"steps": [
  {{"tool": "write_file", "argument": "requirements.txt|||requests>=2.31.0\\npytest>=7.4.0"}},
  {{"tool": "write_file", "argument": "main.py|||# Main application\\nimport requests\\n\\ndef main():\\n    print('Hello World')\\n\\nif __name__ == '__main__':\\n    main()"}}
]
}}

User:
What's the weather in Chicago?

Output:
{{
"goal": "check weather",
"steps": [
  {{"tool": "weather", "argument": "Chicago"}}
]
}}

User:
Search YouTube for the Iron Man trailer

Output:
{{
"goal": "search youtube",
"steps": [
  {{"tool": "search_website", "argument": "youtube|Iron Man trailer"}}
]
}}

User:
Tell me a joke

Output:
{{
"goal": "conversation",
"steps": []
}}

User:
Tell me a story about Iron Man

Output:
{{
"goal": "conversation",
"steps": []
}}

IMPORTANT: When the user asks you to CREATE, WRITE, or BUILD something (code, scripts, games, documents), you MUST generate the complete, working content yourself and use the write_file tool. Do NOT say you can't do it - just generate the code and write it.

CRITICAL: Requests to tell a story, joke, or share creative content are CONVERSATIONAL — return an empty steps list. JARVIS generates creative content directly, it does not search the web for stories. Examples that should return empty steps:
- "Tell me a story about X"
- "Write a joke"
- "Create a poem"
- "Tell me a fun fact"
- "Say something creative"
"""


# ==========================================================
# JSON Extraction
# ==========================================================

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from a string, handling markdown code blocks."""
    if not text:
        return None

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ==========================================================
# Plan Validation
# ==========================================================

def validate_plan(plan: Any) -> Dict[str, Any]:
    """Validate and clean a planner response."""
    if not isinstance(plan, dict) or "steps" not in plan:
        return {"goal": "", "steps": []}

    steps = plan.get("steps")
    if not isinstance(steps, list):
        return {"goal": plan.get("goal", ""), "steps": []}

    clean: List[Dict[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue

        tool = step.get("tool")
        argument = step.get("argument", "")

        if tool not in AVAILABLE_TOOLS:
            logger.warning(f"Rejected unknown tool: {tool}")
            continue

        clean.append({
            "tool": str(tool),
            "argument": str(argument) if argument is not None else ""
        })

    return {
        "goal": plan.get("goal", ""),
        "steps": clean
    }


# ==========================================================
# Create Plan
# ==========================================================

def create_plan(
    user_command: str,
    active_context: Optional[Dict[str, Any]] = None,
    history_text: str = ""
) -> Dict[str, Any]:
    """
    Convert a user command into a plan of tool calls.

    Args:
        user_command: The user's request.
        active_context: Current active task context.
        history_text: Recent conversation history.

    Returns:
        A dict with 'goal' and 'steps' keys.
    """
    if not user_command or not user_command.strip():
        return {"goal": "", "steps": []}

    context_str = ""
    if active_context:
        context_str = f"""

Active task context:
Website: {active_context.get('site', 'none')}
Search query: {active_context.get('last_query', 'none')}
Last tool: {active_context.get('last_tool', 'none')}
"""

    history_str = f"\nRecent conversation:\n{history_text}" if history_text else ""

    messages = [
        {
            "role": "system",
            "content": _planner_prompt() + context_str + history_str
        },
        {
            "role": "user",
            "content": user_command
        }
    ]

    try:
        response = chat(
            model=PLANNER_MODEL,
            messages=messages,
            format="json"
        )
    except Exception as e:
        logger.error(f"Planner LLM call failed: {e}")
        return {"goal": "", "steps": []}

    content = response.get("message", {}).get("content", "")
    data = extract_json(content)

    if not data:
        logger.warning(f"Planner returned invalid JSON: {content[:200]}")
        return {"goal": "", "steps": []}

    return validate_plan(data)
