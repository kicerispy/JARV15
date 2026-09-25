"""JARVIS n8n workflow builder and guarded deployment lifecycle.

The architect remains responsible for discovery/read-only analysis. This module
turns a verified architecture into n8n Workflow SDK code, validates it through
the live n8n MCP builder, creates it, verifies the saved graph, tests it with
pin data, audits it, and only publishes when activation was explicitly asked
for and every required gate passes.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from n8n_mcp import call_tool
from n8n_workflow_architect import audit_workflow, design_workflow

DEFAULT_OLLAMA_HOST = os.getenv("JARVIS_OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("JARVIS_N8N_BUILDER_MODEL", os.getenv("JARVIS_CODING_MODEL", "qwen3.5:9b"))
DEFAULT_TIMEOUT = 180
MAX_ARCHITECT_CONTEXT = 24000
MAX_SDK_REFERENCE_CHARS = 28000
MAX_REPAIR_ATTEMPTS = 2
PROGRESS_ENABLED = os.getenv("JARVIS_N8N_BUILDER_PROGRESS", "1").strip().lower() not in {"0", "false", "no", "off"}


def _progress(stage: str) -> None:
    if PROGRESS_ENABLED:
        print(f"[JARVIS][n8n-builder] {stage}", flush=True)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _bounded(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _result_data(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        return {}
    for key in ("data", "result", "output"):
        nested = data.get(key)
        if isinstance(nested, dict):
            data = nested
    return data


def _failed(message: str, **extra: Any) -> Dict[str, Any]:
    return {
        "success": False,
        "verified": False,
        "retryable": False,
        "terminal": True,
        "execution_owner": "n8n",
        "message": message,
        **extra,
    }


def _parse_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Builder model returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Builder model returned a JSON value instead of an object.")
    return parsed


def _ollama_json(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are JARVIS's n8n workflow compiler. Return only a JSON "
                    "object matching the requested output shape. Do not invent "
                    "node types or parameters outside supplied verified schemas."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 16384},
    }
    request = Request(
        DEFAULT_OLLAMA_HOST.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=max(30, int(timeout))) as response:
        parsed = json.loads(response.read().decode("utf-8", errors="replace"))
    message = parsed.get("message") if isinstance(parsed, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned no builder content.")
    return _parse_json_object(content)


def _architecture_context(design: Dict[str, Any]) -> str:
    payload = {
        "request": design.get("request"),
        "requirements": design.get("requirements"),
        "required_capabilities": design.get("required_capabilities"),
        "quality_gate": design.get("quality_gate"),
        "node_candidates": design.get("node_candidates"),
        "node_definitions": design.get("node_definitions"),
        "best_practices": design.get("best_practices"),
    }
    return _bounded(json.dumps(payload, ensure_ascii=False, indent=2), MAX_ARCHITECT_CONTEXT)


def _get_workflow_sdk_reference() -> Dict[str, Any]:
    """Fetch the live n8n Workflow SDK contract before compiling anything."""
    result = call_tool("get_workflow_sdk_reference", {"section": "all"})
    if result.get("success") is not True:
        return _failed(
            "n8n Workflow SDK reference could not be loaded.",
            stage="sdk_reference",
            details=result,
        )

    data = _result_data(result)
    reference = data.get("reference") or result.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        return _failed(
            "n8n Workflow SDK reference returned no reference text.",
            stage="sdk_reference",
            details=result,
        )

    return {
        "success": True,
        "verified": True,
        "reference": _bounded(reference, MAX_SDK_REFERENCE_CHARS),
        "message": "Live n8n Workflow SDK reference loaded before compilation.",
    }


def _sdk_shape_errors(code: str) -> List[str]:
    """Reject common model-generated SDK shapes before spending an MCP call."""
    errors: List[str] = []
    source = str(code or "")

    if "createWorkflow(" in source or "export default createWorkflow" in source:
        errors.append(
            "Do not use createWorkflow(). Import workflow() from @n8n/workflow-sdk "
            "and export workflow('id', 'name')."
        )

    if "export type " in source or "export interface " in source:
        errors.append(
            "Do not emit TypeScript type/interface exports. The validator expects "
            "executable Workflow SDK source only."
        )

    if not source.lstrip().startswith("import "):
        errors.append(
            "Workflow SDK code must begin with an import from @n8n/workflow-sdk."
        )

    if "@n8n/workflow-sdk" not in source:
        errors.append("Import the Workflow SDK from @n8n/workflow-sdk.")

    if not re.search(
        r"export\s+default\s+workflow\s*\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]",
        source,
    ):
        errors.append(
            "The final export must be export default workflow('stable-id', 'Workflow Name') "
            "with both required string arguments."
        )

    return errors

def _compiler_prompt(
    design: Dict[str, Any],
    *,
    sdk_reference: str,
    previous_code: str = "",
    validation_error: str = "",
) -> str:
    repair = ""
    if validation_error:
        repair = "\nVALIDATOR FEEDBACK:\n" + _bounded(validation_error, 12000)
    previous = ""
    if previous_code:
        previous = "\nPRIOR CODE:\n" + _bounded(previous_code, 30000)

    return f"""
