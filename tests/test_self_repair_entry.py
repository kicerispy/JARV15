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
