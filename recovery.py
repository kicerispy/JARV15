"""
JARVIS error recovery and self-correction system.
"""

from tool_result import ToolResult
from typing import Any, Dict, Optional

from logger import logger
from model_manager import ModelManager


MODEL_MANAGER = ModelManager()


def analyze_error(
    tool_name: str,
    argument: str,
    error_message: str,
    attempt: int = 1,
    max_attempts: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Analyze a tool execution error and suggest a fix.

    Recovery analysis goes through ModelManager so the same centralized
    Ollama retry/response validation applies to self-correction as well.
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
        response = MODEL_MANAGER.recovery(
            [{"role": "user", "content": prompt}],
            format="json",
        )

        import json

        result = json.loads(
            response.get(
                "message",
                {},
            ).get(
                "content",
                "{}",
            )
        )

        if result.get("can_fix") and result.get("new_argument"):
            logger.info(
                f"Error recovery: {result.get('explanation')}"
            )
            return result

        return None

    except Exception as e:
        logger.warning(
            f"Error recovery analysis failed: {e}"
        )
        return None


def validate_code(
    code: str,
    language: str = "python",
) -> Dict[str, Any]:
    """
    Validate generated code before writing it.
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

    if len(code) < 10:
        result["warnings"].append(
            "Code seems very short"
        )

    if language == "python":
        if "    " in code and "	" in code:
            result["warnings"].append(
                "Mixed tabs and spaces detected"
            )

        if "print(" in code and "import" not in code:
            pass

        if "undefined" in code.lower():
            result["issues"].append(
                "Contains 'undefined' - might be JavaScript "
                "code in Python file"
            )

    elif language in ("javascript", "html"):
        if (
            "<html" not in code.lower()
            and "<!doctype" not in code.lower()
        ):
            if language == "html":
                result["warnings"].append(
                    "Missing <!DOCTYPE html> or <html> tag"
                )

    return result


def retry_with_recovery(
    tool_name: str,
    argument: str,
    execute_func,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """
    Execute a tool with error recovery.
    """
    last_error = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        try:
            result = execute_func(
                tool_name,
                argument,
            )

            if isinstance(result, ToolResult):

                if result.success:
                    return {
                        "success": True,
                        "result": result,
                        "attempts": attempt,
                    }

                last_error = (
                    result.error
                    or "Tool returned an unsuccessful result."
                )

                # Respect the tool's explicit retry policy.
                # Deterministic failures should not invoke
                # the LLM recovery system.
                if not result.retryable:
                    return {
                        "success": False,
                        "error": last_error,
                        "attempts": attempt,
                    }

            elif isinstance(result, dict):

                if (
                    result.get("success", True)
                    and result.get("verified", True)
                ):
                    return {
                        "success": True,
                        "result": result,
                        "attempts": attempt,
                    }

                last_error = result.get(
                    "message",
                    result.get(
                        "error",
                        "Unknown error",
                    ),
                )

            else:
                return {
                    "success": True,
                    "result": result,
                    "attempts": attempt,
                }

        except Exception as e:
            last_error = str(e)

            logger.warning(
                f"Tool {tool_name} failed "
                f"(attempt {attempt}/{max_attempts}): "
                f"{last_error}"
            )

        if attempt < max_attempts:

            recovery = analyze_error(
                tool_name,
                argument,
                last_error or "",
                attempt,
                max_attempts,
            )

            if (
                recovery
                and recovery.get("new_argument")
            ):
                logger.info(
                    "Recovering with new argument: "
                    f"{recovery['new_argument'][:100]}..."
                )

                argument = recovery["new_argument"]

            else:
                logger.info(
                    "No recovery suggestion, stopping retries"
                )
                break

    return {
        "success": False,
        "error": last_error or "Max retries exceeded",
        "attempts": attempt,
    }
