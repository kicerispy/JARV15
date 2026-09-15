"""
JARVIS error recovery and self-correction system.
"""
from typing import Any, Dict, Optional

from ollama import chat

from config import CHAT_MODEL
from logger import logger


def analyze_error(
    tool_name: str,
    argument: str,
    error_message: str,
    attempt: int = 1,
    max_attempts: int = 3
) -> Optional[Dict[str, Any]]:
    """
    Analyze a tool execution error and suggest a fix.

    Args:
        tool_name: The tool that failed.
        argument: The argument that was passed.
        error_message: The error message received.
        attempt: Current attempt number.
        max_attempts: Maximum retry attempts.

    Returns:
        Suggested fix dict with new argument, or None if no fix suggested.
    """
    if attempt >= max_attempts:
        return None

    prompt = f"""You are JARVIS's error recovery system.

A tool execution failed. Analyze the error and suggest a fix.

Tool: {tool_name}
Argument: {argument}
Error: {error_message}
Attempt: {attempt}/{max_attempts}

Return ONLY valid JSON with this format:
{{
  "can_fix": true/false,
  "new_argument": "fixed argument or original",
  "explanation": "brief explanation"
}}

If you cannot fix this error, return can_fix: false.
If you can fix it, provide the corrected argument."""

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.0}
        )

        import json
        result = json.loads(response.get("message", {}).get("content", "{}"))

        if result.get("can_fix") and result.get("new_argument"):
            logger.info(f"Error recovery: {result.get('explanation')}")
            return result

        return None

    except Exception as e:
        logger.warning(f"Error recovery analysis failed: {e}")
        return None


def validate_code(code: str, language: str = "python") -> Dict[str, Any]:
    """
    Validate generated code before writing it.

    Args:
        code: The code to validate.
        language: Programming language.

    Returns:
        Validation result dict.
    """
    result = {
        "valid": True,
        "issues": [],
        "warnings": [],
    }

    if not code or not code.strip():
        result["valid"] = False
        result["issues"].append("Code is empty")
        return result

    # Basic checks
    if len(code) < 10:
        result["warnings"].append("Code seems very short")

    # Language-specific checks
    if language == "python":
        # Check for balanced indentation
        if "    " in code and "\t" in code:
            result["warnings"].append("Mixed tabs and spaces detected")

        # Check for common mistakes
        if "print(" in code and "import" not in code:
            pass  # print is built-in, no import needed

        # Check for undefined variables (basic)
        if "undefined" in code.lower():
            result["issues"].append("Contains 'undefined' - might be JavaScript code in Python file")

    elif language in ("javascript", "html"):
        # Check for basic HTML structure
        if "<html" not in code.lower() and "<!doctype" not in code.lower():
            if language == "html":
                result["warnings"].append("Missing <!DOCTYPE html> or <html> tag")

    return result


def retry_with_recovery(
    tool_name: str,
    argument: str,
    execute_func,
    max_attempts: int = 3
) -> Dict[str, Any]:
    """
    Execute a tool with error recovery.

    Args:
        tool_name: The tool to execute.
        argument: The argument to pass.
        execute_func: Function that takes (tool_name, argument) and returns result.
        max_attempts: Maximum retry attempts.

    Returns:
        Result dict with success status and result/error.
    """
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = execute_func(tool_name, argument)

            if isinstance(result, dict):
                if result.get("success", True) and result.get("verified", True):
                    return {"success": True, "result": result, "attempts": attempt}
                last_error = result.get("message", "Unknown error")
            else:
                return {"success": True, "result": result, "attempts": attempt}

        except Exception as e:
            last_error = str(e)
            logger.warning(f"Tool {tool_name} failed (attempt {attempt}/{max_attempts}): {last_error}")

        # Try to recover
        if attempt < max_attempts:
            recovery = analyze_error(tool_name, argument, last_error or "", attempt, max_attempts)
            if recovery and recovery.get("new_argument"):
                logger.info(f"Recovering with new argument: {recovery['new_argument'][:100]}...")
                argument = recovery["new_argument"]
            else:
                logger.info("No recovery suggestion, stopping retries")
                break

    return {
        "success": False,
        "error": last_error or "Max retries exceeded",
        "attempts": attempt,
    }
