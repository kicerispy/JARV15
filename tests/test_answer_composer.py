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



class UnrealStatusTask:
    request = "check Unreal MCP status"
    planner_result = {
        "steps": [
            {"tool": "unreal_mcp_status", "argument": ""},
        ]
    }
    evidence = [
        {
            "tool": "unreal_mcp_status",
            "success": True,
            "verified": True,
            "data": {
                "success": True,
                "verified": True,
                "tool": "unreal_mcp_status",
                "endpoint": "http://127.0.0.1:3000/mcp",
                "protocol_version": "2025-11-25",
                "token_configured": True,
                "token_source": "file:C:/Users/Jordan/Documents/Unreal Projects/FGH/Saved/MCP/capability-token",
                "public_tools": ["unreal"],
                "connected": True,
            },
        }
    ]


class UnrealSearchTask:
    request = "search Unreal for spawning an actor"
    planner_result = {
        "steps": [
            {
                "tool": "unreal_mcp",
                "argument": '{"operation":"search","query":"spawning an actor"}',
            },
        ]
    }
    evidence = [
        {
            "tool": "unreal_mcp",
            "success": True,
            "verified": True,
            "operation": "search",
            "data": {
                "success": True,
                "verified": True,
                "tool": "unreal_mcp",
                "operation": "search",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"results":[{"tool":"control_actor",'
                                '"action":"spawn","description":"Spawn an actor"}]}'
                            ),
                        }
                    ]
                },
            },
        }
    ]


def test_unreal_status_answer_is_compact_and_hides_internal_auth_metadata():
    answer = compose_task_answer(
        "check Unreal MCP status",
        UnrealStatusTask(),
        active_context={},
    )

    assert answer == (
        "Unreal MCP is connected. The native server is authenticated "
        "and the Unreal gateway is ready."
    )
    assert "token_source" not in answer
    assert "Saved/MCP/capability-token" not in answer
    assert "2025-11-25" not in answer


def test_unreal_search_answer_surfaces_gateway_capabilities():
    answer = compose_task_answer(
        "search Unreal for spawning an actor",
        UnrealSearchTask(),
        active_context={},
    )

    assert "control_actor.spawn" in answer
    assert "I found 1 Unreal capability" in answer
    assert "success" not in answer.lower()