Build one new n8n workflow from the verified architecture below.

Return exactly:
{{"name":"short name","description":"short description","code":"full Workflow SDK JavaScript/TypeScript source"}}

Rules:
- The live SDK reference below is authoritative. Follow it over prior knowledge.
- Import only from @n8n/workflow-sdk.
- Define trigger/node instances first, then compose them into the workflow.
- The final export MUST be exactly the SDK shape: export default workflow('stable-id', 'Workflow Name')...
- workflow() requires TWO string arguments: a stable workflow id and a workflow name.
- Put node parameters under config.parameters; do not put parameters directly beside config.
- Use .add(...), .to(...), and the documented branch helpers to wire nodes.
- Do not use createWorkflow, workflow({...}), workflow([ ... ]), a one-argument workflow('name'), or raw workflow JSON.
- Do not emit export type, export interface, typeof default_, or other type-only exports.
- Do not leave branch wiring as standalone statements after export default.
- Use only node types, versions, parameters, and SDK functions supported by the supplied verified definitions and SDK reference.
- Include a real trigger and connect every required stage.
- Do not invent credentials or secrets. Use only documented newCredential(...) references when the verified architecture requires credentials.
- Keep the graph minimal and deterministic.
- Preserve the requested notification, condition, summarization, and source behavior.
- Use n8n expressions for values flowing between nodes.
- When repairing invalid code, rewrite the whole code into the documented SDK pattern instead of making a local textual patch.
- Return executable SDK source only, not TypeScript declarations and not raw workflow JSON.

LIVE WORKFLOW SDK REFERENCE:
{_bounded(sdk_reference, MAX_SDK_REFERENCE_CHARS)}

