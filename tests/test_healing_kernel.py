"""Regression tests for the JARVIS Healing Kernel."""

from healing_kernel import (
    build_healing_evidence,
    choose_recovery,
    diagnose_failure,
)


def test_transient_transport_failure_prefers_direct_retry():
    diagnosis = diagnose_failure(
        "web_search",
        "HTTPSConnectionPool timed out after 15 seconds",
    )

    assert diagnosis.category == "transient_transport"
    decision = choose_recovery(
        diagnosis,
        attempt=1,
        max_attempts=2,
    )
    assert decision.action == "retry"
    assert decision.use_model is False


def test_browser_drift_escalates_to_replan():
    diagnosis = diagnose_failure(
        "browser_click_element",
        "No such element: button with text Downloads",
    )

    assert diagnosis.category == "browser_drift"
    decision = choose_recovery(
        diagnosis,
        attempt=1,
        max_attempts=2,
    )
    assert decision.action == "replan"


def test_code_failure_routes_to_bounded_source_repair():
    diagnosis = diagnose_failure(
        "code_test",
        "SyntaxError: invalid syntax in browser_controller.py",
    )

    assert diagnosis.category == "code_regression"
    decision = choose_recovery(
        diagnosis,
        attempt=1,
        max_attempts=2,
    )
    assert decision.action == "repair_code"


def test_invalid_argument_can_use_recovery_model():
    diagnosis = diagnose_failure(
        "weather",
        "invalid argument: location must be provided",
    )

    assert diagnosis.category == "invalid_argument"
    decision = choose_recovery(
        diagnosis,
        attempt=1,
        max_attempts=3,
        model_available=True,
    )
    assert decision.action == "repair_argument"
    assert decision.use_model is True


def test_budget_exhaustion_stops_local_loop():
    diagnosis = diagnose_failure(
        "web_search",
        "connection reset by peer",
    )

    decision = choose_recovery(
        diagnosis,
        attempt=2,
        max_attempts=2,
    )
    assert decision.action == "stop"


def test_healing_evidence_redacts_common_secrets():
    diagnosis = diagnose_failure(
        "api_call",
        "authorization=Bearer abc123token connection reset",
        argument="api_key=supersecret",
    )

    evidence = build_healing_evidence(
        "api_call",
        "api_key=supersecret",
        "authorization=Bearer abc123token connection reset",
        diagnosis,
        attempt=1,
    )

    assert "supersecret" not in evidence["argument"]
    assert "abc123token" not in evidence["error"]
    assert evidence["diagnosis"]["category"] == "transient_transport"
