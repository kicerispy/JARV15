import threading

from state import TaskState
from task_controller import BackgroundTaskController, is_task_status_request


class FakeAgent:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def execute_task(
        self,
        task,
        active_context,
        task_state,
        speak_callback,
        history_text="",
    ):
        self.started.set()
        self.release.wait(timeout=2)

        if task_state.is_cancelled():
            task.status = "cancelled"
        else:
            task.status = "completed"

        return task


def test_background_task_starts_without_blocking():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "test-task",
        "request": "do a test",
        "goal": "run the test",
        "status": "created",
        "steps": [object(), object()],
        "current_step": -1,
        "replan_count": 0,
        "error": None,
        "started_at": None,
        "completed_at": None,
    })()

    assert controller.start(
        task,
        {},
        task_state,
        lambda message: False,
    ) is True

    assert agent.started.wait(timeout=1)
    assert controller.has_active_task() is True

    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True
    assert controller.snapshot()["task_status"] == "completed"


def test_background_task_can_be_cancelled():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "cancel-task",
        "request": "do a long task",
        "goal": "finish the long task",
        "status": "created",
        "steps": [object()],
        "current_step": -1,
        "replan_count": 0,
        "error": None,
        "started_at": None,
        "completed_at": None,
    })()

    assert controller.start(
        task,
        {},
        task_state,
        lambda message: False,
    ) is True

    assert agent.started.wait(timeout=1)
    assert controller.cancel_current() is True
    assert task_state.is_cancelled() is True

    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True
    assert controller.snapshot()["task_status"] == "cancelled"


def test_status_requests_are_deterministic():
    assert is_task_status_request("what are you doing") is True
    assert is_task_status_request("what's the status") is True
    assert is_task_status_request("explain what you are doing") is False
