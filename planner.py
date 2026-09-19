"""
JARVIS task planner - converts user requests into tool calls.
"""
import ast
import json
import re
from typing import Any, Dict, List, Optional

import config
from model_manager import ModelManager
from logger import logger

MODEL_MANAGER = ModelManager()
PLANNER_MODEL = MODEL_MANAGER.planner_model

# ==========================================================
# Available Tools
# ==========================================================

AVAILABLE_TOOLS: Dict[str, str] = {
    "browser_connect": "Connect to the JARVIS-controlled Chrome browser.",
    "browser_search_google": "Search Google using the controlled browser.",
    "browser_search_bing": "Search Bing using the controlled browser.",
    "browser_click_first_bing_result": "Click the first Bing search result in the controlled browser.",
    "browser_goto": "Navigate the controlled browser to a URL.",
    "browser_page_info": "Read the current browser page title and URL.",
    "browser_page_snapshot": "Read a bounded structured snapshot of the current browser page: title, URL, headings, results, buttons, inputs, links, and cleaned readable text.",
    "browser_click_result": "Click a numbered or last organic Google/YouTube result. Argument is JSON.",
    "browser_back": "Navigate the controlled browser back one page.",
    "browser_find_element": "Find a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_click_element": "Click a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_fill_element": "Fill a browser input by CSS selector, visible text, or ARIA role with optional accessible name. Argument is JSON.",
    "browser_press_key": "Press a keyboard key on a browser element by CSS selector, visible text, or ARIA role with optional accessible name. Argument is JSON.",
    "browser_wait_for_element": "Wait for a browser DOM element to become visible using selector, text, role, or accessible name. Argument is JSON.",
    "browser_extract_text": "Extract text from a browser DOM element selected by selector, text, role, or accessible name. Argument is JSON.",
    "browser_find_text": "Search the readable text of the current browser page for a phrase and return nearby context. Argument is JSON.",
    "browser_click_first_result": "Click the first organic Google or YouTube result through the controlled browser DOM. Argument is JSON.",
    "weather": "Get current weather. argument = location, or empty for default.",
    "current_time": "Get current time. argument = timezone/city, or empty for local.",
    "current_date": "Get today's date. argument = empty.",
    "wait": "Wait N seconds. argument = number of seconds.",
    "open_website": "Open a website in the browser. argument = site name or URL.",
    "search_website": "Search a specific site. argument = 'site|query', e.g. 'youtube|iron man trailer'.",
    "open_program": "Launch a desktop application. argument = program name, e.g. 'notepad', 'chrome'.",
    "system_status": "Report computer and JARVIS subsystem status. argument = empty.",
    "startup_status": "Report whether JARVIS starts with Windows. argument = empty.",
    "enable_startup": "Configure JARVIS to start with Windows. argument = empty.",
    "disable_startup": "Disable JARVIS Windows startup. argument = empty.",
    "task_history": "Report recent JARVIS task history. argument = empty.",
    "create_folder": "Create a folder. argument = folder name.",
    "list_files": "List files in a folder. argument = folder path, or empty for current folder.",
    "find_file": "Search for a file by name. argument = filename.",
    "open_folder": "Open a folder in File Explorer. argument = folder path.",
    "write_file": "Write content to a file. argument = 'filename|||content' format.",
    "read_file": "Read content from a file. argument = filename.",
    "edit_file": "Edit a file by replacing text. argument = 'filename|||old_text|||new_text'.",
    "code_search": "Search project source files for a symbol, string, or error message.",
    "code_test": "Validate project code. argument = JSON such as {\"mode\":\"compile\",\"path\":\"main.py\"} or {\"mode\":\"pytest\",\"path\":\"tests/test_x.py\"}.",
    "code_diagnose": "Run a broader JARVIS project diagnostic pass: Python compilation, available tests, and optional static checks. Argument is JSON.",
    "dev_command": "Run an allowlisted developer command from the JARVIS project root. Argument is JSON such as {\"command\":\"python -m pytest tests/test_x.py -q\",\"timeout\":120}.",
    "code_checkpoint": "Create a safe checkpoint of JARVIS project source files before autonomous edits.",
    "code_restore_checkpoint": "Restore the latest JARVIS source checkpoint after an unsuccessful repair.",
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

    "barehands_state": "Set the Barehands ring state. argument = idle, listening, thinking, or speaking.",
    "barehands_present": "Present a titled message on the Barehands glass board. argument = 'title|||body'.",
    "barehands_add_card": "Add a card to the Barehands glass board. argument = 'title|||body'.",
    "barehands_add_image": "Add an image to the Barehands glass board. argument = 'src|||title|||body'.",
    "barehands_clear": "Clear the Barehands glass board. argument = empty.",
    "barehands_board_state": "Read the current Barehands glass board state. argument = empty.",
}


