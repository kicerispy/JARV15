from answer_composer import _integration_health_answer


def test_integration_health_evidence_compaction_preserves_structured_components():
    from agent_core import JarvisAgent

    payload = {
        "success": True,
        "verified": True,
        "tool": "integration_health",
        "status": "DEGRADED",
        "message": "Integration health is degraded. 8 ready/running, 0 degraded, 4 unavailable.",
        "counts": {"READY": 8, "NOT_INSTALLED": 4},
        "components": [
            {
                "name": "Ollama",
                "status": "READY",
                "message": "Ollama is reachable.",
                "tool_count": 2,
            },
            {
                "name": "Browser Agent",
                "status": "NOT_INSTALLED",
                "message": "Browser agent module is unavailable.",
                "tool_count": 2,
            },
        ],
        "runtime_tool_health": {"historical_failures": [{"tool": f"tool-{i}"} for i in range(100)]},
        "autonomy": {"version": 3, "suspect_tools": 2},
    }

    compact = JarvisAgent._bounded_structured_evidence(
        "integration_health",
        payload,
        max_chars=1200,
    )

    assert isinstance(compact, dict)
    assert compact["status"] == "DEGRADED"
    assert compact["components"][0]["name"] == "Ollama"
    assert compact["components"][1]["status"] == "NOT_INSTALLED"
    assert "runtime_tool_health" not in compact


def test_integration_health_answer_uses_compacted_component_evidence():
    evidence = [{
        "tool": "integration_health",
        "success": True,
        "verified": True,
        "detail": "health sweep complete",
        "data": {
            "success": True,
            "verified": True,
            "message": "Integration health is degraded. 8 ready/running, 0 degraded, 4 unavailable.",
            "components": [
                {"name": "Browser Agent", "status": "NOT_INSTALLED", "message": "missing"},
                {"name": "Ollama", "status": "READY", "message": "ready"},
            ],
        },
    }]

    answer = _integration_health_answer(None, evidence)

    assert "Integration health is degraded." in answer
    assert "Not installed: Browser Agent." in answer