VERIFIED ARCHITECTURE:
{_architecture_context(design)}
{repair}
{previous}
"""


def _validate_code(code: str) -> Dict[str, Any]:
    shape_errors = _sdk_shape_errors(code)
    if shape_errors:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "execution_owner": "n8n",
            "mcp_tool": "local_sdk_guard",
            "data": {
                "valid": False,
                "errors": shape_errors,
                "hint": (
                    "Rewrite the workflow using the live n8n Workflow SDK reference. "
                    "The final export must call workflow('id', 'name')."
                ),
            },
            "message": "Generated workflow failed the local SDK shape guard.",
        }
    return call_tool("validate_workflow", {"code": code})


def _create_workflow(
    code: str,
    name: str,
    description: str,
    project_id: Optional[str],
    folder_id: Optional[str],
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "code": code,
        "name": name[:128],
        "description": description[:255],
        "skillsUsed": ["n8n-workflow-architect", "n8n-workflow-builder"],
    }
    if project_id:
        arguments["projectId"] = project_id
    if folder_id:
        arguments["folderId"] = folder_id
    return call_tool("create_workflow_from_code", arguments)


def _workflow_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    data = _result_data(result)
    workflow = data.get("workflow")
    return workflow if isinstance(workflow, dict) else {}


def _verify_saved_workflow(workflow_id: str) -> Dict[str, Any]:
    result = call_tool(
        "get_workflow_details",
        {"workflowId": workflow_id, "detailLevel": "full"},
    )
    if result.get("success") is not True:
        return result
    workflow = _workflow_from_result(result)
    if not workflow:
        return _failed("n8n returned no workflow graph after creation.")
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    connections = (
        workflow.get("connections")
        if isinstance(workflow.get("connections"), dict)
        else {}
    )
    return {
        "success": True,
        "verified": True,
        "workflow": workflow,
        "node_count": len(nodes),
        "connection_count": sum(
            1 for value in connections.values() if isinstance(value, dict)
        ),
        "message": "Created workflow graph verified through n8n MCP.",
    }


def _sample_from_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return {}
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties")
        if isinstance(props, dict):
            return {
                key: _sample_from_schema(value)
                for key, value in props.items()
            }
        return {}
    if schema_type == "array":
        item = schema.get("items")
        return [_sample_from_schema(item)] if isinstance(item, dict) else []
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if schema_type in {"number", "integer"}:
        return 1
    if schema_type == "boolean":
        return True
    return "sample"


def _prepare_pin_data(workflow_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = call_tool(
        "prepare_workflow_pin_data",
        {"workflowId": workflow_id},
    )
    if result.get("success") is not True:
        return {}, result

    data = _result_data(result)
    pin_data: Dict[str, Any] = {}

    schemas = data.get("nodeSchemasToGenerate")
    if isinstance(schemas, dict):
        for node_name, schema in schemas.items():
            pin_data[str(node_name)] = [
                {"json": _sample_from_schema(schema)}
            ]

    without_schema = data.get("nodesWithoutSchema")
    if isinstance(without_schema, list):
        for node_name in without_schema:
            pin_data[str(node_name)] = [{"json": {}}]

    return pin_data, {
        "success": True,
        "verified": True,
        "coverage": data.get("coverage"),
        "message": "Generated deterministic test pin data from n8n schemas.",
    }


def _select_trigger(workflow: Dict[str, Any]) -> Optional[str]:
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return None

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").lower()
        if any(
            token in node_type
            for token in (
                "webhook",
                "chattrigger",
                "formtrigger",
                "scheduletrigger",
                "manualtrigger",
            )
        ):
            return str(node.get("name") or "") or None

    return None


def _test_workflow(
    workflow_id: str,
    workflow: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    pin_data, prep = _prepare_pin_data(workflow_id)
    if prep.get("success") is not True:
        return _failed(
            "Could not prepare n8n test pin data.",
            stage="test_prepare",
            details=prep,
        )

    arguments: Dict[str, Any] = {
        "workflowId": workflow_id,
        "pinData": pin_data,
        "timeout": max(30, min(int(timeout), 3600)),
    }
    trigger = _select_trigger(workflow)
    if trigger:
        arguments["triggerNodeName"] = trigger

    result = call_tool("test_workflow", arguments)
    data = _result_data(result)
    status = str(
        data.get("status") or result.get("status") or ""
    ).lower()
    success = result.get("success") is True and status == "success"

    return {
        **result,
        "success": success,
        "verified": success,
        "test_status": status,
        "pin_data_coverage": prep.get("coverage"),
        "message": (
            "n8n workflow test completed successfully."
            if success
            else str(
                result.get("message")
                or data.get("error")
                or result.get("error")
                or "n8n workflow test did not pass."
            )
        ),
    }


def build_workflow(arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    arguments = dict(arguments or {})
    request = _clean(arguments.get("request"))
    if not request:
        return _failed("n8n workflow build request is empty.")

    activate_requested = bool(arguments.get("activate", False))
    test_requested = bool(arguments.get("test", True))
    project_id = _clean(arguments.get("project_id")) or None
    folder_id = _clean(arguments.get("folder_id")) or None
    timeout = int(arguments.get("test_timeout", 300) or 300)

    _progress("architecture: discovering n8n capabilities")
    design = design_workflow(request, arguments.get("context"))
    if (
        design.get("quality_gate", {}).get("ready_to_build")
        is not True
    ):
        return _failed(
            "n8n architecture is not ready to build.",
            stage="architecture",
            architecture=design,
        )

    _progress("sdk-reference: loading live n8n Workflow SDK contract")
    sdk_result = _get_workflow_sdk_reference()
    if sdk_result.get("success") is not True:
        return sdk_result
    sdk_reference = str(sdk_result["reference"])

    code = str(arguments.get("workflow_code") or "").strip()
    name = _clean(arguments.get("name"))
    description = _clean(arguments.get("description"))
    attempts: List[Dict[str, Any]] = []

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        _progress(f"compile/validate: attempt {attempt + 1}/{MAX_REPAIR_ATTEMPTS + 1}")
        if not code:
            try:
                generated = _ollama_json(_compiler_prompt(design, sdk_reference=sdk_reference))
            except Exception as exc:
                return _failed(
                    f"n8n workflow compiler failed: {exc}",
                    stage="compile",
                    architecture=design,
                )
            code = str(generated.get("code") or "").strip()
            name = name or _clean(generated.get("name"))
            description = description or _clean(generated.get("description"))

        if not code:
            return _failed(
                "n8n workflow compiler produced empty code.",
                stage="compile",
            )

        validation = _validate_code(code)
        attempts.append({
            "attempt": attempt + 1,
            "validation": validation,
        })
        data = _result_data(validation)
        valid = bool(
            data.get("valid", validation.get("valid", False))
        )

        if validation.get("success") is True and valid:
            break

        if arguments.get("workflow_code") and attempt == 0:
            return _failed(
                "Provided n8n workflow code failed validation.",
                stage="validate",
                attempts=attempts,
            )

        if attempt >= MAX_REPAIR_ATTEMPTS:
            return _failed(
                "n8n workflow code failed validation after repair attempts.",
                stage="validate",
                attempts=attempts,
            )

        error_text = json.dumps(
            validation,
            ensure_ascii=False,
            default=str,
        )
        repaired = _ollama_json(
            _compiler_prompt(
                design,
                sdk_reference=sdk_reference,
                previous_code=code,
                validation_error=error_text,
            )
        )
        code = str(repaired.get("code") or "").strip()

    _progress("create: sending validated workflow to n8n")
    create_result = _create_workflow(
        code,
        name or "JARVIS Generated Workflow",
        description or request,
        project_id,
        folder_id,
    )
    if create_result.get("success") is not True:
        return _failed(
            "n8n workflow mutation failed during creation.",
            stage="create",
            creation=create_result,
            attempts=attempts,
        )

    create_data = _result_data(create_result)
    workflow_id = _clean(
        create_data.get("workflowId")
        or create_result.get("workflowId")
    )
    if not workflow_id:
        return _failed(
            "n8n created the workflow but did not return a workflow ID.",
            stage="create",
            creation=create_result,
        )

    _progress("verify: fetching saved workflow graph")
    verification = _verify_saved_workflow(workflow_id)
    if verification.get("success") is not True:
        return _failed(
            "Created n8n workflow could not be verified.",
            stage="verify_creation",
            workflow_id=workflow_id,
            creation=create_result,
            verification=verification,
        )

    workflow = verification["workflow"]
    _progress("test: preparing pin data and executing workflow")
    test_result = (
        _test_workflow(workflow_id, workflow, timeout)
        if test_requested
        else None
    )
    _progress("audit: checking live workflow graph")
    audit_result = audit_workflow(workflow_id)

    audit_ready = bool(
        audit_result.get("quality_gate", {}).get("ready_to_publish")
    )
    test_ready = (
        not test_requested
        or bool(test_result and test_result.get("success"))
    )

    published = None
    if activate_requested:
        if not test_ready:
            return _failed(
                "Activation blocked because the workflow test did not pass.",
                stage="activate_gate",
                workflow_id=workflow_id,
                test=test_result,
                audit=audit_result,
            )
        if not audit_ready:
            return _failed(
                "Activation blocked because the workflow audit has open "
                "high-severity findings.",
                stage="activate_gate",
                workflow_id=workflow_id,
                test=test_result,
                audit=audit_result,
            )

        _progress("publish: activation gate passed; publishing workflow")
        published = call_tool(
            "publish_workflow",
            {"workflowId": workflow_id},
        )
        if published.get("success") is not True:
            return _failed(
                "Workflow was built and tested, but n8n publication failed.",
                stage="publish",
                workflow_id=workflow_id,
                test=test_result,
                audit=audit_result,
                publish=published,
            )

    return {
        "success": True,
        "verified": True,
        "retryable": False,
        "terminal": True,
        "execution_owner": "n8n",
        "mode": "build",
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name"),
        "workflow_url": create_data.get("url") or create_result.get("url"),
        "architecture": design,
        "sdk_reference_loaded": True,
        "validation_attempts": attempts,
        "creation": create_result,
        "verification": {
            "node_count": verification.get("node_count"),
            "connection_count": verification.get("connection_count"),
        },
        "test": test_result,
        "audit": audit_result,
        "published": published,
        "activation_requested": activate_requested,
        "message": (
            "n8n workflow created, verified, tested, and published."
            if published is not None
            else "n8n workflow created, verified, tested, and audited."
            if test_result is not None
            else "n8n workflow created, verified, and audited."
        ),
    }


def run_builder(
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return build_workflow(arguments)
