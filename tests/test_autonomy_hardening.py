import json
from pathlib import Path

import planner
import tools
import tool_executor
from agent_core import JarvisAgent
from superpowers_engine import classify_software_request
from tool_result import ToolResult


BENCHMARK_PATH = Path("benchmarks/autonomous_coding_cases.json")


def test_autonomous_coding_benchmark_contract_is_complete():
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    cases = payload["cases"]
    assert len(cases) >= 10

    ids = {case["id"] for case in cases}
    assert {
        "readonly_python",
        "bounded_regression_change",
        "named_repair",
        "diagnostic_only",
        "architectural",
        "browser_change",
        "roblox_change",
        "self_repair",
    } <= ids

    change_cases = [
        case for case in cases
        if case.get("kind") == "change"
    ]
    assert change_cases
    assert all(case.get("requires_mutation") for case in change_cases)
    assert all(case.get("requires_validation") for case in change_cases)


def test_read_only_benchmark_cases_stay_out_of_superpowers():
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        if case.get("kind") != "read_only":
            continue

        assert case["superpowers"] is False
        assert classify_software_request(case["request"]) is None


def test_explicit_change_benchmark_targets_resolve_deterministically():
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        if case.get("kind") != "change" or not case.get("target"):
            continue

        target = case["target"]
        assert JarvisAgent._infer_requested_file_target(case["request"]) == target
        assert JarvisAgent._requested_file_exists(target) is True
        assert case["first_phase"] == "read_file"


def test_named_repair_benchmark_starts_with_real_target_discovery():
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "named_repair")

    target = JarvisAgent._infer_requested_file_target(case["request"])

    assert target == case["target"]
    assert JarvisAgent._requested_file_exists(target) is True
    assert case["first_phase"] == "find_file"


def test_architectural_benchmark_requires_design_workflow():
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "architectural")

    workflow = classify_software_request(case["request"])

    assert workflow is not None
    assert workflow.classification == "architectural"
    assert workflow.requires_design is True


def test_code_test_git_diff_check_is_a_verified_tool_mode(monkeypatch):
    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(tools.subprocess, "run", lambda *args, **kwargs: Completed())

    result = tools.code_test(json.dumps({"mode": "git_diff_check"}))

    assert result["success"] is True
    assert result["verified"] is True
    assert result["mode"] == "git_diff_check"


class ChangeRecoveryPlanner:
    def __init__(self):
        self.calls = []

    def __call__(self, request, active_context=None, history_text=""):
        self.calls.append(request)

        if "[JARVIS_INTERNAL_PHASE:REPAIR]" in request:
            return {
                "goal": "correct failed regression change",
                "steps": [
                    {"tool": "code_checkpoint", "argument": ""},
                    {
                        "tool": "edit_file",
                        "argument": (
                            "tests/test_superpowers_engine.py"
                            "|||old repaired source|||new repaired source"
                        ),
                    },
                    {
                        "tool": "code_test",
                        "argument": (
                            '{"mode":"pytest",'
                            '"path":"tests/test_superpowers_engine.py"}'
                        ),
                    },
                ],
            }

        return {
            "goal": "apply requested regression change",
            "steps": [
                {"tool": "code_checkpoint", "argument": ""},
                {
                    "tool": "edit_file",
                    "argument": (
                        "tests/test_superpowers_engine.py"
                        "|||old source|||new broken source"
                    ),
                },
                {
                    "tool": "code_test",
                    "argument": (
                        '{"mode":"pytest",'
                        '"path":"tests/test_superpowers_engine.py"}'
                    ),
                },
            ],
        }


class ChangeRecoveryExecutor:
    def __init__(self):
        self.calls = []
        self.failed_test_once = False

    def __call__(self, plan, active_context, task_state, speak_callback):
        self.calls.append(plan)
        trace = []
        failed = False

        for index, step in enumerate(plan.get("steps", []), start=1):
            tool = step["tool"]
            argument = step.get("argument", "")

            if tool == "read_file":
                result = ToolResult(
                    success=True,
                    verified=True,
                    tool=tool,
                    data="def existing_regression():\n    assert True\n",
                )
                message = "Source inspection completed."
                success = True
                verified = True

            elif (
                tool == "code_test"
                and "git_diff_check" not in str(argument)
                and not self.failed_test_once
            ):
                self.failed_test_once = True
                result = ToolResult(
                    success=False,
                    verified=False,
                    tool=tool,
                    data={
                        "mode": "pytest",
                        "path": "tests/test_superpowers_engine.py",
                        "stdout": "1 failed",
                        "stderr": "assertion failed",
                    },
                    error="Focused pytest failed.",
                    retryable=True,
                )
                message = "Code validation failed."
                success = False
                verified = False
                failed = True

            elif tool == "code_test" and "git_diff_check" in str(argument):
                result = ToolResult(
                    success=True,
                    verified=True,
                    tool=tool,
                    data={
                        "mode": "git_diff_check",
                        "path": ".",
                        "message": "Git diff whitespace validation passed.",
                    },
                )
                message = "Git diff validation passed."
                success = True
                verified = True

            else:
                result = ToolResult(
                    success=True,
                    verified=True,
                    tool=tool,
                    data={"message": "completed"},
                )
                message = "completed"
                success = True
                verified = True

            trace.append(
                {
                    "index": index,
                    "tool": tool,
                    "argument": argument,
                    "status": "completed" if success else "failed",
                    "success": success,
                    "verified": verified,
                    "result": result,
                    "message": message,
                    "retryable": bool(getattr(result, "retryable", False)),
                }
            )

        tool_executor.LAST_EXECUTION_TRACE = trace
        return "failed" if failed else "done"


def test_failed_change_test_restores_checkpoint_and_repairs():
    planner_stub = ChangeRecoveryPlanner()
    executor_stub = ChangeRecoveryExecutor()
    agent = JarvisAgent(
        planner=planner_stub,
        executor=executor_stub,
    )

    task = agent.create_task(
        "Add a regression test to tests/test_superpowers_engine.py "
        "and run the relevant tests afterward."
    )
    planned = agent.plan_task(task)

    completed = agent.execute_task(
        planned,
        {},
        type("TaskStateStub", (), {
            "set_progress_callback": lambda self, cb: None,
            "is_cancelled": lambda self: False,
            "finish": lambda self: None,
        })(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert completed.change_recovery_attempts == 1
    assert completed.replan_count == 1
    assert len(planner_stub.calls) == 2
    assert "[JARVIS_INTERNAL_PHASE:CHANGE]" in planner_stub.calls[0]
    assert "[JARVIS_INTERNAL_PHASE:REPAIR]" in planner_stub.calls[1]

    tool_sequences = [
        [step["tool"] for step in call["steps"]]
        for call in executor_stub.calls
    ]
    assert tool_sequences == [
        ["read_file"],
        ["code_checkpoint", "edit_file", "code_test"],
        ["code_restore_checkpoint"],
        ["code_checkpoint", "edit_file", "code_test"],
        ["code_test"],
    ]

    assert any(
        "git diff validation" in str(observation).lower()
        for observation in completed.observations
    )
