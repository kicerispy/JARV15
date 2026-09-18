from agent_core import JarvisAgent
from planner import assess_plan, is_software_repair_request


def valid_repair_plan():
    return {
        "goal": "repair browser automation",
        "steps": [
            {"tool": "code_search", "argument": "browser_controller.py"},
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


def test_software_repair_detection():
    assert is_software_repair_request(
        "inspect the browser automation and fix the problem"
    ) is True
    assert is_software_repair_request(
        "tell me a story about a robot"
    ) is False


def test_repair_plan_requires_inspection_checkpoint_and_test():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "repair browser automation",
            "steps": [
                {
                    "tool": "edit_file",
                    "argument": "browser_controller.py|||old|||new",
                }
            ],
        },
    )

    assert any("inspect" in issue.lower() for issue in issues)
    assert any("checkpoint" in issue.lower() for issue in issues)
    assert any("code_test" in issue.lower() for issue in issues)


def test_valid_repair_plan_passes_quality_gate():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        valid_repair_plan(),
    )
    assert issues == []


class RetryPlanner:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        request,
        active_context=None,
        history_text="",
    ):
        self.calls.append(request)

        if len(self.calls) == 1:
            return {
                "goal": "repair browser automation",
                "steps": [],
            }

        return valid_repair_plan()


def test_agent_retries_an_empty_repair_plan():
    planner = RetryPlanner()
    agent = JarvisAgent(planner=planner)

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )

    planned = agent.plan_task(task)

    assert len(planner.calls) == 2
    assert planned.status == "ready"
    assert [step.tool for step in planned.steps] == [
        "code_search",
        "read_file",
        "code_checkpoint",
        "edit_file",
        "code_test",
    ]
    assert any(
        "Planner quality gate" in observation
        for observation in planned.observations
    )


class AlwaysIncompletePlanner:
    def __init__(self):
        self.calls = 0

    def __call__(
        self,
        request,
        active_context=None,
        history_text="",
    ):
        self.calls += 1
        return {
            "goal": "repair browser automation",
            "steps": [
                {
                    "tool": "edit_file",
                    "argument": "browser_controller.py|||old|||new",
                }
            ],
        }


def test_agent_fails_when_corrective_plan_is_still_unsafe():
    planner = AlwaysIncompletePlanner()
    agent = JarvisAgent(planner=planner)

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )

    planned = agent.plan_task(task)

    assert planner.calls == 2
    assert planned.status == "failed"
    assert "Planner quality validation failed" in planned.error
