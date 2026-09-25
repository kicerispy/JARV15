"""
JARVIS error recovery and self-correction system.
"""

import json
import time

from tool_result import ToolResult
from typing import Any, Dict, Optional

from logger import logger
from model_manager import ModelManager
from healing_kernel import (
    build_healing_evidence,
    choose_recovery,
    diagnose_failure,
    healing_hints,
    recovery_backoff_seconds,
    record_healing_event,
)


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

    hints = healing_hints(
        tool_name,
        error=error_message,
        limit=3,
    )
    failure_hints = json.dumps(
        hints,
        ensure_ascii=True,
    )
    if not hints:
        failure_hints = "No matching prior failure patterns."

    prompt = f"""You are JARVIS's error recovery system.

A tool execution failed. Analyze the error and suggest a fix.

Tool: {tool_name}
Argument: {argument}
Error: {error_message}
Attempt: {attempt}/{max_attempts}

Prior recovery evidence from this tool:
{failure_hints}

Use prior evidence to avoid repeating a strategy that already failed. Do not
blindly copy a previous argument; only return a new argument when it directly
addresses the current failure.

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
    last_signature = ""

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
                    if last_signature:
                        try:
                            from healing_playbook import mark_recovered
                            mark_recovered(
                                tool_name,
                                signature=last_signature,
                            )
                        except Exception as playbook_exc:
                            logger.debug(
                                f"JARVIS HEALING: recovery mark skipped: {playbook_exc}"
                            )
                    return {
                        "success": True,
                        "result": result,
                        "attempts": attempt,
                    }

                last_error = (
                    result.error
                    or "Tool returned an unsuccessful result."
                )

                diagnosis = diagnose_failure(
                    tool_name,
                    last_error,
                    argument=argument,
                    result=result.data,
                )
                last_signature = diagnosis.signature
                decision = choose_recovery(
                    diagnosis,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    model_available=True,
                )
                record_healing_event(
                    {
                        **build_healing_evidence(
                            tool_name,
                            argument,
                            last_error,
                            diagnosis,
                            attempt=attempt,
                            result=result.data,
                        ),
                        "action": decision.action,
                        "decision_reason": decision.reason,
                    }
                )

                # Respect both the tool's explicit retry policy and the
                # Healing Kernel's diagnosis. Browser drift, missing targets,
                # and code defects belong to Agent Core's evidence/replan
                # workflow rather than another blind local retry.
                if (
                    decision.action in {"replan", "repair_code", "stop", "escalate"}
                    or (
                        not result.retryable
                        and decision.action != "repair_argument"
                    )
                ):
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
                    if last_signature:
                        try:
                            from healing_playbook import mark_recovered
                            mark_recovered(
                                tool_name,
                                signature=last_signature,
                            )
                        except Exception as playbook_exc:
                            logger.debug(
                                f"JARVIS HEALING: recovery mark skipped: {playbook_exc}"
                            )
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

                diagnosis = diagnose_failure(
                    tool_name,
                    last_error,
                    argument=argument,
                    result=result,
                )
                last_signature = diagnosis.signature
                decision = choose_recovery(
                    diagnosis,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    model_available=True,
                )
                record_healing_event(
                    {
                        **build_healing_evidence(
                            tool_name,
                            argument,
                            last_error,
                            diagnosis,
                            attempt=attempt,
                            result=result,
                        ),
                        "action": decision.action,
                        "decision_reason": decision.reason,
                    }
                )

                if decision.action in {"replan", "repair_code", "stop", "escalate"}:
                    return {
                        "success": False,
                        "error": str(last_error),
                        "attempts": attempt,
                    }

            else:
                return {
                    "success": True,
                    "result": result,
                    "attempts": attempt,
                }

        except Exception as e:
            last_error = str(e)

            diagnosis = diagnose_failure(
                tool_name,
                last_error,
                argument=argument,
            )
            last_signature = diagnosis.signature
            decision = choose_recovery(
                diagnosis,
                attempt=attempt,
                max_attempts=max_attempts,
                model_available=True,
            )
            record_healing_event(
                {
                    **build_healing_evidence(
                        tool_name,
                        argument,
                        last_error,
                        diagnosis,
                        attempt=attempt,
                    ),
                    "action": decision.action,
                    "decision_reason": decision.reason,
                }
            )

            logger.warning(
                f"Tool {tool_name} failed "
                f"(attempt {attempt}/{max_attempts}): "
                f"{last_error} "
                f"[healing={decision.action}/{diagnosis.category}]"
            )

            if decision.action in {"replan", "repair_code", "stop", "escalate"}:
                break

        if attempt < max_attempts:
            diagnosis = diagnose_failure(
                tool_name,
                last_error or "",
                argument=argument,
            )
            last_signature = diagnosis.signature
            decision = choose_recovery(
                diagnosis,
                attempt=attempt,
                max_attempts=max_attempts,
                model_available=True,
            )

            if decision.action == "retry":
                delay = recovery_backoff_seconds(attempt)
                if delay > 0:
                    logger.info(
                        "JARVIS HEALING: transient retry backoff "
                        f"{delay:.3f}s for {diagnosis.category}"
                    )
                    time.sleep(delay)
                logger.info(
                    "JARVIS HEALING: retrying without model intervention: "
                    f"{diagnosis.category}"
                )
                continue

            if decision.action == "repair_argument":
                recovery = analyze_error(
                    tool_name,
                    argument,
                    last_error or "",
                    attempt,
                    max_attempts,
                )

                if recovery and recovery.get("new_argument"):
                    logger.info(
                        "Recovering with new argument: "
                        f"{recovery['new_argument'][:100]}..."
                    )
                    argument = recovery["new_argument"]
                    continue

            logger.info(
                "JARVIS HEALING: local recovery stopped; escalating "
                f"with action={decision.action}."
            )
            break

    return {
        "success": False,
        "error": last_error or "Max retries exceeded",
        "attempts": attempt,
    }
