"""Regression tests for natural-language action phrase routing."""

from smart_router import route_command


def test_take_a_look_is_actionable():
    decision = route_command("take a look at my Roblox game")
    assert decision.kind == "agent"


def test_check_out_is_actionable():
    decision = route_command("check out the current browser page")
    assert decision.kind in {"agent", "fast", "contextual"}


def test_figure_out_is_actionable():
    decision = route_command("figure out what is broken")
    assert decision.kind == "agent"
