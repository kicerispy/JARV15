from planner import _qol_plan


def test_qol_preflight_routes_jarvis_health():
    plan = _qol_plan("Is JARVIS healthy?")
    assert plan["steps"] == [{"tool": "jarvis_quickcheck", "argument": ""}]


def test_qol_preflight_routes_resources():
    plan = _qol_plan("Show me my CPU and RAM usage")
    assert plan["steps"] == [{"tool": "resource_status", "argument": ""}]


def test_qol_preflight_routes_healing_hints():
    plan = _qol_plan("What keeps failing?")
    assert plan["steps"][0]["tool"] == "healing_hints"
