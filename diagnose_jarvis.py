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

    failures = []

    cases = [
        ("currency_convert", "100 USD to EUR"),
        ("location_lookup", "Chicago, Illinois"),
        ("air_quality", "Chicago, Illinois"),
        ("weather_alerts", "Illinois"),
        ("elevation_lookup", "Denver, Colorado"),
        ("knowledge_lookup", "quantum computing"),
        ("book_search", "Frank Herbert"),
        ("research_arxiv", "large language models"),
        ("research_crossref", "quantum computing"),
        ("holiday_lookup", "US 2026"),
    ]

    print()
    print("=" * 80)
    print("LIVE API SMOKE TESTS")
    print("=" * 80)

    for tool, argument in cases:
        try:
            result = run_tool(tool, argument)
            success = (
                bool(result.success)
                if hasattr(result, "success")
                else bool(
                    result.get("success", False)
                    if isinstance(result, dict)
                    else False
                )
            )

            if not success:
                error = getattr(result, "error", None)
                if not error and isinstance(result, dict):
                    error = result.get("error")
                failures.append(
                    f"live API {tool}: {error or 'unsuccessful result'}"
                )
                print(
                    f"[FAIL] live API: {tool} -> "
                    f"{error or 'unsuccessful result'}"
                )
            else:
                print(
                    f"[PASS] live API: {tool}"
                )

                if tool == "book_search":
                    context = ActiveContext()
                    update_active_context(
                        plan={
                            "steps": [
                                {
                                    "tool": tool,
                                    "argument": argument,
                                }
                            ]
                        },
                        active_context=context,
                        result_message="I found live book results.",
                        raw_result=result,
                    )

                    stored = context.to_dict()
                    followup = resolve_result_followup(
                        "What was the second one?",
                        stored,
                    )

                    if (
                        stored.get("last_result_data") is None
                        or not followup
                    ):
                        raise AssertionError(
                            "live structured result was not retained"
                        )

                    print(
                        "[PASS] live structured result + ordinal follow-up"
                    )

        except Exception as exc:
            failures.append(
                f"live API {tool}: {exc}"
            )
            print(
                f"[FAIL] live API: {tool} -> {exc}"
            )

    return failures


def check_speech_summaries() -> list[str]:
    from tool_executor import _api_spoken_summary

    failures = []

    cases = {
        "currency_convert": {
            "rate": 0.87005,
            "converted": 87.005,
            "from": "USD",
            "to": "EUR",
        },
        "location_lookup": {
            "name": "Chicago",
            "country": "United States",
            "timezone": "America/Chicago",
        },
        "air_quality": {
            "location": "Chicago",
            "current": {
                "pm2_5": 3.2,
                "pm10": 3.3,
            },
        },
        "weather_alerts": {
            "count": 2,
            "alerts": [
                {"event": "Flash Flood Warning"},
                {"event": "Flood Advisory"},
            ],
        },
        "elevation_lookup": {
            "location": {"name": "Denver"},
            "elevation_meters": 1615,
            "elevation_feet": 5298.56,
        },
    }

    field_cases = [
        (
            "currency_convert",
            "What was the exchange rate?",
            {
                "from": "USD",
                "to": "EUR",
                "rate": 0.87,
            },
        ),
        (
            "weather_alerts",
            "How many weather alerts were there?",
            {
                "count": 3,
                "alerts": [],
            },
        ),
    ]

    for tool, query, data in field_cases:
        try:
            from result_context import resolve_result_followup

            result = resolve_result_followup(
                query,
                {
                    "last_tool": tool,
                    "last_result_data": data,
                },
            )

            if not result:
                raise AssertionError("empty field follow-up")

            print(
                f"[PASS] field follow-up: {tool}"
            )
        except Exception as exc:
            failures.append(
                f"field follow-up {tool}: {exc}"
            )
            print(
                f"[FAIL] field follow-up: {tool} -> {exc}"
            )

    for tool, data in cases.items():
        try:
            summary = _api_spoken_summary(
                tool,
                data,
            )

            if not summary:
                raise AssertionError("empty spoken summary")

            print(
                f"[PASS] speech summary: {tool}"
            )

        except Exception as exc:
            failures.append(
                f"speech summary {tool}: {exc}"
            )
            print(
                f"[FAIL] speech summary: {tool} -> {exc}"
            )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run JARVIS regression diagnostics."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="also exercise the real no-key API endpoints",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("JARVIS REGRESSION DIAGNOSTIC")
    print("=" * 80)

    failures = []
    failures.extend(check_compile())

    if not failures:
        failures.extend(check_routing())
        failures.extend(check_structured_context())
        failures.extend(check_speech_summaries())

        if args.live:
            failures.extend(check_live_apis())

    print()
    print("=" * 80)

    if failures:
        print(
            f"DIAGNOSTIC FAILED: {len(failures)} issue(s)"
        )
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("DIAGNOSTIC PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
