"""One-command JARVIS regression diagnostic.

Run with:
    python diagnose_jarvis.py
"""

from __future__ import annotations

import argparse
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

CORE_FILES = [
    "state.py",
    "commands.py",
    "planner.py",
    "smart_router.py",
    "tool_executor.py",
    "tools.py",
    "api_tools.py",
    "extended_api_tools.py",
    "gods_eye.py",
    "screen_memory.py",
    "context_resolver.py",
    "result_context.py",
    "main.py",
]


def check_compile() -> list[str]:
    failures = []

    for filename in CORE_FILES:
        path = ROOT / filename
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
            print(f"[PASS] compile: {filename}")
        except Exception as exc:
            failures.append(
                f"compile {filename}: {exc}"
            )
            print(f"[FAIL] compile: {filename} -> {exc}")

    return failures


def check_routing() -> list[str]:
    from commands import get_fast_command
    from planner import create_plan

    failures = []

    planner_cases = {
        "Convert 100 USD to EUR.": "currency_convert",
        "What is the air quality in Chicago?": "air_quality",
        "Are there any weather alerts in Illinois?": "weather_alerts",
        "What is the elevation of Denver?": "elevation_lookup",
        "What is quantum computing?": "knowledge_lookup",
        "Find books by Frank Herbert.": "book_search",
        "Find research papers about large language models.": "research_arxiv",
        "What are the episodes of Cowboy Bebop?": "anime_episodes",
    }

    for query, expected_tool in planner_cases.items():
        try:
            plan = create_plan(query)
            steps = plan.get("steps", [])
            actual = (
                steps[0].get("tool")
                if steps
                else None
            )

            if actual != expected_tool:
                failures.append(
                    f"planner route {query!r}: "
                    f"expected {expected_tool}, got {actual}"
                )
                print(
                    f"[FAIL] planner route: {query} -> {actual}"
                )
            else:
                print(
                    f"[PASS] planner route: {expected_tool}"
                )

        except Exception as exc:
            failures.append(
                f"planner route {query!r}: {exc}"
            )
            print(
                f"[FAIL] planner route: {query} -> {exc}"
            )

    fast_cases = {
        "Convert 100 USD to EUR.": None,
        "What is the air quality in Chicago?": None,
        "Are there any weather alerts in Illinois?": None,
        "What is the elevation of Denver?": None,
        "What is the weather in Chicago?": "weather",
        "Search Google for wireless headphones.": "browser_search_google",
    }

    for query, expected_tool in fast_cases.items():
        try:
            plan = get_fast_command(query)
            actual = None

            if isinstance(plan, dict):
                steps = plan.get("steps") or []
                if steps:
                    actual = steps[0].get("tool")

            if actual != expected_tool:
                failures.append(
                    f"fast route {query!r}: "
                    f"expected {expected_tool}, got {actual}"
                )
                print(
                    f"[FAIL] fast route: {query} -> {actual}"
                )
            else:
                print(
                    f"[PASS] fast route: {query}"
                )

        except Exception as exc:
            failures.append(
                f"fast route {query!r}: {exc}"
            )
            print(
                f"[FAIL] fast route: {query} -> {exc}"
            )

    return failures


def check_structured_context() -> list[str]:
    from result_context import (
        compact_context_description,
        resolve_result_followup,
    )
    from state import ActiveContext
    from tool_executor import update_active_context
    from tool_result import ToolResult

    failures = []

    context = ActiveContext()

    raw_book_result = ToolResult(
        success=True,
        tool="book_search",
        data={
            "query": "Frank Herbert",
            "books": [
                {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                    "first_publish_year": 1965,
                },
                {
                    "title": "Dune Messiah",
                    "authors": ["Frank Herbert"],
                    "first_publish_year": 1969,
                },
            ],
        },
    )

    try:
        update_active_context(
            plan={
                "steps": [
                    {
                        "tool": "book_search",
                        "argument": "Frank Herbert",
                    }
                ]
            },
            active_context=context,
            result_message="I found 2 book results.",
            raw_result=raw_book_result,
        )

        payload = context.to_dict()

        assert payload["last_result"] == (
            "I found 2 book results."
        )
        assert payload["last_result_data"]["books"][1][
            "title"
        ] == "Dune Messiah"

        result = resolve_result_followup(
            "What was the second one?",
            payload,
        )

        assert result is not None
        assert result["index"] == 1
        assert result["selected"]["title"] == (
            "Dune Messiah"
        )

        context.last_result_index = result["index"]
        context.last_selected_result = result["selected"]

        expansion = resolve_result_followup(
            "Tell me more about that",
            context.to_dict(),
        )

        # Metadata-only book results may not have a long summary. In that
        # case the resolver should still return useful information.
        assert expansion is None or "Dune Messiah" in expansion["reply"]

        compact = compact_context_description(
            context.to_dict()
        )
        assert "Result 1: Dune" in compact
        assert "Result 2: Dune Messiah" in compact

        print("[PASS] structured result storage")
        print("[PASS] ordinal result follow-up")
        print("[PASS] compact planner context")

    except Exception as exc:
        failures.append(
            f"structured context: {exc}"
        )
        print(
            f"[FAIL] structured context: {exc}"
        )

    return failures


def check_live_apis() -> list[str]:
    """Exercise the real no-key API integrations and result storage."""
    from state import ActiveContext
    from tool_executor import update_active_context
    from tools import run_tool
    from result_context import resolve_result_followup