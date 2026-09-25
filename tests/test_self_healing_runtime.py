"""End-to-end tests for the runtime -> source self-healing bridge."""

from pathlib import Path

import agent_core
from state import TaskState
from tool_result import ToolResult


class RuntimeRepairPlanner:
    def __init__(self):
        self.calls = []

    def __call__(self, request, active_context=None, history_text=""):
        self.calls.append(request)
        assert "[JARVIS_INTERNAL_PHASE:REPAIR]" in request
        assert "runtime_target.py" in request

        return {
            "goal": "repair runtime defect",
            "steps": [
                {"tool": "code_checkpoint", "argument": ""},
                {
                    "tool": "edit_file",
                    "argument": "runtime_target.py|||raise_old|||raise_new",
                },
                {
                    "tool": "code_test",
                    "argument": (
                        '{"mode":"compile","path":"runtime_target.py"}'
                    ),
                },
            ],
        }


def _trace_entry(index, tool, result, message, *, verified=True):
    return {
        "index": index,
        "tool": tool,
        "argument": "",
        "status": "completed" if result.success else "failed",
        "success": result.success,
        "verified": verified,
        "result": result,
        "message": message,
        "retryable": result.retryable,
    }


def test_runtime_failure_starts_bounded_source_repair_bridge(tmp_path, monkeypatch):
    target = tmp_path / "runtime_target.py"
    target.write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    planner = RuntimeRepairPlanner()
    calls = {"count": 0}

    def executor(plan, active_context, task_state, speak_callback):
        import tool_executor

        calls["count"] += 1

        if calls["count"] == 1:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "run_python",
                    ToolResult(
                        success=False,
                        tool="run_python",
                        data={
                            "traceback": (
                                'Traceback (most recent call last):\\n'
                                '  File "runtime_target.py", line 2, in run\\n'
                                "    raise TypeError('boom')\\n"
                                "TypeError: boom"
                            )
                        },
                        retryable=False,
                        error="runtime TypeError",
                    ),
                    "Application runtime failed.",
                )
            ]
            return "failed"

        if calls["count"] == 2:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "read_file",
                    ToolResult(
                        success=True,
                        tool="read_file",
                        data="def run():\\n    return 1\\n",
                    ),
                    "Source inspection completed.",
                )
            ]
            return "done"

        if calls["count"] == 3:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "code_checkpoint",
                    ToolResult(
                        success=True,
                        tool="code_checkpoint",
                        data="checkpoint created",
                    ),
                    "Checkpoint created.",
                ),
                _trace_entry(
                    2,
                    "edit_file",
                    ToolResult(
                        success=True,
                        tool="edit_file",
                        data="runtime_target.py",
                    ),
                    "Source edited.",
                ),
                _trace_entry(
                    3,
                    "code_test",
                    ToolResult(
                        success=True,
                        tool="code_test",
                        data={
                            "mode": "compile",
                            "path": "runtime_target.py",
                            "message": "Code validation passed.",
                        },
                    ),
                    "Code validation passed.",
                ),
            ]
            return "done"

        assert plan["steps"][0]["tool"] == "code_test"
        tool_executor.LAST_EXECUTION_TRACE = [
            _trace_entry(
                1,
                "code_test",
                ToolResult(
                    success=True,
                    tool="code_test",
                    data={
                        "mode": "git_diff_check",
                        "message": "Diff validation passed.",
                    },
                ),
                "Diff validation passed.",
            )
        ]
        return "done"

    agent = agent_core.JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task("run the application")
    task.planner_result = {
        "goal": "run application",
        "steps": [
            {
                "tool": "run_python",
                "argument": "runtime_target.py",
            }
        ],
    }
    task.goal = "run application"
    task.steps = [
        agent_core.AgentStep(
            tool="run_python",
            argument="runtime_target.py",
        )
    ]
    task.status = "ready"

    completed = agent.execute_task(
        task,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert calls["count"] == 4
    assert len(planner.calls) == 1
    assert completed.self_healing_repair_attempts == 1
    assert any(
        "runtime self-healing" in observation.lower()
        for observation in completed.observations
    )


def test_runtime_self_healing_retries_once_after_failed_repair_validation(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "runtime_target.py"
    target.write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    planner = RuntimeRepairPlanner()
    calls = {"count": 0}

    def executor(plan, active_context, task_state, speak_callback):
        import tool_executor

        calls["count"] += 1

        if calls["count"] == 1:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "run_python",
                    ToolResult(
                        success=False,
                        tool="run_python",
                        data={
                            "traceback": (
                                'Traceback (most recent call last):\\n'
                                '  File "runtime_target.py", line 2, in run\\n'
                                "    raise AttributeError('boom')\\n"
                                "AttributeError: boom"
                            )
                        },
                        retryable=True,
                        error="runtime AttributeError",
                    ),
                    "Application runtime failed.",
                )
            ]
            return "failed"

        if calls["count"] == 2:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "read_file",
                    ToolResult(
                        success=True,
                        tool="read_file",
                        data="def run():\\n    return 1\\n",
                    ),
                    "Source inspection completed.",
                )
            ]
            return "done"

        if calls["count"] == 3:
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "code_checkpoint",
                    ToolResult(
                        success=True,
                        tool="code_checkpoint",
                        data="checkpoint created",
                    ),
                    "Checkpoint created.",
                ),
                _trace_entry(
                    2,
                    "edit_file",
                    ToolResult(
                        success=True,
                        tool="edit_file",
                        data="runtime_target.py",
                    ),
                    "Source edited.",
                ),
                _trace_entry(
                    3,
                    "code_test",
                    ToolResult(
                        success=False,
                        tool="code_test",
                        data={
                            "mode": "compile",
                            "path": "runtime_target.py",
                            "message": "Validation failed.",
                        },
                        error="TypeError: repaired code still fails",
                        retryable=True,
                    ),
                    "Code validation failed.",
                    verified=False,
                ),
            ]
            return "failed"

        if calls["count"] == 4:
            assert plan["steps"][0]["tool"] == "code_restore_checkpoint"
            tool_executor.LAST_EXECUTION_TRACE = [
                _trace_entry(
                    1,
                    "code_restore_checkpoint",
                    ToolResult(
                        success=True,
                        tool="code_restore_checkpoint",
                        data="checkpoint restored",
                    ),
                    "Checkpoint restored.",
                )
            ]
            return "done"

        if calls["count"] == 5:
            assert plan["steps"][0]["tool"] == "code_checkpoint"
            return executor._repair_success_trace(plan, tool_executor)

        assert plan["steps"][0]["tool"] == "code_test"
        tool_executor.LAST_EXECUTION_TRACE = [
            _trace_entry(
                1,
                "code_test",
                ToolResult(
                    success=True,
                    tool="code_test",
                    data={
                        "mode": "git_diff_check",
                        "message": "Diff validation passed.",
                    },
                ),
                "Diff validation passed.",
            )
        ]
        return "done"

    def _repair_success_trace(plan, tool_executor):
        tool_executor.LAST_EXECUTION_TRACE = [
            _trace_entry(
                1,
                "code_checkpoint",
                ToolResult(
                    success=True,
                    tool="code_checkpoint",
                    data="checkpoint created",
                ),
                "Checkpoint created.",
            ),
            _trace_entry(
                2,
                "edit_file",
                ToolResult(
                    success=True,
                    tool="edit_file",
                    data="runtime_target.py",
                ),
                "Source edited.",
            ),
            _trace_entry(
                3,
                "code_test",
                ToolResult(
                    success=True,
                    tool="code_test",
                    data={
                        "mode": "compile",
                        "path": "runtime_target.py",
                        "message": "Code validation passed.",
                    },
                ),
                "Code validation passed.",
            ),
        ]
        return "done"

    executor._repair_success_trace = _repair_success_trace

    agent = agent_core.JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task("run the application")
    task.planner_result = {
        "goal": "run application",
        "steps": [
            {
                "tool": "run_python",
                "argument": "runtime_target.py",
            }
        ],
    }
    task.goal = "run application"
    task.steps = [
        agent_core.AgentStep(
            tool="run_python",
            argument="runtime_target.py",
        )
    ]
    task.status = "ready"

    completed = agent.execute_task(
        task,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert calls["count"] == 6
    assert len(planner.calls) == 2
    assert completed.self_healing_repair_attempts == 2


def test_runtime_target_inference_rejects_python_files_outside_project(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    task = agent_core.JarvisAgent(
        planner=lambda *args, **kwargs: {"steps": []},
        executor=lambda *args, **kwargs: "done",
    ).create_task("run the application")

    task.evidence = [
        {
            "tool": "run_python",
            "target": "run",
            "success": False,
            "verified": False,
            "detail": (
                'Traceback: File "C:/outside/runtime_target.py", line 4, '
                "in run"
            ),
            "data": {
                "traceback": (
                    'File "C:/outside/runtime_target.py", line 4, '
                    "in run"
                )
            },
        }
    ]

    assert (
        agent_core.JarvisAgent._infer_runtime_source_target_from_evidence(task)
        is None
    )
