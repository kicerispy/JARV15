import threading
import time

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
            speak_callback("Background task progress.")
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


class PlanningFakeAgent:
    def __init__(self):
        self.planning_started = threading.Event()
        self.release_planning = threading.Event()
        self.executed = threading.Event()

    def plan_task(self, task, history_text=""):
        self.planning_started.set()
        self.release_planning.wait(timeout=2)
        task.goal = "planned task"
        task.steps = [object(), object()]
        task.status = "ready"
        return task

    def execute_task(
        self,
        task,
        active_context,
        task_state,
        speak_callback,
        history_text="",
    ):
        self.executed.set()
        speak_callback("Execution finished.")
        task.status = "completed"
        return task


def test_background_planning_does_not_block_caller():
    agent = PlanningFakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "planning-task",
        "request": "inspect and fix the browser",
        "goal": "",
        "status": "created",
        "steps": [],
        "current_step": -1,
        "replan_count": 0,
        "error": None,
        "started_at": None,
        "completed_at": None,
    })()

    assert controller.start_planning(
        task,
        {},
        task_state,
    ) is True

    assert agent.planning_started.wait(timeout=1)
    assert controller.has_active_task() is True
    assert controller.status_message() == "I'm getting the task underway."

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 1
    assert spoken == [
        "I'm on it. I'll keep you updated and let you know when it's finished."
    ]

    agent.release_planning.set()
    assert agent.executed.wait(timeout=1)
    assert controller.wait_for_current(timeout=1) is True
    assert controller.snapshot()["task_status"] == "completed"


def test_worker_speech_is_queued_until_main_loop_drains_it():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "speech-task",
        "request": "do a test",
        "goal": "run the test",
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
        None,
    ) is True

    assert agent.started.wait(timeout=1)

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if controller.drain_speech(lambda message: False) == 1:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Worker speech was not queued.")

    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 1
    assert spoken == ["Background task progress."]
