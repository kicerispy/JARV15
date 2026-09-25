from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import plan_memory
from postcondition_verifier import verify_execution_trace
from regression_detector import detect_strategy_regression
from strategy_selector import select_learned_plan
import planner
import tools


def _isolate_plan_memory(tmp_path):
    plan_memory._DB_DIR = Path(tmp_path)
    plan_memory._DB_PATH = Path(tmp_path) / "plan_memory.sqlite3"
    plan_memory._SCHEMA_READY = False


def test_learned_strategy_requires_repeated_verified_successes(tmp_path):
    _isolate_plan_memory(tmp_path)

    request = "go back one page"
    plan = {
        "goal": "navigate back",
        "steps": [{"tool": "browser_back", "argument": ""}],
    }

    assert select_learned_plan(request, context={}) is None

    for _ in range(2):
        result = plan_memory.record_strategy(
            request,
            plan,
            success=True,
            verified=True,
            context={"site": "browser"},
        )
        assert result["recorded"] is True

    assert select_learned_plan(request, context={"site": "browser"}) is None

    plan_memory.record_strategy(
        request,
        plan,
        success=True,
        verified=True,
        context={"site": "browser"},
    )

    learned = select_learned_plan(
        request,
        context={"site": "browser"},
    )

    assert learned is not None
    assert learned["learned_strategy"] is True
    assert learned["steps"][0]["tool"] == "browser_back"
    assert learned["steps"][0]["argument"] == ""


def test_learned_strategy_preserves_real_arguments(tmp_path):
    _isolate_plan_memory(tmp_path)

    request = "search Google for wifi skeleton"
    plan = {
        "goal": "search Google",
        "steps": [
            {
                "tool": "browser_search_google",
                "argument": "wifi skeleton",
            }
        ],
    }

    for _ in range(3):
        plan_memory.record_strategy(
            request,
            plan,
            success=True,
            verified=True,
            context={"site": "google"},
        )

    learned = select_learned_plan(
        request,
        context={"site": "google"},
    )

    assert learned is not None
    assert learned["steps"][0]["argument"] == "wifi skeleton"
    assert "<num>" not in learned["steps"][0]["argument"]
    assert "<path>" not in learned["steps"][0]["argument"]


def test_strategy_regression_detects_recent_failure_cluster(tmp_path):
    _isolate_plan_memory(tmp_path)

    request = "go back one page"
    plan = {
        "goal": "navigate back",
        "steps": [{"tool": "browser_back", "argument": ""}],
    }

    for _ in range(15):
        plan_memory.record_strategy(
            request,
            plan,
            success=True,
            verified=True,
        )

    for _ in range(4):
        plan_memory.record_strategy(
            request,
            plan,
            success=False,
            verified=False,
            error="browser navigation failed",
        )

    strategy = plan_memory.find_strategies(
        request,
        limit=1,
        include_quarantined=True,
    )[0]
    regression = detect_strategy_regression(strategy)

    assert regression["regressed"] is True
    assert regression["recent_failures"] >= 3


def test_execution_trace_verifier_rejects_failed_steps():
    trace = [
        {
            "tool": "browser_search_google",
            "status": "completed",
            "success": True,
            "verified": True,
            "message": "search complete",
        },
        {
            "tool": "browser_click_first_result",
            "status": "failed",
            "success": False,
            "verified": False,
            "message": "No such element",
        },
    ]

    with patch(
        "tool_executor.get_last_execution_trace",
        return_value=trace,
    ):
        result = verify_execution_trace(object())

    assert result["trace_available"] is True
    assert result["ready"] is False
    assert result["failed_steps"]


def test_execution_trace_verifier_accepts_successful_trace():
    trace = [
        {
            "tool": "browser_back",
            "status": "completed",
            "success": True,
            "verified": True,
            "message": "navigated back",
        }
    ]

    with patch(
        "tool_executor.get_last_execution_trace",
        return_value=trace,
    ):
        result = verify_execution_trace(object())

    assert result["ready"] is True
    assert result["verified"] is True
    assert result["failed_steps"] == []


def test_planner_exposes_autonomy_self_service_routes():
    plan = planner.create_plan("show learned strategies")
    assert plan["steps"][0]["tool"] == "autonomy_status"

    plan = planner.create_plan("which strategies are regressing")
    assert plan["steps"][0]["tool"] == "regression_status"


def test_public_dispatcher_exposes_autonomy_status():
    result = tools.execute_tool("autonomy_status")
    assert result.success is True
    assert "strategy" in result.data
    assert "trace" in result.data


def test_public_dispatcher_exposes_regression_status():
    result = tools.execute_tool(
        "regression_status",
        json.dumps({"request": "go back one page"}),
    )
    assert result.success is True
    assert "tool_regressions" in result.data


def test_strategy_status_reports_persistent_learning_state():
    result = tools.execute_tool("autonomy_status")
    assert result.success is True
    assert result.data["enabled"] is True
    assert result.data["trace"]["enabled"] is True
    assert result.data["strategy"]["enabled"] is True
