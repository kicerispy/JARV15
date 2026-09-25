"""
JARVIS Agent Core

Autonomous task orchestration layer.

Flow:

    request
       ↓
     plan
       ↓
    execute
       ↓
    observe
       ↓
    success? ── yes ──> completed
       │
       no
       ↓
     replan
       ↓
    execute again

The existing tool_executor.py remains responsible for:
- executing tools
- task state
- cancellation
- screen verification
- retries/recovery
- active context updates
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from logger import logger
from project_fs import iter_project_files
from autonomy_memory import get_failure_hints, record_episode
from answer_composer import compose_task_answer
from postcondition_verifier import verify_postcondition
from planner import (
    assess_plan,
    create_plan,
    is_explicit_self_repair_request,
    is_software_change_request,
    is_software_diagnostic_request,
    is_software_repair_request,
    is_roblox_mutation_tool,
    is_roblox_request,
    ROBLOX_INSPECTION_TOOLS,
    ROBLOX_TEST_TOOLS,
    validate_plan,
)
from tool_executor import execute_plan
from state import ActiveContext, TaskState
from superpowers_engine import classify_software_request


# ==========================================================
# Agent Step
# ==========================================================

@dataclass
class AgentStep:
    tool: str
    argument: str = ""

    description: str = ""

    status: str = "pending"

    attempts: int = 0

    result: Any = None

    error: Optional[str] = None

    initial_acknowledged: bool = False

    verified: bool = False

    observation: str = ""


# ==========================================================
# Agent Task
# ==========================================================

@dataclass
class AgentTask:
    task_id: str

    request: str

    goal: str = ""

    status: str = "created"

    steps: List[AgentStep] = field(
        default_factory=list
    )

    active_context: Dict[str, Any] = field(
        default_factory=dict
    )

    planner_result: Optional[Dict[str, Any]] = None

    execution_result: Any = None

    observations: List[str] = field(
        default_factory=list
    )

    # Structured execution evidence kept separate from user-facing
    # progress text. Raw source/test output stays here and is bounded
    # before it is sent back to the planner.
    evidence: List[Dict[str, Any]] = field(
        default_factory=list
    )

    replan_count: int = 0

    # Failed post-edit validation can trigger a checkpoint restore + focused
    # repair loop. Keep that loop bounded independently of generic replans.
    change_recovery_attempts: int = 0

    max_replans: int = 2

    current_step: int = -1

    created_at: float = field(
        default_factory=time.time
    )

    started_at: Optional[float] = None

    completed_at: Optional[float] = None

    error: Optional[str] = None

    initial_acknowledged: bool = False

    # Native Superpowers workflow metadata retained across replanning.
    superpowers: Dict[str, Any] = field(default_factory=dict)


# ==========================================================
# JARVIS Agent
# ==========================================================


# ============================================================
# Browser State Observation Helpers
# ============================================================

BROWSER_STATE_TOOLS = {
    "browser_connect",
    "browser_search_google",
    "browser_search_bing",
    "browser_click_first_bing_result",
    "browser_goto",
    "browser_page_info",
    "browser_click_first_result",
    "browser_find_element",
    "browser_click_element",
    "browser_fill_element",
    "browser_press_key",
    "browser_wait_for_element",
    "browser_extract_text",
    "browser_click_result",
    "browser_back",
    "browser_agent_run",
}


def _is_browser_trace(trace):
    for entry in trace or []:
        tool = str(entry.get("tool", "")).strip()

        if tool in BROWSER_STATE_TOOLS:
            return True

    return False


def _capture_browser_state():
    try:
        from browser_controller import browser_page_info

        result = browser_page_info()

        if not isinstance(result, dict):
            return {
                "success": False,
                "error": (
                    "browser_page_info returned "
                    "a non-dict result"
                ),
            }

        return result

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
        }


class JarvisAgent:

    def __init__(
        self,
        planner=create_plan,
        executor=execute_plan,
    ):
        self.planner = planner
        self.executor = executor

        self.current_task: Optional[
            AgentTask
        ] = None

        self.state: Dict[str, Any] = {
            "last_request": "",
            "last_goal": "",
            "last_result": None,
            "last_status": "",
            "last_error": None,
            "replans": 0,
        }

    # ======================================================
    # Experience Memory
    # ======================================================

    @staticmethod
    def _record_autonomy_episode(task: AgentTask) -> None:
        """Persist a compact outcome so future plans can learn from it."""
        if task is None:
            return

        try:
            start = task.started_at or task.created_at
            end = task.completed_at or time.time()
            tools = [
                step.tool
                for step in task.steps
                if step.tool
            ]

            context_site = str(
                task.active_context.get("site", "") or ""
            ).strip().lower()

            domain = context_site
            if not domain:
                request_lower = str(task.request or "").lower()
                if "roblox" in request_lower or "luau" in request_lower:
                    domain = "roblox"
                elif any(
                    term in request_lower
                    for term in ("browser", "chrome", "website", "google", "youtube")
                ):
                    domain = "browser"
                elif any(
                    term in request_lower
                    for term in ("code", "python", "repository", "git", "fix", "repair")
                ):
                    domain = "code"

            record_episode(
                task.request,
                task.status,
                tools,
                replans=task.replan_count,
                duration_seconds=max(0.0, end - start),
                error=task.error or "",
                domain=domain,
            )
        except Exception as exc:
            logger.debug(
                f"JARVIS AGENT: experience-memory write skipped: {exc}"
            )

    # ======================================================
    # Create Task
    # ======================================================

    def create_task(
        self,
        request: str,
        active_context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AgentTask:

        normalized_request = str(
            request or ""
        ).strip()

        task = AgentTask(
            task_id=str(
                uuid.uuid4()
            ),
            request=normalized_request,
            active_context=dict(
                active_context or {}
            ),
        )

        # Give software repair work a larger bounded recovery budget while
        # preserving the existing budget for ordinary assistant tasks.
        if is_software_repair_request(normalized_request) or is_software_change_request(normalized_request):
            task.max_replans = 5
        elif is_software_diagnostic_request(normalized_request):
            task.max_replans = 3

        workflow = classify_software_request(normalized_request)
        if workflow is not None:
            task.superpowers = workflow.to_dict()
            task.active_context["superpowers"] = workflow.to_dict()
            task.observations.append(
                "Superpowers workflow selected: "
                f"{workflow.classification} / {workflow.execution_mode}."
            )

        self.current_task = task

        # Reuse bounded lessons from earlier failures that overlap this request.
        # These hints guide the planner but never mutate source code.
        try:
            learned_hints = get_failure_hints(
                normalized_request,
                limit=3,
            )
        except Exception as exc:
            learned_hints = []
            logger.debug(
                f"JARVIS AGENT: experience-memory lookup skipped: {exc}"
            )

        if learned_hints:
            task.active_context["learned_hints"] = learned_hints
            task.observations.append(
                f"Loaded {len(learned_hints)} relevant prior failure lesson(s)."
            )

        self.state[
            "last_request"
        ] = task.request

        self.state[
            "last_error"
        ] = None

        self.state[
            "replans"
        ] = 0

        return task

    # ======================================================
    # Progress Reporting
    # ======================================================

    @staticmethod
    def _announce(message: str, speak_callback) -> None:
        """Give the user a concise milestone update without exposing internals."""
        try:
            if speak_callback:
                speak_callback(message)
        except Exception as exc:
            logger.debug(
                f"JARVIS AGENT: Progress announcement skipped: {exc}"
            )

    def _should_report_progress(self, task: AgentTask) -> bool:
        request = task.request.lower()
        progress_terms = (
            "fix",
            "debug",
            "repair",
            "diagnose",
            "refactor",
            "investigate",
            "inspect",
        )
        # Keep the initial acknowledgement, but reserve spoken milestone
        # updates for genuinely complex plans. This prevents simple repairs
        # from turning into a stream of 4-5 second TTS messages.
        return len(task.steps) > 3

    # ======================================================
    # Build Steps
    # ======================================================

    def _build_steps(
        self,
        plan: Dict[str, Any],
    ) -> List[AgentStep]:

        steps: List[AgentStep] = []

        for step in plan.get(
            "steps",
            [],
        ):

            if not isinstance(
                step,
                dict,
            ):
                continue

            tool = str(
                step.get(
                    "tool",
                    "",
                )
                or ""
            ).strip()

            argument = str(
                step.get(
                    "argument",
                    "",
                )
                or ""
            )

            if not tool:
                continue

            steps.append(
                AgentStep(
                    tool=tool,
                    argument=argument,
                    description=str(
                        step.get(
                            "description",
                            "",
                        )
                        or ""
                    ),
                )
            )

        return steps

    @staticmethod
    def _plan_has_mutation(plan: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(plan, dict):
            return False

        return any(
            (
                str(step.get("tool", "") or "").strip()
                in {
                    "write_file",
                    "edit_file",
                    "delete_file",
                }
                or is_roblox_mutation_tool(
                    str(step.get("tool", "") or "").strip()
                )
            )
            for step in plan.get("steps", [])
            if isinstance(step, dict)
        )

    @staticmethod
    def _extract_tool_data(result: Any) -> Any:
        """Return the raw data carried by a normalized ToolResult."""
        data = getattr(result, "data", None)

        if data is not None:
            return data

        return result

    @staticmethod
    def _compact_text(value: Any, limit: int = 5000) -> str:
        """Bound internal evidence so one tool cannot flood planner context."""
        text = str(value or "").strip()

        if len(text) <= limit:
            return text

        return (
            text[:limit]
            + "\n... [evidence truncated by JARVIS] ..."
        )

    @staticmethod
    def _source_excerpt(
        source: str,
        request: str,
        max_chars: int = 9000,
    ) -> str:
        """Extract a useful, line-numbered source excerpt for the repair planner."""
        source = str(source or "")
        lines = source.splitlines()

        if len(source) <= max_chars:
            return "\n".join(
                f"{index}: {line}"
                for index, line in enumerate(lines, start=1)
            )

        raw_terms = re.findall(
            r"[A-Za-z_][A-Za-z0-9_.-]{3,}",
            str(request or "").lower(),
        )

        stop_words = {
            "inspect",
            "find",
            "problem",
            "fix",
            "repair",
            "debug",
            "diagnose",
            "test",
            "the",
            "and",
            "with",
            "this",
            "that",
            "from",
            "into",
            "before",
            "after",
            "actual",
            "source",
        }

        terms = {
            term
            for term in raw_terms
            if term not in stop_words
        }

        selected = set(range(min(len(lines), 50)))

        if terms:
            for index, line in enumerate(lines):
                lowered = line.lower()

                if any(
                    term in lowered
                    for term in terms
                ):
                    start = max(0, index - 3)
                    end = min(len(lines), index + 4)
                    selected.update(
                        range(start, end)
                    )

        selected.update(
            range(
                max(0, len(lines) - 40),
                len(lines),
            )
        )

        ordered = sorted(selected)
        chunks = []
        total = 0

        for index in ordered:
            line = f"{index + 1}: {lines[index]}"

            if total + len(line) + 1 > max_chars:
                break

            chunks.append(line)
            total += len(line) + 1

        if not chunks:
            chunks = [
                f"{index + 1}: {lines[index]}"
                for index in range(
                    min(len(lines), 40)
                )
            ]

        return "\n".join(chunks)

    def _build_evidence_packet(
        self,
        task: AgentTask,
        max_chars: int = 18000,
    ) -> str:
        """Build bounded, repair-focused evidence for the next planner phase."""
        sections = [
            "Evidence gathered from completed execution phases:",
            "",
            "Treat the evidence below as observations. Do not invent facts "
            "that are not supported by it.",
        ]

        total = sum(len(line) + 1 for line in sections)

        for index, evidence in enumerate(
            task.evidence,
            start=1,
        ):
            if not isinstance(evidence, dict):
                continue

            tool = str(
                evidence.get("tool", "")
                or ""
            ).strip()

            header = f"\nEvidence {index}: {tool or 'tool'}"

            body_parts = []

            target = str(
                evidence.get("target", "")
                or ""
            ).strip()

            if target:
                body_parts.append(
                    f"Target: {target}"
                )

            status = (
                "verified"
                if evidence.get("verified")
                else (
                    "completed"
                    if evidence.get("success")
                    else "failed"
                )
            )

            body_parts.append(
                f"Status: {status}"
            )

            detail = str(
                evidence.get("detail", "")
                or ""
            ).strip()

            if detail:
                body_parts.append(detail)

            block = header + "\n" + "\n".join(body_parts)

            if total + len(block) + 1 > max_chars:
                sections.extend(
                    [
                        "",
                        "[Additional evidence omitted to keep the repair context bounded.]",
                    ]
                )
                break

            sections.append(block)
            total += len(block) + 1

        if not task.evidence:
            sections.extend([
                "",
                "No structured evidence was captured.",
            ])

        return "\n".join(sections)

    # ======================================================
    # Planning
    # ======================================================

    @staticmethod
    def _has_verified_evidence(
        task: AgentTask,
        tools: set[str],
    ) -> bool:
        """Return True only when prior verified evidence actually satisfies a phase."""
        for evidence in task.evidence:
            if not isinstance(evidence, dict):
                continue

            if not evidence.get("success") or not evidence.get("verified"):
                continue

            tool = str(
                evidence.get("tool", "") or ""
            ).strip()

            if tool in tools:
                return True

        return False

    @staticmethod
    def _infer_source_target_from_evidence(
        task: AgentTask,
    ) -> Optional[str]:
        """Infer an existing Python source target from verified discovery evidence."""
        candidates: List[str] = []

        for evidence in task.evidence:
            if not isinstance(evidence, dict):
                continue

            if not evidence.get("success") or not evidence.get("verified"):
                continue

            tool = str(
                evidence.get("tool", "") or ""
            ).strip()

            if tool == "read_file":
                candidate_targets = [str(evidence.get("target", "") or "").strip()]
            elif tool in {"write_file", "edit_file", "delete_file"}:
                raw_target = str(evidence.get("target", "") or "").strip()
                candidate_targets = [raw_target.split("|||", 1)[0].strip()]
            elif tool in {
                "code_search",
                "code_diagnose",
                "list_files",
                "find_file",
            }:
                candidate_targets = []
            else:
                continue

            detail = str(
                evidence.get("detail", "") or ""
            )

            explicit_target = str(
                evidence.get("target", "") or ""
            ).strip()

            candidate_strings = []
            if tool == "read_file":
                candidate_strings.append(explicit_target)
            elif tool in {"write_file", "edit_file", "delete_file"}:
                candidate_strings.append(
                    explicit_target.split("|||", 1)[0].strip()
                )

            candidate_strings.extend(
                re.findall(
                    r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]*\.py)(?![A-Za-z0-9_.-])",
                    detail,
                )
            )

            for candidate in candidate_strings:
                normalized = candidate.strip()

                if not normalized or normalized in candidates:
                    continue

                lowered = normalized.lower()

                if (
                    ".before_" in lowered
                    or ".backup" in lowered
                    or ".bak" in lowered
                    or "backup" in lowered
                    or "__pycache__" in lowered
                    or ".jarvis_checkpoints" in lowered
                ):
                    continue

                if not lowered.endswith(".py"):
                    continue

                candidates.append(normalized)

        if not candidates:
            return None

        request_terms = {
            term
            for term in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]{3,}",
                str(task.request or "").lower(),
            )
            if term not in {
                "inspect",
                "find",
                "problem",
                "fix",
                "repair",
                "debug",
                "diagnose",
                "test",
                "browser",
            }
        }

        def score(path: str) -> tuple:
            lowered = path.lower()
            stem_terms = set(
                re.findall(
                    r"[a-z_][a-z0-9_]{3,}",
                    lowered,
                )
            )
            overlap = len(request_terms & stem_terms)

            domain_bonus = 0
            request_lower = str(task.request or "").lower()

            if "browser" in request_lower and "browser" in lowered:
                domain_bonus += 4

            if "automation" in request_lower and (
                "browser" in lowered or "automation" in lowered
            ):
                domain_bonus += 2

            return (
                overlap + domain_bonus,
                -lowered.count("_"),
                -len(lowered),
            )

        return max(candidates, key=score)

    @staticmethod
    def _latest_verified_code_test_evidence(
        task: AgentTask,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest successful, verified code-test evidence."""
        for evidence in reversed(task.evidence):
            if not isinstance(evidence, dict):
                continue

            if (
                str(evidence.get("tool", "") or "").strip()
                not in {"code_test", "code_diagnose"}
            ):
                continue

            if (
                evidence.get("success")
                and evidence.get("verified")
            ):
                return evidence

        return None

    @staticmethod
    def _latest_failed_execution_evidence(
        task: AgentTask,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest failed tool evidence entry."""
        for evidence in reversed(task.evidence):
            if not isinstance(evidence, dict):
                continue
            if evidence.get("success"):
                continue
            tool = str(evidence.get("tool", "") or "").strip()
            if tool:
                return evidence
        return None

    @staticmethod
    def _has_verified_git_diff_check(task: AgentTask) -> bool:
        """Return True once deterministic git diff validation has passed."""
        for evidence in reversed(task.evidence):
            if not isinstance(evidence, dict):
                continue
            if (
                str(evidence.get("tool", "") or "").strip() != "code_test"
                or not evidence.get("success")
                or not evidence.get("verified")
            ):
                continue

            data = evidence.get("data")
            if isinstance(data, dict):
                if str(data.get("mode", "") or "").strip().lower() == "git_diff_check":
                    return True

            detail = str(evidence.get("detail", "") or "").lower()
            if "git diff whitespace validation passed" in detail:
                return True

        return False

    @staticmethod
    def _requested_file_exists(requested_target: Optional[str]) -> bool:
        """Return True when a requested filename matches an existing project file."""
        if not requested_target:
            return False

        target_key = re.sub(
            r"[^a-z0-9]",
            "",
            str(requested_target).lower(),
        )

        if not target_key:
            return False

        try:
            project_root = Path.cwd().resolve()

            for path in iter_project_files(project_root):
                filename_key = re.sub(
                    r"[^a-z0-9]",
                    "",
                    path.name.lower(),
                )

                if filename_key == target_key:
                    return True

                # Nested explicit paths such as
                # tests/test_superpowers_engine.py must be matched against
                # their normalized relative path as well as the basename.
                try:
                    relative_key = re.sub(
                        r"[^a-z0-9]",
                        "",
                        path.relative_to(project_root).as_posix().lower(),
                    )
                except ValueError:
                    relative_key = ""

                if relative_key == target_key:
                    return True

        except OSError:
            return False

        return False


    @staticmethod
    def _infer_requested_file_target(
        request: str,
    ) -> Optional[str]:
        """Recover an explicitly requested project filename."""
        text = str(request or "").strip()
        if not text:
            return None

        extension_pattern = (
            r"(?:py|js|ts|tsx|jsx|html|css|json|yaml|yml|toml|md|lua|"
            r"java|cpp|c|h|go|rs|rb|php)"
        )

        # Whisper frequently transcribes ".py" as "dot py". Normalize that
        # spelling before extracting the explicitly requested filename.
        normalized_text = re.sub(
            rf"\s+\bdot\s+({extension_pattern})\b",
            lambda match: "." + match.group(1).lower(),
            text,
            flags=re.IGNORECASE,
        )

        # Prefer an explicit filename from the user's request. This preserves
        # spaces, hyphens, and casing instead of replacing the user's spelling
        # with a differently formatted physical filename found on disk.
        direct_match = re.search(
            rf"\b(?:diagnose\s+and\s+repair|repair|fix)\s+"
            rf"(?:(?:the|a|an)\s+)?"
            rf"(?:(?:intentional\s+)?(?:bug|issue|problem)\s+in\s+)?"
            rf"(.+?\.{extension_pattern})",
            normalized_text,
            flags=re.IGNORECASE,
        )

        if direct_match:
            candidate = " ".join(
                str(direct_match.group(1)).strip().split()
            )
            candidate = candidate.rstrip(".,!?;:")
            if candidate:
                return candidate

        # Recover an explicitly named nested project path first.
        # Requiring at least one directory separator prevents ordinary prose
        # containing the word "file" from becoming the target.
        nested_path_match = re.search(
            rf"(?<![A-Za-z0-9_.-])"
            rf"((?:[A-Za-z0-9_-]+[\\/])+"
            rf"[A-Za-z0-9_.-]+\.{extension_pattern})"
            rf"(?![A-Za-z0-9_.-])",
            normalized_text,
            flags=re.IGNORECASE,
        )

        if nested_path_match:
            candidate = str(
                nested_path_match.group(1)
            ).strip().rstrip(".,!?;:")
            if candidate:
                return candidate

        # Also support requests where the filename follows "target", "file",
        # or similar wording instead of a repair verb.
        command_match = re.search(
            rf"(?:target|file)\s+"
            rf"(.+?\.{extension_pattern})",
            normalized_text,
            flags=re.IGNORECASE,
        )

        if command_match:
            candidate = " ".join(
                str(command_match.group(1)).strip().split()
            ).rstrip(".,!?;:")
            if candidate:
                return candidate

        def normalized_key(value: str) -> str:
            return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

        request_key = normalized_key(normalized_text)

        # If the request did not contain a clean explicit filename, match
        # against real project files. This handles underscores, spaces,
        # hyphens, casing, and voice transcription artifacts safely.
        project_root = Path.cwd().resolve()
        matches = []

        try:
            for path in iter_project_files(project_root):
                filename_key = normalized_key(path.name)

                if (
                    filename_key
                    and len(filename_key) >= 5
                    and filename_key in request_key
                ):
                    matches.append(path.name)

                    if len(matches) > 1:
                        break
        except OSError:
            matches = []

        if len(matches) == 1:
            return matches[0]

        return None


    @staticmethod
    def _latest_verified_source_target(
        task: AgentTask,
    ) -> Optional[str]:
        """Return the latest verified read_file target from task evidence."""
        for evidence in reversed(task.evidence):
            if not isinstance(evidence, dict):
                continue

            if (
                str(evidence.get("tool", "") or "").strip()
                not in {"read_file", "find_file"}
            ):
                continue

            if not (
                evidence.get("success")
                and evidence.get("verified")
            ):
                continue

            target = str(
                evidence.get("target", "")
                or ""
            ).strip()

            if target:
                return target

        inferred = JarvisAgent._infer_source_target_from_evidence(task)

        if inferred:
            return inferred

        return None

    @staticmethod
    def _infer_diagnostic_source_target(
        task: AgentTask,
    ) -> Optional[str]:
        """Infer a real project source file from failed diagnostic evidence."""
        base = Path.cwd().resolve()
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
            ".jarvis_checkpoints",
        }

        candidates: List[str] = []

        for evidence in reversed(task.evidence):
            if not isinstance(evidence, dict):
                continue

            if str(evidence.get("tool", "") or "").strip() != "code_diagnose":
                continue

            if evidence.get("success"):
                continue

            detail = str(evidence.get("detail", "") or "")
            matches = re.findall(
                r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_./\\-]*\.py)(?![A-Za-z0-9_.-])",
                detail,
            )

            for raw_path in matches:
                normalized = (
                    raw_path.strip().strip("\"'")
                    .replace("\\", "/")
                )

                candidate = (base / normalized).resolve()

                try:
                    relative = candidate.relative_to(base)
                except ValueError:
                    continue

                if any(part.lower() in ignored for part in relative.parts):
                    continue

                if candidate.is_file():
                    relative_text = relative.as_posix()
                    if relative_text not in candidates:
                        candidates.append(relative_text)

        if len(candidates) == 1:
            return candidates[0]

        if candidates:
            request_lower = str(task.request or "").lower()

            def score(path: str) -> tuple:
                lowered = path.lower()
                score_value = 0

                if "browser" in request_lower and "browser" in lowered:
                    score_value += 4

                if "automation" in request_lower and (
                    "browser" in lowered or "automation" in lowered
                ):
                    score_value += 2

                return (score_value, -len(lowered))

            return max(candidates, key=score)

        return None


    def _build_phase_fallback_plan(
        self,
        task: AgentTask,
        require_code_read: bool = False,
        require_code_test: bool = False,
        require_code_diagnose: bool = False,
        require_repair_plan: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Build a deterministic minimal plan when a required phase dead-ends."""
        target = self._latest_verified_source_target(task)

        # A failed project-wide diagnostic can identify a concrete source file
        # before any read_file phase has executed. Resolve that filename against
        # the real project tree so the next phase can inspect it deterministically.
        if not target and require_code_read:
            target = self._infer_diagnostic_source_target(task)

        if not target and require_code_read:
            target = self._infer_requested_file_target(task.request)

        if require_code_diagnose and target:
            return {
                "goal": "targeted diagnostic",
                "jarvis_internal_phase": True,
                "steps": [
                    {
                        "tool": "code_diagnose",
                        "argument": json.dumps(
                            {
                                "path": target,
                                "run_tests": False,
                                "run_lint": False,
                                "run_types": False,
                            }
                        ),
                    }
                ],
            }

        if require_code_test and target:
            request_lower = str(task.request or "").lower()
            smoke_test = (
                "browser" in request_lower
                or "automation" in request_lower
            ) and target.lower().endswith("browser_controller.py")

            return {
                "goal": (
                    "browser runtime diagnostic"
                    if smoke_test
                    else "diagnostic validation"
                ),
                "jarvis_internal_phase": True,
                "steps": [
                    {
                        "tool": "code_test",
                        "argument": json.dumps(
                            {
                                "mode": (
                                    "browser_smoke"
                                    if smoke_test
                                    else "compile"
                                ),
                                "path": target,
                            }
                        ),
                    }
                ],
            }

        if require_code_read and target:
            return {
                "goal": "inspect verified target source",
                "jarvis_internal_phase": True,
                "steps": [
                    {
                        "tool": "read_file",
                        "argument": target,
                    }
                ],
            }

        # Initial targeted repair fallback. If the general planner cannot
        # produce a usable plan twice, recover the explicitly named file
        # deterministically and let the normal discovery state machine take
        # over from there.
        if (
            not require_code_read
            and not require_code_test
            and not require_code_diagnose
            and not require_repair_plan
            and is_software_repair_request(task.request)
        ):
            requested_target = self._infer_requested_file_target(
                task.request
            )

            if requested_target:
                return {
                    "goal": "discover requested repair target",
                    "jarvis_internal_phase": True,
                    "steps": [
                        {
                            "tool": "find_file",
                            "argument": requested_target,
                        }
                    ],
                }

        return None

    def plan_task(
        self,
        task: AgentTask,
        history_text: str = "",
        planning_request: Optional[str] = None,
        require_repair_plan: bool = False,
        require_change_plan: bool = False,
        require_code_read: bool = False,
        require_code_test: bool = False,
        require_code_diagnose: bool = False,
    ) -> AgentTask:

        task.status = "planning"

        phase_marker = ""
        if require_repair_plan:
            phase_marker = "[JARVIS_INTERNAL_PHASE:REPAIR]\n"
        elif require_change_plan:
            phase_marker = "[JARVIS_INTERNAL_PHASE:CHANGE]\n"
        elif require_code_diagnose:
            phase_marker = "[JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]\n"
        elif require_code_test:
            phase_marker = "[JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]\n"
        elif require_code_read:
            phase_marker = "[JARVIS_INTERNAL_PHASE:SOURCE_READ]\n"

        base_planning_request = (
            planning_request
            if planning_request is not None
            else task.request
        )

        request_for_planner = (
            phase_marker + base_planning_request
        )

        logger.info(
            "JARVIS AGENT: Planning task "
            f"{task.task_id}"
        )

        # A self-diagnostic repair request is a special case: the target is
        # the JARVIS project itself, so there is no single filename to discover.
        # Start with a deterministic full-project diagnostic instead of asking
        # the general planner to invent a workflow. If the diagnostic finds
        # actionable failures, the existing evidence-driven repair handoff
        # will take over.
        if (
            planning_request is None
            and is_explicit_self_repair_request(task.request)
            and not (
                require_repair_plan
                or require_code_read
                or require_code_test
                or require_code_diagnose
            )
        ):
            deterministic_plan = {
                "goal": "full JARVIS project diagnostic",
                "jarvis_internal_phase": True,
                "steps": [
                    {
                        "tool": "code_diagnose",
                        "argument": json.dumps(
                            {
                                "path": "",
                                "run_tests": True,
                                "run_lint": True,
                                "run_types": False,
                                "timeout": 180,
                            }
                        ),
                    }
                ],
            }

            deterministic_plan = validate_plan(
                deterministic_plan
            )

            diagnostic_issues = assess_plan(
                task.request,
                deterministic_plan,
                require_modification=False,
                require_code_diagnose=True,
            )

            if not diagnostic_issues:
                logger.info(
                    "JARVIS AGENT: Self-repair request detected; "
                    "starting deterministic full-project diagnostic "
                    "without planner call."
                )
                task = self._install_phase_plan(
                    task,
                    deterministic_plan,
                )
                task.observations.append(
                    "Deterministic self-repair entry point: full-project "
                    "diagnostic started without an LLM planning call."
                )
                return task

        # A repair request that explicitly names an existing file does not
        # need an LLM to rediscover the entry point. Start with deterministic
        # file discovery; the LLM remains responsible for the evidence-based
        # repair decision after diagnosis.
        if (
            planning_request is None
            and is_software_repair_request(task.request)
            and not (
                require_repair_plan
                or require_change_plan
                or require_code_read
                or require_code_test
                or require_code_diagnose
            )
        ):
            requested_target = self._infer_requested_file_target(
                task.request
            )

            if self._requested_file_exists(requested_target):
                deterministic_plan = self._build_phase_fallback_plan(
                    task
                )

                if deterministic_plan is not None:
                    logger.info(
                        "JARVIS AGENT: Explicit existing repair target found; "
                        "starting deterministic discovery without planner call."
                    )
                    task = self._install_phase_plan(
                        task,
                        deterministic_plan,
                    )
                    task.observations.append(
                        "Deterministic repair entry point: explicit existing "
                        "target file was discovered without an LLM planning call."
                    )
                    return task

        # Explicit software change requests with a named existing file start
        # from deterministic source evidence. The planner is reserved for the
        # implementation decision after the actual file has been read.
        if (
            planning_request is None
            and is_software_change_request(task.request)
            and not is_software_repair_request(task.request)
            and not (
                require_repair_plan
                or require_change_plan
                or require_code_read
                or require_code_test
                or require_code_diagnose
            )
        ):
            requested_target = self._infer_requested_file_target(
                task.request
            )

            if self._requested_file_exists(requested_target):
                deterministic_plan = {
                    "goal": "inspect requested change target",
                    "jarvis_internal_phase": True,
                    "steps": [
                        {
                            "tool": "read_file",
                            "argument": requested_target,
                        }
                    ],
                }

                logger.info(
                    "JARVIS AGENT: Explicit existing change target found; "
                    "starting deterministic source inspection without planner call."
                )
                task = self._install_phase_plan(
                    task,
                    deterministic_plan,
                )
                task.observations.append(
                    "Deterministic change entry point: explicit existing "
                    "target file was inspected without an LLM planning call."
                )
                return task

        # Give an incomplete plan one corrective planning pass in general.
        # For a repair request that already names an existing target file,
        # deterministic discovery can take over immediately after the first
        # bad planner response; there is no value in asking the same model
        # to rediscover a filename it already received.
        max_plan_repairs = 1

        if (
            planning_request is None
            and is_software_repair_request(task.request)
            and not (
                require_repair_plan
                or require_code_read
                or require_code_test
                or require_code_diagnose
            )
        ):
            requested_target = self._infer_requested_file_target(task.request)
            if requested_target and Path(requested_target).is_file():
                max_plan_repairs = 0

        for planning_attempt in range(
            max_plan_repairs + 1
        ):

            try:

                plan = self.planner(
                    request_for_planner,
                    active_context=(
                        task.active_context
                    ),
                    history_text=history_text,
                )

                plan = validate_plan(
                    plan
                )

                # Product research must always operate on the original user
                # request. During replanning, request_for_planner contains
                # recovery/evidence instructions intended only for the LLM.
                # Never allow that temporary planner context to leak into the
                # product_research tool argument.
                if isinstance(plan, dict):
                    steps = plan.get("steps", [])
                    if isinstance(steps, list):
                        for step in steps:
                            if not isinstance(step, dict):
                                continue

                            if (
                                str(
                                    step.get("tool", "")
                                    or ""
                                ).strip()
                                != "product_research"
                            ):
                                continue

                            step["argument"] = json.dumps(
                                {
                                    "request": task.request,
                                }
                            )

                            task.observations.append(
                                "Product research argument normalized to the "
                                "original user request before execution."
                            )

            except Exception as exc:

                logger.exception(
                    "JARVIS AGENT: "
                    "Planning failed"
                )

                task.status = "failed"

                task.error = str(
                    exc
                )

                self.state[
                    "last_error"
                ] = str(
                    exc
                )

                self.state[
                    "last_status"
                ] = task.status

                return task

            candidate_has_mutation = any(
                (
                    str(step.get("tool", "") or "").strip()
                    in {"write_file", "edit_file", "delete_file"}
                    or is_roblox_mutation_tool(
                        str(step.get("tool", "") or "").strip()
                    )
                )
                for step in plan.get("steps", [])
                if isinstance(step, dict)
            )

            # Superpowers change workflows are mutation-bearing by definition.
            # Do not allow a read-only candidate plan to complete an explicit
            # feature/change request after the planner has selected TDD.
            superpowers_requires_mutation = (
                bool(task.superpowers)
                and bool(task.superpowers.get("requires_tdd"))
                and not bool(task.superpowers.get("requires_debugging"))
            )

            enforce_change_workflow = (
                require_repair_plan
                or superpowers_requires_mutation
                or (
                    (
                        is_software_change_request(task.request)
                        or is_software_repair_request(task.request)
                    )
                    and candidate_has_mutation
                )
            )

            plan_issues = assess_plan(
                task.request,
                plan,
                require_modification=enforce_change_workflow,
                require_code_read=require_code_read,
                require_code_test=require_code_test,
                require_code_diagnose=require_code_diagnose,
                allow_prior_evidence=(
                    (
                        self._has_verified_evidence(
                            task,
                            {"read_file"},
                        )
                        if require_code_read
                        else
                        self._has_verified_evidence(
                            task,
                            {
                                "code_search",
                                "read_file",
                                "list_files",
                                "find_file",
                            },
                        )
                    )
                    if (
                        require_repair_plan
                        or require_change_plan
                        or require_code_read
                        or require_code_test
                        or require_code_diagnose
                    )
                    else False
                ),
            )

            if plan_issues:

                logger.warning(
                    "JARVIS AGENT: Planner quality gate rejected "
                    f"attempt {planning_attempt + 1}: "
                    + " | ".join(plan_issues)
                )

                task.observations.extend(
                    [
                        "Planner quality gate: "
                        + issue
                        for issue in plan_issues
                    ]
                )

                if planning_attempt < max_plan_repairs:

                    correction_lines = [
                        "The previous planner output was incomplete.",
                        "Do not execute the previous plan.",
                        "",
                        f"Original request: {task.request}",
                        "",
                        "Planner quality problems:",
                    ]

                    correction_lines.extend(
                        f"- {issue}"
                        for issue in plan_issues
                    )

                    correction_lines.extend(
                        [
                            "",
                            "Previous candidate plan:",
                            str(plan),
                            "",
                            "Produce a corrected plan as JSON.",
                            (
                                "For the repair phase, use the verified "
                                "evidence from the previous phase. Do not "
                                "repeat generic discovery when the evidence "
                                "already identifies the relevant source. "
                                "The corrected plan must contain a "
                                "code_checkpoint before modification, an "
                                "appropriate file modification, and "
                                "code_test afterward."
                                if require_repair_plan
                                else
                                (
                                    "For the change implementation phase, "
                                    "use the verified source evidence above. "
                                    "Do not repeat generic discovery. Include "
                                    "code_checkpoint before modification, an "
                                    "appropriate file change, and code_test "
                                    "afterward."
                                    if require_change_plan
                                    else
                                    "For the discovery phase, inspect the "
                                    "relevant project code and do not modify "
                                    "files yet."
                                )
                            ),
                            (
                                "The corrected plan must include the "
                                "required read_file step before proceeding."
                                if require_code_read
                                else
                                (
                                    "The corrected plan must include "
                                    "code_diagnose before proceeding."
                                    if require_code_diagnose
                                    else
                                    (
                                        "The corrected plan must include "
                                        "code_test before proceeding."
                                        if require_code_test
                                        else
                                        "Use the observed code and do not "
                                        "invent filenames."
                                    )
                                )
                            ),
                            "Do not invent filenames. Discover the actual "
                            "target file before editing.",
                        ]
                    )

                    if task.evidence:
                        correction_lines.extend(
                            [
                                "",
                                "VERIFIED PRIOR EVIDENCE:",
                                self._build_evidence_packet(task),
                                "",
                                "This evidence is authoritative for the "
                                "next repair-planning attempt. Use it to "
                                "choose the existing target and smallest "
                                "safe change. Do not restart project-wide "
                                "discovery just because the previous "
                                "candidate plan was rejected.",
                            ]
                        )

                    request_for_planner = (
                        phase_marker
                        + "\n".join(correction_lines)
                    )

                    continue

                fallback_plan = self._build_phase_fallback_plan(
                    task,
                    require_code_read=require_code_read,
                    require_code_test=require_code_test,
                    require_code_diagnose=require_code_diagnose,
                    require_repair_plan=require_repair_plan,
                )

                if fallback_plan is not None:
                    fallback_plan = validate_plan(fallback_plan)
                    fallback_issues = assess_plan(
                        task.request,
                        fallback_plan,
                        require_modification=(
                            require_repair_plan or require_change_plan
                        ),
                        require_code_read=require_code_read,
                        require_code_test=require_code_test,
                        require_code_diagnose=require_code_diagnose,
                        allow_prior_evidence=(
                            (
                                self._has_verified_evidence(
                                    task,
                                    {"read_file"},
                                )
                                if require_code_read
                                else
                                self._has_verified_evidence(
                                    task,
                                    {
                                        "code_search",
                                        "read_file",
                                        "list_files",
                                        "find_file",
                                    },
                                )
                            )
                            if (
                                require_repair_plan
                                or require_change_plan
                                or require_code_read
                                or require_code_test
                                or require_code_diagnose
                            )
                            else False
                        ),
                    )

                    if not fallback_issues:
                        logger.info(
                            "JARVIS AGENT: Using deterministic fallback "
                            "for the required planning phase."
                        )
                        task.observations.append(
                            "Planner fallback: generated a deterministic "
                            "required-phase validation step from verified "
                            "evidence."
                        )
                        task.planner_result = fallback_plan
                        task.goal = str(
                            fallback_plan.get("goal", "") or ""
                        )
                        task.steps = self._build_steps(
                            fallback_plan
                        )
                        task.status = "ready"
                        self.state["last_goal"] = task.goal
                        self.state["last_status"] = task.status
                        return task

                task.status = "failed"
                task.error = (
                    "Planner quality validation failed: "
                    + " ".join(plan_issues)
                )

                self.state[
                    "last_error"
                ] = task.error

                self.state[
                    "last_status"
                ] = task.status

                return task

            task.planner_result = plan

            task.goal = str(
                plan.get(
                    "goal",
                    "",
                )
                or ""
            )

            task.steps = self._build_steps(
                plan
            )

            self.state[
                "last_goal"
            ] = task.goal

            break

        if not task.steps:

            task.status = "conversation"

            self.state[
                "last_status"
            ] = task.status

            logger.info(
                "JARVIS AGENT: "
                "No executable tools required."
            )

            return task

        task.status = "ready"

        self.state[
            "last_status"
        ] = task.status

        logger.info(
            "JARVIS AGENT: Planned "
            f"{len(task.steps)} step(s)"
        )

        for index, step in enumerate(
            task.steps,
            start=1,
        ):

            logger.info(
                "JARVIS AGENT STEP "
                f"{index}: "
                f"{step.tool}"
                f"({step.argument})"
            )

        return task

    def _build_roblox_repair_request(
        self,
        task: AgentTask,
    ) -> str:
        lines = [
            "The previous Roblox Studio investigation has completed successfully.",
            "Use the verified Studio evidence below to produce the smallest safe game repair.",
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            self._build_evidence_packet(task),
            "",
            "ROBLOX REPAIR RULES:",
            "1. Do not use JARVIS filesystem tools for Roblox Studio code.",
            "2. Use exact instance paths returned by verified Roblox evidence.",
            "3. Read the relevant Luau source before modifying it.",
            "4. Prefer edit_script_lines for a targeted fix.",
            "5. After the mutation, start a playtest and inspect playtest/output-log evidence.",
            "6. Iterate from real Roblox errors instead of inventing failures.",
            "7. Do not claim success until the Roblox behavior is verified.",
            "",
            "Return ONLY JSON.",
        ]

        return "\n".join(lines)


    def _build_change_repair_request_after_failure(
        self,
        task: AgentTask,
    ) -> str:
        """Build a focused corrective handoff after failed change validation."""
        return "\n".join([
            "The requested software change was attempted and validation failed.",
            "The project was restored to the pre-change checkpoint.",
            "Use the verified source and failure evidence below to correct the implementation.",
            "",
            f"Original request: {task.request}",
            "",
            self._build_evidence_packet(task, max_chars=12000),
            "",
            "CHANGE RECOVERY RULES:",
            "1. Treat the failed test or edit error as authoritative evidence.",
            "2. Make the smallest safe correction that satisfies the original request.",
            "3. Create code_checkpoint before the corrective mutation.",
            "4. Use edit_file/write_file only after inspecting the verified source.",
            "5. Run the focused code_test that validates the original request.",
            "6. Do not repeat the failed edit blindly.",
            "7. Return executable JSON only.",
            "",
            "Return ONLY JSON.",
        ])

    def _build_change_request_after_source(
        self,
        task: AgentTask,
    ) -> str:
        """Build a focused implementation request from verified source evidence."""
        return "\n".join([
            "The deterministic source-inspection phase has completed successfully.",
            "Use the verified source evidence below to implement the original software change.",
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            self._build_evidence_packet(task),
            "",
            "CHANGE IMPLEMENTATION RULES:",
            "1. Treat verified source evidence as authoritative.",
            "2. Make the smallest safe change that satisfies the original request.",
            "3. Include code_checkpoint before the first file modification.",
            "4. For a regression-test request, update the named test file and run the relevant focused tests afterward.",
            "5. Use edit_file/write_file only after inspecting the source evidence.",
            "6. Run code_test after the final file modification.",
            "7. Do not invent filenames, functions, or behavior not supported by the evidence.",
            "",
            "Return ONLY JSON.",
        ])

    def _build_repair_request_after_discovery(
        self,
        task: AgentTask,
    ) -> str:

        has_failed_diagnostic = any(
            isinstance(evidence, dict)
            and str(evidence.get("tool", "") or "").strip() == "code_diagnose"
            and not evidence.get("success")
            for evidence in task.evidence
        )

        if has_failed_diagnostic:
            opening = (
                "The previous diagnostic phase produced actionable "
                "failure evidence. You are now handing that evidence "
                "directly to the repair planner."
            )
        else:
            opening = (
                "The previous investigation phase has completed successfully. "
                "You are now handing evidence to the repair planner."
            )

        lines = [
            opening,
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            self._build_evidence_packet(task),
            "",
            "REPAIR PHASE RULES:",
            "1. Do not repeat generic discovery or list the project again.",
            "2. Use the concrete evidence above to identify the defect and target file.",
            "3. If source content is not already present in verified read_file evidence, "
            "include one focused read_file for the verified target before editing.",
            "4. Otherwise create a repair plan with code_checkpoint BEFORE the first modification.",
            "5. Modify the existing target with the smallest safe change.",
            "6. Run code_test AFTER the modification.",
            "7. Never claim success unless validation succeeds.",
            "8. Do not invent filenames, functions, or errors that are not supported by the evidence.",
            "",
            "Return ONLY JSON.",
        ]

        return "\n".join(lines)


    # ======================================================
    # Build Replan Request
    # ======================================================

    def _build_replan_request(
        self,
        task: AgentTask,
    ) -> str:

        lines = [
            "Replan the task below because the previous plan "
            "did not complete successfully.",
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            self._build_evidence_packet(task),
        ]

        # Include current browser state when available.
        browser_state = task.active_context.get(
            "browser_state",
            {},
        )

        if isinstance(browser_state, dict):

            if browser_state.get("success"):
                lines.extend(
                    [
                        "",
                        "Current browser state:",
                        (
                            "URL: "
                            f"{browser_state.get('url', '')}"
                        ),
                        (
                            "Title: "
                            f"{browser_state.get('title', '')}"
                        ),
                    ]
                )

                pages = browser_state.get("open_pages")
                if not isinstance(pages, list):
                    pages = browser_state.get("pages")

                if isinstance(pages, list) and pages:
                    lines.append(
                        "Open browser pages:"
                    )

                    for page in pages:
                        if not isinstance(page, dict):
                            continue

                        page_url = page.get(
                            "url",
                            "",
                        )

                        page_title = page.get(
                            "title",
                            "",
                        )

                        lines.append(
                            f"- {page_title!r} — "
                            f"{page_url!r}"
                        )

            elif browser_state.get("error"):
                lines.extend(
                    [
                        "",
                        "Browser state observation error:",
                        str(
                            browser_state.get(
                                "error"
                            )
                        ),
                    ]
                )

        # Make the recovery history explicit so the planner does not blindly
        # repeat a strategy that already failed.
        browser_recoveries = []

        for evidence in task.evidence:
            if not isinstance(evidence, dict):
                continue

            recovery = evidence.get("browser_recovery")
            if not isinstance(recovery, dict):
                continue

            browser_recoveries.append(
                recovery
            )

        if browser_recoveries:
            lines.extend(
                [
                    "",
                    "Browser recovery history:",
                    (
                        "Do not blindly repeat a browser strategy already "
                        "recorded as failed. Treat successful observations as "
                        "the current browser state and choose a meaningfully "
                        "different action when recovery is still required."
                    ),
                ]
            )

            for recovery_index, recovery in enumerate(
                browser_recoveries,
                start=1,
            ):
                recovered_by = str(
                    recovery.get("recovered_by", "") or ""
                ).strip()

                observed_before = recovery.get("observed_before")
                observed_after = recovery.get("observed_after")

                summary_parts = [
                    f"Recovery {recovery_index}:",
                    (
                        "method="
                        + (recovered_by or "unspecified")
                    ),
                ]

                if isinstance(observed_before, dict):
                    summary_parts.append(
                        "before="
                        + repr(
                            {
                                "url": observed_before.get("url", ""),
                                "title": observed_before.get("title", ""),
                            }
                        )
                    )

                if isinstance(observed_after, dict):
                    summary_parts.append(
                        "after="
                        + repr(
                            {
                                "url": observed_after.get("url", ""),
                                "title": observed_after.get("title", ""),
                            }
                        )
                    )

                if recovery.get("attempts") is not None:
                    summary_parts.append(
                        f"attempts={recovery.get('attempts')}"
                    )

                if recovery.get("recovery_count") is not None:
                    summary_parts.append(
                        f"retries={recovery.get('recovery_count')}"
                    )

                lines.append(
                    " ".join(summary_parts)
                )

        lines.extend(
            [
                "",
                "Previous execution result:",
                str(
                    task.execution_result
                    or ""
                ),
                "",
                "Previous error:",
                str(
                    task.error
                    or ""
                ),
                "",
                "Create a new plan that attempts to "
                "complete the original goal from the "
                "current computer state.",
            ]
        )

        return "\n".join(lines)

    # ======================================================
    # Record Execution Observation
    # ======================================================

    def _record_execution_observation(
        self,
        task: AgentTask,
        attempt: int,
        execution_result: Any,
    ) -> None:
        """
        Record execution observations and capture actual
        browser state whenever browser tools were involved.
        """
        from tool_executor import get_last_execution_trace

        trace = get_last_execution_trace()

        result_text = self._compact_text(
            self._extract_tool_data(execution_result),
            limit=1600,
        )

        # Keep high-level observations concise. Detailed source/test data
        # is stored in the structured evidence packet below.
        task.observations.append(
            f"Execution attempt {attempt}: {result_text}"
        )

        # Structured step observations and bounded evidence.
        for entry in trace:
            index = entry.get("index", -1)
            tool = str(
                entry.get("tool", "")
                or ""
            ).strip()
            argument = str(
                entry.get("argument", "")
                or ""
            ).strip()
            status = entry.get("status", "")
            verified = bool(
                entry.get("verified", False)
            )
            message = entry.get("message", "")
            success = entry.get("success")
            raw_result = entry.get("result")

            if success is True:
                outcome = "completed"
            elif success is False:
                outcome = "failed"
            else:
                outcome = status or "unknown"

            verification = (
                "verified"
                if verified
                else "unverified"
            )

            detail = (
                f"Execution attempt {attempt}: "
                f"Step {index + 1} {tool}"
            )

            if argument:
                detail += f"({argument})"

            detail += (
                f" {outcome} {verification}"
            )

            concise_message = self._compact_text(
                (
                    "Source inspection completed."
                    if tool == "read_file" and success
                    else
                    "Project code search completed."
                    if tool == "code_search" and success
                    else
                    message
                ),
                limit=800,
            )

            if concise_message:
                detail += f" — {concise_message}"

            task.observations.append(detail)

            # Build structured evidence for the next planner phase.
            data = self._extract_tool_data(raw_result)

            evidence = {
                "attempt": attempt,
                "tool": tool,
                "target": argument,
                "success": success is True,
                "verified": verified,
                "detail": "",
            }

            if tool == "read_file" and success:
                source = str(data or "")
                evidence["detail"] = (
                    "Source excerpt with line numbers:\n"
                    + self._source_excerpt(
                        source,
                        task.request,
                    )
                )

            elif tool == "code_search":
                evidence["detail"] = self._compact_text(
                    data,
                    limit=6000,
                )

            elif tool in {"code_test", "code_diagnose", "dev_command"}:
                if isinstance(data, dict):
                    parts = [
                        str(
                            data.get("message")
                            or "Code test completed."
                        ),
                        f"Mode: {data.get('mode', '')}",
                        f"Path: {data.get('path', '')}",
                    ]

                    stdout = str(
                        data.get("stdout")
                        or ""
                    ).strip()

                    stderr = str(
                        data.get("stderr")
                        or ""
                    ).strip()

                    if stdout:
                        parts.append(
                            "stdout:\n"
                            + self._compact_text(
                                stdout,
                                limit=3500,
                            )
                        )

                    if stderr:
                        parts.append(
                            "stderr:\n"
                            + self._compact_text(
                                stderr,
                                limit=3500,
                            )
                        )

                    evidence["detail"] = "\n".join(parts)

                else:
                    evidence["detail"] = self._compact_text(
                        data,
                        limit=5000,
                    )

                if tool == "dev_command" and isinstance(data, dict):
                    command = str(data.get("command") or "").strip()
                    stdout = str(data.get("stdout") or "").strip()
                    stderr = str(data.get("stderr") or "").strip()
                    evidence["detail"] = "\n".join([
                        "Developer command: " + command,
                        "Status: " + str(data.get("message") or ""),
                        "stdout: " + self._compact_text(stdout, limit=3500),
                        "stderr: " + self._compact_text(stderr, limit=3500),
                    ])

                if tool == "code_diagnose" and isinstance(data, dict):
                    failures = data.get("failures")
                    if isinstance(failures, list) and failures:
                        evidence["detail"] += (
                            "\nActionable failures:\n"
                            + self._compact_text(
                                "\n".join(str(item) for item in failures),
                                limit=5000,
                            )
                        )

            else:
                evidence["detail"] = self._compact_text(
                    message,
                    limit=1600,
                )

            # Preserve bounded structured result data for Autonomy Kernel v2.
            # Concise messages are useful for logs, but information-seeking
            # answers need the actual tool payload as evidence.
            if data is not None:
                try:
                    serialized = json.dumps(
                        data,
                        ensure_ascii=False,
                        default=str,
                    )
                except Exception:
                    serialized = str(data)

                if len(serialized) <= 9000:
                    evidence["data"] = data
                else:
                    evidence["data"] = (
                        serialized[:9000]
                        + "\n... [structured evidence truncated by JARVIS] ..."
                    )
            task.evidence.append(evidence)

        # Capture actual browser state.
        if _is_browser_trace(trace):
            browser_state = _capture_browser_state()

            task.active_context["browser_state"] = browser_state

            if browser_state.get("success"):
                url = str(browser_state.get("url", "") or "")
                title = str(browser_state.get("title", "") or "")

                task.active_context["browser_url"] = url
                task.active_context["browser_title"] = title

                task.observations.append(
                    "Browser state after execution: "
                    f"title={title!r}, url={url!r}"
                )

            else:
                error = browser_state.get(
                    "error",
                    "Unknown browser-state error",
                )

                task.observations.append(
                    "Browser state observation failed: "
                    f"{error}"
                )

            # Preserve state-aware recovery evidence from the executor.
            # This gives Agent Core concrete information about what was tried
            # and what the browser looked like during recovery.
            for entry in trace:
                if not isinstance(entry, dict):
                    continue

                raw_result = entry.get("result")
                result_data = self._extract_tool_data(raw_result)

                if not isinstance(result_data, dict):
                    continue

                recovery = result_data.get("recovery")
                if not isinstance(recovery, dict):
                    continue

                evidence = {
                    "attempt": attempt,
                    "tool": str(entry.get("tool", "") or "").strip(),
                    "target": str(entry.get("argument", "") or "").strip(),
                    "success": bool(entry.get("success") is True),
                    "verified": bool(entry.get("verified", False)),
                    "detail": "",
                    "browser_recovery": {},
                }

                recovered_by = str(
                    recovery.get("recovered_by", "") or ""
                ).strip()

                if recovered_by:
                    evidence["browser_recovery"][
                        "recovered_by"
                    ] = recovered_by

                observed_before = recovery.get("observed_before")
                if isinstance(observed_before, dict):
                    evidence["browser_recovery"][
                        "observed_before"
                    ] = {
                        "url": str(
                            observed_before.get("url", "") or ""
                        ),
                        "title": str(
                            observed_before.get("title", "") or ""
                        ),
                    }

                observed_after = recovery.get("observed_after")
                if isinstance(observed_after, dict):
                    evidence["browser_recovery"][
                        "observed_after"
                    ] = {
                        "url": str(
                            observed_after.get("url", "") or ""
                        ),
                        "title": str(
                            observed_after.get("title", "") or ""
                        ),
                    }

                attempt_count = entry.get("attempts")
                recovery_count = entry.get("recovery_count")

                evidence["browser_recovery"]["attempts"] = (
                    attempt_count
                )
                evidence["browser_recovery"]["recovery_count"] = (
                    recovery_count
                )

                evidence["detail"] = (
                    "Browser recovery: "
                    + self._compact_text(
                        recovery,
                        limit=1800,
                    )
                )

                task.evidence.append(evidence)

    @staticmethod
    def _failure_is_retryable() -> tuple[bool, str]:
        """Inspect the execution trace for an explicit retryability contract."""
        try:
            from tool_executor import get_last_execution_trace

            trace = get_last_execution_trace()
        except Exception:
            return True, ""

        for entry in reversed(trace or []):
            if not isinstance(entry, dict):
                continue

            if entry.get("success") is not False:
                continue

            raw_result = entry.get("result")
            data = getattr(raw_result, "data", None)

            if data is None:
                data = raw_result

            if isinstance(data, dict) and "retryable" in data:
                retryable = bool(data.get("retryable"))
                message = str(
                    data.get("message")
                    or data.get("error")
                    or entry.get("message")
                    or ""
                ).strip()
                return retryable, message

            if "retryable" in entry:
                retryable = bool(entry.get("retryable"))
                message = str(
                    entry.get("message")
                    or ""
                ).strip()
                return retryable, message

        return True, ""


    def _apply_step_status(
        self,
        task: AgentTask,
        success: bool,
        result: Any,
    ) -> None:

        result_text = str(
            result
            or ""
        ).strip()

        # ----------------------------------------------------
        # Prefer exact per-step execution trace.
        # ----------------------------------------------------

        try:

            from tool_executor import (
                get_last_execution_trace,
            )

            trace = get_last_execution_trace()

        except Exception:

            trace = []

        if trace:

            for entry in trace:

                raw_index = entry.get(
                    "index",
                    0,
                )

                try:
                    index = int(
                        raw_index
                    ) - 1
                except Exception:
                    continue

                if index < 0 or index >= len(
                    task.steps
                ):
                    continue

                step = task.steps[index]

                trace_attempts = entry.get("attempts", 1)
                try:
                    trace_attempts = max(1, int(trace_attempts or 1))
                except (TypeError, ValueError):
                    trace_attempts = 1

                step.attempts = max(
                    step.attempts + 1,
                    trace_attempts,
                )

                step.result = entry.get(
                    "result"
                )

                step.observation = str(
                    entry.get(
                        "message",
                        "",
                    )
                    or ""
                )

                step.verified = bool(
                    entry.get(
                        "verified",
                        False,
                    )
                )

                entry_success = bool(
                    entry.get(
                        "success",
                        False,
                    )
                )

                entry_status = str(
                    entry.get(
                        "status",
                        "",
                    )
                ).lower()

                if (
                    entry_success
                    and entry_status != "failed"
                ):

                    step.status = "completed"

                    if not step.verified:
                        step.verified = True

                    step.error = None

                else:

                    step.status = "failed"

                    step.error = str(
                        entry.get(
                            "message",
                            result_text,
                        )
                        or result_text
                    )

                task.current_step = index

            return

        # ----------------------------------------------------
        # Legacy fallback.
        #
        # Only mark the final step rather than every step.
        # This prevents one failure from incorrectly marking
        # the entire plan as failed.
        # ----------------------------------------------------

        if task.steps:

            index = min(
                max(
                    task.current_step,
                    0,
                ),
                len(task.steps) - 1,
            )

            step = task.steps[index]

            task.current_step = index
            step.attempts += 1
            step.result = result
            step.observation = result_text

            if success:

                step.status = "completed"
                step.verified = True
                step.error = None

            else:

                step.status = "failed"
                step.error = result_text

    # ======================================================
    # Execute Plan Once
    # ======================================================

    def _execute_once(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
    ) -> str:

        if not task.planner_result:
            return "failed"

        task.status = "executing"

        # Each execution attempt owns its own staged completion message.
        # Clear any prior phase's message before starting the next attempt.
        try:
            task_state.clear_final_speech()
        except Exception:
            pass

        logger.info(
            "JARVIS AGENT: Executing plan "
            f"(attempt={task.replan_count + 1})"
        )

        # The executor processes the complete plan, but keep
        # a sensible current-step baseline for legacy fallback.
        task.current_step = 0

        try:

            result = self.executor(
                task.planner_result,
                active_context,
                task_state,
                speak_callback,
            )

            task.execution_result = result

            result_text = str(
                result
                or ""
            ).strip().lower()

            self._record_execution_observation(
                task,
                task.replan_count + 1,
                result,
            )

            if result_text == "cancelled":

                task.status = "cancelled"

                for step in task.steps:

                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "cancelled"

                return "cancelled"

            if result_text == "interrupted":

                task.status = "failed"

                task.error = (
                    "Execution was interrupted."
                )

                return "failed"

            if result_text == "failed":

                self._apply_step_status(
                    task,
                    success=False,
                    result=result,
                )

                task.error = str(
                    result
                )

                # Cancellation must win over any recovery/replan attempt.
                # In particular, do not start a new Ollama planning call after
                # the user has already requested shutdown/cancellation.
                try:
                    if task_state.is_cancelled():
                        task.status = "cancelled"
                        task.completed_at = time.time()
                        self.state["last_status"] = task.status
                        self.state["last_error"] = "Cancellation requested by the user."
                        self._record_autonomy_episode(task)
                        task_state.set_progress_callback(None)
                        return task
                except Exception:
                    pass

                retryable, retry_message = self._failure_is_retryable()

                if not retryable:
                    if retry_message:
                        task.error = retry_message

                    task.status = "failed"
                    task.completed_at = time.time()

                    self.state["last_result"] = (
                        task.execution_result
                    )
                    self.state["last_status"] = task.status
                    self.state["last_error"] = task.error
                    self.state["replans"] = task.replan_count

                    logger.warning(
                        "JARVIS AGENT: Execution failed with "
                        "retryable=False; stopping recovery loop."
                    )

                    self._announce(
                        task.error or "I wasn't able to complete the task.",
                        speak_callback,
                    )

                    task_state.set_progress_callback(None)
                    return "failed"

                return "failed"

            if result_text == "done":

                # Autonomous software repair/change phases must be backed by
                # the executor's structured trace. A legacy/custom executor
                # that returns "done" without a trace cannot prove that any
                # step ran, so fail closed instead of allowing the repair
                # state machine to re-enter deterministic phases forever.
                try:
                    from tool_executor import get_last_execution_trace

                    execution_trace = get_last_execution_trace()
                except Exception:
                    execution_trace = []

                if (
                    not execution_trace
                    and task.planner_result.get("steps")
                    and (
                        is_software_repair_request(task.request)
                        or is_software_change_request(task.request)
                    )
                ):
                    reason = (
                        "Executor returned 'done' without an execution trace; "
                        "JARVIS refused to treat the autonomous software phase "
                        "as verified."
                    )
                    task.error = reason
                    task.execution_result = "failed"
                    task.observations.append(reason)

                    try:
                        import tool_executor

                        tool_executor.LAST_EXECUTION_TRACE = [
                            {
                                "index": 1,
                                "tool": "agent_verification_guard",
                                "argument": "",
                                "status": "failed",
                                "success": False,
                                "verified": False,
                                "result": {
                                    "success": False,
                                    "verified": False,
                                    "retryable": False,
                                    "message": reason,
                                },
                                "message": reason,
                                "retryable": False,
                                "terminal": True,
                            }
                        ]
                    except Exception:
                        pass

                    self._apply_step_status(
                        task,
                        success=False,
                        result=reason,
                    )

                    return "failed"

                self._apply_step_status(
                    task,
                    success=True,
                    result=result,
                )

                return "done"

            self._apply_step_status(
                task,
                success=False,
                result=result,
            )

            task.error = (
                "Executor returned an "
                "unexpected result."
            )

            return "failed"

        except Exception as exc:

            logger.exception(
                "JARVIS AGENT: "
                "Execution failed"
            )

            task.execution_result = str(
                exc
            )

            task.error = str(
                exc
            )

            self._apply_step_status(
                task,
                success=False,
                result=exc,
            )

            return "failed"

    def _install_phase_plan(
        self,
        task: AgentTask,
        plan: Dict[str, Any],
    ) -> AgentTask:
        """Install a deterministic phase plan without invoking the LLM."""
        internal_phase = bool(
            isinstance(plan, dict)
            and plan.get("jarvis_internal_phase")
        )

        validated = validate_plan(plan)

        # Reassert internal-phase metadata at the Agent Core boundary so a
        # deterministic orchestration plan can never accidentally become
        # user-facing speech because a future validator drops metadata.
        if internal_phase:
            validated["jarvis_internal_phase"] = True

        task.planner_result = validated
        task.goal = str(validated.get("goal", "") or "")
        task.steps = self._build_steps(validated)
        task.status = "ready"

        self.state["last_goal"] = task.goal
        self.state["last_status"] = task.status

        return task

    # ======================================================
    # Autonomous Execute
    # ======================================================

    def execute_task(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
        history_text: str = "",
    ) -> AgentTask:

        if task.status in {
            "conversation",
            "failed",
            "cancelled",
        }:
            return task

        if not task.planner_result:

            task.status = "failed"

            task.error = (
                "No valid planner result."
            )

            self.state[
                "last_status"
            ] = task.status

            self.state[
                "last_error"
            ] = task.error

            return task

        task.started_at = (
            task.started_at
            or time.time()
        )

        report_progress = self._should_report_progress(task)

        if report_progress:
            task_state.set_progress_callback(
                lambda message: self._announce(
                    message,
                    speak_callback,
                )
            )
        else:
            task_state.set_progress_callback(None)

        if not task.initial_acknowledged:
            self._announce(
                "On it.",
                speak_callback,
            )
        else:
            task_state.set_progress_callback(None)

        while True:

            result = self._execute_once(
                task,
                active_context,
                task_state,
                speak_callback,
            )

            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            if result == "done":

                # A self-repair request is satisfied when the full-project
                # diagnostic passes and no verified defect remains. Do not
                # invoke the coding planner merely because the original
                # request contained "fix"; there is nothing concrete to fix.
                if (
                    is_explicit_self_repair_request(task.request)
                    and not self._plan_has_mutation(task.planner_result)
                    and self._latest_verified_code_test_evidence(task) is not None
                ):
                    logger.info(
                        "JARVIS AGENT: Self-repair diagnostic passed; "
                        "no verified defect remains to repair."
                    )

                    task.status = "completed"
                    task.completed_at = time.time()
                    task.execution_result = (
                        "Self-repair diagnostic passed; "
                        "no reproducible defect was found, so no "
                        "code change was made."
                    )
                    self.state["last_result"] = task.execution_result
                    self.state["last_status"] = task.status
                    self.state["last_error"] = None
                    self.state["replans"] = task.replan_count

                    if report_progress:
                        self._announce(
                            "The diagnostic passed, so I found no verified defect to repair.",
                            speak_callback,
                        )

                    self._record_autonomy_episode(task)
                    task_state.set_progress_callback(None)
                    return task

                # A failed bounded change is restored to its checkpoint before
                # the focused coding model attempts the corrective edit.
                if task.active_context.pop(
                    "_change_recovery_pending",
                    False,
                ):
                    logger.info(
                        "JARVIS AGENT: Change checkpoint restored; "
                        "planning focused corrective repair from verified failure evidence."
                    )

                    replanned = self.plan_task(
                        task,
                        history_text=history_text,
                        planning_request=(
                            self._build_change_repair_request_after_failure(task)
                        ),
                        require_repair_plan=True,
                        require_code_read=False,
                    )

                    if replanned.status in {
                        "conversation",
                        "failed",
                    }:
                        return replanned

                    continue

                # Repair requests can legitimately begin with discovery.
                # Roblox Studio uses its own inspection/test loop and must not
                # fall into JARVIS's Python-file phase fallback.
                if (
                    is_software_repair_request(task.request)
                    and not self._plan_has_mutation(
                        task.planner_result
                    )
                ):

                    if is_roblox_request(task.request):
                        replanned = self.plan_task(
                            task,
                            history_text=history_text,
                            planning_request=self._build_roblox_repair_request(task),
                            require_repair_plan=True,
                            require_code_read=False,
                            require_code_test=False,
                            require_code_diagnose=False,
                        )

                        if replanned.status in {
                            "conversation",
                            "failed",
                        }:
                            return replanned

                        continue

                    has_source_read = (
                        self._has_verified_evidence(
                            task,
                            {"read_file"},
                        )
                    )

                    has_code_test = (
                        self._has_verified_evidence(
                            task,
                            {"code_test", "code_diagnose"},
                        )
                    )

                    if not has_source_read:
                        logger.info(
                            "JARVIS AGENT: Discovery is incomplete; "
                            "planning a source-reading phase."
                        )

                        if report_progress:
                            self._announce(
                                "I need to inspect the actual source before changing anything.",
                                speak_callback,
                            )

                    elif not has_code_test:
                        logger.info(
                            "JARVIS AGENT: Source inspection complete; "
                            "planning a diagnostic test phase."
                        )

                        if report_progress:
                            self._announce(
                                "I've inspected the source. I'm running a targeted test before changing anything.",
                                speak_callback,
                            )

                    else:
                        # A successful diagnostic is evidence that the reported
                        # problem cannot currently be reproduced by the relevant
                        # validation. Never invent a code change just because the
                        # original request contained the word "fix".
                        diagnostic_evidence = (
                            self._latest_verified_code_test_evidence(task)
                        )

                        if diagnostic_evidence is not None:
                            logger.info(
                                "JARVIS AGENT: Diagnostic validation passed; "
                                "no verified defect remains to repair."
                            )

                            task.status = "completed"
                            task.completed_at = time.time()
                            task.execution_result = (
                                "Diagnostic validation passed; "
                                "no reproducible defect was found, so no "
                                "code change was made."
                            )
                            self.state["last_result"] = task.execution_result
                            self.state["last_status"] = task.status
                            self.state["last_error"] = None
                            self.state["replans"] = task.replan_count

                            if report_progress:
                                self._announce(
                                    "The diagnostic passed, so I couldn't reproduce a failure and made no code changes.",
                                    speak_callback,
                                )

                            self._record_autonomy_episode(task)
                            task_state.set_progress_callback(None)
                            return task

                        logger.info(
                            "JARVIS AGENT: Diagnostic phase complete; "
                            "planning repair phase."
                        )

                        if report_progress:
                            self._announce(
                                "I've finished the investigation. I'm moving on to the fix and validation.",
                                speak_callback,
                            )

                    # Discovery -> source read -> diagnostic are deterministic
                    # transitions. The coding model is reserved for the actual
                    # repair decision after concrete evidence exists.
                    phase_plan = self._build_phase_fallback_plan(
                        task,
                        require_code_read=not has_source_read,
                        require_code_diagnose=(
                            has_source_read and not has_code_test
                        ),
                    )

                    if phase_plan is not None:
                        self._install_phase_plan(
                            task,
                            phase_plan,
                        )

                        logger.info(
                            "JARVIS AGENT: Advancing directly to the next "
                            "required repair phase without another planner call."
                        )

                        continue

                    planning_request = (
                        self._build_repair_request_after_discovery(
                            task
                        )
                    )

                    replanned = self.plan_task(
                        task,
                        history_text=history_text,
                        planning_request=planning_request,
                        require_repair_plan=(
                            has_source_read and has_code_test
                        ),
                        require_code_read=not has_source_read,
                        require_code_test=False,
                        require_code_diagnose=(
                            has_source_read and not has_code_test
                        ),
                    )

                    if replanned.status in {
                        "conversation",
                        "failed",
                    }:
                        return replanned

                    continue

                # Explicit software changes use the same evidence-first
                # orchestration as repairs: deterministic source read first,
                # then a focused implementation plan, then execution and
                # validation.
                if (
                    is_software_change_request(task.request)
                    and not is_software_repair_request(task.request)
                    and not self._plan_has_mutation(task.planner_result)
                    and not self._has_verified_evidence(
                        task,
                        {"edit_file", "write_file", "delete_file"},
                    )
                ):
                    has_source_read = self._has_verified_evidence(
                        task,
                        {"read_file"},
                    )

                    if not has_source_read:
                        phase_plan = self._build_phase_fallback_plan(
                            task,
                            require_code_read=True,
                        )

                        if phase_plan is not None:
                            self._install_phase_plan(
                                task,
                                phase_plan,
                            )
                            logger.info(
                                "JARVIS AGENT: Advancing directly to the "
                                "change source-read phase without another "
                                "planner call."
                            )
                            continue

                    else:
                        logger.info(
                            "JARVIS AGENT: Source inspection complete; "
                            "planning the focused change implementation."
                        )

                        replanned = self.plan_task(
                            task,
                            history_text=history_text,
                            planning_request=(
                                self._build_change_request_after_source(task)
                            ),
                            require_change_plan=True,
                        )

                        if replanned.status in {
                            "conversation",
                            "failed",
                        }:
                            return replanned

                        continue

                # Every successful source mutation gets one deterministic
                # diff-integrity check in addition to the requested focused test.
                if (
                    is_software_change_request(task.request)
                    and self._plan_has_mutation(task.planner_result)
                    and not is_roblox_request(task.request)
                    and self._has_verified_evidence(
                        task,
                        {"code_test"},
                    )
                    and not self._has_verified_git_diff_check(task)
                ):
                    self._install_phase_plan(
                        task,
                        {
                            "goal": "verify source diff integrity",
                            "jarvis_internal_phase": True,
                            "steps": [
                                {
                                    "tool": "code_test",
                                    "argument": json.dumps(
                                        {"mode": "git_diff_check"}
                                    ),
                                }
                            ],
                        },
                    )

                    task.observations.append(
                        "Automatic post-edit git diff validation scheduled."
                    )

                    logger.info(
                        "JARVIS AGENT: Focused tests passed; "
                        "running deterministic git diff validation before completion."
                    )
                    continue

                # Any successful software change must be validated even when
                # the initial plan did not explicitly include a test step.
                if (
                    is_software_change_request(task.request)
                    and self._plan_has_mutation(task.planner_result)
                    and (
                        (
                            is_roblox_request(task.request)
                            and not self._has_verified_evidence(
                                task,
                                ROBLOX_TEST_TOOLS,
                            )
                        )
                        or (
                            not is_roblox_request(task.request)
                            and not self._has_verified_evidence(
                                task,
                                {"code_test", "code_diagnose"},
                            )
                        )
                    )
                ):
                    logger.info(
                        "JARVIS AGENT: Software change completed without "
                        "validation evidence; planning validation phase."
                    )

                    if is_roblox_request(task.request):
                        validation_request = "\n".join([
                            "The Roblox Studio implementation phase completed successfully.",
                            "Now validate the changed game behavior before reporting completion.",
                            "",
                            f"Original request: {task.request}",
                            "",
                            self._build_evidence_packet(task),
                            "",
                            "Roblox validation rules:",
                            "1. Start a playtest when one is not already running.",
                            "2. Inspect get_playtest_output and/or get_output_log for errors or expected behavior.",
                            "3. Treat output failures as evidence for the next repair attempt.",
                            "4. Do not claim completion until the Roblox behavior is verified.",
                            "",
                            "Return ONLY JSON.",
                        ])

                        replanned = self.plan_task(
                            task,
                            history_text=history_text,
                            planning_request=validation_request,
                            require_code_test=False,
                        )
                    else:
                        validation_request = "\n".join([
                            "The implementation phase completed successfully.",
                            "Now validate the changed software before reporting completion.",
                            "",
                            f"Original request: {task.request}",
                            "",
                            self._build_evidence_packet(task),
                            "",
                            "Validation rules:",
                            "1. Validate the actual changed implementation.",
                            "2. Use code_test for focused validation or code_diagnose for broader validation.",
                            "3. Treat failures as evidence for the next repair attempt.",
                            "4. Do not claim completion until validation succeeds.",
                            "",
                            "Return ONLY JSON.",
                        ])

                        replanned = self.plan_task(
                            task,
                            history_text=history_text,
                            planning_request=validation_request,
                            require_code_test=True,
                        )

                    if replanned.status in {
                        "conversation",
                        "failed",
                    }:
                        return replanned

                    continue

                task.status = "completed"

                task.completed_at = (
                    time.time()
                )

                self.state[
                    "last_result"
                ] = task.execution_result

                self.state[
                    "last_status"
                ] = task.status

                self.state[
                    "last_error"
                ] = None

                self.state[
                    "replans"
                ] = task.replan_count

                logger.info(
                    "JARVIS AGENT: Task completed "
                    f"after {task.replan_count} replan(s)."
                )

                # Autonomy Kernel v2: informational tasks are not complete
                # until JARVIS has verified that concrete evidence exists and
                # converted that evidence into an actual answer.
                try:
                    postcondition = verify_postcondition(
                        task.request,
                        task,
                        active_context=(
                            active_context.to_dict()
                            if hasattr(active_context, "to_dict")
                            else active_context
                        ),
                    )
                except Exception as exc:
                    postcondition = {
                        "ready": False,
                        "requires_answer": False,
                        "reason": f"postcondition check failed: {exc}",
                    }
                    logger.warning(
                        "JARVIS AGENT: Postcondition verification error: "
                        f"{exc}"
                    )

                if postcondition.get("requires_answer"):
                    if postcondition.get("ready"):
                        try:
                            composed_answer = compose_task_answer(
                                task.request,
                                task,
                                active_context=(
                                    active_context.to_dict()
                                    if hasattr(active_context, "to_dict")
                                    else active_context
                                ),
                            )
                        except Exception as exc:
                            composed_answer = ""
                            logger.warning(
                                "JARVIS AGENT: Answer composition failed: "
                                f"{exc}"
                            )

                        if composed_answer.strip():
                            task.execution_result = composed_answer
                            self.state["last_result"] = composed_answer
                            self.state["last_error"] = None

                            try:
                                from tool_executor import add_assistant_message
                                add_assistant_message(composed_answer)
                            except Exception as exc:
                                logger.debug(
                                    "JARVIS AGENT: Conversation answer write skipped: "
                                    f"{exc}"
                                )

                            try:
                                background_owned = (
                                    task_state.is_background_speech_owned()
                                    if hasattr(
                                        task_state,
                                        "is_background_speech_owned",
                                    )
                                    else False
                                )
                            except Exception:
                                background_owned = False

                            if background_owned:
                                task_state.set_final_speech(composed_answer)
                            else:
                                interrupted = bool(
                                    speak_callback(composed_answer)
                                )
                                if not interrupted and hasattr(
                                    task_state,
                                    "mark_completion_spoken",
                                ):
                                    task_state.mark_completion_spoken()

                            logger.info(
                                "JARVIS AGENT: Autonomy Kernel v2 answer "
                                "composer selected evidence-grounded response."
                            )
                        else:
                            task.error = (
                                "Answer composer produced no safe response "
                                "from verified evidence."
                            )
                            task.status = "failed"
                            task.completed_at = time.time()
                            self.state["last_result"] = None
                            self.state["last_status"] = task.status
                            self.state["last_error"] = task.error

                            self._announce(
                                "I found the requested information, but I could not safely turn the verified evidence into an answer.",
                                speak_callback,
                            )

                            logger.warning(
                                "JARVIS AGENT: answer composer produced no safe response; failing task."
                            )
                            self._record_autonomy_episode(task)
                            task_state.set_progress_callback(None)
                            return task
                    else:
                        # Never announce false completion for a data-seeking
                        # task when postcondition evidence is missing.
                        reason = str(
                            postcondition.get(
                                "reason",
                                "Required evidence was not available.",
                            )
                        )
                        task.error = reason
                        self.state["last_result"] = None
                        self.state["last_status"] = "failed"
                        self.state["last_error"] = reason
                        task.status = "failed"
                        task.completed_at = time.time()

                        if report_progress:
                            self._announce(
                                "I completed the checks, but I don't have enough verified evidence to give you a reliable answer.",
                                speak_callback,
                            )

                        self._record_autonomy_episode(task)
                        task_state.set_progress_callback(None)
                        return task

                if report_progress:
                    completion_spoken = False
                    pending_final_speech = False
                    try:
                        completion_spoken = task_state.was_completion_spoken()
                        pending_final_speech = task_state.has_pending_final_speech()
                    except Exception:
                        pass

                    if (
                        not completion_spoken
                        and not pending_final_speech
                        and not (
                            postcondition.get("requires_answer")
                            and postcondition.get("ready")
                        )
                    ):
                        self._announce(
                            "The task is complete.",
                            speak_callback,
                        )

                task_state.set_progress_callback(None)
                return task

            # ------------------------------------------------
            # Cancelled
            # ------------------------------------------------

            if result == "cancelled":

                task.status = "cancelled"

                task.completed_at = (
                    time.time()
                )

                self.state[
                    "last_status"
                ] = task.status

                if not task.initial_acknowledged:
                    self._announce(
                        "Stopped.",
                        speak_callback,
                    )

                self._record_autonomy_episode(task)
                task_state.set_progress_callback(None)
                return task

            # ------------------------------------------------
            # Failure
            # ------------------------------------------------

            if result == "failed":

                # Respect the tool's explicit retryability contract at the
                # Agent Core boundary. _execute_once() already records and
                # announces retryable=False failures, but this outer failure
                # branch previously treated every "failed" result as a signal
                # to replan. That could cause deterministic failures such as
                # product-research collection failures to enter an endless
                # LLM replan loop.
                retryable, retry_message = self._failure_is_retryable()

                if not retryable:
                    if retry_message:
                        task.error = retry_message

                    task.status = "failed"
                    task.completed_at = time.time()

                    self.state["last_result"] = task.execution_result
                    self.state["last_status"] = task.status
                    self.state["last_error"] = task.error
                    self.state["replans"] = task.replan_count

                    logger.warning(
                        "JARVIS AGENT: Non-retryable failure reached "
                        "outer execution loop; skipping replan."
                    )

                    self._record_autonomy_episode(task)
                    task_state.set_progress_callback(None)
                    return task

                # A failed diagnostic is useful evidence, not a generic
                # planning failure. For software repair tasks, hand the
                # verified source + diagnostic evidence directly to the
                # focused repair planner instead of asking the model to
                # rediscover the task from scratch.
                # Bounded CHANGE recovery: failed edits/tests restore the
                # known-good checkpoint before the 14B coding planner retries.
                latest_failure = self._latest_failed_execution_evidence(task)
                latest_failure_tool = (
                    str(latest_failure.get("tool", "") or "").strip()
                    if latest_failure
                    else ""
                )

                if (
                    is_software_change_request(task.request)
                    and latest_failure_tool in {
                        "edit_file",
                        "write_file",
                        "delete_file",
                        "code_test",
                    }
                    and task.change_recovery_attempts < 2
                    and task.replan_count < task.max_replans
                ):
                    task.change_recovery_attempts += 1
                    task.replan_count += 1
                    self.state["replans"] = task.replan_count
                    task.active_context["_change_recovery_pending"] = True

                    self._install_phase_plan(
                        task,
                        {
                            "goal": "restore pre-change checkpoint",
                            "jarvis_internal_phase": True,
                            "steps": [
                                {
                                    "tool": "code_restore_checkpoint",
                                    "argument": "",
                                }
                            ],
                        },
                    )

                    logger.warning(
                        "JARVIS AGENT: Bounded change validation failed; "
                        f"restoring checkpoint for corrective repair "
                        f"(attempt {task.change_recovery_attempts}/2)."
                    )
                    continue

                latest_diagnostic = None
                for evidence in reversed(task.evidence):
                    if not isinstance(evidence, dict):
                        continue
                    if str(evidence.get("tool", "") or "").strip() != "code_diagnose":
                        continue
                    if not evidence.get("success"):
                        latest_diagnostic = evidence
                        break

                try:
                    if task_state.is_cancelled():
                        task.status = "cancelled"
                        task.completed_at = time.time()
                        self.state["last_status"] = task.status
                        self.state["last_error"] = "Cancellation requested by the user."
                        self._record_autonomy_episode(task)
                        task_state.set_progress_callback(None)
                        return task
                except Exception:
                    pass

                if (
                    is_software_repair_request(task.request)
                    and latest_diagnostic is not None
                ):
                    has_source_read = self._has_verified_evidence(
                        task,
                        {"read_file"},
                    )

                    if has_source_read:
                        logger.info(
                            "JARVIS AGENT: Diagnostic failure captured as repair evidence; "
                            "switching directly to focused repair planning."
                        )
                    else:
                        logger.info(
                            "JARVIS AGENT: Diagnostic failure captured from the project-wide "
                            "diagnostic; switching directly to focused repair planning with "
                            "mandatory source inspection."
                        )

                    self.state["replans"] = task.replan_count

                    planning_request = (
                        self._build_repair_request_after_discovery(task)
                    )

                    replanned = self.plan_task(
                        task,
                        history_text=history_text,
                        planning_request=planning_request,
                        require_repair_plan=True,
                        require_code_read=not has_source_read,
                    )

                    if replanned.status not in {
                        "conversation",
                        "failed",
                    }:
                        task.replan_count += 1
                        self.state["replans"] = task.replan_count
                        continue

                    logger.warning(
                        "JARVIS AGENT: Focused repair handoff failed; "
                        "continuing through normal bounded recovery."
                    )

                if (
                    task.replan_count
                    >= task.max_replans
                ):

                    task.status = "failed"

                    task.completed_at = (
                        time.time()
                    )

                    self.state[
                        "last_result"
                    ] = task.execution_result

                    self.state[
                        "last_status"
                    ] = task.status

                    self.state[
                        "last_error"
                    ] = task.error

                    self.state[
                        "replans"
                    ] = task.replan_count

                    logger.error(
                        "JARVIS AGENT: "
                        "Maximum replans reached."
                    )

                    self._announce(
                        "I wasn't able to complete the task.",
                        speak_callback,
                    )

                    self._record_autonomy_episode(task)
                    task_state.set_progress_callback(None)
                    return task

                # --------------------------------------------
                # REPLAN
                # --------------------------------------------

                task.replan_count += 1

                self.state[
                    "replans"
                ] = task.replan_count

                logger.warning(
                    "JARVIS AGENT: "
                    f"Execution failed. "
                    f"Replanning "
                    f"({task.replan_count}/"
                    f"{task.max_replans})..."
                )

                if report_progress:
                    self._announce(
                        "That approach didn't work as expected. I'm adjusting the plan and trying again.",
                        speak_callback,
                    )

                planning_request = (
                    self._build_replan_request(
                        task
                    )
                )

                replanned = self.plan_task(
                    task,
                    history_text=history_text,
                    planning_request=planning_request,
                    require_repair_plan=(
                        is_software_repair_request(task.request)
                    ),
                )

                if replanned.status in {
                    "conversation",
                    "failed",
                }:

                    self._record_autonomy_episode(replanned)
                    return replanned

                continue

    # ======================================================
    # Full Run
    # ======================================================

    def run(
        self,
        request: str,
        active_context,
        task_state,
        speak_callback,
        history_text: str = "",
    ) -> AgentTask:

        task = self.create_task(
            request,
            active_context=(
                active_context.to_dict()
                if hasattr(
                    active_context,
                    "to_dict",
                )
                else dict(
                    active_context or {}
                )
            ),
        )

        task = self.plan_task(
            task,
            history_text=history_text,
        )

        if task.status in {
            "conversation",
            "failed",
        }:

            return task

        task = self.execute_task(
            task,
            active_context,
            task_state,
            speak_callback,
            history_text=history_text,
        )

        return task

    # ======================================================
    # Summary
    # ======================================================

    def summarize(
        self,
        task: Optional[AgentTask] = None,
    ) -> Dict[str, Any]:

        task = (
            task
            or self.current_task
        )

        if task is None:

            return {
                "status": "idle"
            }

        start = (
            task.started_at
            or task.created_at
        )

        end = (
            task.completed_at
            or time.time()
        )

        return {
            "task_id": task.task_id,
            "request": task.request,
            "goal": task.goal,
            "status": task.status,
            "step_count": len(
                task.steps
            ),
            "current_step": (
                task.current_step
            ),
            "duration": max(
                0.0,
                end - start,
            ),
            "result": (
                task.execution_result
            ),
            "error": task.error,
            "replans": task.replan_count,
            "change_recovery_attempts": task.change_recovery_attempts,
            "observations": list(
                task.observations
            ),
            "steps": [
                {
                    "tool": step.tool,
                    "argument": step.argument,
                    "status": step.status,
                    "attempts": step.attempts,
                    "verified": step.verified,
                    "result": step.result,
                    "error": step.error,
                    "observation": step.observation,
                }
                for step in task.steps
            ],
        }


# ==========================================================
# Factory
# ==========================================================

def build_agent() -> JarvisAgent:

    return JarvisAgent(
        planner=create_plan,
        executor=execute_plan,
    )


# ==========================================================
# Standalone Test
# ==========================================================

if __name__ == "__main__":

    active_context = ActiveContext(
        site="google",
        last_query="Wi-Fi skeleton",
        last_tool="search_website",
        last_result=None,
    )

    task_state = TaskState()

    def test_speak(text):
        print(
            "[TEST SPEAK]",
            text,
        )

    agent = build_agent()

    task = agent.run(
        "Click the first result",
        active_context=active_context,
        task_state=task_state,
        speak_callback=test_speak,
    )

    print()
    print(
        "========== AGENT SUMMARY =========="
    )

    print(
        agent.summarize(task)
    )

    print(
        "===================================="
    )

    print()
    print(
        "Active context after execution:"
    )

    print(
        active_context
    )

    print()
    print(
        "Task state after execution:"
    )

    print(
        task_state
    )
