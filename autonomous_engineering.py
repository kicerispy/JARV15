"""Deterministic engineering policies and task-branch helpers for JARVIS.

This module deliberately keeps Git operations conservative. JARVIS can create a
task branch when the worktree is clean; it never force-resets, rebases, or
silently destroys user changes.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any


_REGRESSION_PHRASES = (
    "regression test",
    "regression tests",
    "regression coverage",
    "add a test for",
    "add tests for",
)


def _normalized(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def requires_regression_test(request: str) -> bool:
    """Return True when a change request explicitly or strongly implies regression coverage."""
    text = _normalized(request)

    if any(phrase in text for phrase in _REGRESSION_PHRASES):
        return True

    repair_signals = (
        "fix ",
        "fix the ",
        "repair ",
        "debug ",
        "broken",
        "failing",
        "not working",
        "bug",
        "exception",
        "crash",
    )
    software_signals = (
        ".py",
        "python",
        "code",
        "repository",
        "project",
        "browser",
        "jarvis",
        "module",
        "script",
    )

    return (
        any(signal in text for signal in repair_signals)
        and any(signal in text for signal in software_signals)
    )


def is_test_target(path: str) -> bool:
    """Return True when a path is conventionally a test source target."""
    normalized = str(path or "").replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]

    return (
        "/tests/" in f"/{normalized}/"
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def task_branch_name(task_id: str, request: str) -> str:
    """Build a deterministic short-lived engineering branch name."""
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        _normalized(request),
    ).strip("-")[:42]

    digest = hashlib.sha1(
        f"{task_id}|{request}".encode("utf-8")
    ).hexdigest()[:8]

    return f"jarvis/task/{slug or 'engineering'}-{digest}"


def _git(
    root: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=20,
    )


def current_branch(root: Path | str = ".") -> str:
    root = Path(root).resolve()

    result = _git(root, ["branch", "--show-current"])

    if result.returncode != 0:
        return ""

    return (result.stdout or "").strip()


def tracked_worktree_clean(root: Path | str = ".") -> bool:
    """Return True when tracked files are clean; ignored/untracked state is allowed."""
    root = Path(root).resolve()

    result = _git(
        root,
        ["status", "--porcelain", "--untracked-files=no"],
    )

    return result.returncode == 0 and not (result.stdout or "").strip()


def prepare_task_branch(
    branch_name: str,
    root: Path | str = ".",
) -> dict[str, Any]:
    """Create/switch to a task branch when safe without destroying local changes."""
    root = Path(root).resolve()
    branch = str(branch_name or "").strip()

    if not branch:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "Task branch name cannot be empty.",
        }

    original = current_branch(root)
    if not original:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "JARVIS could not determine the current Git branch.",
        }

    if original == branch:
        return {
            "success": True,
            "verified": True,
            "message": f"Already on task branch {branch}.",
            "original_branch": original,
            "task_branch": branch,
            "switched": False,
            "created": False,
            "isolated": True,
        }

    exists = _git(
        root,
        ["show-ref", "--verify", f"refs/heads/{branch}"],
    ).returncode == 0

    if exists:
        checkout = _git(root, ["switch", branch])
        if checkout.returncode == 0:
            return {
                "success": True,
                "verified": True,
                "message": f"Switched to existing task branch {branch}.",
                "original_branch": original,
                "task_branch": branch,
                "switched": True,
                "created": False,
                "isolated": True,
            }

        # A branch can exist but be unsafe to switch to because the user has
        # local changes. Keep the current worktree intact and report that the
        # branch could not be activated.
        return {
            "success": True,
            "verified": True,
            "message": (
                f"Task branch {branch} already exists, but JARVIS kept the "
                "current branch because switching was unsafe."
            ),
            "original_branch": original,
            "task_branch": branch,
            "switched": False,
            "created": False,
            "isolated": False,
        }

    if not tracked_worktree_clean(root):
        create = _git(root, ["branch", branch, original])
        if create.returncode == 0:
            return {
                "success": True,
                "verified": True,
                "message": (
                    f"Created task branch {branch}, but kept the current branch "
                    "because tracked local changes are present."
                ),
                "original_branch": original,
                "task_branch": branch,
                "switched": False,
                "created": True,
                "isolated": False,
            }

        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": (
                "JARVIS could not create the task branch without risking "
                "local changes: "
                + (create.stderr or create.stdout or "unknown Git error")
            ).strip(),
        }

    create = _git(root, ["switch", "-c", branch])

    if create.returncode != 0:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": (
                f"JARVIS could not create task branch {branch}: "
                + (create.stderr or create.stdout or "unknown Git error")
            ).strip(),
        }

    return {
        "success": True,
        "verified": True,
        "message": f"Created and switched to task branch {branch}.",
        "original_branch": original,
        "task_branch": branch,
        "switched": True,
        "created": True,
        "isolated": True,
    }
