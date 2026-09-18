from agent_core import JarvisAgent
from planner import is_software_diagnostic_request, is_software_repair_request


def test_self_audit_and_repair_request_is_classified_as_software_work():
    request = (
        "Run a full diagnostic on yourself, identify any real problems you find, "
        "and fix them. Then run the relevant tests to verify the repairs."
    )

    assert is_software_diagnostic_request(request) is True
    assert is_software_repair_request(request) is True


def test_self_repair_starts_with_deterministic_full_project_diagnostic():
    request = (
        "Run a full diagnostic on yourself, identify any real problems you find, "
        "and fix them. Then run the relevant tests to verify the repairs."
    )

    def unexpected_planner(*args, **kwargs):
        raise AssertionError("generic planner should not be called for self-repair entry")

    agent = JarvisAgent(planner=unexpected_planner)
    task = agent.create_task(request)
    planned = agent.plan_task(task)

    assert planned.status == "ready"
    assert planned.planner_result.get("jarvis_internal_phase") is True
    assert [step.tool for step in planned.steps] == ["code_diagnose"]
    assert planned.steps[0].argument == (
        '{"path":"","run_tests":true,"run_lint":true,'
        '"run_types":false,"timeout":180}'
    )



def test_failed_self_diagnostic_hands_off_directly_to_repair_planner():
    request = (
        "Run a full diagnostic on yourself, identify any real problems you find, "
        "and fix them. Then run the relevant tests to verify the repairs."
    )

    planner_calls = []

    def repair_planner(request_text, active_context=None, history_text=""):
        planner_calls.append(request_text)
        assert "[JARVIS_INTERNAL_PHASE:REPAIR]" in request_text
        assert "code_diagnose" in request_text
        return {
            "goal": "repair diagnostic failure",
            "steps": [
                {"tool": "read_file", "argument": "browser_controller.py"},
                {"tool": "code_checkpoint", "argument": ""},
                {
                    "tool": "edit_file",
                    "argument": "browser_controller.py|||old|||new",
                },
                {
                    "tool": "code_test",
                    "argument": '{"mode":"compile","path":"browser_controller.py"}',
                },
            ],
        }

    agent = JarvisAgent(planner=repair_planner)
    task = agent.create_task(request)
    task.status = "ready"
    task.planner_result = {
        "goal": "full JARVIS project diagnostic",
        "jarvis_internal_phase": True,
        "steps": [
            {
                "tool": "code_diagnose",
                "argument": (
                    '{"path":"","run_tests":true,"run_lint":true,'
                    '"run_types":false,"timeout":180}'
                ),
            }
        ],
    }
    task.steps = agent._build_steps(task.planner_result)
    task.evidence = [
        {
            "tool": "code_diagnose",
            "target": ".",
            "success": False,
            "verified": False,
            "detail": (
                "compile_all failed: browser_controller.py: SyntaxError"
            ),
        }
    ]

    execution_calls = []

    def fake_execute_once(task_arg, active_context, task_state, speak_callback):
        execution_calls.append(True)
        return "failed" if len(execution_calls) == 1 else "done"

    agent._execute_once = fake_execute_once

    task_state = __import__("state").TaskState()
    completed = agent.execute_task(
        task,
        active_context={},
        task_state=task_state,
        speak_callback=lambda message: None,
    )

    assert completed.status == "completed"
    assert len(planner_calls) == 1
    assert len(execution_calls) == 2



def test_clean_self_diagnostic_does_not_call_planner():
    request = (
        "Run a full diagnostic on yourself, identify any real problems you find, "
        "and fix them. Then run the relevant tests to verify the repairs."
    )

    planner_calls = []

    def unexpected_planner(*args, **kwargs):
        planner_calls.append(True)
        raise AssertionError("planner should not run after a clean self-diagnostic")

    agent = JarvisAgent(planner=unexpected_planner)
    task = agent.create_task(request)
    task.status = "ready"
    task.planner_result = {
        "goal": "full JARVIS project diagnostic",
        "jarvis_internal_phase": True,
        "steps": [
            {
                "tool": "code_diagnose",
                "argument": (
                    '{"path":"","run_tests":true,"run_lint":true,'
                    '"run_types":false,"timeout":180}'
                ),
            }
        ],
    }
    task.steps = agent._build_steps(task.planner_result)

    def fake_execute_once(task_arg, active_context, task_state, speak_callback):
        task_arg.evidence.append({
            "tool": "code_diagnose",
            "target": ".",
            "success": True,
            "verified": True,
            "detail": "Project diagnostic passed.",
        })
        return "done"

    agent._execute_once = fake_execute_once

    task_state = __import__("state").TaskState()
    completed = agent.execute_task(
        task,
        active_context={},
        task_state=task_state,
        speak_callback=lambda message: None,
    )

    assert completed.status == "completed"
    assert len(planner_calls) == 0
    assert "no reproducible defect" in completed.execution_result
