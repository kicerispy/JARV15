from answer_composer import compose_task_answer


class Task:
    request = "Find browser_controller.py in my project"
    planner_result = {
        "steps": [
            {"tool": "find_file", "argument": "browser_controller.py"},
        ]
    }
    evidence = [
        {
            "tool": "find_file",
            "target": "browser_controller.py",
            "success": True,
            "verified": True,
            "detail": "Found:\nC:/repo/browser_controller.py",
            "data": "Found:\nC:/repo/browser_controller.py",
        }
    ]


def test_find_file_answer_uses_file_evidence_not_browser_intent():
    answer = compose_task_answer(
        "Find browser_controller.py in my project",
        Task(),
        active_context={},
    )

    assert "found 1 matching project file" in answer.lower()
    assert "browser_controller.py" in answer
    assert "browser search results" not in answer.lower()
