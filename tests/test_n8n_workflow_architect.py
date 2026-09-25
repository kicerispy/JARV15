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

    def test_node_search_parsing_preserves_discriminators(self):
        result = {
            "success": True,
            "data": {
                "results": (
                    "n8n-nodes-base.github "
                    "resource: issue operation: get_issues version: 1\n"
                    "n8n-nodes-base.slack "
                    "resource: message operation: send version: 2.4\n"
                    "n8n-nodes-base.switch mode: rules version: 3.4"
                )
            },
        }

        values = architect._result_list(
            result,
            ("nodes", "results", "items"),
        )

        by_id = {item["nodeId"]: item for item in values}
        self.assertEqual(by_id["n8n-nodes-base.github"]["resource"], "issue")
        self.assertEqual(by_id["n8n-nodes-base.github"]["operation"], "get_issues")
        self.assertEqual(by_id["n8n-nodes-base.slack"]["resource"], "message")
        self.assertEqual(by_id["n8n-nodes-base.slack"]["operation"], "send")
        self.assertEqual(by_id["n8n-nodes-base.switch"]["mode"], "rules")
        self.assertEqual(by_id["n8n-nodes-base.switch"]["version"], 3.4)


    def test_get_node_types_isolates_invalid_node_from_valid_schema(self):
        calls = []

        def fake_call(tool_name, arguments=None):
            self.assertEqual(tool_name, "get_node_types")
            ref = (arguments or {})["nodeIds"][0]
            calls.append(ref)

            if ref["nodeId"] == "n8n-nodes-base.badNode":
                return {
                    "success": False,
                    "message": "bad discriminator",
                }

            return {
                "success": True,
                "data": {
                    "definitions": (
                        "interface GithubTriggerParams { events: string[] }"
                    )
                },
            }

        with patch.object(architect, "_call", side_effect=fake_call):
            result = architect._get_node_types(
                [
                    {
                        "nodeId": "n8n-nodes-base.badNode",
                        "type": "n8n-nodes-base.badNode",
                    },
                    {
                        "nodeId": "n8n-nodes-base.githubTrigger",
                        "type": "n8n-nodes-base.githubTrigger",
                        "version": 1,
                    },
                ]
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["definitions"])
        self.assertEqual(len(calls), 2)


    def test_search_queries_expand_explicit_summarization_and_notification_nodes(self):
        queries = architect._search_queries(
            "Monitor GitHub issues, summarize bugs, and send me an alert",
            ["monitoring", "content_generation", "notification"],
        )

        self.assertIn("OpenAI text generation", queries)
        self.assertIn("Slack notification", queries)
        self.assertIn("Email send", queries)


    def test_get_node_types_forwards_search_discriminators(self):
        captured = {}

        def fake_call(tool_name, arguments=None):
            self.assertEqual(tool_name, "get_node_types")
            captured.update(arguments or {})
            return {
                "success": True,
                "data": {
                    "definitions": (
                        "interface SlackParams { resource: 'message'; operation: 'send' }"
                    )
                },
            }

        with patch.object(architect, "_call", side_effect=fake_call):
            result = architect._get_node_types(
                [
                    {
                        "nodeId": "n8n-nodes-base.slack",
                        "type": "n8n-nodes-base.slack",
                        "resource": "message",
                        "operation": "send",
                        "version": 2.4,
                    }
                ]
            )

        self.assertTrue(result["definitions"])
        self.assertEqual(
            captured["nodeIds"][0]["resource"],
            "message",
        )
        self.assertEqual(
            captured["nodeIds"][0]["operation"],
            "send",
        )
        self.assertEqual(
            captured["nodeIds"][0]["version"],
            2.4,
        )


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


    def test_search_queries_include_workflow_capabilities(self):
        queries = architect._search_queries(
            "Build a workflow that monitors GitHub issues, summarizes bugs, and sends me an alert",
            ["monitoring", "content_generation", "notification"],
        )

        self.assertIn("GitHub issues", queries)
        self.assertIn("notification", queries)
        self.assertIn("text generation", queries)


    def test_node_relevance_ignores_other_nodes_in_search_text(self):
        relevant = architect._node_relevance(
            "Build a workflow that monitors GitHub issues",
            {
                "name": "manualTrigger",
                "nodeId": "n8n-nodes-base.manualTrigger",
                "type": "n8n-nodes-base.manualTrigger",
                "_search_text": "n8n-nodes-base.github n8n-nodes-base.githubTrigger",
            },
        )
        github = architect._node_relevance(
            "Build a workflow that monitors GitHub issues",
            {
                "name": "GitHub",
                "nodeId": "n8n-nodes-base.github",
                "type": "n8n-nodes-base.github",
                "_search_text": "n8n-nodes-base.manualTrigger n8n-nodes-base.github",
            },
        )

        # A generic GitHub node is still textually relevant, but it must not
        # receive the strict github_source capability score without issue
        # semantics/discriminators. The manual trigger has neither.
        self.assertEqual(github[0], relevant[0])
        self.assertGreater(github[1], relevant[1])


    def test_best_practice_guidance_can_augment_missing_capability_nodes(self):
        candidates = [
            {
                "nodeId": "n8n-nodes-base.githubTrigger",
                "type": "n8n-nodes-base.githubTrigger",
                "name": "githubTrigger",
            }
        ]
        guidance = [
            {
                "technique": "notification",
                "guidance": (
                    "Recommended nodes: n8n-nodes-base.if, "
                    "n8n-nodes-base.slack, "
                    "@n8n/n8n-nodes-langchain.openAi"
                ),
            }
        ]

        augmented = architect._augment_nodes_from_guidance(
            "Monitor GitHub issues, summarize bugs, and send me an alert",
            candidates,
            guidance,
        )

        ids = {item["nodeId"] for item in augmented}
        self.assertIn("n8n-nodes-base.githubTrigger", ids)
        self.assertIn("n8n-nodes-base.if", ids)
        self.assertIn("n8n-nodes-base.slack", ids)
        self.assertIn("@n8n/n8n-nodes-langchain.openAi", ids)


    def test_node_relevance_prioritizes_multiple_requested_capabilities(self):
        request = "Monitor GitHub issues, summarize bugs, and send me an alert"

        github = architect._node_relevance(
            request,
            {"name": "GitHub Trigger", "nodeId": "n8n-nodes-base.githubTrigger", "type": "n8n-nodes-base.githubTrigger"},
        )
        unrelated = architect._node_relevance(
            request,
            {"name": "SSE Trigger", "nodeId": "n8n-nodes-base.sseTrigger", "type": "n8n-nodes-base.sseTrigger"},
        )

        self.assertGreater(github[:3], unrelated[:3])


    def test_quality_gate_requires_requested_capabilities(self):
        candidates = [
            {"name": "GitHub Trigger", "nodeId": "n8n-nodes-base.githubTrigger", "type": "n8n-nodes-base.githubTrigger"},
            {"name": "OpenAI", "nodeId": "n8n-nodes-langchain.openAi", "type": "n8n-nodes-langchain.openAi"},
            {"name": "If", "nodeId": "n8n-nodes-base.if", "type": "n8n-nodes-base.if"},
            {"name": "Slack", "nodeId": "n8n-nodes-base.slack", "type": "n8n-nodes-base.slack"},
        ]
        requirements = architect._requirements(
            "Monitor GitHub issues, summarize bugs, and send me an alert.",
            ["monitoring", "content_generation", "notification"],
        )
        gate = architect._quality_gate(
            "Monitor GitHub issues, summarize bugs, and send me an alert.",
            requirements,
            candidates,
            [{"content": "valid schema"}],
        )

        self.assertTrue(gate["ready_to_build"])
        self.assertEqual(gate["missing"], [])


    def test_capability_matching_rejects_lookalike_github_file_node(self):
        github_file = {
            "name": "GitHub",
            "nodeId": "n8n-nodes-base.githubTool",
            "type": "n8n-nodes-base.githubTool",
            "resource": "file",
            "operation": "create",
        }
        github_trigger = {
            "name": "GitHub Trigger",
            "nodeId": "n8n-nodes-base.githubTrigger",
            "type": "n8n-nodes-base.githubTrigger",
        }

        self.assertFalse(
            architect._capability_matches_node("github_source", github_file)
        )
        self.assertTrue(
            architect._capability_matches_node("github_source", github_trigger)
        )


    def test_capability_matching_rejects_classifier_as_condition(self):
        classifier = {
            "name": "Text Classifier",
            "nodeId": "@n8n/n8n-nodes-langchain.textClassifier",
            "type": "@n8n/n8n-nodes-langchain.textClassifier",
        }
        switch = {
            "name": "Switch",
            "nodeId": "n8n-nodes-base.switch",
            "type": "n8n-nodes-base.switch",
        }

        self.assertFalse(
            architect._capability_matches_node("condition", classifier)
        )
        self.assertTrue(
            architect._capability_matches_node("condition", switch)
        )


    def test_capability_matching_rejects_notification_trigger(self):
        slack_trigger = {
            "name": "Slack Trigger",
            "nodeId": "n8n-nodes-base.slackTrigger",
            "type": "n8n-nodes-base.slackTrigger",
        }
        slack = {
            "name": "Slack",
            "nodeId": "n8n-nodes-base.slack",
            "type": "n8n-nodes-base.slack",
        }

        self.assertFalse(
            architect._capability_matches_node("notification", slack_trigger)
        )
        self.assertTrue(
            architect._capability_matches_node("notification", slack)
        )


    def test_discover_nodes_backfills_missing_required_capabilities(self):
        request = "Monitor GitHub issues, summarize bugs, and send me an alert"

        def fake_call(tool_name, arguments=None):
            self.assertEqual(tool_name, "search_nodes")
            query = arguments["queries"][0]

            if query == "GitHub issue trigger":
                nodes = [{
                    "nodeId": "n8n-nodes-base.githubTrigger",
                    "name": "GitHub Trigger",
                    "type": "n8n-nodes-base.githubTrigger",
                }]
            elif query == "OpenAI text generation":
                nodes = [{
                    "nodeId": "@n8n/n8n-nodes-langchain.openAi",
                    "name": "OpenAI",
                    "type": "@n8n/n8n-nodes-langchain.openAi",
                }]
            elif query == "IF node":
                nodes = [{
                    "nodeId": "n8n-nodes-base.if",
                    "name": "If",
                    "type": "n8n-nodes-base.if",
                }]
            elif query == "Slack send":
                nodes = [{
                    "nodeId": "n8n-nodes-base.slack",
                    "name": "Slack",
                    "type": "n8n-nodes-base.slack",
                }]
            else:
                nodes = [
                    {
                        "nodeId": "n8n-nodes-base.manualTrigger",
                        "name": "Manual Trigger",
                        "type": "n8n-nodes-base.manualTrigger",
                    },
                    {
                        "nodeId": "n8n-nodes-base.githubTool",
                        "name": "GitHub",
                        "type": "n8n-nodes-base.githubTool",
                        "resource": "file",
                        "operation": "create",
                    },
                    {
                        "nodeId": "@n8n/n8n-nodes-langchain.textClassifier",
                        "name": "Text Classifier",
                        "type": "@n8n/n8n-nodes-langchain.textClassifier",
                    },
                ]

            return {"success": True, "data": {"nodes": nodes}}

        with patch.object(architect, "_call", side_effect=fake_call):
            nodes, _ = architect._discover_nodes(
                request,
                ["monitoring", "content_generation", "notification"],
            )

        node_ids = {item["nodeId"] for item in nodes}
        self.assertIn("n8n-nodes-base.githubTrigger", node_ids)
        self.assertIn("@n8n/n8n-nodes-langchain.openAi", node_ids)
        self.assertIn("n8n-nodes-base.if", node_ids)
        self.assertIn("n8n-nodes-base.slack", node_ids)


    def test_deprecated_nodes_are_detected_from_type_definitions(self):
        definition_text = """
/** @deprecated Do not use this node. */
export type RetiredNode = {
  type: 'n8n-nodes-base.workflowTrigger';
  version: 1;
};
"""
        ids = architect._deprecated_node_ids(
            definition_text,
            [
                {
                    "nodeId": "n8n-nodes-base.workflowTrigger",
                    "type": "n8n-nodes-base.workflowTrigger",
                }
            ],
        )

        self.assertIn("n8n-nodes-base.workflowTrigger", ids)


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
