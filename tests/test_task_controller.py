import threading
import time

from state import TaskState
from task_controller import (
    BackgroundTaskController,
    is_task_acknowledgement,
    is_task_status_request,
)


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



def test_cancellation_discards_stale_worker_speech():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "cancel-speech-task",
        "request": "do a long task",
        "goal": "finish the long task",
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
        None,
    ) is True

    assert agent.started.wait(timeout=1)

    controller._queue_speech("Progress from before cancellation.")
    assert controller.cancel_current() is True

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 0
    assert spoken == []

    # Worker announcements arriving after cancellation are ignored.
    assert controller._queue_speech(
        "Late progress after cancellation."
    ) is False

    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 0


def test_background_planning_can_be_cancelled_before_execution():
    agent = PlanningFakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "planning-cancel-task",
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
    assert controller.cancel_current() is True
    assert task_state.is_cancelled() is True

    # Cancellation also removes the initial acknowledgement so stale
    # "On it." speech cannot play after the user says stop.
    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 0
    assert spoken == []

    agent.release_planning.set()
    assert controller.wait_for_current(timeout=1) is True

    assert agent.executed.is_set() is False
    assert controller.snapshot()["task_status"] == "cancelled"


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


def test_task_progress_suppresses_duplicate_milestones():
    task_state = TaskState()
    task_state.prepare("long task", 6)

    spoken = []
    task_state.set_progress_callback(
        lambda message: spoken.append(message)
    )

    task_state.report_progress(
        "I'm locating the relevant code.",
        key="code_discovery",
    )
    task_state.report_progress(
        "I'm locating the relevant file.",
        key="code_discovery",
    )
    task_state.report_progress(
        "I'm inspecting the relevant source.",
        key="source_inspection",
    )

    assert spoken == [
        "I'm locating the relevant code.",
        "I'm inspecting the relevant source.",
    ]


def test_status_message_reports_current_activity():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task_state.prepare("inspect and validate", 5)
    task_state.start("inspect and validate", 5)
    task_state.update_step(3, "code_test")

    task = type("Task", (), {
        "task_id": "status-activity-task",
        "request": "inspect and validate",
        "goal": "inspect and validate",
        "status": "executing",
        "steps": [object(), object(), object(), object(), object()],
        "current_step": 2,
        "replan_count": 0,
        "error": None,
        "started_at": time.time(),
        "completed_at": None,
    })()

    controller._task = task
    controller._task_state = task_state
    controller._thread = threading.current_thread()

    assert controller.status_message() == (
        "I'm validating the result. I'm on step 3 of 5."
    )


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
    assert controller.status_message() == "I'm planning the task now."

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 1
    assert spoken == [
        "On it."
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
    assert controller.drain_speech(lambda message: False) == 0

    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 1
    assert spoken == ["Background task progress."]



class EmptyPlanAgent:
    def __init__(self):
        self.planning_started = threading.Event()

    def plan_task(self, task, history_text=""):
        self.planning_started.set()
        task.goal = "unable to plan"
        task.steps = []
        task.status = "ready"
        return task


def test_action_request_with_empty_plan_fails_without_chat_fallback():
    agent = EmptyPlanAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()
    spoken = []

    task = type("Task", (), {
        "task_id": "empty-plan-task",
        "request": "inspect and fix the browser",
        "goal": "",
        "status": "created",
        "steps": [],
        "current_step": -1,
        "replan_count": 0,
        "error": None,
        "started_at": None,
        "completed_at": None,
        "initial_acknowledged": False,
    })()

    assert controller.start_planning(
        task,
        {},
        task_state,
    ) is True

    assert agent.planning_started.wait(timeout=1)
    assert controller.wait_for_current(timeout=1) is True

    assert controller.snapshot()["task_status"] == "failed"

    controller.drain_speech(
        lambda message: spoken.append(message) or False
    )

    assert spoken == [
        "On it.",
        "I couldn't create an action plan for that request.",
    ]



def test_task_acknowledgements_are_deterministic():
    assert is_task_acknowledgement("All right") is True
    assert is_task_acknowledgement("okay") is True
    assert is_task_acknowledgement("tell me a joke") is False


def test_background_task_completion_signal_is_set_and_consumed():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "completion-signal-task",
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

    assert controller.completion_event.is_set() is False

    wait_event, already_completed = controller.prepare_followup_wait()
    assert wait_event is None
    assert already_completed is False

    assert controller.start(
        task,
        {},
        task_state,
        None,
    ) is True

    assert agent.started.wait(timeout=1)
    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True

    assert controller.completion_event.is_set() is True
    wait_event, already_completed = controller.prepare_followup_wait()
    assert wait_event is None
    assert already_completed is True
    assert controller.consume_completion_signal() is False


def test_task_controller_status_works_without_active_task():
    agent = FakeAgent()
    controller = BackgroundTaskController(agent)
    task_state = TaskState()

    task = type("Task", (), {
        "task_id": "completed-task",
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
    agent.release.set()
    assert controller.wait_for_current(timeout=1) is True

    assert controller.status_message() == (
        "The last background task is complete."
    )



def test_internal_source_results_have_concise_speech_summaries():
    from tool_executor import _spoken_execution_summary

    source = "from pathlib import Path\n\n" + ("x = 1\n" * 500)

    assert _spoken_execution_summary("read_file", source) == (
        "I inspected the relevant source file."
    )
    assert _spoken_execution_summary(
        "code_search",
        "browser_controller.py:42: browser_connect",
    ) == "I searched the project code for relevant matches."

def test_background_speech_deduplicates_across_queue_drains():
    controller = BackgroundTaskController(None)

    assert controller._queue_speech("Task complete.") is False

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 1
    assert spoken == ["Task complete."]

    # The first copy has already been delivered, so a later completion layer
    # cannot enqueue the same user-facing message again.
    assert controller._queue_speech("Task complete.") is False
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 0
    assert spoken == ["Task complete."]


def test_delivery_layer_suppresses_duplicate_queue_entries():
    controller = BackgroundTaskController(None)

    # Simulate the queue containing two identical completion messages. This
    # bypasses enqueue-time de-duplication and exercises the final delivery
    # boundary directly.
    controller._speech_queue.put("Task complete.")
    controller._speech_queue.put("Task complete.")

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 2
    assert spoken == ["Task complete."]


def test_delivery_layer_normalizes_formatting_differences():
    controller = BackgroundTaskController(None)

    controller._speech_queue.put("Found 'Downloads' on the page.")
    controller._speech_queue.put("Found  'Downloads'   on the page.\u200b")

    spoken = []
    assert controller.drain_speech(
        lambda message: spoken.append(message) or False
    ) == 2
    assert spoken == ["Found 'Downloads' on the page."]


def test_speech_key_matches_tts_normalization():
    controller = BackgroundTaskController(None)

    assert controller._speech_key(
        "JARVIS: Found 'Downloads' on the page."
    ) == controller._speech_key(
        "Found 'Downloads' on the page."
    )
