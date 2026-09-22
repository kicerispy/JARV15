"""Regression tests for JARVIS self-improvement intent."""

from planner import (
    is_explicit_self_repair_request,
    is_software_repair_request,
)


def test_improve_yourself_is_self_repair_workflow():
    request = "improve yourself and make yourself smarter"
    assert is_explicit_self_repair_request(request)
    assert is_software_repair_request(request)


def test_upgrade_your_own_code_is_actionable():
    request = "upgrade your own code"
    assert is_explicit_self_repair_request(request)
    assert is_software_repair_request(request)