# Browser tools whose arguments are JSON objects encoded as strings.
JSON_ARGUMENT_TOOLS = {
    "browser_click_result",
    "browser_click_first_result",
    "browser_find_element",
    "browser_click_element",
    "browser_fill_element",
    "browser_press_key",
    "browser_wait_for_element",
    "browser_extract_text",
    "code_diagnose",
    "dev_command",
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
You are JARVIS's task planner â€” an expert software engineer and systems architect.

Your job: convert a user request into a list of tool calls.

If the request needs no tool (a question, chit-chat, opinion,
or something you'd just answer in conversation), return an
empty steps list.

Available tools:

{tool_list}

Rules:

WINDOWS STARTUP AND RUNTIME STATUS:

- Use system_status when the user asks about computer or JARVIS subsystem health.
- Use startup_status when the user asks whether JARVIS starts with Windows.
- Use enable_startup when the user asks JARVIS to start automatically with Windows.
- Use disable_startup when the user asks JARVIS to stop starting with Windows.
- Use task_history when the user asks what JARVIS has recently done.

BAREHANDS TOOL SELECTION:

- jarvis_status is for reporting JARVIS's own internal status or uptime.
- barehands_present is for presenting information on the Barehands glass board.
- If the user asks to show, display, present, put, or place information
  on the Barehands display or glass board, use barehands_present.
- A request to display JARVIS status on Barehands is a display request,
  not a jarvis_status query; use barehands_present rather than jarvis_status.

CODE REPAIR RULES:

When the user asks JARVIS to fix, debug, repair, diagnose, inspect,
refactor, modify, patch, or test software:

1. Treat the request as an actionable task, not ordinary conversation.
2. Inspect the relevant project files before editing.
3. Use code_search to locate symbols, error messages, and likely call sites.
4. Use read_file to inspect the surrounding implementation.
5. Make the smallest targeted change needed.
6. Before modifying project code, create a code_checkpoint.
7. Use code_test after changes. Prefer py_compile for individual Python files,
   and pytest for relevant automated tests.
8. For browser automation in this project, browser_controller.py is the
   primary browser implementation file. Do not invent a filename such as
   browser_automation.py when browser_controller.py is the relevant module.
9. Do not invent file paths. When the target file is uncertain, discover it
   with code_search, list_files, or find_file before reading or modifying it.
10. Do not claim a fix is complete until validation succeeds.
11. If validation fails, inspect the failure, revise the change, and test again.
12. If repeated repair attempts are unsuccessful, use code_restore_checkpoint
    before reporting that the task could not be completed.
13. For multi-step repairs, keep working through the task instead of returning
    code or instructions for the user to apply manually.
14. Treat software work as an iterative engineering loop: inspect, diagnose,
    plan the smallest safe change, checkpoint, modify, validate, inspect failures,
    and repeat until the requested behavior is verified.
15. When the user asks JARVIS to diagnose or repair itself, prefer
    code_diagnose first when the failure or target is not already known.
16. Use validation output as evidence. Never replace a failing implementation
    with a guessed fix without reading the relevant source and understanding the
    failure.
17. For code creation, do not stop after writing files. Run an appropriate
    validation step and repair the generated implementation when validation fails.
18. Use dev_command only for controlled development operations when the
existing file/search/test tools cannot perform the required step. Never use
shell operators, pipes, or command chaining; pass one developer command.

INTERNAL PHASE OVERRIDES:

JARVIS may prepend an internal phase marker to a planning request. When one is
present, it is authoritative and overrides generic planning preferences:

- [JARVIS_INTERNAL_PHASE:SOURCE_READ]
  Return a minimal inspection plan containing read_file for the verified target.
  Do not edit files and do not add unrelated discovery steps.

- [JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]
  Return a minimal diagnostic plan containing code_diagnose for the verified
  target. Do not use code_test instead. Do not edit files. Prefer a narrow
  targeted diagnostic argument such as:
  {{"path":"target.py","run_tests":false,"run_lint":false,"run_types":false}}

- [JARVIS_INTERNAL_PHASE:REPAIR]
  Use the verified evidence supplied in the request. Return the smallest safe
  repair plan with code_checkpoint before mutation and code_test after mutation.
  Do not repeat generic discovery unless the evidence explicitly shows that
  another focused source read is required.
  For edit_file, the argument MUST be exactly:
  filename|||old_text|||new_text
  Use three literal pipe characters between all three fields. Never use ||
  between old_text and new_text.

DEVELOPER COMMAND RULES:

- Use dev_command for dependency installation, targeted test execution,
  static-analysis commands, or other necessary developer tooling.
- Prefer the active JARVIS Python interpreter for Python and pip commands.
- Keep commands project-scoped and do not use shell chaining.
- Treat command output as evidence for subsequent repair decisions.

AUTONOMOUS SOFTWARE ENGINEERING LOOP:

For coding, debugging, repair, and self-diagnosis tasks, JARVIS should
behave like a careful senior engineer working directly in the project:

1. Discover the real project files and relevant symbols.
2. Run the narrowest useful diagnostic first.
3. Read the exact source involved in the failure.
4. Form a concrete hypothesis from the evidence.
5. Create a checkpoint before modifying source.
6. Apply the smallest targeted change.
7. Re-run focused tests, then broader validation when appropriate.
8. If validation fails, treat the failure output as new evidence and iterate.
9. Stop only when the requested behavior is verified, or when the evidence
   shows that the problem cannot be safely completed.

GENERIC BROWSER DOM RULES:

When controlling a browser, prefer browser_* DOM tools over
screen-coordinate tools whenever the target can be located in
the page DOM.

Browser workflow:

1. Navigate to the intended page.
2. Inspect the page with browser_page_info or browser_find_element.
3. For semantic controls, prefer ARIA role plus accessible name, for example
   {{"role":"button","name":"Sign in"}} or {{"role":"textbox","name":"Email"}}.
4. Use browser_fill_element for text inputs.
5. Use browser_press_key for Enter or other keyboard actions.
6. Use browser_click_element for links, buttons, tabs, menus, and controls.
7. Use browser_wait_for_element when content may load asynchronously.
8. Use browser_extract_text or browser_page_info to verify the result.
9. Use browser_click_result for second, third, or last search results.
10. Use browser_back for requests to go back to the previous page.
11. When an action fails, use the browser state and observations to
   choose a different strategy during replanning.

DOM TOOL ARGUMENT FORMAT:

DOM browser tools use a JSON object encoded as the step's argument string.
Supported target fields are selector, text, role, and optional name.
"name" is an accessible-name filter used with "role".

Examples:

browser_find_element
argument = {{"role":"searchbox"}}

browser_find_element
argument = {{"role":"button","name":"Sign in"}}

browser_find_element
argument = {{"text":"Sign in"}}

browser_find_element
argument = {{"selector":"button[type=submit]"}}

browser_fill_element
argument = {{"role":"searchbox","value":"Iron Man trailer"}}

browser_press_key
argument = {{"role":"searchbox","key":"Enter"}}

browser_click_element
argument = {{"role":"button","name":"Submit"}}

browser_wait_for_element
argument = {{"role":"heading","name":"Results","timeout":10000}}

browser_extract_text
argument = {{"selector":"main"}}

Browser rules:

- Every DOM tool argument MUST be valid JSON.
- Prefer ARIA roles and visible text over fragile CSS selectors.
- Do not invent CSS selectors when a stable semantic target exists.
- Do not use screen coordinates for browser interaction when a DOM
  action can perform the same operation.
- Keep browser actions atomic: one action per step.
- Do not assume a click succeeded; verify the resulting state.
- Use browser_page_info after important navigation or interactions.
- Use browser_extract_text when page contents must be inspected.
- Use browser_find_element before acting when element existence is uncertain.
- Use browser_wait_for_element when the page may still be loading.
- Use the specialized Bing/YouTube browser tools when their deterministic
  behavior is clearly more reliable.
- Do not combine multiple DOM operations into one step.

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
What's the weather in Belvidere, IL?

Output:
{{
"goal": "check weather",
"steps": [
  {{"tool": "weather", "argument": "Belvidere, IL"}}
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

CRITICAL: Requests to tell a story, joke, or share creative content are CONVERSATIONAL â€” return an empty steps list. JARVIS generates creative content directly, it does not search the web for stories. Examples that should return empty steps:
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
# Planner Quality Gates
# ==========================================================

CODE_REPAIR_TERMS = (
    "fix",
    "repair",
    "refactor",
    "modify",
    "patch",
    "resolve",
    "broken",
    "not working",
    "doesn't work",
    "doesnt work",
    "self-heal",
    "self heal",
)

CODE_DIAGNOSTIC_TERMS = (
    "debug",
    "diagnose",
    "inspect",
    "investigate",
    "test",
    "broken",
    "not working",
    "doesn't work",
    "doesnt work",
    "crash",
    "crashed",
    "failure",
)

SOFTWARE_DOMAIN_TERMS = (
    "code",
    "script",
    "software",
    "jarvis",
    "runtime",
    "project",
    "automation",
    "browser",
    "python",
    "javascript",
    "program",
    "bug",
    "error",
    "exception",
    "traceback",
    "module",
    "repository",
    "codebase",
    "app",
    "application",
    "website",
    "game",
    ".py",
    ".js",
)

SOFTWARE_CHANGE_DOMAIN_TERMS = SOFTWARE_DOMAIN_TERMS + (
    "function",
    "capability",
)

CODE_INSPECTION_TOOLS = {
    "code_search",
    "code_diagnose",
    "read_file",
    "list_files",
    "find_file",
}

CODE_MUTATION_TOOLS = {
    "write_file",
    "edit_file",
    "delete_file",
}


def _normalized_words(text: str) -> str:
    return " ".join(
        str(text or "").strip().lower().split()
    )


def is_explicit_self_repair_request(text: str) -> bool:
    """Return True only when the request targets JARVIS's own code and asks for a repair."""
    normalized = _normalized_words(text)

    self_directed = any(
        phrase in normalized
        for phrase in (
            "fix yourself",
            "repair yourself",
            "diagnose yourself",
            "self diagnose",
            "self-diagnose",
            "run a full diagnostic on yourself",
            "run a full diagnostic on your own code",
            "audit yourself",
            "audit your own code",
            "find bugs in your own code",
            "check yourself for bugs",
            "check your own code",
            "inspect your own code",
        )
    )

    repair_requested = any(
        term in normalized
        for term in CODE_REPAIR_TERMS
    )

    return self_directed and repair_requested


def is_software_repair_request(text: str) -> bool:
    normalized = _normalized_words(text)

    explicit_self_repair = any(
        phrase in normalized
        for phrase in (
            "fix yourself",
            "repair yourself",
            "self diagnose and fix",
            "self-diagnose and fix",
            "diagnose yourself and fix",
            "diagnose yourself and repair",
            "run a full diagnostic on yourself and fix",
            "run a full diagnostic on yourself and repair",
            "audit yourself and fix",
            "audit your own code and fix",
            "find bugs in your own code and fix",
            "check your own code and fix",
            "fix your own code",
            "repair your own code",
        )
    )

    explicit_self_diagnostic_repair = (
        any(
            phrase in normalized
            for phrase in (
                "diagnose yourself",
                "self diagnose",
                "self-diagnose",
                "run a full diagnostic on yourself",
                "run a full diagnostic on your own code",
                "audit yourself",
                "audit your own code",
                "check yourself for bugs",
                "check your own code",
                "inspect your own code",
                "find bugs in your own code",
            )
        )
        and any(
            term in normalized
            for term in CODE_REPAIR_TERMS
        )
    )

    return explicit_self_repair or explicit_self_diagnostic_repair or (
        any(term in normalized for term in CODE_REPAIR_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def is_software_diagnostic_request(text: str) -> bool:
    normalized = _normalized_words(text)

    explicit_self_diagnostic = any(
        phrase in normalized
        for phrase in (
            "diagnose yourself",
            "self diagnose",
            "self-diagnose",
            "run a full diagnostic on yourself",
            "run a full diagnostic on your own code",
            "audit yourself",
            "audit your own code",
            "check yourself for bugs",
            "check your own code",
            "inspect your own code",
            "find bugs in your own code",
        )
    )

    return explicit_self_diagnostic or (
        any(term in normalized for term in CODE_DIAGNOSTIC_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def is_software_change_request(text: str) -> bool:
    """Return True for software feature/change work that should be validated."""
    normalized = _normalized_words(text)

    change_terms = (
        "add",
        "implement",
        "integrate",
        "enhance",
        "improve",
        "upgrade",
        "introduce",
        "enable",
        "support",
        "build",
        "create",
        "make",
        "write",
        "generate",
        "change",
    )

    explicit_self_change = any(
        phrase in normalized
        for phrase in (
            "change your own code",
            "modify your own code",
            "improve yourself",
            "add a feature to yourself",
            "add a feature to jarvis",
            "add a function to jarvis",
        )
    )

    return explicit_self_change or (
        any(term in normalized for term in change_terms)
        and any(term in normalized for term in SOFTWARE_CHANGE_DOMAIN_TERMS)
    )


def assess_plan(
    user_command: str,
    plan: Dict[str, Any],
    require_modification: Optional[bool] = None,
    require_code_read: bool = False,
    require_code_test: bool = False,
    require_code_diagnose: bool = False,
    allow_prior_evidence: bool = False,
) -> List[str]:
    """
    Return planner-quality issues for code/automation repair tasks.

    These are pre-execution guardrails: an incomplete candidate plan is
    rejected and given one chance to be repaired by the planner.
    """
    steps = (
        plan.get("steps", [])
        if isinstance(plan, dict)
        else []
    )

    if not (
        is_software_diagnostic_request(user_command)
        or is_software_change_request(user_command)
        or is_software_repair_request(user_command)
    ):
        return []

    if require_modification is None:
        require_modification = is_software_repair_request(
            user_command
        )

    tool_names = [
        str(
            step.get("tool", "")
            or ""
        ).strip()
        for step in steps
        if isinstance(step, dict)
    ]

    issues: List[str] = []

    inspection_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool in CODE_INSPECTION_TOOLS
        ),
        None,
    )

    mutation_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in CODE_MUTATION_TOOLS
    ]

    # Validate edit_file's three-part wire format before execution.
    # The executor expects: filename|||old_text|||new_text.
    for step in steps:
        if not isinstance(step, dict):
            continue

        if str(step.get("tool", "") or "").strip() != "edit_file":
            continue

        argument = str(step.get("argument", "") or "")
        parts = argument.split("|||", 2)

        if len(parts) != 3 or any(not part for part in parts):
            issues.append(
                "edit_file arguments must use exactly "
                "filename|||old_text|||new_text with three non-empty parts. "
                "Do not use || between old_text and new_text."
            )

    checkpoint_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool == "code_checkpoint"
        ),
        None,
    )

    test_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in {"code_test", "code_diagnose"}
    ]

    # --------------------------------------------------------
    # File-target sanity checks for diagnostic/repair plans.
    # --------------------------------------------------------
    # A planner hallucinating a source filename is worse than returning
    # an incomplete plan: it causes an avoidable execution failure and can
    # contaminate the repair evidence. Reject nonexistent read/edit targets
    # before execution and give the planner a concrete correction.
    # --------------------------------------------------------
    import ast
    from pathlib import Path

    base = Path.cwd().resolve()
    protected_parts = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "jarvis_cuda",
        "venv",
        ".venv",
        "node_modules",
        "build",
        "dist",
        ".jarvis_checkpoints",
    }

    for step in steps:
        if not isinstance(step, dict):
            continue

        tool = str(step.get("tool", "") or "").strip()
        argument = str(step.get("argument", "") or "").strip()

        target = ""
        if tool == "read_file":
            target = argument
        elif tool in {"edit_file", "delete_file", "write_file"}:
            target = argument.split("|||", 1)[0].strip()
        elif tool == "code_test":
            try:
                payload = json.loads(argument)
                if not isinstance(payload, dict):
                    payload = ast.literal_eval(argument)
                if isinstance(payload, dict):
                    target = str(payload.get("path", "") or "").strip()
            except (json.JSONDecodeError, ValueError, SyntaxError):
                target = ""

        if not target or tool == "write_file":
            continue

        candidate = (base / target).resolve()

        try:
            relative_candidate = candidate.relative_to(base)
        except ValueError:
            issues.append(
                f"The {tool} target must stay inside the project: {target}"
            )
            continue

        if any(
            part.lower() in protected_parts
            for part in relative_candidate.parts
        ):
            issues.append(
                f"The {tool} target points to an internal/generated path: "
                f"{target}. Use the actual project source file instead."
            )
            continue

        if not candidate.exists():
            issues.append(
                f"The planner referenced a nonexistent {tool} target: {target}. "
                "Do not invent filenames; use the actual discovered project file."
            )

    request_lower = str(user_command or "").lower()

    if (
        "browser" in request_lower
        and "automation" in request_lower
    ):
        for step in steps:
            if not isinstance(step, dict):
                continue

            tool = str(step.get("tool", "") or "").strip()
            argument = str(step.get("argument", "") or "").strip()

            if tool not in {
                "read_file",
                "edit_file",
                "delete_file",
                "code_test",
            }:
                continue

            if "browser_automation.py" in argument.lower():
                issues.append(
                    "For browser automation in this project, use the existing "
                    "browser_controller.py target. browser_automation.py does not exist."
                )

    # A standalone diagnostic-test phase is intentionally allowed to
    # operate on already-verified source evidence. The runtime controller
    # uses this phase only after source inspection has completed, so requiring
    # another inspection tool here would reject the diagnostic plan itself.
    if (
        inspection_index is None
        and not allow_prior_evidence
        and not require_code_test
    ):
        issues.append(
            "The repair plan must inspect the relevant project code "
            "before attempting to fix it."
        )

    read_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool == "read_file"
        ),
        None,
    )

    if require_code_read and read_index is None and not allow_prior_evidence:
        issues.append(
            "The next investigation phase must read the actual relevant "
            "source file with read_file before choosing a code change."
        )

    if require_code_test and not test_indices:
        issues.append(
            "The next diagnostic phase must run code_test so the "
            "implementation can be validated before deciding whether to edit."
        )

    if require_code_diagnose:
        diagnose_indices = [
            index
            for index, tool in enumerate(tool_names)
            if tool == "code_diagnose"
        ]

        if not diagnose_indices:
            issues.append(
                "The required diagnostic phase must run code_diagnose "
                "against the verified target before any repair decision."
            )

    # Browser automation needs a behavioral smoke test, not only a syntax
    # check. Once browser automation is the active repair domain, require the
    # dedicated browser_smoke mode so the planner cannot satisfy the gate
    # with a meaningless compile-only validation.
    request_lower = str(user_command or "").lower()
    if (
        require_code_test
        and "browser" in request_lower
        and "automation" in request_lower
        and test_indices
    ):
        browser_smoke_present = False

        for step in steps:
            if not isinstance(step, dict):
                continue

            if str(step.get("tool", "") or "").strip() != "code_test":
                continue

            argument = str(step.get("argument", "") or "").strip()

            try:
                payload = json.loads(argument)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            if (
                isinstance(payload, dict)
                and str(payload.get("mode", "") or "").strip().lower()
                in {"browser_smoke", "browser_self_test"}
            ):
                browser_smoke_present = True
                break

        if not browser_smoke_present:
            issues.append(
                "Browser automation diagnostics must use code_test with "
                'mode "browser_smoke" before any repair decision.'
            )

    requires_modification = bool(require_modification)

    if requires_modification and not mutation_indices:
        issues.append(
            "This request explicitly asks for a fix or code change. "
            "The plan must include an appropriate file modification step."
        )

    if mutation_indices:
        first_mutation = min(mutation_indices)

        if (
            not allow_prior_evidence
            and (
                inspection_index is None
                or inspection_index > first_mutation
            )
        ):
            issues.append(
                "Inspection must occur before the first file modification."
            )

        if checkpoint_index is None or checkpoint_index > first_mutation:
            issues.append(
                "A code_checkpoint must occur before autonomous "
                "file modification work."
            )

        if not test_indices or max(test_indices) < max(mutation_indices):
            issues.append(
                "The repair plan must run code_test after the final file "
                "modification."
            )
    elif requires_modification and not test_indices:
        issues.append(
            "A software repair plan must include code_test so the result "
            "can be validated."
        )

    return issues


