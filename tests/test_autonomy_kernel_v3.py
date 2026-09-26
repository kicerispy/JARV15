import json


def test_browser_agent_natural_phrase_routes_to_dedicated_tool():
    from commands import deterministic_route

    plan = deterministic_route("set up browser agent")

    assert plan is not None
    assert plan["steps"] == [
        {
            "tool": "browser_agent_setup",
            "argument": json.dumps({"action": "install"}),
        }
    ]


def test_browser_agent_natural_phrase_reaches_agent_router():
    from smart_router import route_command

    decision = route_command("set up browser agent")

    assert decision.kind == "agent"
    assert "specialized" in decision.reason


def test_project_health_routes_without_conversation_fallback():
    from commands import deterministic_route
    from smart_router import route_command

    decision = route_command("show me project health")
    plan = deterministic_route("show me project health")

    assert decision.kind == "agent"
    assert plan["steps"][0]["tool"] == "jarvis_quickcheck"


def test_autonomy_failure_classification_detects_scope_and_contract_failures():
    from autonomy_kernel import classify_failure

    scope = classify_failure(
        "edit_file",
        "target mismatch: requested file differs from verified file",
    )
    contract = classify_failure(
        "unknown_tool",
        "tool contract failure: tool is not registered",
    )

    assert scope.category == "scope_mismatch"
    assert scope.confidence >= 0.99
    assert contract.category == "tool_contract"
    assert contract.recoverable is True


def test_targeted_tests_are_selected_from_changed_files():
    from autonomy_kernel import targeted_test_paths

    selected = targeted_test_paths(
        ["planner.py", "browser_agent.py"],
        "repair the browser agent planner regression",
    )

    assert "tests/test_agent_planning.py" in selected
    assert "tests/test_browser_agent.py" in selected
    assert "tests/test_smart_router.py" in selected


def test_scope_gate_rejects_unexpected_mutation_target():
    from autonomy_kernel import assess_scope

    result = assess_scope(
        "Fix planner.py",
        {
            "steps": [
                {
                    "tool": "edit_file",
                    "argument": "commands.py|||old|||new",
                }
            ]
        },
    )

    assert result["allowed"] is False
    assert "commands.py" in result["unexpected_targets"]


def test_plan_confidence_requires_scope_and_verification():
    from autonomy_kernel import plan_confidence

    low = plan_confidence(
        "Fix planner.py",
        {"steps": [{"tool": "edit_file", "argument": "commands.py|||a|||b"}]},
    )
    high = plan_confidence(
        "Fix planner.py",
        {
            "steps": [
                {"tool": "read_file", "argument": "planner.py"},
                {"tool": "code_checkpoint", "argument": ""},
                {"tool": "edit_file", "argument": "planner.py|||a|||b"},
                {"tool": "code_test", "argument": '{"mode":"pytest","path":"tests/test_agent_planning.py"}'},
            ]
        },
        evidence=[{"success": True, "verified": True}],
    )

    assert low["allowed"] is False
    assert high["allowed"] is True
    assert high["confidence"] >= high["minimum"]


def test_select_recovery_rolls_back_validation_failures():
    from autonomy_kernel import classify_failure, select_recovery

    failure = classify_failure("code_test", "pytest failed: AssertionError")
    recovery = select_recovery(
        failure,
        attempt=1,
        max_attempts=3,
        changed_paths=["planner.py"],
        request="repair planner.py",
    )

    assert failure.category == "validation_failure"
    assert recovery.action == "rollback_repair"
    assert recovery.restore_checkpoint is True
    assert "tests/test_agent_planning.py" in recovery.targeted_tests
