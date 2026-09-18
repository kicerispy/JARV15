"""
JARVIS code generation handler - intercepts coding requests and generates files directly.
"""
import ast
import re
import shutil
import subprocess
import sys
from typing import Optional, Tuple

from ollama import chat

from config import (
    CODING_FALLBACK_MODEL,
    CODING_MODEL,
    CODING_TEMPERATURE,
)
from logger import logger

# Patterns that indicate a code generation request
CODE_PATTERNS = [
    r"\b(create|make|build|write|generate)\b.*\b(code|script|program|game|app|application|website|webpage|html|python|javascript|js|file|lua|roblox)\b",
    r"\b(write|create)\b.*\b\d+\s*(file|script|program)\b",
    r"\b(flay|snake|tic\s*tac\s*toe|pong|browser\s*game)\b",
    r"\bhtml\b.*\bcss\b.*\bjavascript\b",
    r"\bpython\b.*\bscript\b",
    r"\broblox\b.*\b(script|game|model|part|tool|gui)\b",
    r"\blua\b.*\b(script|roblox|game)\b",
]


def is_code_request(text: str) -> bool:
    """Check if the user is asking for code to be generated."""
    if not text:
        return False

    text_lower = text.lower()
    for pattern in CODE_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    return False


def extract_filename(text: str) -> str:
    """
    Extract a filename from the user's request.
    Looks for patterns like 'to filename.py' or 'called filename.html'
    """
    if not text:
        return ""

    # Pattern: "to filename" or "called filename" or "named filename" or "filename"
    patterns = [
        r'\b(?:to|called|named|as|save\s+(?:as|to))\s+([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+)',
        r'\b(?:to|called|named|as)\s+([a-zA-Z0-9_\-]+)',
        r'\b([a-zA-Z0-9_\-]+\.(?:py|html|js|ts|jsx|tsx|css|java|cpp|c|go|rs|rb|php|lua))\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    # Default filenames based on content
    text_lower = text.lower()
    if "roblox" in text_lower or "lua" in text_lower:
        if "server" in text_lower or "server" in text_lower:
            return "server_script.lua"
        if "client" in text_lower or "local" in text_lower:
            return "local_script.lua"
        return "script.lua"
    if "flappy" in text_lower or "bird" in text_lower:
        return "flappy_bird.html"
    if "snake" in text_lower:
        return "snake_game.html"
    if "pong" in text_lower:
        return "pong.html"
    if "tic" in text_lower and "tac" in text_lower:
        return "tic_tac_toe.html"
    if "python" in text_lower or "py" in text_lower:
        return "script.py"
    if "javascript" in text_lower or "js" in text_lower:
        return "script.js"
    if "html" in text_lower:
        return "index.html"

    return "output.txt"



def is_complex_code_request(text: str) -> bool:
    """Identify coding requests that should use the full agent workflow."""
    normalized = str(text or "").strip().lower()

    if not normalized:
        return False

    complexity_markers = (
        "project",
        "codebase",
        "repository",
        "repo",
        "multi-file",
        "multiple files",
        "full app",
        "full application",
        "full website",
        "dashboard",
        "backend",
        "frontend",
        "database",
        "api",
        "integrate",
        "integration",
        "feature",
        "refactor",
        "architecture",
        "plugin",
        "module",
        "system",
        "jarvis",
        "game",
    )

    return any(marker in normalized for marker in complexity_markers)

def generate_code(user_request: str) -> Optional[Tuple[str, str]]:
    """
    Generate code based on the user's request.
    
    Args:
        user_request: The user's coding request.
    
    Returns:
        Tuple of (filename, code_content) or None if generation failed.
    """
    filename = extract_filename(user_request)
    is_roblox = "roblox" in user_request.lower() or "lua" in user_request.lower()

    if is_roblox:
        prompt = f"""You are an expert Roblox Lua developer. Generate complete, working Roblox Lua code for the following request.

User request: {user_request}

Roblox Lua Requirements:
1. Use proper Roblox API: game:GetService(), Instance.new(), workspace, etc.
2. For Script: use .Touched events, tweens, remote events
3. For LocalScript: use player local scripts, GUI, camera
4. Use proper indentation and comments
5. Handle edge cases (parts touching, player respawning)
6. Return ONLY the Lua code, no markdown blocks, no explanations

Generate the Roblox Lua code now:"""
    else:
        prompt = f"""You are an expert software engineer. Generate complete, working, production-ready code for the following request.

User request: {user_request}

Requirements:
1. Generate COMPLETE, WORKING code that actually runs
2. Include ALL necessary HTML, CSS, and JavaScript in a single file if it's a web app
3. Use modern, clean code with comments
4. Make it visually appealing and functional
5. For games, include collision detection, scoring, and game states
6. Return ONLY the code, no explanations before or after
7. Start with the first line of actual code (no markdown code blocks)

Generate the code now:"""

    try:
        response = chat(
            model=CODING_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": CODING_TEMPERATURE},
        )

        code = response.get("message", {}).get("content", "").strip()

        if (
            not code
            and CODING_FALLBACK_MODEL
            and CODING_FALLBACK_MODEL != CODING_MODEL
        ):
            logger.warning(
                "Primary coding model returned empty output; "
                f"falling back to {CODING_FALLBACK_MODEL}."
            )
            response = chat(
                model=CODING_FALLBACK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": CODING_TEMPERATURE},
            )
            code = response.get("message", {}).get("content", "").strip()

        # Remove markdown code fences if present
        code = re.sub(r'^```(?:html|javascript|python|js|lua)?\n', '', code)
        code = re.sub(r'\n```$', '', code)
        code = re.sub(r'^```(?:html|javascript|python|js|lua)?$', '', code)
        code = code.strip()

        if not code:
            return None

        return (filename, code)

    except Exception as e:
        logger.error(f"Code generation failed: {e}")
        return None


def _clean_generated_code(code: str) -> str:
    """Normalize model output before validation/writing."""
    code = str(code or "").strip()
    code = re.sub(
        r"^```(?:html|javascript|python|js|lua|css|typescript|ts)?\s*\n",
        "",
        code,
        flags=re.IGNORECASE,
    )
    code = re.sub(r"\s*```$", "", code)
    return code.strip()
def _validate_generated_file(filename: str, code: str) -> Tuple[bool, str]:
    """Validate generated source without executing arbitrary generated code."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if not code.strip():
        return False, "Generated code is empty."

    if suffix == "py":
        try:
            ast.parse(code, filename=filename)
        except SyntaxError as exc:
            return False, (
                f"Python syntax error at line {exc.lineno}: "
                f"{exc.msg}"
            )

        try:
            completed = subprocess.run(
                [sys.executable, "-m", "py_compile", filename],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            return False, f"Python compile check could not start: {exc}"

        if completed.returncode != 0:
            return False, (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Python compilation failed."
            )

        return True, "Python syntax and compilation checks passed."

    if suffix in {"js", "mjs", "cjs"}:
        node = shutil.which("node")
        if not node:
            return True, "JavaScript generated; Node.js syntax validation unavailable."

        try:
            completed = subprocess.run(
                [node, "--check", filename],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            return False, f"JavaScript syntax check could not start: {exc}"

        if completed.returncode != 0:
            return False, (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "JavaScript syntax validation failed."
            )

        return True, "JavaScript syntax validation passed."

    if suffix == "html":
        lowered = code.lower()
        required = ("<html", "<body", "</html>")
        missing = [tag for tag in required if tag not in lowered]
        if missing:
            return False, (
                "HTML structure check failed; missing: "
                + ", ".join(missing)
            )

        return True, "HTML structure validation passed."

    if suffix == "lua":
        lua = shutil.which("luac") or shutil.which("lua")
        if not lua:
            return True, "Lua generated; Lua syntax validation unavailable."

        command = (
            [lua, "-p", filename]
            if lua.lower().endswith("luac.exe")
            or lua.lower().endswith("luac")
            else [lua, "-e", f"assert(loadfile({filename!r}))"]
        )

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            return False, f"Lua syntax check could not start: {exc}"

        if completed.returncode != 0:
            return False, (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Lua syntax validation failed."
            )

        return True, "Lua syntax validation passed."

    return True, "No language-specific executable validation was available."


def _repair_generated_code(
    user_request: str,
    filename: str,
    code: str,
    failure: str,
) -> Optional[str]:
    """Ask the dedicated coding model to repair generated source from evidence."""
    prompt = f"""You are JARVIS's coding specialist.

A generated implementation failed validation.

User request:
{user_request}

Target file:
{filename}

Validation failure:
{failure}

Current implementation:
---BEGIN CURRENT CODE---
{code}
---END CURRENT CODE---

Repair the implementation so it directly satisfies the original request.
Preserve correct existing behavior. Do not invent external files unless
the request requires them. Return ONLY the complete replacement contents
of {filename}; no markdown fences and no explanation.
"""

    try:
        response = chat(
            model=CODING_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": min(float(CODING_TEMPERATURE), 0.2)},
        )

        repaired = _clean_generated_code(
            response.get("message", {}).get("content", "")
        )

        return repaired or None

    except Exception as exc:
        logger.error(f"Code repair generation failed: {exc}")
        return None


def handle_code_generation(user_input: str) -> str:
    """
    Handle a code generation request end-to-end.

    Generated source gets a bounded validation/repair loop before JARVIS
    reports the request complete. Existing successful behavior and public
    return strings are preserved.
    """
    logger.info(f"Generating code for: {user_input}")

    result = generate_code(user_input)
    if not result:
        return "I couldn't generate the code. Please try rephrasing your request."

    filename, code = result
    code = _clean_generated_code(code)
    is_roblox = "roblox" in user_input.lower() or filename.endswith(".lua")

    from file_tools import write_file

    original_exists = False
    original_content = ""

    try:
        from pathlib import Path

        target = Path.cwd() / filename
        if target.exists() and target.is_file():
            original_exists = True
            original_content = target.read_text(encoding="utf-8")
    except Exception:
        pass

    max_repair_attempts = 3
    last_failure = ""

    for attempt in range(max_repair_attempts + 1):
        write_result = write_file(
            filename,
            code,
            overwrite=True,
        )

        if str(write_result).startswith(
            ("I couldn't", "File not found", "Invalid", "Error")
        ):
            last_failure = str(write_result)
        else:
            valid, diagnostic = _validate_generated_file(
                filename,
                code,
            )

            logger.info(
                "Generated code validation attempt %s/%s for %s: %s",
                attempt + 1,
                max_repair_attempts + 1,
                filename,
                diagnostic,
            )

            if valid:
                if is_roblox:
                    return (
                        f"{write_result} "
                        "For Roblox Studio: Insert the script into a Script "
                        "object inside a Part, or use it as a "
                        "ModuleScript/LocalScript as needed."
                    )

                return (
                    f"{write_result} "
                    f"You can open {filename} to see your new "
                    f"{'game' if any(g in user_input.lower() for g in ['flappy', 'snake', 'pong', 'game']) else 'code'}."
                )

            last_failure = diagnostic

        if attempt >= max_repair_attempts:
            break

        repaired = _repair_generated_code(
            user_input,
            filename,
            code,
            last_failure,
        )

        if not repaired:
            break

        code = repaired

    # Never leave a previously working file replaced by an unvalidated
    # generated implementation after all repair attempts fail.
    if original_exists:
        try:
            write_file(
                filename,
                original_content,
                overwrite=True,
            )
        except Exception as exc:
            logger.warning(
                f"Could not restore original {filename}: {exc}"
            )
        return (
            f"I generated {filename}, but validation failed after "
            f"{max_repair_attempts} repair attempts. "
            "The previous file was preserved."
        )

    return (
        f"I generated {filename}, but validation failed after "
        f"{max_repair_attempts} repair attempts: {last_failure}"
    )
