"""
JARVIS task planner - converts user requests into tool calls.
"""
import json
from typing import Any, Dict, List, Optional

from ollama import chat

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
    "browser_self_test": "Run a focused runtime smoke test of JARVIS browser automation, including generic DOM controls and the live Google result selector.",
    "browser_find_element": "Find a browser DOM element by CSS selector, visible text, or ARIA role.",
    "browser_click_element": "Click a browser DOM element by CSS selector, visible text, or ARIA role.",
    "browser_fill_element": "Fill a browser input by CSS selector, visible text, or ARIA role. Argument is JSON.",
    "browser_press_key": "Press a keyboard key on a browser element by CSS selector, visible text, or ARIA role. Argument is JSON.",
    "browser_wait_for_element": "Wait for a browser DOM element to become visible. Argument is JSON.",
    "browser_extract_text": "Extract text from a browser DOM element. Argument is JSON.",
    "browser_click_first_result": "Click the first organic Google or YouTube result through the controlled browser DOM. Argument is JSON.",
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
    "code_search": "Search project source files for a symbol, string, or error message.",
    "code_test": "Validate project code. argument = JSON such as {\"mode\":\"compile\",\"path\":\"main.py\"} or {\"mode\":\"pytest\",\"path\":\"tests/test_x.py\"}.",
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

GENERIC BROWSER DOM RULES:

When controlling a browser, prefer browser_* DOM tools over
screen-coordinate tools whenever the target can be located in
the page DOM.

Browser workflow:

1. Navigate to the intended page.
2. Inspect the page with browser_page_info or browser_find_element.
3. Use browser_fill_element for text inputs.
4. Use browser_press_key for Enter or other keyboard actions.
5. Use browser_click_element for links, buttons, and controls.
6. Use browser_wait_for_element when content may load asynchronously.
7. Use browser_extract_text or browser_page_info to verify the result.
8. When an action fails, use the browser state and observations to
   choose a different strategy during replanning.

DOM TOOL ARGUMENT FORMAT:

DOM browser tools use a JSON object encoded as the step's argument string.

Examples:

browser_find_element
argument = {{"role":"searchbox"}}

browser_find_element
argument = {{"text":"Sign in"}}

browser_find_element
argument = {{"selector":"button[type=submit]"}}

browser_fill_element
argument = {{"role":"searchbox","value":"Iron Man trailer"}}

browser_press_key
argument = {{"role":"searchbox","key":"Enter"}}

browser_click_element
argument = {{"role":"button","text":"Submit"}}

browser_wait_for_element
argument = {{"text":"Results","timeout":10000}}

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
)

CODE_DIAGNOSTIC_TERMS = (
    "debug",
    "diagnose",
    "inspect",
    "investigate",
    "test",
)

SOFTWARE_DOMAIN_TERMS = (
    "code",
    "script",
    "software",
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
    ".py",
    ".js",
)

CODE_INSPECTION_TOOLS = {
    "code_search",
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


def is_software_repair_request(text: str) -> bool:
    normalized = _normalized_words(text)
    return (
        any(term in normalized for term in CODE_REPAIR_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def is_software_diagnostic_request(text: str) -> bool:
    normalized = _normalized_words(text)
    return (
        any(term in normalized for term in CODE_DIAGNOSTIC_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def assess_plan(
    user_command: str,
    plan: Dict[str, Any],
    require_modification: Optional[bool] = None,
    require_code_read: bool = False,
    require_code_test: bool = False,
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

    if not is_software_diagnostic_request(user_command):
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
        if tool == "code_test"
    ]

    if inspection_index is None and not allow_prior_evidence:
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

        "open the first result",
        "open first result",

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

    # Repair handoffs get a focused prompt instead of the full general
    # planner prompt. This keeps verified source evidence prominent and
    # avoids the model reverting to generic discovery behavior.
    if "REPAIR PHASE RULES:" in user_command:
        repair_tools = {
            name: AVAILABLE_TOOLS[name]
            for name in (
                "code_checkpoint",
                "edit_file",
                "write_file",
                "delete_file",
                "code_test",
                "read_file",
                "code_search",
                "list_files",
                "find_file",
            )
        }

        repair_tool_list = "\n".join(
            f"{name}: {desc}"
            for name, desc in repair_tools.items()
        )

        system_content = f"""You are JARVIS's focused software repair planner.

The investigation phase is already complete. The user message contains
verified evidence from the actual project source and validation steps.

Available repair tools:
{repair_tool_list}

REPAIR HANDOFF MODE — HIGH PRIORITY:

Do NOT restart generic discovery.
Do NOT use list_files or broad code_search unless the evidence explicitly
shows that the existing target is insufficient.
Do NOT return an empty steps list for this repair request.

Use the verified evidence to identify ONE concrete, evidence-supported defect
or robustness problem and make the smallest safe repair.

The repair plan MUST be ordered exactly as:
1. code_checkpoint
2. one or more appropriate file mutation steps
3. code_test after the final mutation

For existing source, prefer edit_file with this exact argument format:
"filename|||old_text|||new_text"

Copy old_text from the verified source evidence. Do not invent filenames,
source text, functions, errors, or behavior.

If a targeted reread is truly necessary, use read_file on the specific file,
then return the mutation plan on the next planning attempt. Do not repeat
project-wide discovery.

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
            if "REPAIR PHASE RULES:" in user_command
            else PLANNER_MODEL
        )

        if "REPAIR PHASE RULES:" in user_command:
            print(
                f"JARVIS DEBUG: repair planner -> using {planner_model}",
                flush=True,
            )

        response = chat(
            model=planner_model,
            messages=messages,
            format="json"
        )

        print(
            f"JARVIS DEBUG: Ollama returned after "
            f"{time.perf_counter() - planner_start:.3f}s",
            flush=True
        )
        print(
            f"JARVIS DEBUG: response type={type(response).__name__}",
            flush=True
        )

    except Exception as e:
        logger.error(f"Planner LLM call failed: {e}")
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
        return {"goal": "", "steps": []}

    print("JARVIS DEBUG: calling validate_plan()", flush=True)

    validated = validate_plan(data)

    print(
        f"JARVIS DEBUG: validate_plan returned "
        f"{validated!r}",
        flush=True
    )

    return validated

