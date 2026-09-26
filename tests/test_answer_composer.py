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


class IntegrationHealthTask:
    request = "what tools are working right now"
    planner_result = {
        "steps": [
            {"tool": "integration_health", "argument": ""},
        ]
    }
    evidence = [
        {
            "tool": "integration_health",
            "success": True,
            "verified": True,
            "data": {
                "message": "Integration health is degraded.",
                "components": [
                    {"name": "God's Eye View", "status": "NOT_READY"},
                    {"name": "Browser", "status": "READY"},
                    {"name": "Broken Tool", "status": "ERROR"},
                ],
            },
        }
    ]


def test_integration_health_answer_includes_not_ready_and_error():
    answer = compose_task_answer(
        "what tools are working right now",
        IntegrationHealthTask(),
        active_context={},
    )

    assert "Not ready: God's Eye View." in answer
    assert "Error: Broken Tool." in answer


class RobloxMcpLifecycleTask:
    request = "setup Roblox MCP"
    planner_result = {
        "steps": [
            {"tool": "roblox_mcp_setup", "argument": ""},
        ]
    }
    evidence = [
        {
            "tool": "roblox_mcp_setup",
            "success": True,
            "verified": True,
            "data": {
                "server_url": "http://127.0.0.1:58741",
                "health": {"status": "ok"},
                "status": {"plugin_connected": True},
            },
        }
    ]


def test_roblox_mcp_setup_answer_reports_plugin_connection():
    answer = compose_task_answer(
        "setup Roblox MCP",
        RobloxMcpLifecycleTask(),
        active_context={},
    )

    assert "setup completed" in answer.lower()
    assert "plugin is connected" in answer.lower()
    assert "127.0.0.1:58741" in answer


class RobloxMcpCompactStatusTask:
    request = "check Roblox MCP status"
    planner_result = {
        "steps": [
            {"tool": "roblox_mcp_status", "argument": ""},
        ]
    }
    evidence = [
        {
            "tool": "roblox_mcp_status",
            "success": True,
            "verified": True,
            "data": {
                "server_url": "http://127.0.0.1:58741",
                "health": {"status": "ok", "pluginConnected": True},
                "status": {"pluginConnected": True, "mcpServerActive": True},
            },
        }
    ]


def test_roblox_mcp_answer_does_not_speak_url():
    answer = compose_task_answer(
        "check Roblox MCP status",
        RobloxMcpCompactStatusTask(),
        active_context={},
    )

    assert "plugin is connected" in answer.lower()
    assert "127.0.0.1:58741" not in answer


def test_integration_health_answer_precedes_active_roblox_context():
    class HealthTask:
        request = "what tools are working right now"
        planner_result = {
            "steps": [{"tool": "integration_health", "argument": ""}]
        }
        evidence = [
            {
                "tool": "integration_health",
                "success": True,
                "verified": True,
                "data": {
                    "message": "Integration health is degraded.",
                    "components": [
                        {"name": "Roblox MCP", "status": "DEGRADED"},
                        {"name": "Ollama", "status": "READY"},
                    ],
                },
            }
        ]

    answer = compose_task_answer(
        "what tools are working right now",
        HealthTask(),
        active_context={"site": "roblox"},
    )

    assert "Integration health is degraded." in answer
    assert "Roblox inspection" not in answer


def test_integration_health_answer_keeps_spoken_health_compact():
    class HealthTask:
        request = "what tools are working right now"
        planner_result = {
            "steps": [{"tool": "integration_health", "argument": ""}]
        }
        evidence = [
            {
                "tool": "integration_health",
                "success": True,
                "verified": True,
                "data": {
                    "message": "Integration health is degraded. 8 ready/running, 1 degraded, 2 unavailable.",
                    "components": [
                        {"name": "Ollama", "status": "READY"},
                        {"name": "Browser", "status": "RUNNING"},
                        {"name": "Roblox MCP", "status": "DEGRADED"},
                        {"name": "Screenpipe Memory", "status": "OFFLINE"},
                        {"name": "God's Eye View", "status": "OFFLINE"},
                    ],
                },
            }
        ]

    answer = compose_task_answer(
        "what tools are working right now",
        HealthTask(),
        active_context={},
    )

    assert "8 ready/running" in answer
    assert "Degraded: Roblox MCP." in answer
    assert "Offline: Screenpipe Memory, God's Eye View." in answer
    assert "Ready: Ollama" not in answer
    assert "Running: Browser" not in answer
