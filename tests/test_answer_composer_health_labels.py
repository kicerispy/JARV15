from answer_composer import _platform_answer


def test_quickcheck_answer_humanizes_internal_tool_identifier():
    task = object()
    evidence = [{
        "tool": "jarvis_quickcheck",
        "success": True,
        "verified": True,
        "data": {
            "overall": "DEGRADED",
            "health": {
                "ollama": True,
                "whisper": True,
                "piper": True,
            },
            "tool_health": {
                "degraded": ["agentbrowsersetup"],
            },
        },
    }]

    answer = _platform_answer(task, evidence)

    assert "Browser Agent Setup" in answer
    assert "agentbrowsersetup" not in answer