# ==========================================================
# Project File Target Resolution
# ==========================================================

def _normalized_filename_key(value: str) -> str:
    """Normalize a filename so voice-transcribed punctuation is ignored."""
    import re

    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _resolve_project_file_target(target: str, base) -> Optional[str]:
    """Resolve an existing project file when punctuation/underscores were lost.

    Resolution is conservative: a correction is returned only when exactly one
    project file has the same normalized filename (or normalized relative path).
    """
    from pathlib import Path

    raw = str(target or "").strip().strip('"').strip("'")
    if not raw:
        return None

    base = Path(base).resolve()
    direct = (base / raw).resolve()
    try:
        direct.relative_to(base)
    except ValueError:
        return None

    if direct.exists() and direct.is_file():
        return direct.relative_to(base).as_posix()

    ignored = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "jarvis_cuda",
        "venv",
        ".venv",
        "node_modules",
        "build",
        "dist",
    }

    target_key = _normalized_filename_key(raw)
    target_parts = [
        _normalized_filename_key(part)
        for part in Path(raw).parts
        if part not in {".", ""}
    ]

    matches = []
    try:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignored for part in path.parts):
                continue

            relative = path.relative_to(base)
            name_key = _normalized_filename_key(path.name)
            relative_parts = [
                _normalized_filename_key(part)
                for part in relative.parts
            ]

            if name_key == target_key or relative_parts == target_parts:
                matches.append(relative.as_posix())
                if len(matches) > 1:
                    break
    except OSError:
        return None

    return matches[0] if len(matches) == 1 else None


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

        normalized_argument = (
            str(argument) if argument is not None else ""
        )

        # LLMs occasionally emit Python-literal dictionaries such as
        # {'role': 'button'} instead of strict JSON. Canonicalize browser
        # object arguments at the planner boundary so every downstream
        # browser dispatcher receives one stable JSON representation.
        if tool in JSON_ARGUMENT_TOOLS and normalized_argument.strip():
            raw_argument = normalized_argument.strip()
            try:
                payload = json.loads(raw_argument)
            except json.JSONDecodeError as json_exc:
                try:
                    payload = ast.literal_eval(raw_argument)
                except (ValueError, SyntaxError):
                    logger.warning(
                        f"Rejected invalid browser argument for {tool}: {json_exc}"
                    )
                    continue

            if not isinstance(payload, dict):
                logger.warning(
                    f"Rejected non-object browser argument for {tool}"
                )
                continue

            try:
                normalized_argument = json.dumps(
                    payload,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    f"Rejected non-JSON browser argument for {tool}: {exc}"
                )
                continue

        # Discard hallucinated source-read steps before execution when the
        # planner also supplied other usable steps. A bad read target should
        # never be allowed to turn a valid investigation into a tool failure.
        if tool == "read_file" and normalized_argument.strip():
            from pathlib import Path

            candidate = (Path.cwd().resolve() / normalized_argument.strip()).resolve()

            try:
                candidate.relative_to(Path.cwd().resolve())
            except ValueError:
                logger.warning(
                    f"Rejected read_file target outside project: {normalized_argument}"
                )
                continue

            if not candidate.exists():
                resolved = _resolve_project_file_target(
                    normalized_argument,
                    Path.cwd().resolve(),
                )
                if resolved:
                    logger.info(
                        "Resolved probable voice-transcribed file path "
                        f"{normalized_argument!r} -> {resolved!r}"
                    )
                    normalized_argument = resolved
                else:
                    logger.warning(
                        f"Rejected nonexistent read_file target: {normalized_argument}"
                    )
                    continue

        clean.append({
            "tool": str(tool),
            "argument": normalized_argument,
        })

    validated_plan = {
        "goal": plan.get("goal", ""),
        "steps": clean,
    }

    # Preserve orchestration metadata that is not an executable step. Agent
    # Core uses this marker to keep deterministic internal phases silent.
    if plan.get("jarvis_internal_phase"):
        validated_plan["jarvis_internal_phase"] = True

    if "resolved_command" in plan:
        validated_plan["resolved_command"] = str(
            plan.get("resolved_command") or ""
        )

    return validated_plan


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

    # ========================================================
    # DETERMINISTIC FIRST-RESULT ROUTER
    # ========================================================
    #
    # When a previous search established a website and query,
    # commands such as:
    #
    #   Click the first result
    #
    # should NOT be left to the language model.
    #
    # Google:
    #   click the first organic Google result for QUERY
    #
    # YouTube:
    #   click the first organic YouTube result for QUERY
    #
    # This creates a normal planner result so the rest of the
    # existing execution pipeline remains unchanged.
    # ========================================================

    normalized_command = (
        user_command
        .strip()
        .lower()
        .rstrip(".,!?")
    )

    normalized_command = " ".join(
        normalized_command.split()
    )

    first_result_phrases = {
        "click the first result",
        "click first result",
        "click on the first result",
        "click on first result",

        "click the first browser result",
        "click first browser result",
        "click the first browser result on google",
        "click first browser result on google",
        "click the first browser result on youtube",
        "click first browser result on youtube",

        "open the first result",
        "open first result",
        "open the first browser result",
        "open first browser result",
        "open the first browser result on google",
        "open first browser result on google",
        "open the first browser result on youtube",
        "open first browser result on youtube",

        "play the first result",
        "play first result",

        "click the first video",
        "click first video",
        "click on the first video",
        "click on first video",

        "open the first video",
        "open first video",

        "play the first video",
        "play first video",

        "click the first link",
        "click first link",
        "click on the first link",
        "click on first link",

        "open the first link",
        "open first link",

        "click the first one",
        "click first one",
        "click on the first one",
        "click on first one",

        "open the first one",
        "open first one",
    }

    if (
        normalized_command in first_result_phrases
        and active_context
    ):
        active_site = str(
            active_context.get("site", "") or ""
        ).strip().lower()

        active_query = str(
            active_context.get("last_query", "") or ""
        ).strip()

        if (
            active_site in {
                "google",
                "youtube",
            }
            and active_query
        ):
            if active_site == "google":
                resolved_command = (
                    "click the first organic Google result for "
                    + active_query
                )

                print(
                    "JARVIS planner:"
                )

                print(
                    f"  Original: {user_command}"
                )

                print(
                    f"  Context site: Google"
                )

                print(
                    f"  Context query: {active_query}"
                )

                print(
                    f"  Resolved: {resolved_command}"
                )

                return {
                    "goal": "click first Google result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": "google",
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

            if active_site == "youtube":
                resolved_command = (
                    "click the first organic YouTube result for "
                    + active_query
                )

                print(
                    "JARVIS planner:"
                )

                print(
                    f"  Original: {user_command}"
                )

                print(
                    f"  Context site: YouTube"
                )

                print(
                    f"  Context query: {active_query}"
                )

                print(
                    f"  Resolved: {resolved_command}"
                )

                return {
                    "goal": "click first YouTube result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": "youtube",
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

    # ========================================================
    # DETERMINISTIC BROWSER READ ROUTER
    # ========================================================
    if normalized_command in {
        "read the current browser page",
        "read current browser page",
        "read this page",
        "read the page",
        "read page",
        "read the page text",
        "show this page",
    }:
        return {
            "goal": "read current browser page",
            "steps": [
                {
                    "tool": "browser_extract_text",
                    "argument": json.dumps({
                        "selector": "body",
                    }),
                }
            ],
            "resolved_command": "read the current browser page",
        }

    if normalized_command in {
        "inspect the current browser page",
        "read the current browser title",
        "read the page title",
        "inspect the page title",
    }:
        return {
            "goal": "inspect current browser page",
            "steps": [
                {
                    "tool": "browser_page_info",
                    "argument": "",
                }
            ],
            "resolved_command": "inspect the current browser page",
        }

    # ========================================================
    # ========================================================
    # DETERMINISTIC ORDINAL BROWSER RESULT ROUTER
    # ========================================================
    #
    # Context resolution can produce canonical browser phrases such as:
    #   click the second browser result on google
    #   click the last browser result on youtube
    #
    # These are execution-safe browser actions and should never be handed
    # back to the LLM planner. Use the active browser context for the site
    # and search query so the action stays on the current search.
    # ========================================================

    browser_result_match = re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"(?:the\s+)?"
        r"(first|top|second|third|last|final)\s+"
        r"(?:browser\s+)?"
        r"(?:result|link|video|one|item)"
        r"(?:\s+on\s+([a-z0-9.-]+))?$",
        normalized_command,
        re.IGNORECASE,
    )

    if browser_result_match and active_context:
        ordinal = browser_result_match.group(1).lower()
        explicit_site = (
            browser_result_match.group(2) or ""
        ).strip().lower()

        active_site = str(
            active_context.get("site", "") or ""
        ).strip().lower()

        active_query = str(
            active_context.get("last_query", "") or ""
        ).strip()

        site = explicit_site or active_site

        if site in {"google", "youtube"} and active_query:
            if ordinal in {"first", "top"}:
                resolved_command = (
                    f"click the first browser result on {site}"
                )
                return {
                    "goal": f"click first {site} result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": site,
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

            index = {
                "second": 2,
                "third": 3,
                "last": "last",
                "final": "last",
            }.get(ordinal)

            if index is not None:
                resolved_command = (
                    f"click the {ordinal} browser result on {site}"
                )
                return {
                    "goal": f"click {ordinal} {site} result",
                    "steps": [
                        {
                            "tool": "browser_click_result",
                            "argument": json.dumps({
                                "index": index,
                                "site": site,
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

    # ========================================================
    # DETERMINISTIC SELECTED-RESULT REOPEN ROUTER
    # ========================================================
    if normalized_command in {
        "open the previously selected browser result",
        "open the previously selected result",
    } and active_context:
        selected_url = str(
            active_context.get("last_result_url", "") or ""
        ).strip()

        if selected_url:
            return {
                "goal": "reopen previously selected browser result",
                "steps": [
                    {
                        "tool": "browser_goto",
                        "argument": selected_url,
                    }
                ],
                "resolved_command": normalized_command,
            }

    # ========================================================
    # DETERMINISTIC BROWSER ELEMENT REFERENCE ROUTER
    # ========================================================
    #
    # The context resolver can resolve phrases such as "click it" to:
    #   click the browser element with visible text '...'
    #
    # Keep that path model-free so a selected browser result does not
    # fall back to the LLM planner or screen vision.
    # ========================================================

    visible_text_match = re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"the\s+browser\s+element\s+with\s+visible\s+text\s+"
        r"(?P<quoted>['\"].+['\"])$",
        user_command.strip(),
        re.IGNORECASE,
    )

    if visible_text_match:
        try:
            visible_text = ast.literal_eval(
                visible_text_match.group("quoted")
            )
        except (SyntaxError, ValueError):
            visible_text = ""

        if isinstance(visible_text, str) and visible_text.strip():
            return {
                "goal": "click referenced browser element",
                "steps": [
                    {
                        "tool": "browser_click_element",
                        "argument": json.dumps({
                            "text": visible_text.strip(),
                        }),
                    }
                ],
                "resolved_command": user_command.strip(),
            }

    # ========================================================
    # DETERMINISTIC BAREHANDS DISPLAY ROUTER
    # ========================================================
    #
    # Display requests should never depend on the planner model choosing
    # between jarvis_status and a Barehands presentation tool. The user
    # explicitly asked for a display action, so route it directly.
    # ========================================================

    if (
        "barehands" in normalized_command
        and (
            "display" in normalized_command
            or "glass board" in normalized_command
            or "show" in normalized_command
            or "present" in normalized_command
            or "put" in normalized_command
            or "place" in normalized_command
        )
        and "status" in normalized_command
        and (
            "card" in normalized_command
            or "status" in normalized_command
        )
    ):
        return {
            "goal": "show JARVIS status on Barehands",
            "steps": [
                {
                    "tool": "barehands_present",
                    "argument": (
                        "JARVIS Status|||"
                        "JARVIS status requested on the Barehands display."
                    ),
                }
            ],
        }

    context_str = ""
    if active_context:
        context_str = f"""

Active task context:
Website: {active_context.get('site', 'none')}
Search query: {active_context.get('last_query', 'none')}
Last tool: {active_context.get('last_tool', 'none')}
"""

    history_str = f"\nRecent conversation:\n{history_text}" if history_text else ""

    # --------------------------------------------------------
    # Focused autonomous phase prompts
    # --------------------------------------------------------
    # Agent Core prefixes internal phase markers so intermediate
    # investigation/test planning cannot accidentally enter repair mode.
    # Only the final repair phase uses the coding model.
    # --------------------------------------------------------
    is_repair_phase = "[JARVIS_INTERNAL_PHASE:REPAIR]" in user_command
    is_source_read_phase = "[JARVIS_INTERNAL_PHASE:SOURCE_READ]" in user_command
    is_diagnostic_test_phase = "[JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]" in user_command

    if is_repair_phase:
        repair_tools = {
            name: AVAILABLE_TOOLS[name]
            for name in (
                "code_checkpoint",
                "edit_file",
                "write_file",
                "delete_file",
                "code_test",
                "read_file",
            )
        }

        repair_tool_list = "\n".join(
            f"{name}: {desc}"
            for name, desc in repair_tools.items()
        )

        system_content = f"""You are JARVIS's focused software repair planner.

The investigation is complete. The user message contains verified source and
diagnostic evidence from the real project.

Available tools:
{repair_tool_list}

REPAIR HANDOFF MODE — HIGH PRIORITY:

Rules:
- Make ONE evidence-supported repair; do not rediscover the project.
- Use the existing verified target file.
- Prefer edit_file for existing source:
  filename|||old_text|||new_text
- Copy old_text exactly from the verified source evidence.
- Create code_checkpoint before any mutation.
- Run code_test after the final mutation.
- Use read_file only when the supplied evidence does not contain enough source
  to make the repair safely.
- Do not invent filenames, code, errors, or behavior.
- Return executable JSON only. Never return prose or an empty plan.

Required shape:
{{
  "goal": "brief repair goal",
  "steps": [
    {{"tool": "code_checkpoint", "argument": ""}},
    {{"tool": "edit_file", "argument": "existing_file.py|||exact old source|||exact new source"}},
    {{"tool": "code_test", "argument": "{{\"mode\":\"compile\",\"path\":\"existing_file.py\"}}"}}
  ]
}}

The final step must validate the changed target. Return ONLY JSON.
"""
    elif is_source_read_phase:
        system_content = f"""You are JARVIS's focused source-inspection planner.

The project discovery phase is complete. Verified evidence is included in
the user message. You must inspect the actual existing source before any
repair is planned.

Do NOT modify files.
Do NOT use list_files.
Do NOT perform broad project-wide discovery when the evidence already names
the target.
Prefer exactly one read_file step for the verified target source file.
Do not invent filenames.

Return ONLY valid JSON with goal and steps. Every argument must be a string.
"""

    elif is_diagnostic_test_phase:
        system_content = f"""You are JARVIS's focused diagnostic test planner.

The relevant source file has already been inspected. Verified evidence is
included in the user message. Run a targeted diagnostic against the existing
implementation before any repair is planned.

Do NOT modify files.
Do NOT use list_files.
Do NOT perform broad rediscovery.
Prefer exactly one code_diagnose step for the verified target.
Use a narrow JSON argument such as:
{{"path":"target.py","run_tests":false,"run_lint":false,"run_types":false}}
Do not invent filenames.

Return ONLY valid JSON with goal and steps. Every argument must be a string.
"""

    else:
        system_content = _planner_prompt() + context_str + history_str

    messages = [
        {
            "role": "system",
            "content": system_content
        },
        {
            "role": "user",
            "content": user_command
        }
    ]

    import time

    try:
        print("JARVIS DEBUG: planner -> calling Ollama", flush=True)
        planner_start = time.perf_counter()

        planner_model = (
            MODEL_MANAGER.coding_model
            if is_repair_phase
            else PLANNER_MODEL
        )

        if is_repair_phase:
            print(
                f"JARVIS DEBUG: repair planner -> using {planner_model}",
                flush=True,
            )

        repair_options = (
            {
                "temperature": 0,
                "num_predict": 240,
                "num_ctx": config.CODING_NUM_CTX,
            }
            if is_repair_phase
            else None
        )

        if is_repair_phase:
            response = MODEL_MANAGER.coding(
                messages,
                format="json",
                options=repair_options,
                model=planner_model,
            )
        else:
            response = MODEL_MANAGER.planner(messages, format="json")

        elapsed = time.perf_counter() - planner_start

        print(
            f"JARVIS DEBUG: Ollama returned after "
            f"{elapsed:.3f}s",
            flush=True
        )

        # Ollama reports the major latency components on ChatResponse. Keep
        # these metrics in the debug log so cold-load time is distinguishable
        # from prompt evaluation and token generation time.
        if is_repair_phase:
            def _seconds_from_ns(name: str):
                try:
                    value = getattr(response, name, None)
                    if value is None:
                        return None
                    return float(value) / 1_000_000_000.0
                except (TypeError, ValueError):
                    return None

            metric_parts = []
            for name, label in (
                ("load_duration", "load"),
                ("prompt_eval_duration", "prompt_eval"),
                ("eval_duration", "generation"),
            ):
                seconds = _seconds_from_ns(name)
                if seconds is not None:
                    metric_parts.append(f"{label}={seconds:.3f}s")

            if metric_parts:
                print(
                    "JARVIS DEBUG: repair latency breakdown: "
                    + " | ".join(metric_parts),
                    flush=True,
                )

            for name, label in (
                ("prompt_eval_count", "prompt_tokens"),
                ("eval_count", "generated_tokens"),
            ):
                try:
                    value = getattr(response, name, None)
                    if value is not None:
                        print(
                            f"JARVIS DEBUG: repair {label}={value}",
                            flush=True,
                        )
                except Exception:
                    pass

        print(
            f"JARVIS DEBUG: response type={type(response).__name__}",
            flush=True
        )

    except Exception as e:
        logger.error(f"Planner LLM call failed: {e}")

        if is_repair_phase:
            fallback_model = MODEL_MANAGER.coding_fallback_model
            if fallback_model and fallback_model != planner_model:
                logger.warning(
                    "JARVIS DEBUG: primary coding planner failed; "
                    f"falling back to {fallback_model}"
                )
                try:
                    fallback_response = MODEL_MANAGER.coding(
                        messages,
                        format="json",
                        options={
                            "temperature": 0,
                            "num_predict": 240,
                            "num_ctx": config.CODING_NUM_CTX,
                        },
                        model=fallback_model,
                    )
                    fallback_content = (
                        fallback_response
                        .get("message", {})
                        .get("content", "")
                    )
                    fallback_data = extract_json(fallback_content)

                    if fallback_data:
                        validated_fallback = validate_plan(fallback_data)
                        if validated_fallback.get("steps"):
                            logger.info(
                                "JARVIS DEBUG: coding fallback planner "
                                "recovered a valid plan."
                            )
                            return validated_fallback
                except Exception as fallback_exc:
                    logger.error(
                        f"Coding fallback planner failed: {fallback_exc}"
                    )

        return {"goal": "", "steps": []}

    print("JARVIS DEBUG: extracting message content", flush=True)

    content = response.get("message", {}).get("content", "")

    print(
        f"JARVIS DEBUG: content length={len(content)}",
        flush=True
    )

    print("JARVIS DEBUG: calling extract_json()", flush=True)

    data = extract_json(content)

    print(
        f"JARVIS DEBUG: extract_json returned "
        f"type={type(data).__name__}",
        flush=True
    )

    if not data:
        logger.warning(f"Planner returned invalid JSON: {content[:200]}")

        if is_repair_phase:
            fallback_model = MODEL_MANAGER.coding_fallback_model
            if fallback_model and fallback_model != planner_model:
                logger.warning(
                    "JARVIS DEBUG: primary coding planner returned invalid "
                    f"output; falling back to {fallback_model}"
                )
                try:
                    fallback_response = chat(
                        model=fallback_model,
                        messages=messages,
                        format="json",
                        options={
                            "temperature": 0,
                            "num_predict": 240,
                            "num_ctx": config.CODING_NUM_CTX,
                        },
                        keep_alive=config.CODING_MODEL_KEEP_ALIVE,
                    )
                    fallback_content = (
                        fallback_response
                        .get("message", {})
                        .get("content", "")
                    )
                    fallback_data = extract_json(fallback_content)

                    if fallback_data:
                        logger.info(
                            "JARVIS DEBUG: coding fallback planner "
                            "returned a valid plan."
                        )
                        validated_fallback = validate_plan(fallback_data)
                        if validated_fallback.get("steps"):
                            return validated_fallback

                except Exception as fallback_exc:
                    logger.error(
                        f"Coding fallback planner failed: {fallback_exc}"
                    )

        return {"goal": "", "steps": []}

    print("JARVIS DEBUG: calling validate_plan()", flush=True)

    validated = validate_plan(data)

    print(
        f"JARVIS DEBUG: validate_plan returned "
        f"{validated!r}",
        flush=True
    )

    return validated

