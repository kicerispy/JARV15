import unittest
from unittest.mock import patch

import n8n_workflow_builder as builder


class N8nWorkflowBuilderTests(unittest.TestCase):
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
                    "data": {"reference": "SDK: workflow('id', 'name'); node({config: {parameters: {}}});"},
                }
        if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "verified": True,
                    "data": {"reference": "SDK: workflow('id', 'name'); node({config: {parameters: {}}});"},
                }
        if name == "get_workflow_sdk_reference":
                return {
                    "success": True,
                    "verified": True,
                    "data": {"reference": "SDK: workflow('id', 'name'); node({config: {parameters: {}}});"},
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
                     "code": "export default {};",
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

    def test_activation_requires_passing_test_and_audit_then_publishes(self):
        graph = self._graph()
        design = self._design()
        calls = []

        def fake_call(name, args=None):
            calls.append(name)
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
             patch.object(builder, "_ollama_json", return_value={"name": "x", "code": "code"}), \
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
             patch.object(builder, "_ollama_json", return_value={"name": "x", "code": "code"}), \
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
        self.assertEqual(result["stage"], "activate_gate")


if __name__ == "__main__":
    unittest.main()
