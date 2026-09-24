"""Native JARVIS adapter for the upstream Superpowers methodology.

Upstream project: https://github.com/obra/superpowers
Pinned upstream reference: 6.4.1
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
import re
from typing import Any, Dict, Optional

SUPERPOWERS_VERSION = "6.4.1"
SUPERPOWERS_UPSTREAM = "https://github.com/obra/superpowers"

CORE_SKILLS = (
    "using-superpowers",
    "brainstorming",
    "writing-plans",
    "test-driven-development",
    "systematic-debugging",
    "verification-before-completion",
    "executing-plans",
    "subagent-driven-development",
    "requesting-code-review",
    "finishing-a-development-branch",
    "using-git-worktrees",
    "diagnosing-superpowers",
)

_SOFTWARE_SIGNALS = (
    "code", "coding", "script", "software", "project", "repository", "repo",
    "python", "javascript", "typescript", "program", "bug", "error", "exception",
    "traceback", "module", "application", "browser automation", "roblox", "luau",
    "test", "pytest", "compile", "refactor", "feature", "implementation",
    ".py", ".js", ".ts", "framework",
)

_CHANGE_SIGNALS = (
    "add", "implement", "integrate", "enhance", "improve", "upgrade",
    "introduce", "enable", "support", "build", "create", "make", "write",
    "generate", "change", "modify", "patch",
)

_REPAIR_SIGNALS = (
    "fix", "repair", "debug", "diagnose", "investigate", "broken", "crash",
    "not working", "doesn't work", "doesnt work", "failure", "failing",
)

_ARCHITECTURAL_SIGNALS = (
    "architecture", "architectural", "subsystem", "system redesign",
    "restructure", "re-architect", "redesign", "integrate", "integration",
    "framework", "major upgrade", "large update", "big update", "entire system",
    "multiple systems", "new system", "new capability",
)


@dataclass(frozen=True)
class SuperpowersWorkflow:
    classification: str
    skills: tuple[str, ...]
    requires_design: bool
    requires_plan: bool
    requires_tdd: bool
    requires_debugging: bool
    requires_verification: bool
    execution_mode: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["version"] = SUPERPOWERS_VERSION
        payload["upstream"] = SUPERPOWERS_UPSTREAM
        return payload


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _is_enabled() -> bool:
    try:
        import config
        return bool(getattr(config, "SUPERPOWERS_ENABLED", True))
    except Exception:
        return True


def _has_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal in text for signal in signals)


def _is_software_request(text: str) -> bool:
    return _has_any(text, _SOFTWARE_SIGNALS)


def classify_software_request(request: str) -> Optional[SuperpowersWorkflow]:
    """Select the engineering workflow before an LLM planner runs."""
    normalized = _normalize(request)
    if not _is_enabled() or not normalized or not _is_software_request(normalized):
        return None

    repair = _has_any(normalized, _REPAIR_SIGNALS)
    change = _has_any(normalized, _CHANGE_SIGNALS)
    architectural = _has_any(normalized, _ARCHITECTURAL_SIGNALS)

    complexity_markers = len(
        re.findall(r"\b(?:and|then|also|plus|with)\b", normalized)
    )
    explicit_file_count = len(
        re.findall(
            r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|md|lua|css|html)\b",
            normalized,
        )
    )
    multi_step = complexity_markers >= 2 or explicit_file_count >= 2

    if architectural or multi_step:
        return SuperpowersWorkflow(
            classification="architectural",
            skills=(
                "using-superpowers",
                "brainstorming",
                "using-git-worktrees",
                "writing-plans",
                "executing-plans",
                "test-driven-development",
                "requesting-code-review",
                "verification-before-completion",
                "finishing-a-development-branch",
            ),
            requires_design=True,
            requires_plan=True,
            requires_tdd=change or repair,
            requires_debugging=repair,
            requires_verification=True,
            execution_mode="executing-plans",
            rationale="The request spans multiple concerns or changes system boundaries.",
        )

    if repair:
        return SuperpowersWorkflow(
            classification="bounded",
            skills=(
                "using-superpowers",
                "systematic-debugging",
                "test-driven-development",
                "verification-before-completion",
            ),
            requires_design=False,
            requires_plan=False,
            requires_tdd=True,
            requires_debugging=True,
            requires_verification=True,
            execution_mode="inline",
            rationale="Diagnose from evidence, make the smallest safe change, and verify it.",
        )

    if change:
        return SuperpowersWorkflow(
            classification="bounded",
            skills=(
                "using-superpowers",
                "brainstorming",
                "test-driven-development",
                "verification-before-completion",
            ),
            requires_design=True,
            requires_plan=multi_step,
            requires_tdd=True,
            requires_debugging=False,
            requires_verification=True,
            execution_mode="inline",
            rationale="Change existing behavior with a design-sized process.",
        )

    return SuperpowersWorkflow(
        classification="bounded",
        skills=("using-superpowers", "verification-before-completion"),
        requires_design=False,
        requires_plan=False,
        requires_tdd=False,
        requires_debugging=False,
        requires_verification=True,
        execution_mode="inline",
        rationale="Software-related request without a clear mutation.",
    )


def planner_directives(request: str) -> str:
    workflow = classify_software_request(request)
    if workflow is None:
        return ""

    lines = [
        f"SUPERPOWERS WORKFLOW v{SUPERPOWERS_VERSION}:",
        f"- Classification: {workflow.classification}.",
        f"- Execution mode: {workflow.execution_mode}.",
        f"- Required skills: {', '.join(workflow.skills)}.",
        "- Treat observed source, diagnostics, and test output as authoritative evidence.",
        "- Preserve user intent; avoid unrelated refactors; apply YAGNI and DRY.",
    ]

    if workflow.requires_design:
        lines.extend([
            "- Establish a concise design and acceptance understanding before implementation.",
            "- Architectural work should separate design/specification from the implementation plan.",
        ])

    if workflow.requires_plan:
        lines.extend([
            "- Break implementation into independently testable steps with explicit files and verification.",
            "- Use JARVIS's inline execution path when no separate subagent runtime is available.",
        ])

    if workflow.requires_tdd:
        lines.extend([
            "- Prefer RED -> GREEN -> REFACTOR for behavioral changes.",
            "- Add or extend the narrowest regression/feature test before production changes when practical.",
            "- Keep the smallest implementation change that turns the test green.",
        ])

    if workflow.requires_debugging:
        lines.extend([
            "- Reproduce, localize, form an evidence-backed hypothesis, then patch.",
            "- Never patch a symptom or guess at filenames, errors, or root causes.",
        ])

    if workflow.requires_verification:
        lines.extend([
            "- A successful tool return is not completion evidence by itself.",
            "- Run fresh validation after the final mutation before claiming completion.",
        ])

    return "\n".join(lines)


def artifact_paths(request: str, today: Optional[date] = None) -> Dict[str, str]:
    workflow = classify_software_request(request)
    if workflow is None:
        return {}

    stamp = (today or date.today()).isoformat()
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        _normalize(request),
    ).strip("-")[:72] or "jarvis-task"

    result: Dict[str, str] = {}
    if workflow.requires_design:
        result["spec"] = f"docs/superpowers/specs/{stamp}-{slug}-design.md"
    if workflow.requires_plan:
        result["plan"] = f"docs/superpowers/plans/{stamp}-{slug}.md"
    return result


def skill_path(skill_name: str) -> Path:
    return Path(__file__).resolve().parent / "superpowers" / "skills" / skill_name / "SKILL.md"


def load_skill(skill_name: str) -> str:
    return skill_path(skill_name).read_text(encoding="utf-8")


def status() -> Dict[str, Any]:
    skills = [
        {"name": name, "available": skill_path(name).is_file()}
        for name in CORE_SKILLS
    ]
    return {
        "enabled": _is_enabled(),
        "version": SUPERPOWERS_VERSION,
        "upstream": SUPERPOWERS_UPSTREAM,
        "native_adapter": True,
        "skill_count": len(skills),
        "skills": skills,
    }
