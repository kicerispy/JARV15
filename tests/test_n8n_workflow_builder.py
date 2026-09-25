import unittest
from unittest.mock import patch

import n8n_workflow_builder as builder


class N8nWorkflowBuilderTests(unittest.TestCase):
    VALID_CODE = (
        "import { workflow } from '@n8n/workflow-sdk';\n"
        "export default workflow('id', 'Test Workflow');"
    )
    def test_sdk_shape_guard_rejects_common_model_failures(self):
        bad_codes = [
            "export default createWorkflow('Name', []);",
            "import { workflow } from '@n8n/workflow-sdk'; export default workflow('Name');",
            "import { workflow } from '@n8n/workflow-sdk'; export type Foo = typeof default_;",
        ]

        for code in bad_codes:
            self.assertTrue(builder._sdk_shape_errors(code), code)

        good = (
            "import { workflow } from '@n8n/workflow-sdk';\n"
            "export default workflow('stable-id', 'Workflow Name');"
        )
        self.assertEqual(builder._sdk_shape_errors(good), [])

    def test_compiler_prompt_includes_hard_node_type_allowlist(self):
        prompt = builder._compiler_prompt(
            self._design(),
            sdk_reference="workflow('id', 'name')",
            previous_code="const x = node({type: 'n8n-nodes-base.fake'});",
            validation_error=(
                "These node types are not present in the verified live n8n schemas: "
                "n8n-nodes-base.fake"
            ),
        )
        self.assertIn("ALLOWED NODE TYPES:", prompt)
        self.assertIn("@n8n/n8n-nodes-langchain.lmChatOpenAi", prompt)
        self.assertIn("HARD REPAIR REQUIREMENT:", prompt)
        self.assertIn("Remove every unknown node type", prompt)

    def test_compiler_prompt_renders_ai_reference_without_python_formatting_error(self):
        prompt = builder._compiler_prompt(
            self._design(),
            sdk_reference="workflow('id', 'name')",
        )
        self.assertIn("subnodes: { model: openAiModel }", prompt)
        self.assertIn("const openAiModel = languageModel({", prompt)

    def test_invented_node_version_is_rejected_when_schema_version_is_unknown(self):
        code = (
            "import { workflow, node } from '@n8n/workflow-sdk';\n"
            "const filter = node({type: 'n8n-nodes-base.filter', version: 1.2, config: {name: 'Filter', parameters: {}}});\n"
            "export default workflow('id', 'Workflow').add(filter);"
        )
        errors = builder._sdk_shape_errors(
            code,
            allowed_node_types=["n8n-nodes-base.filter"],
            verified_node_versions={},
        )
        self.assertTrue(any("invented version 1.2" in error for error in errors))

    def test_verified_node_version_passes_version_guard(self):
        code = (
            "import { workflow, node } from '@n8n/workflow-sdk';\n"
            "const filter = node({type: 'n8n-nodes-base.filter', version: 2.3, config: {name: 'Filter', parameters: {}}});\n"
            "export default workflow('id', 'Workflow').add(filter);"
        )
        errors = builder._sdk_shape_errors(
            code,
            allowed_node_types=["n8n-nodes-base.filter"],
            verified_node_versions={"n8n-nodes-base.filter": ["2.3"]},
        )
        self.assertFalse(any("version 2.3" in error for error in errors))

    def test_verified_node_allowlist_includes_common_runtime_nodes(self):
        design = self._design()
        allowed = builder._verified_node_types(design)
        self.assertIn("n8n-nodes-base.set", allowed)
        self.assertIn("n8n-nodes-base.httpRequest", allowed)
        self.assertIn("@n8n/n8n-nodes-langchain.chainLlm", allowed)

    def test_compiler_retry_instruction_for_unknown_nodes(self):
        prompt = builder._compiler_prompt(
            self._design(),
            sdk_reference="workflow('id', 'name')",
            validation_error=(
                "These node types are not present in the verified live n8n schemas: "
                "n8n-nodes-base.fake. Do not invent node types."
            ),
        )
        self.assertIn("HARD REPAIR REQUIREMENT:", prompt)
        self.assertIn("ONLY the exact node types listed under ALLOWED NODE TYPES", prompt)

    def test_compiler_for_unspecified_alert_uses_safe_set_output(self):
        design = self._design()
        design["required_capabilities"] = ["trigger", "github_source", "summarization", "condition", "alert_output"]
        prompt = builder._compiler_prompt(
            design,
            sdk_reference="workflow('id', 'name')",
        )
        self.assertIn('required_capabilities contains "alert_output"', prompt)
        self.assertIn("NEVER use emailSend, slack, Discord, Telegram", prompt)
        self.assertIn("n8n-nodes-base.set", prompt)

    def test_unknown_node_type_is_rejected_against_verified_schemas(self):
        code = (
            "import { workflow } from '@n8n/workflow-sdk';\n"
            "const summarize = node({type: '@n8n/n8n-nodes-langchain.summarize'});\n"
            "export default workflow('id', 'Workflow').add(summarize);"
        )
        errors = builder._sdk_shape_errors(
            code,
            allowed_node_types=["n8n-nodes-base.code"],
        )
        self.assertTrue(any("not present in the verified live n8n schemas" in error for error in errors))
        self.assertTrue(any("summarize" in error for error in errors))

    def test_verified_node_type_passes_node_type_guard(self):
        code = (
            "import { workflow } from '@n8n/workflow-sdk';\n"
            "const codeNode = node({type: 'n8n-nodes-base.code'});\n"
            "export default workflow('id', 'Workflow').add(codeNode);"
        )
        errors = builder._sdk_shape_errors(
            code,
            allowed_node_types=["n8n-nodes-base.code"],
        )
        self.assertFalse(any("not present in the verified live n8n schemas" in error for error in errors))

    def test_undefined_ai_subnode_reference_is_rejected(self):
        code = (
            "import { workflow, node } from '@n8n/workflow-sdk';\n"
            "const startTrigger = trigger({});\n"
            "const aiAgent = node({config: {subnodes: {model: openAiModel}}});\n"
            "export default workflow('id', 'name').add(startTrigger).to(aiAgent);"
        )
        errors = builder._sdk_shape_errors(code)
        self.assertTrue(any("undefined" in error.lower() for error in errors))
        self.assertTrue(any("openAiModel" in error for error in errors))

    def test_defined_ai_subnode_reference_passes_shape_guard(self):
        code = (
            "import { workflow, node, trigger, languageModel } from '@n8n/workflow-sdk';\n"
            "const openAiModel = languageModel({type: '@n8n/n8n-nodes-langchain.lmChatOpenAi', version: 1.3, config: {name: 'OpenAI Model', parameters: {}}});\n"
            "const startTrigger = trigger({});\n"
            "const aiAgent = node({config: {subnodes: {model: openAiModel}}});\n"
            "export default workflow('id', 'name').add(startTrigger).to(aiAgent);"
        )
        self.assertFalse(builder._sdk_shape_errors(code))

    def test_validation_warning_blockers_force_repair(self):
        validation = {
            "success": True,
            "data": {
                "valid": True,
                "warnings": [
                    {
                        "code": "MISSING_EXPRESSION_PREFIX",
                        "message": "message contains an expression without '=' prefix",
                    },
                    {
                        "code": "INVALID_PARAMETER",
                        "message": "parameters.text expected string, got undefined",
                    },
                ],
            },
        }
        blockers = builder._validation_blockers(validation)
        self.assertEqual(len(blockers), 2)
        self.assertTrue(all(":" in item for item in blockers))

    def test_structural_n8n_warnings_are_blockers_and_have_repair_rules(self):
        validation = {
            "success": True,
            "data": {
                "valid": True,
                "warnings": [
                    {"code": "SET_INVALID_ASSIGNMENT", "message": "assignments must be an object"},
                    {"code": "INVALID_INPUT_INDEX", "message": "input index 0 is invalid"},
                    {"code": "INVALID_OUTPUT_INDEX", "message": "output index 1 is invalid"},
                    {"code": "INVALID_PARAMETER", "message": "Slack operation invalid"},
                    {"code": "MISSING_EXPRESSION_PREFIX", "message": "expression without '='"},
                ],
            },
        }
        blockers = builder._validation_blockers(validation)
        self.assertEqual(len(blockers), 5)
        rules = builder._schema_repair_instructions(blockers)
        self.assertGreaterEqual(len(rules), 4)
        self.assertTrue(any("inner assignments array" in rule for rule in rules))
        self.assertTrue(any("resource: 'message' and operation: 'post'" in rule for rule in rules))
        self.assertTrue(any("output 0 to input 0" in rule for rule in rules))

    def test_select_trigger_detects_service_specific_trigger(self):
        graph = {
            "nodes": [
                {
                    "name": "GitHub Trigger",
                    "type": "n8n-nodes-base.githubTrigger",
                    "isTrigger": True,
                },
            ],
        }
        self.assertEqual(builder._select_trigger(graph), "GitHub Trigger")

    def test_failed_requested_test_returns_failure_even_without_activation(self):
        graph = self._graph()
        design = self._design()

        def fake_call(name, args=None):
            if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "data": {"reference": "SDK: workflow('id', 'name')"},
                }
            if name == "validate_workflow":
                return {"success": True, "data": {"valid": True}}
            if name == "create_workflow_from_code":
                return {"success": True, "data": {"workflowId": "wf-123"}}
            if name == "get_workflow_details":
                return {"success": True, "data": {"workflow": graph}}
            if name == "prepare_workflow_pin_data":
                return {
                    "success": True,
                    "data": {
                        "nodeSchemasToGenerate": {},
                        "nodesWithoutSchema": ["Slack"],
                        "coverage": {},
                    },
                }
            if name == "test_workflow":
                return {
                    "success": True,
                    "data": {"status": "error", "error": "No active execution found"},
                }
            raise AssertionError(name)

        with patch.object(builder, "design_workflow", return_value=design),              patch.object(builder, "_ollama_json", return_value={"name": "x", "code": self.VALID_CODE}),              patch.object(builder, "call_tool", side_effect=fake_call),              patch.object(
                 builder,
                 "audit_workflow",
                 return_value={
                     "success": True,
                     "quality_gate": {"ready_to_publish": True},
                     "findings": [],
                 },
             ):
            result = builder.build_workflow({
                "request": "Build it",
                "test": True,
                "activate": False,
            })

        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "test_gate")
        self.assertEqual(result["workflow_id"], "wf-123")

    def test_sdk_reference_loader_requires_live_reference(self):
        with patch.object(
            builder,
            "call_tool",
            return_value={
                "success": True,
                "verified": True,
                "data": {"reference": "workflow('id', 'name')"},
            },
        ) as call_tool:
            result = builder._get_workflow_sdk_reference()

        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertIn("workflow('id', 'name')", result["reference"])
        call_tool.assert_called_once_with(
            "get_workflow_sdk_reference",
            {"section": "all"},
        )

    def _design(self):
        return {
            "success": True,
            "verified": True,
            "quality_gate": {
                "ready_to_build": True,
                "missing": [],
            },
            "request": "Build a workflow that alerts me when GitHub issues appear",
            "requirements": {"trigger": "GitHub issue trigger"},
            "required_capabilities": ["trigger", "notification"],
            "node_candidates": [],
            "node_definitions": [],
            "best_practices": [],
        }

    def _graph(self):
        return {
            "id": "wf-123",
            "name": "GitHub Issue Alert",
            "active": False,
            "nodes": [
                {
                    "name": "Manual Trigger",
                    "type": "n8n-nodes-base.manualTrigger",
                },
                {
                    "name": "Slack",
                    "type": "n8n-nodes-base.slack",
                },
            ],
            "connections": {
                "Manual Trigger": {
                    "main": [[{"node": "Slack", "type": "main", "index": 0}]]
                }
            },
        }

    def test_sample_from_schema_builds_deterministic_values(self):
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "count": {"type": "integer"},
                "enabled": {"type": "boolean"},
                "mode": {"enum": ["open", "closed"]},
            },
        }

        self.assertEqual(
            builder._sample_from_schema(schema),
            {
                "title": "sample",
                "count": 1,
                "enabled": True,
                "mode": "open",
            },
        )

    def test_build_stops_before_mutation_when_architecture_is_not_ready(self):
        design = self._design()
        design["quality_gate"]["ready_to_build"] = False
        with patch.object(builder, "design_workflow", return_value=design), \
             patch.object(builder, "call_tool") as call_tool:
            result = builder.build_workflow({"request": "Build it"})

        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "architecture")
        call_tool.assert_not_called()

    def test_builder_validates_creates_verifies_tests_and_audits_without_publish(self):
        graph = self._graph()
        design = self._design()

        def fake_call(name, args=None):
            if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "verified": True,
                    "data": {
                        "reference": (
                            "SDK: workflow('id', 'name'); "
                            "node({config: {parameters: {}}});"
                        )
                    },
                }
            if name == "validate_workflow":
                return {"success": True, "verified": True, "data": {"valid": True}}
            if name == "create_workflow_from_code":
                return {
                    "success": True,
                    "verified": True,
                    "data": {
                        "workflowId": "wf-123",
                        "name": "GitHub Issue Alert",
                        "url": "http://n8n.local/workflow/wf-123",
                    },
                }
            if name == "get_workflow_details":
                return {"success": True, "verified": True, "data": {"workflow": graph}}
            if name == "prepare_workflow_pin_data":
                return {
                    "success": True,
                    "verified": True,
                    "data": {
                        "nodeSchemasToGenerate": {},
                        "nodesWithoutSchema": ["Slack"],
                        "coverage": {"total": 2, "skipped": 1},
                    },
                }
            if name == "test_workflow":
                return {"success": True, "verified": True, "data": {"status": "success"}}
            raise AssertionError(f"Unexpected tool call: {name}")

        with patch.object(builder, "design_workflow", return_value=design), \
             patch.object(
                 builder,
                 "_ollama_json",
                 return_value={
                     "name": "GitHub Issue Alert",
                     "description": "Alerts on issues",
                     "code": self.VALID_CODE,
                 },
             ), \
             patch.object(builder, "call_tool", side_effect=fake_call), \
             patch.object(
                 builder,
                 "audit_workflow",
                 return_value={
                     "success": True,
                     "verified": True,
                     "quality_gate": {"ready_to_publish": True},
                     "findings": [],
                 },
             ):

            result = builder.build_workflow({
                "request": "Build it",
                "test": True,
                "activate": False,
            })

        self.assertTrue(result["success"])
        self.assertEqual(result["workflow_id"], "wf-123")
        self.assertTrue(result["verification"]["node_count"])
        self.assertTrue(result["test"]["success"])
        self.assertIsNone(result["published"])

    def test_validation_warnings_are_repaired_before_creation(self):
        graph = self._graph()
        design = self._design()
        calls = []
        generated = [
            {
                "name": "x",
                "code": (
                    "import { workflow } from '@n8n/workflow-sdk';\n"
                    "export default workflow('id', 'x');"
                ),
            },
            {
                "name": "x",
                "code": (
                    "import { workflow } from '@n8n/workflow-sdk';\n"
                    "export default workflow('id', 'x');"
                ),
            },
        ]

        def fake_ollama(*args, **kwargs):
            return generated.pop(0)

        def fake_call(name, args=None):
            calls.append((name, args))
            if name == "get_workflow_sdk_reference":
                return {"success": True, "data": {"reference": "SDK: workflow('id', 'name')"}}
            if name == "validate_workflow":
                if sum(1 for call, _ in calls if call == "validate_workflow") == 1:
                    return {
                        "success": True,
                        "data": {
                            "valid": True,
                            "warnings": [
                                {
                                    "code": "INVALID_PARAMETER",
                                    "message": "bad type",
                                }
                            ],
                        },
                    }
                return {"success": True, "data": {"valid": True, "warnings": []}}
            if name == "create_workflow_from_code":
                return {"success": True, "data": {"workflowId": "wf-123"}}
            if name == "get_workflow_details":
                return {"success": True, "data": {"workflow": graph}}
            if name == "prepare_workflow_pin_data":
                return {"success": True, "data": {"nodeSchemasToGenerate": {}, "nodesWithoutSchema": []}}
            if name == "test_workflow":
                return {"success": True, "data": {"status": "success"}}
            raise AssertionError(name)

        with patch.object(builder, "design_workflow", return_value=design),              patch.object(builder, "_ollama_json", side_effect=fake_ollama),              patch.object(builder, "call_tool", side_effect=fake_call),              patch.object(
                 builder,
                 "audit_workflow",
                 return_value={
                     "success": True,
                     "quality_gate": {"ready_to_publish": True},
                     "findings": [],
                 },
             ):
            result = builder.build_workflow({
                "request": "Build it",
                "test": True,
                "activate": False,
            })

        self.assertTrue(result["success"])
        self.assertEqual(
            sum(1 for call, _ in calls if call == "validate_workflow"),
            2,
        )

    def test_activation_requires_passing_test_and_audit_then_publishes(self):
        graph = self._graph()
        design = self._design()
        calls = []

        def fake_call(name, args=None):
            calls.append(name)
            if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "verified": True,
                    "data": {"reference": "SDK: workflow('id', 'name')"},
                }
            if name == "validate_workflow":
                return {"success": True, "verified": True, "data": {"valid": True}}
            if name == "create_workflow_from_code":
                return {"success": True, "data": {"workflowId": "wf-123"}}
            if name == "get_workflow_details":
                return {"success": True, "data": {"workflow": graph}}
            if name == "prepare_workflow_pin_data":
                return {
                    "success": True,
                    "data": {
                        "nodeSchemasToGenerate": {},
                        "nodesWithoutSchema": [],
                    },
                }
            if name == "test_workflow":
                return {"success": True, "data": {"status": "success"}}
            if name == "publish_workflow":
                return {"success": True, "data": {"activeVersionId": "v2"}}
            raise AssertionError(name)

        with patch.object(builder, "design_workflow", return_value=design), \
             patch.object(builder, "_ollama_json", return_value={"name": "x", "code": self.VALID_CODE}), \
             patch.object(builder, "call_tool", side_effect=fake_call), \
             patch.object(
                 builder,
                 "audit_workflow",
                 return_value={
                     "success": True,
                     "verified": True,
                     "quality_gate": {"ready_to_publish": True},
                     "findings": [],
                 },
             ):
            result = builder.build_workflow({
                "request": "Build it",
                "test": True,
                "activate": True,
            })

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["published"])
        self.assertEqual(calls[-1], "publish_workflow")

    def test_activation_is_blocked_when_test_fails(self):
        graph = self._graph()
        design = self._design()

        def fake_call(name, args=None):
            if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "verified": True,
                    "data": {"reference": "SDK: workflow('id', 'name')"},
                }
            if name == "validate_workflow":
                return {"success": True, "data": {"valid": True}}
            if name == "create_workflow_from_code":
                return {"success": True, "data": {"workflowId": "wf-123"}}
            if name == "get_workflow_details":
                return {"success": True, "data": {"workflow": graph}}
            if name == "prepare_workflow_pin_data":
                return {"success": True, "data": {"nodeSchemasToGenerate": {}, "nodesWithoutSchema": []}}
            if name == "test_workflow":
                return {"success": True, "data": {"status": "error", "error": "boom"}}
            if name == "publish_workflow":
                raise AssertionError("publish must not be called")
            raise AssertionError(name)

        with patch.object(builder, "design_workflow", return_value=design), \
             patch.object(builder, "_ollama_json", return_value={"name": "x", "code": self.VALID_CODE}), \
             patch.object(builder, "call_tool", side_effect=fake_call), \
             patch.object(
                 builder,
                 "audit_workflow",
                 return_value={
                     "success": True,
                     "quality_gate": {"ready_to_publish": True},
                     "findings": [],
                 },
             ):
            result = builder.build_workflow({
                "request": "Build it",
                "test": True,
                "activate": True,
            })

        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "test_gate")


if __name__ == "__main__":
    unittest.main()
