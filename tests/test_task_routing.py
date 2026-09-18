import pytest

from smart_router import route_command


@pytest.mark.parametrize("request", [
    "fix the browser automation",
    "debug the YouTube click",
    "repair your code",
    "diagnose the error",
    "can you fix the broken task",
])
def test_repair_requests_route_to_agent(request):
    decision = route_command(request)
    assert decision.kind == "agent"


def test_normal_explanation_stays_conversational():
    decision = route_command("Can you explain how Python decorators work?")
    assert decision.kind == "conversation"


def test_multi_step_repair_routes_to_agent():
    decision = route_command(
        "Inspect the browser code, fix the issue, and test it"
    )
    assert decision.kind == "agent"
