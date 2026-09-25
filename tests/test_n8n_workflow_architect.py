import unittest
from unittest.mock import patch

import n8n_workflow_architect as architect


class N8nWorkflowArchitectTests(unittest.TestCase):

    def test_infer_techniques_prefers_relevant_workflow_patterns(self):
        techniques = architect._infer_techniques(
            "Monitor GitHub issues and send an email alert when a bug appears."
        )

        self.assertIn("monitoring", techniques)
        self.assertIn("notification", techniques)

    def test_design_workflow_uses_live_search_schema_and_guidance(self):
        calls = []

        def fake_call(tool_name, arguments=None):
            calls.append((tool_name, arguments))

            if tool_name == "search_nodes":
                return {
                    "success": True,
                    "data": {
                        "nodes": [
                            {
                                "nodeId": "n8n-nodes-base.webhook",
                                "name": "Webhook",
                                "type": "n8n-nodes-base.webhook",
                                "version": 2.1,
                                "description": "Webhook trigger",
                            },
                            {
                                "nodeId": "n8n-nodes-base.set",
                                "name": "Edit Fields",
                                "type": "n8n-nodes-base.set",
                                "version": 3.4,
                                "description": "Set and transform fields",
                            },
                        ]
                    },
                }

            if tool_name == "get_node_types":
                return {
                    "success": True,
                    "data": {
                        "nodeTypes": [
                            {
                                "nodeId": "n8n-nodes-base.webhook",
                                "properties": {"httpMethod": {"type": "options"}},
                            },
                            {
                                "nodeId": "n8n-nodes-base.set",
                                "properties": {"assignments": {"type": "collection"}},
                            },
                        ]
                    },
                }

            if tool_name == "get_workflow_best_practices":
                return {
                    "success": True,
                    "data": {
                        "guidance": "Validate webhook input before processing."
                    },
                }

            raise AssertionError(tool_name)

        with patch.object(architect, "_call", side_effect=fake_call):
            result = architect.design_workflow(
                "Build a webhook that validates incoming data",
                {"owner": "JARVIS"},
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["mode"], "design")
        self.assertTrue(result["node_definitions"])
        self.assertTrue(result["best_practices"])
        self.assertIn("validation", result["requirements"])
        self.assertTrue(
            any(name == "search_nodes" for name, _ in calls)
        )
        self.assertTrue(
            any(name == "get_node_types" for name, _ in calls)
        )

    def test_result_list_accepts_nested_data_payloads(self):
        result = {
            "success": True,
            "data": {
                "data": {
                    "nodes": [
                        {"name": "Webhook", "type": "n8n-nodes-base.webhook"}
                    ]
                }
            },
        }

        values = architect._result_list(
            result,
            ("nodes", "results", "items"),
        )

        self.assertEqual(values[0]["name"], "Webhook")

    def test_result_list_parses_documented_string_search_results(self):
        result = {
            "success": True,
            "data": {
                "results": (
                    "Found nodes:\n"
                    "- n8n-nodes-base.scheduleTrigger [TRIGGER]\n"
                    "- n8n-nodes-base.github"
                )
            },
        }

        values = architect._result_list(
            result,
            ("nodes", "results", "items"),
        )

        node_ids = {item["nodeId"] for item in values}
        self.assertIn("n8n-nodes-base.scheduleTrigger", node_ids)
        self.assertIn("n8n-nodes-base.github", node_ids)


    def test_get_node_types_does_not_treat_string_definitions_as_search_nodes(self):
        with patch.object(
            architect,
            "_call",
            return_value={
                "success": True,
                "data": {
                    "definitions": "interface GithubParameters { resource: string; operation: string }"
                },
            },
        ):
            result = architect._get_node_types(
                [
                    {
                        "nodeId": "n8n-nodes-base.github",
                        "type": "n8n-nodes-base.github",
                    }
                ]
            )

        self.assertEqual(len(result["definitions"]), 1)
        self.assertIn(
            "GithubParameters",
            result["definitions"][0]["content"],
        )
        self.assertNotIn(
            "_search_text",
            result["definitions"][0],
        )


    def test_get_node_types_accepts_documented_string_definitions(self):
        with patch.object(
            architect,
            "_call",
            return_value={
                "success": True,
                "data": {
                    "definitions": "interface ScheduleTriggerParameters { cronExpression: string }"
                },
            },
        ):
            result = architect._get_node_types(
                [
                    {
                        "nodeId": "n8n-nodes-base.scheduleTrigger",
                        "type": "n8n-nodes-base.scheduleTrigger",
                    }
                ]
            )

        self.assertTrue(result["definitions"])
        self.assertIn(
            "ScheduleTriggerParameters",
            result["definitions"][0]["content"],
        )


    def test_discover_nodes_prioritizes_request_relevant_nodes_over_trigger_flood(self):
        fake_results = {
            "Build a workflow that monitors GitHub issues": {
                "nodes": [
                    {
                        "nodeId": "n8n-nodes-base.github",
                        "name": "GitHub",
                        "type": "n8n-nodes-base.github",
                    },
                    {
                        "nodeId": "n8n-nodes-base.githubTrigger",
                        "name": "GitHub Trigger",
                        "type": "n8n-nodes-base.githubTrigger",
                    },
                ]
            },
            "trigger": {
                "results": (
                    "n8n-nodes-base.manualTrigger "
                    "n8n-nodes-base.scheduleTrigger "
                    "n8n-nodes-base.webhook "
                    "n8n-nodes-base.formTrigger"
                )
            },
        }

        def fake_call(tool_name, arguments=None):
            self.assertEqual(tool_name, "search_nodes")
            query = arguments["queries"][0]
            payload = fake_results.get(query, {"nodes": []})
            return {"success": True, "data": payload}

        with patch.object(architect, "_call", side_effect=fake_call):
            nodes, _ = architect._discover_nodes(
                "Build a workflow that monitors GitHub issues",
                ["monitoring"],
            )

        node_ids = [item["nodeId"] for item in nodes]
        self.assertEqual(node_ids[0], "n8n-nodes-base.githubTrigger")
        self.assertIn("n8n-nodes-base.github", node_ids)


    def test_node_id_only_definitions_do_not_count_as_exact_schema(self):
        with patch.object(
            architect,
            "_call",
            return_value={
                "success": True,
                "data": {
                    "definitions": "n8n-nodes-base.github n8n-nodes-base.webhook"
                },
            },
        ):
            result = architect._get_node_types(
                [
                    {
                        "nodeId": "n8n-nodes-base.github",
                        "type": "n8n-nodes-base.github",
                    }
                ]
            )

        self.assertFalse(result["definitions"])


    def test_schema_markers_are_required_for_string_definitions(self):
        self.assertTrue(
            architect._looks_like_node_schema(
                "interface GithubParameters { resource: string; operation: string }"
            )
        )
        self.assertFalse(
            architect._looks_like_node_schema(
                "n8n-nodes-base.github n8n-nodes-base.webhook"
            )
        )


    def test_best_practices_prefers_documentation_field(self):
        with patch.object(
            architect,
            "_call",
            return_value={
                "success": True,
                "data": {
                    "technique": "monitoring",
                    "message": "summary",
                    "documentation": "Use bounded polling and explicit failure handling.",
                },
            },
        ):
            result = architect._best_practice_guidance(["monitoring"])

        self.assertEqual(
            result[0]["guidance"],
            "Use bounded polling and explicit failure handling.",
        )


    def test_external_alerts_are_treated_as_side_effects(self):
        requirements = architect._requirements(
            "Monitor GitHub issues and send me an alert when a bug appears.",
            ["monitoring"],
        )

        self.assertTrue(requirements["side_effect_review"]["required"])
        self.assertTrue(requirements["error_handling"]["required"])

    def test_design_workflow_fails_cleanly_for_empty_request(self):
        result = architect.design_workflow("")

        self.assertFalse(result["success"])
        self.assertIn("empty", result["message"].lower())

    def test_audit_workflow_flags_http_resilience_and_error_strategy(self):
        def fake_call(tool_name, arguments=None):
            self.assertEqual(tool_name, "get_workflow_details")
            return {
                "success": True,
                "data": {
                    "workflow": {
                        "id": "abc",
                        "name": "Example",
                        "active": True,
                        "nodes": [
                            {
                                "name": "Webhook",
                                "type": "n8n-nodes-base.webhook",
                            },
                            {
                                "name": "HTTP Request",
                                "type": "n8n-nodes-base.httpRequest",
                            },
                        ],
                        "connections": {
                            "Webhook": {
                                "main": [[{"node": "HTTP Request"}]]
                            }
                        },
                    }
                },
            }

        with patch.object(architect, "_call", side_effect=fake_call):
            result = architect.audit_workflow("abc")

        self.assertTrue(result["success"])
        finding_ids = {item["id"] for item in result["findings"]}
        self.assertIn("http_resilience_review", finding_ids)
        self.assertIn("missing_error_strategy", finding_ids)
        self.assertIn("active_with_open_findings", finding_ids)
        self.assertFalse(result["quality_gate"]["ready_to_publish"])

    def test_audit_workflow_requires_workflow_id(self):
        result = architect.audit_workflow("")

        self.assertFalse(result["success"])
        self.assertIn("workflow id", result["message"].lower())

    def test_run_architect_dispatches_audit_mode(self):
        with patch.object(
            architect,
            "audit_workflow",
            return_value={"success": True, "mode": "audit"},
        ) as audited:
            result = architect.run_architect(
                {
                    "mode": "audit",
                    "workflow_id": "abc",
                }
            )

        self.assertTrue(result["success"])
        audited.assert_called_once_with("abc")


    def test_registry_and_planner_expose_architect(self):
        from tool_registry import JSON_ARGUMENT_TOOLS, N8N_TOOLS

        self.assertIn("n8n_workflow_architect", N8N_TOOLS)
        self.assertIn("n8n_workflow_architect", JSON_ARGUMENT_TOOLS)

        import config
        import planner

        with patch.object(config, "N8N_MCP_ENABLED", True),              patch.object(
                 planner,
                 "config",
                 config,
             ),              patch(
                 "n8n_bridge.classify_n8n_request",
                 return_value="orchestration",
             ):
            scope = planner._planner_tool_scope(
                "Create an n8n workflow that monitors GitHub issues",
                {},
            )

        self.assertIn("n8n_workflow_architect", scope)

    def test_tool_dispatch_sends_json_to_architect(self):
        import tools

        with patch(
            "n8n_workflow_architect.run_architect",
            return_value={
                "success": True,
                "verified": True,
                "terminal": True,
                "execution_owner": "n8n",
                "mode": "design",
            },
        ) as architect_run:
            raw = tools._run_tool_raw(
                "n8n_workflow_architect",
                '{"request":"Design a webhook workflow"}',
            )

        self.assertTrue(raw["success"])
        architect_run.assert_called_once_with(
            {"request": "Design a webhook workflow"}
        )

if __name__ == "__main__":
    unittest.main()
