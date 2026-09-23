import unittest
from types import SimpleNamespace

from answer_composer import compose_task_answer
from intent_resolver import needs_evidence_answer, resolve_intent
from postcondition_verifier import verify_postcondition


def _task(request, evidence, plan=None):
    return SimpleNamespace(
        request=request,
        planner_result=plan or {"goal": request, "steps": []},
        evidence=evidence,
    )


class AutonomyKernelV2Tests(unittest.TestCase):

    def test_intent_resolver_understands_roblox_followup_as_evidence_task(self):
        intent = resolve_intent(
            "find the scripts that control the core gameplay systems",
            active_context={"site": "roblox"},
        )

        self.assertEqual(intent["domain"], "roblox")
        self.assertEqual(intent["intent"], "inspect")
        self.assertEqual(intent["mode"], "answer")
        self.assertEqual(intent["entities"]["artifact"], "script")
        self.assertEqual(intent["entities"]["system"], "gameplay")

    def test_intent_resolver_keeps_google_search_as_action(self):
        intent = resolve_intent(
            "search Google for wifi skeleton",
            active_context={"site": "roblox"},
        )

        self.assertEqual(intent["domain"], "browser")
        self.assertEqual(intent["intent"], "search")
        self.assertEqual(intent["mode"], "action")
        self.assertEqual(intent["entities"]["site"], "google")

    def test_intent_resolver_handles_search_and_report(self):
        intent = resolve_intent(
            "search Google for wifi skeleton and tell me what you find"
        )

        self.assertEqual(intent["mode"], "answer")

    def test_intent_resolver_report_overrides_action_plan(self):
        intent = resolve_intent(
            "search Google for wifi skeleton and tell me what you find",
            plan={"response_mode": "action"},
        )

        self.assertEqual(intent["mode"], "answer")

    def test_postcondition_rejects_generic_completion_for_info_request(self):
        task = _task(
            "find the scripts that control the core gameplay systems",
            [
                {
                    "tool": "roblox__search_files",
                    "success": True,
                    "verified": True,
                    "detail": "Tool completed.",
                }
            ],
        )

        result = verify_postcondition(task.request, task)

        self.assertTrue(result["requires_answer"])
        self.assertFalse(result["ready"])

    def test_postcondition_rejects_metadata_only_payload(self):
        task = _task(
            "inspect my Roblox game and tell me how the project is structured",
            [
                {
                    "tool": "roblox__get_project_structure",
                    "success": True,
                    "verified": True,
                    "data": {
                        "success": True,
                        "message": "Tool completed.",
                    },
                }
            ],
        )

        result = verify_postcondition(task.request, task)

        self.assertFalse(result["ready"])

    def test_postcondition_accepts_structured_evidence(self):
        task = _task(
            "find the scripts that control the core gameplay systems",
            [
                {
                    "tool": "roblox__search_files",
                    "success": True,
                    "verified": True,
                    "detail": "Tool completed.",
                    "data": {
                        "matches": [
                            {
                                "name": "CombatController",
                                "className": "ModuleScript",
                            }
                        ]
                    },
                }
            ],
        )

        result = verify_postcondition(task.request, task)

        self.assertTrue(result["requires_answer"])
        self.assertTrue(result["ready"])

    def test_roblox_answer_uses_place_and_script_evidence(self):
        task = _task(
            "inspect my Roblox game and tell me how the project is structured",
            [
                {
                    "tool": "roblox__get_place_info",
                    "success": True,
                    "verified": True,
                    "detail": "Tool completed.",
                    "data": {
                        "name": "Test Place",
                        "placeId": 123,
                        "gameId": 456,
                    },
                },
                {
                    "tool": "roblox__get_project_structure",
                    "success": True,
                    "verified": True,
                    "detail": "Tool completed.",
                    "data": {
                        "children": [
                            {
                                "name": "ServerScriptService",
                                "className": "ServerScriptService",
                            },
                            {
                                "name": "ReplicatedStorage",
                                "className": "ReplicatedStorage",
                            },
                            {
                                "name": "CombatController",
                                "className": "ModuleScript",
                            },
                            {
                                "name": "RoundManager",
                                "className": "Script",
                            },
                        ]
                    },
                },
            ],
        )

        answer = compose_task_answer(task.request, task)

        self.assertIn("Test Place", answer)
        self.assertIn("123", answer)
        self.assertIn("456", answer)
        self.assertIn("CombatController", answer)
        self.assertIn("RoundManager", answer)

    def test_roblox_mcp_text_payload_is_decoded(self):
        task = _task(
            "find the scripts that control the core gameplay systems",
            [
                {
                    "tool": "roblox__search_files",
                    "success": True,
                    "verified": True,
                    "detail": "Tool completed.",
                    "data": {
                        "content": [
                            {
                                "type": "text",
                                "text": "{\"matches\":[{\"name\":\"CombatService\",\"className\":\"Script\"}]}"
                            }
                        ]
                    },
                }
            ],
        )

        answer = compose_task_answer(task.request, task)

        self.assertIn("CombatService", answer)

    def test_failed_roblox_tool_preserves_domain_context(self):
        from state import ActiveContext
        from tool_executor import update_active_context

        context = ActiveContext()
        context.site = "google"

        update_active_context(
            {
                "steps": [
                    {
                        "tool": "roblox__get_project_structure",
                        "argument": "{}",
                    }
                ]
            },
            context,
            result_message="Roblox MCP HTTP 500: Studio plugin connection timeout.",
        )

        self.assertEqual(context.site, "roblox")
        self.assertEqual(
            context.last_tool,
            "roblox__get_project_structure",
        )
        self.assertIn("connection timeout", context.last_result.lower())

    def test_task_state_start_preserves_background_speech_ownership(self):
        from state import TaskState

        state = TaskState()
        state.prepare(
            description="background task",
            total_steps=1,
        )

        # BackgroundTaskController claims ownership after prepare() and before
        # the worker reaches TaskState.start(). Verify start() preserves it.
        state.set_background_speech_owned(True)
        self.assertTrue(state.is_background_speech_owned())

        self.assertTrue(
            state.start(
                description="background task",
                total_steps=1,
            )
        )

        self.assertTrue(state.is_background_speech_owned())

    def test_executor_defers_answer_bearing_task_to_agent_core(self):
        from unittest.mock import patch

        import tool_executor
        from state import ActiveContext, TaskState
        from tool_result import ToolResult

        plan = {
            "goal": "find the scripts that control the core gameplay systems",
            "steps": [
                {
                    "tool": "roblox__search_files",
                    "argument": '{"query":"Script","searchType":"type"}',
                }
            ],
        }

        task_state = TaskState()
        active_context = ActiveContext()
        spoken = []

        def speak(message):
            spoken.append(message)
            return False

        result = ToolResult(
            success=True,
            tool="roblox__search_files",
            data={
                "matches": [
                    {
                        "name": "CombatController",
                        "className": "ModuleScript",
                    }
                ]
            },
        )

        with patch.object(tool_executor, "run_tool", return_value=result):
            execution_result = tool_executor.execute_plan(
                plan,
                active_context,
                task_state,
                speak,
            )

        self.assertEqual(execution_result, "done")
        self.assertEqual(spoken, [])
        self.assertEqual(active_context.site, "roblox")

    def test_roblox_answer_does_not_count_services_as_scripts(self):
        task = _task(
            "inspect my Roblox game and tell me how the project is structured",
            [
                {
                    "tool": "roblox__get_place_info",
                    "success": True,
                    "verified": True,
                    "data": {
                        "name": "Baddies",
                        "placeId": 129980665337091,
                        "gameId": 10767662715,
                    },
                },
                {
                    "tool": "roblox__get_project_structure",
                    "success": True,
                    "verified": True,
                    "data": {
                        "children": [
                            {
                                "name": "ServerScriptService",
                                "className": "ServerScriptService",
                            },
                            {
                                "name": "ScriptService",
                                "className": "ScriptService",
                            },
                            {
                                "name": "ServerMain",
                                "className": "Script",
                                "fullName": "game.ServerScriptService.ServerMain",
                            },
                            {
                                "name": "ClientMain",
                                "className": "LocalScript",
                                "fullName": "game.StarterPlayer.StarterPlayerScripts.ClientMain",
                            },
                        ]
                    },
                },
            ],
        )

        answer = compose_task_answer(task.request, task)

        self.assertIn("2 script-related item(s)", answer)
        self.assertIn("ServerMain", answer)
        self.assertIn("ClientMain", answer)
        self.assertIn("ServerScriptService", answer)
        self.assertNotIn("The project is organized around game.", answer)
        self.assertNotIn("The project uses: ScriptService", answer)

    def test_roblox_gameplay_answer_stays_compact(self):
        task = _task(
            "find the scripts that control the core gameplay systems",
            [
                {
                    "tool": "roblox__search_files",
                    "success": True,
                    "verified": True,
                    "data": {
                        "matches": [
                            {
                                "name": "ServerMain",
                                "className": "Script",
                                "fullName": "game.ServerScriptService.ServerMain",
                            },
                            {
                                "name": "ClientMain",
                                "className": "LocalScript",
                                "fullName": "game.StarterPlayer.StarterPlayerScripts.ClientMain",
                            },
                            {
                                "name": "ScriptService",
                                "className": "ScriptService",
                                "fullName": "game.ScriptService",
                            },
                            {
                                "name": "Script Context",
                                "className": "ScriptContext",
                                "fullName": "game.Script Context",
                            },
                        ]
                    },
                }
            ],
        )

        answer = compose_task_answer(task.request, task)

        self.assertIn("likely core gameplay scripts", answer)
        self.assertIn("ServerMain", answer)
        self.assertIn("ClientMain", answer)
        self.assertNotIn("Script Context", answer)
        self.assertNotIn("ClickTrigger.Script", answer)
        self.assertLess(len(answer), 500)

    def test_browser_search_answer_uses_structured_result_titles(self):
        task = _task(
            "search Google for wifi skeleton and tell me what you find",
            [
                {
                    "tool": "browser_search_google",
                    "success": True,
                    "verified": True,
                    "detail": "Google search complete.",
                    "data": {
                        "query": "wifi skeleton",
                        "title": "wifi skeleton - Google Search",
                        "url": "https://www.google.com/search?q=wifi+skeleton",
                        "results": [
                            {
                                "index": 1,
                                "title": "WiFi Skeleton | Example",
                                "url": "https://example.com/wifi",
                            },
                            {
                                "index": 2,
                                "title": "Wi-Fi Skeleton Documentation",
                                "url": "https://example.org/docs",
                            },
                        ],
                    },
                }
            ],
        )

        answer = compose_task_answer(task.request, task)

        self.assertIn("wifi skeleton", answer)
        self.assertIn("WiFi Skeleton | Example", answer)
        self.assertIn("Wi-Fi Skeleton Documentation", answer)
        self.assertNotIn("browsersearchgoogle", answer)
        self.assertLess(len(answer), 700)

    def test_needs_evidence_answer_distinguishes_action_and_information(self):
        self.assertTrue(
            needs_evidence_answer(
                "inspect my Roblox game and tell me how the project is structured"
            )
        )
        self.assertTrue(
            needs_evidence_answer(
                "find the scripts that control the core gameplay systems"
            )
        )
        self.assertFalse(
            needs_evidence_answer(
                "search Google for wifi skeleton"
            )
        )


if __name__ == "__main__":
    unittest.main()
