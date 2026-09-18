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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from logger import logger
from planner import (
    assess_plan,
    create_plan,
    is_software_repair_request,
    validate_plan,
)
from tool_executor import execute_plan
from state import ActiveContext, TaskState


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

    max_replans: int = 2

    current_step: int = -1

    created_at: float = field(
        default_factory=time.time
    )

    started_at: Optional[float] = None

    completed_at: Optional[float] = None

    error: Optional[str] = None

    initial_acknowledged: bool = False


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
    # Create Task
    # ======================================================

    def create_task(
        self,
        request: str,
        active_context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AgentTask:

        task = AgentTask(
            task_id=str(
                uuid.uuid4()
            ),
            request=str(
                request or ""
            ).strip(),
            active_context=dict(
                active_context or {}
            ),
        )

        self.current_task = task

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
            str(step.get("tool", "") or "").strip()
            in {
                "write_file",
                "edit_file",
                "delete_file",
            }
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

            if tool not in {
                "code_search",
                "list_files",
                "find_file",
            }:
                continue

            detail = str(
                evidence.get("detail", "") or ""
            )

            for candidate in re.findall(
                r"(?<![A-Za-z0-9_.-])([A-Za-z_][A-Za-z0-9_.-]*\.py)(?![A-Za-z0-9_.-])",
                detail,
            ):
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
                ):
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
                != "code_test"
            ):
                continue

            if (
                evidence.get("success")
                and evidence.get("verified")
            ):
                return evidence

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
                != "read_file"
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

    def _build_phase_fallback_plan(
        self,
        task: AgentTask,
        require_code_read: bool = False,
        require_code_test: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Build a deterministic minimal plan when a required phase dead-ends."""
        target = self._latest_verified_source_target(task)

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
                "steps": [
                    {
                        "tool": "read_file",
                        "argument": target,
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
        require_code_read: bool = False,
        require_code_test: bool = False,
    ) -> AgentTask:

        task.status = "planning"

        phase_marker = ""
        if require_repair_plan:
            phase_marker = "[JARVIS_INTERNAL_PHASE:REPAIR]\n"
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

        # Give an incomplete software-repair plan one corrective
        # planning pass before allowing execution to begin.
        max_plan_repairs = 1

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

            plan_issues = assess_plan(
                task.request,
                plan,
                require_modification=require_repair_plan,
                require_code_read=require_code_read,
                require_code_test=require_code_test,
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
                        or require_code_read
                        or require_code_test
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
                                "For the discovery phase, inspect the "
                                "relevant project code and do not modify "
                                "files yet."
                            ),
                            (
                                "The corrected plan must include the "
                                "required read_file step before proceeding."
                                if require_code_read
                                else
                                (
                                    "The corrected plan must include "
                                    "code_test before proceeding."
                                    if require_code_test
                                    else
                                    "Use the observed code and do not "
                                    "invent filenames."
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
                )

                if fallback_plan is not None:
                    fallback_plan = validate_plan(fallback_plan)
                    fallback_issues = assess_plan(
                        task.request,
                        fallback_plan,
                        require_modification=require_repair_plan,
                        require_code_read=require_code_read,
                        require_code_test=require_code_test,
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
                                or require_code_read
                                or require_code_test
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

    def _build_repair_request_after_discovery(
        self,
        task: AgentTask,
    ) -> str:

        lines = [
            "The previous investigation phase has completed successfully.",
            "You are now handing evidence to the repair planner.",
            "",
            f"Original request: {task.request}",
            f"Goal: {task.goal}",
            "",
            self._build_evidence_packet(task),
            "",
            "REPAIR PHASE RULES:",
            "1. Do not repeat generic discovery or list the project again.",
            "2. Use the concrete evidence above to identify the defect and target file.",
            "3. If one small targeted source read is still required, request that specific file/region only.",
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

            elif tool == "code_test":
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

            else:
                evidence["detail"] = self._compact_text(
                    message,
                    limit=1600,
                )

            task.evidence.append(evidence)

        # Capture actual browser state.
        if _is_browser_trace(trace):
            browser_state = _capture_browser_state()

            task.active_context["browser_state"] = (
                browser_state
            )

            if browser_state.get("success"):
                url = browser_state.get("url", "")
                title = browser_state.get("title", "")

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

                step.attempts += 1

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

                return "failed"

            if result_text == "done":

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

                # Repair requests can legitimately begin with discovery.
                # After successful discovery, force a repair/test planning phase.
                if (
                    is_software_repair_request(task.request)
                    and not self._plan_has_mutation(
                        task.planner_result
                    )
                ):

                    has_source_read = (
                        self._has_verified_evidence(
                            task,
                            {"read_file"},
                        )
                    )

                    has_code_test = (
                        self._has_verified_evidence(
                            task,
                            {"code_test"},
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
                                    "The browser automation passed its diagnostic test, so I couldn't reproduce a failure and made no code changes.",
                                    speak_callback,
                                )

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
                        require_code_test=(
                            has_source_read and not has_code_test
                        ),
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

                if report_progress:
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

                task_state.set_progress_callback(None)
                return task

            # ------------------------------------------------
            # Failure
            # ------------------------------------------------

            if result == "failed":

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

