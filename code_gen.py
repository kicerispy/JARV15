"""
JARVIS code generation handler - intercepts coding requests and generates files directly.
"""
import re
from typing import Optional, Tuple

from ollama import chat

from config import CHAT_MODEL
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
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3}
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


def handle_code_generation(user_input: str) -> str:
    """
    Handle a code generation request end-to-end.
    
    Args:
        user_input: The user's coding request.
    
    Returns:
        Status message.
    """
    logger.info(f"Generating code for: {user_input}")

    result = generate_code(user_input)
    if not result:
        return "I couldn't generate the code. Please try rephrasing your request."

    filename, code = result
    is_roblox = "roblox" in user_input.lower() or filename.endswith(".lua")

    # Write the file
    from file_tools import write_file
    write_result = write_file(filename, code, overwrite=True)

    if is_roblox:
        return f"{write_result} For Roblox Studio: Insert the script into a Script object inside a Part, or use it as a ModuleScript/LocalScript as needed."

    return f"{write_result} You can open {filename} to see your new {'game' if any(g in user_input.lower() for g in ['flappy', 'snake', 'pong', 'game']) else 'code'}."
