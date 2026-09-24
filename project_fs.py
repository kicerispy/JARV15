"""Shared, pruned filesystem traversal for the JARVIS project.

The repository contains a large local virtual environment (jarvis_cuda) and
other generated/cache trees. Callers that need project-wide discovery should
use iter_project_files() so those trees are pruned before os.walk descends
into them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator, Optional

DEFAULT_PRUNED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pytype",
        ".hypothesis",
        ".tox",
        ".nox",
        ".cache",
        "cache",
        "caches",
        "coverage",
        "htmlcov",
        ".coverage",
        ".jarvis_checkpoints",
        "jarvis_cuda",
        "venv",
        ".venv",
        "env",
        ".env",
        "node_modules",
        "bower_components",
        "build",
        "dist",
        "out",
        "target",
        ".gradle",
        ".idea",
        ".vscode",
        "site-packages",
    }
)


def _resolve_root(root: Optional[os.PathLike | str]) -> Path:
    base = Path(root) if root is not None else Path.cwd()
    return base.expanduser().resolve()


def iter_project_files(
    root: Optional[os.PathLike | str] = None,
    *,
    suffixes: Optional[Iterable[str]] = None,
    pruned_dirs: Iterable[str] = DEFAULT_PRUNED_DIRS,
) -> Iterator[Path]:
    """Yield project files without descending into generated/heavy directories.

    Pruning happens by mutating os.walk's dirnames list while traversal is
    top-down. This is intentionally different from filtering paths after a
    recursive glob has already descended into them.
    """
    base = _resolve_root(root)
    wanted_suffixes = None

    if suffixes is not None:
        wanted_suffixes = {
            str(suffix).lower()
            if str(suffix).startswith(".")
            else "." + str(suffix).lower()
            for suffix in suffixes
        }

    pruned = {str(name).lower() for name in pruned_dirs}

    for current, dirnames, filenames in os.walk(
        base,
        topdown=True,
        followlinks=False,
    ):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name.lower() not in pruned
        )

        for filename in sorted(filenames):
            path = Path(current) / filename

            if (
                wanted_suffixes is not None
                and path.suffix.lower() not in wanted_suffixes
            ):
                continue

            yield path
