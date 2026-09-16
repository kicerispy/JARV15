import capability_runtime


def fast_plan_for_request(request):
    return getattr(capability_runtime, "fast_plan_for_request", None)(request) if hasattr(capability_runtime, "fast_plan_for_request") else None


def _tools(plan):
    return [step["tool"] for step in plan["steps"]]


def test_latest_release_question_uses_web_search_without_full_planner():
    plan = fast_plan_for_request("What is the latest Python release?")

    assert plan is not None
    assert _tools(plan) == ["web_search"]
    assert plan["steps"][0]["argument"] == "What is the latest Python release?"


def test_current_weather_question_uses_weather_tool():
    plan = fast_plan_for_request("What's the current weather in Chicago?")

    assert plan is not None
    assert _tools(plan) == ["weather"]
    assert plan["steps"][0]["argument"] == "Chicago"


def test_local_current_project_request_stays_out_of_online_fast_path():
    assert fast_plan_for_request("Open the current project folder") is None


def test_complex_online_request_still_uses_full_planner():
    request = "Find the latest Python release, download it, install it, and configure my PATH."
    assert fast_plan_for_request(request) is None
