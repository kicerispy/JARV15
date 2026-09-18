from agent_core import JarvisAgent
from planner import assess_plan, is_software_repair_request
from state import TaskState


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
    assert any("modification" in issue.lower() for issue in issues)


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


def test_diagnostic_only_request_does_not_require_modification():
    issues = assess_plan(
        "inspect the browser automation and test it",
        {
            "goal": "inspect browser automation",
            "steps": [
                {"tool": "code_search", "argument": "browser"},
                {
                    "tool": "code_test",
                    "argument": '{"mode":"compile","path":"browser_controller.py"}',
                },
            ],
        },
    )

    assert issues == []


def test_discovery_plan_is_allowed_before_repair_phase():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "inspect browser automation",
            "steps": [
                {"tool": "list_files", "argument": ""},
                {
                    "tool": "find_file",
                    "argument": "browser_controller.py",
                },
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
            ],
        },
        require_modification=False,
    )

    assert issues == []


def test_repair_phase_requires_modification_and_validation():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "inspect browser automation",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
            ],
        },
        require_modification=True,
    )

    assert any("modification" in issue.lower() for issue in issues)
    assert any("code_test" in issue.lower() for issue in issues)


class DiscoveryThenRepairPlanner:
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
                "goal": "inspect browser automation",
                "steps": [
                    {"tool": "list_files", "argument": ""},
                    {
                        "tool": "find_file",
                        "argument": "browser_controller.py",
                    },
                    {
                        "tool": "read_file",
                        "argument": "browser_controller.py",
                    },
                ],
            }

        return valid_repair_plan()


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        plan,
        active_context,
        task_state,
        speak_callback,
    ):
        import tool_executor

        tool_executor.LAST_EXECUTION_TRACE = []
        self.calls.append(plan)
        return "done"


def test_successful_discovery_transitions_into_repair_phase():
    planner = DiscoveryThenRepairPlanner()
    executor = RecordingExecutor()
    agent = JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task(
        "inspect the browser automation, find the problem, fix it, and test it"
    )

    planned = agent.plan_task(task)
    assert planned.status == "ready"
    assert [step.tool for step in planned.steps] == [
        "list_files",
        "find_file",
        "read_file",
    ]

    completed = agent.execute_task(
        planned,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert len(planner.calls) == 2
    assert len(executor.calls) == 2
    assert executor.calls[1]["steps"][-1]["tool"] == "code_test"



class ThreePhasePlanner:
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
                "goal": "discover browser automation",
                "steps": [
                    {"tool": "list_files", "argument": ""},
                    {
                        "tool": "find_file",
                        "argument": "browser_controller.py",
                    },
                ],
            }

        if len(self.calls) == 2:
            return {
                "goal": "read browser automation source",
                "steps": [
                    {
                        "tool": "read_file",
                        "argument": "browser_controller.py",
                    },
                ],
            }

        return valid_repair_plan()


def test_repair_task_can_gather_source_before_editing():
    planner = ThreePhasePlanner()
    executor = RecordingExecutor()
    agent = JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task(
        "inspect the browser automation, find the problem, fix it, and test it"
    )

    planned = agent.plan_task(task)

    completed = agent.execute_task(
        planned,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert len(planner.calls) == 3
    assert len(executor.calls) == 3
    assert [
        step["tool"]
        for step in executor.calls[0]["steps"]
    ] == ["list_files", "find_file"]
    assert [
        step["tool"]
        for step in executor.calls[1]["steps"]
    ] == ["read_file"]
    assert executor.calls[2]["steps"][-1]["tool"] == "code_test"



def test_repair_phase_can_require_source_read_without_forcing_an_edit():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "read browser source",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
            ],
        },
        require_modification=False,
        require_code_read=True,
    )

    assert issues == []



def test_repair_task_can_require_a_diagnostic_test_phase():
    issues = assess_plan(
        "inspect the browser automation, find the problem, fix it, and test it",
        {
            "goal": "diagnostic validation",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
            ],
        },
        require_modification=False,
        require_code_read=True,
        require_code_test=True,
    )

    assert any("code_test" in issue.lower() for issue in issues)

    issues = assess_plan(
        "inspect the browser automation, find the problem, fix it, and test it",
        {
            "goal": "diagnostic validation",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
                {
                    "tool": "code_test",
                    "argument": '{"mode":"compile","path":"browser_controller.py"}',
                },
            ],
        },
        require_modification=False,
        require_code_read=True,
        require_code_test=True,
    )

    assert issues == []
