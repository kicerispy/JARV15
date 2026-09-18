from agent_core import JarvisAgent
from planner import (
    assess_plan,
    is_software_diagnostic_request,
    is_software_repair_request,
    validate_plan,
)
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


def test_malformed_edit_file_is_rejected_before_execution():
    issues = assess_plan(
        "fix the broken Python module",
        {
            "goal": "repair module",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "broken_module.py",
                },
                {
                    "tool": "code_checkpoint",
                    "argument": "",
                },
                {
                    "tool": "edit_file",
                    "argument": "broken_module.py|||old||new",
                },
                {
                    "tool": "code_test",
                    "argument": (
                        '{"mode":"compile","path":"broken_module.py"}'
                    ),
                },
            ],
        },
    )

    assert any(
        "filename|||old_text|||new_text" in issue
        for issue in issues
    )
    assert any(
        "do not use ||" in issue.lower()
        for issue in issues
    )


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


class EvidenceAwareRetryPlanner:
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

        assert "VERIFIED PRIOR EVIDENCE:" in request
        assert "browser_controller.py" in request
        assert "Do not restart project-wide discovery" in request

        return {
            "goal": "repair browser automation",
            "steps": [
                {
                    "tool": "code_checkpoint",
                    "argument": "",
                },
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


def test_corrective_repair_planning_retains_verified_evidence():
    planner = EvidenceAwareRetryPlanner()
    agent = JarvisAgent(planner=planner)

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )
    task.evidence = [
        {
            "attempt": 1,
            "tool": "read_file",
            "target": "browser_controller.py",
            "success": True,
            "verified": True,
            "detail": "10: def browser_connect():",
        }
    ]

    planned = agent.plan_task(
        task,
        require_repair_plan=True,
    )

    assert planned.status == "ready"
    assert len(planner.calls) == 2
    assert [step.tool for step in planned.steps] == [
        "code_checkpoint",
        "edit_file",
        "code_test",
    ]


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


def test_prior_evidence_can_satisfy_repair_inspection_gate():
    repair_plan = {
        "goal": "apply evidence-backed browser repair",
        "steps": [
            {
                "tool": "code_checkpoint",
                "argument": "",
            },
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

    without_evidence = assess_plan(
        "inspect the browser automation and fix the problem",
        repair_plan,
        require_modification=True,
    )

    assert any(
        "inspect" in issue.lower()
        for issue in without_evidence
    )

    with_evidence = assess_plan(
        "inspect the browser automation and fix the problem",
        repair_plan,
        require_modification=True,
        allow_prior_evidence=True,
    )

    assert with_evidence == []


class EvidenceAwareDiagnosticFallbackPlanner:
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
                "steps": [],
            }

        return {
            "goal": "inspect browser automation",
            "steps": [
                {
                    "tool": "code_search",
                    "argument": "browser",
                },
            ],
        }



def test_browser_diagnostic_requires_behavioral_smoke_test():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "diagnostic validation",
            "steps": [
                {
                    "tool": "code_test",
                    "argument": (
                        '{"mode": "compile", '
                        '"path": "browser_controller.py"}'
                    ),
                },
            ],
        },
        require_modification=False,
        require_code_test=True,
    )

    assert any("browser_smoke" in issue.lower() for issue in issues)


def test_browser_diagnostic_accepts_browser_smoke_test():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "browser runtime diagnostic",
            "steps": [
                {
                    "tool": "code_test",
                    "argument": (
                        '{"mode": "browser_smoke", '
                        '"path": "browser_controller.py"}'
                    ),
                },
            ],
        },
        require_modification=False,
        require_code_test=True,
    )

    assert issues == []


def test_required_code_diagnose_gate_rejects_code_test_only():
    issues = assess_plan(
        "diagnose the broken Python module before repairing it",
        {
            "goal": "diagnostic validation",
            "steps": [
                {
                    "tool": "code_test",
                    "argument": '{"mode":"compile","path":"broken_module.py"}',
                },
            ],
        },
        require_modification=False,
        require_code_diagnose=True,
        allow_prior_evidence=True,
    )

    assert any(
        "code_diagnose" in issue.lower()
        for issue in issues
    )

    issues = assess_plan(
        "diagnose the broken Python module before repairing it",
        {
            "goal": "diagnostic validation",
            "steps": [
                {
                    "tool": "code_diagnose",
                    "argument": (
                        '{"path":"broken_module.py","run_tests":false,'
                        '"run_lint":false,"run_types":false}'
                    ),
                },
            ],
        },
        require_modification=False,
        require_code_diagnose=True,
        allow_prior_evidence=True,
    )

    assert issues == []


def test_required_diagnostic_phase_falls_back_to_verified_source_target():
    planner = EvidenceAwareDiagnosticFallbackPlanner()
    agent = JarvisAgent(planner=planner)

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )
    task.evidence = [
        {
            "attempt": 1,
            "tool": "read_file",
            "target": "browser_controller.py",
            "success": True,
            "verified": True,
            "detail": "10: def browser_connect():",
        }
    ]

    planned = agent.plan_task(
        task,
        require_code_diagnose=True,
    )

    assert planned.status == "ready"
    assert len(planner.calls) == 2
    assert [step.tool for step in planned.steps] == [
        "code_diagnose",
    ]
    assert planned.steps[0].argument == (
        '{"path":"browser_controller.py","run_tests":false,'
        '"run_lint":false,"run_types":false}'
    )



def test_dom_tools_are_tracked_as_browser_state_tools():
    from agent_core import BROWSER_STATE_TOOLS

    assert {
        "browser_find_element",
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_wait_for_element",
        "browser_extract_text",
    }.issubset(BROWSER_STATE_TOOLS)


class EvidenceAwareRepairPlanner:
    def __call__(
        self,
        request,
        active_context=None,
        history_text="",
    ):
        return {
            "goal": "apply evidence-backed browser repair",
            "steps": [
                {
                    "tool": "code_checkpoint",
                    "argument": "",
                },
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


def test_plan_task_passes_prior_evidence_to_repair_quality_gate():
    agent = JarvisAgent(
        planner=EvidenceAwareRepairPlanner(),
    )
    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )
    task.evidence = [
        {
            "attempt": 1,
            "tool": "read_file",
            "target": "browser_controller.py",
            "success": True,
            "verified": True,
            "detail": "10: def browser_connect():",
        }
    ]

    planned = agent.plan_task(
        task,
        require_repair_plan=True,
    )

    assert planned.status == "ready"
    assert [
        step.tool
        for step in planned.steps
    ] == [
        "code_checkpoint",
        "edit_file",
        "code_test",
    ]


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




def test_validate_plan_drops_nonexistent_read_target():
    plan = validate_plan(
        {
            "goal": "inspect browser automation",
            "steps": [
                {
                    "tool": "read_file",
                    "argument": "browser_automation.py",
                },
                {
                    "tool": "read_file",
                    "argument": "browser_controller.py",
                },
            ],
        }
    )

    assert [step["argument"] for step in plan["steps"]] == [
        "browser_controller.py",
    ]


def test_diagnostic_plan_rejects_hallucinated_file_target():
    issues = assess_plan(
        "inspect the browser automation and fix the problem",
        {
            "goal": "inspect browser automation",
            "steps": [
                {
                    "tool": "code_search",
                    "argument": "browser",
                },
                {
                    "tool": "read_file",
                    "argument": "browser_automation.py",
                },
            ],
            },
        require_modification=False,
    )

    assert any(
        "nonexistent read_file target" in issue.lower()
        or "browser_automation.py does not exist" in issue.lower()
        for issue in issues
    )


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
                    "argument": '{"mode":"browser_smoke","path":"browser_controller.py"}',
                },
            ],
        },
        require_modification=False,
        require_code_read=True,
        require_code_test=True,
    )

    assert issues == []



def test_source_results_become_bounded_repair_evidence():
    import tool_executor
    from tool_result import ToolResult

    source = "\n".join(
        [
            "from pathlib import Path",
            "",
            "def browser_connect():",
            "    return True",
            "",
            "def browser_goto(url):",
            "    return url",
        ]
        + ["unused = 1"] * 1200
    )

    tool_executor.LAST_EXECUTION_TRACE = [
        {
            "index": 1,
            "tool": "read_file",
            "argument": "browser_controller.py",
            "status": "completed",
            "success": True,
            "verified": True,
            "result": ToolResult(
                success=True,
                tool="read_file",
                data=source,
            ),
            "message": source,
        }
    ]

    agent = JarvisAgent()
    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )

    agent._record_execution_observation(
        task,
        attempt=1,
        execution_result="done",
    )

    assert any(
        "Source inspection completed." in observation
        for observation in task.observations
    )

    assert not any(
        "unused = 1" in observation
        for observation in task.observations
    )

    assert task.evidence
    evidence = task.evidence[-1]

    assert evidence["tool"] == "read_file"
    assert evidence["target"] == "browser_controller.py"
    assert "browser_connect" in evidence["detail"]
    assert "[evidence truncated by JARVIS]" not in evidence["detail"]

    packet = agent._build_evidence_packet(task)

    assert "browser_controller.py" in packet
    assert "browser_connect" in packet
    assert len(packet) < 18000


def test_repair_handoff_tells_planner_to_use_evidence_and_stop_generic_discovery():
    agent = JarvisAgent()
    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )
    task.goal = "repair browser automation"
    task.evidence = [
        {
            "attempt": 1,
            "tool": "read_file",
            "target": "browser_controller.py",
            "success": True,
            "verified": True,
            "detail": (
                "Source excerpt with line numbers:\n"
                "10: def browser_connect():"
            ),
        }
    ]

    request = agent._build_repair_request_after_discovery(task)

    assert "You are now handing evidence to the repair planner." in request
    assert "Do not repeat generic discovery" in request
    assert "browser_controller.py" in request
    assert "code_checkpoint BEFORE" in request
    assert "code_test AFTER" in request
    assert "Do not invent filenames" in request


def test_code_test_progress_does_not_claim_a_change_was_applied():
    import tool_executor

    messages = {}

    class FakeTaskState:
        def report_progress(self, message):
            messages["message"] = message

    tool_executor._report_tool_progress(
        FakeTaskState(),
        "code_test",
        3,
        3,
    )

    assert "Step 3 of 3. I'm running the validation now." == messages["message"]
    assert "change is in place" not in messages["message"].lower()

class MalformedRequiredReadPlanner:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        request,
        active_context=None,
        history_text="",
    ):
        self.calls.append(request)

        # Simulate Ollama/create_plan returning an empty plan after malformed JSON.
        return {
            "goal": "",
            "steps": [],
        }


def test_requested_file_target_extractor_preserves_multi_word_names():
    from agent_core import JarvisAgent

    assert (
        JarvisAgent._infer_requested_file_target(
            "diagnose and repair Jarvis Autonomous Test Target.py"
        )
        == "Jarvis Autonomous Test Target.py"
    )

    assert (
        JarvisAgent._infer_requested_file_target(
            "diagnose and repair Jarvis Autonomous Test Target dot py"
        )
        == "Jarvis Autonomous Test Target.py"
    )

    assert (
        JarvisAgent._infer_requested_file_target(
            "repair jarvis-autonomous-test-target.py"
        )
        == "jarvis-autonomous-test-target.py"
    )


def test_initial_repair_plan_recovers_named_target_after_planner_failure():
    class EmptyPlanner:
        def __init__(self):
            self.calls = []

        def __call__(
            self,
            request,
            active_context=None,
            history_text="",
        ):
            self.calls.append(request)
            return {"goal": "", "steps": []}

    agent = JarvisAgent(planner=EmptyPlanner())

    task = agent.create_task(
        "diagnose and repair Jarvis Autonomous Test Target.py",
    )

    planned = agent.plan_task(task)

    assert planned.status == "ready"
    assert len(planned.steps) == 1
    assert planned.steps[0].tool == "find_file"
    assert planned.steps[0].argument == (
        "Jarvis Autonomous Test Target.py"
    )
    assert len(agent.planner.calls) == 1


def test_voice_dotted_filename_is_recovered_for_initial_repair():
    class EmptyPlanner:
        def __call__(
            self,
            request,
            active_context=None,
            history_text="",
        ):
            return {"goal": "", "steps": []}

    agent = JarvisAgent(planner=EmptyPlanner())

    task = agent.create_task(
        "diagnose and repair Jarvis Autonomous Test Target dot py",
    )

    planned = agent.plan_task(task)

    assert planned.status == "ready"
    assert planned.steps[0].tool == "find_file"
    assert planned.steps[0].argument == (
        "Jarvis Autonomous Test Target.py"
    )


def test_verified_find_file_target_feeds_deterministic_source_phase():
    agent = JarvisAgent(
        planner=lambda *args, **kwargs: {"steps": []},
        executor=lambda *args, **kwargs: "done",
    )
    task = agent.create_task(
        "diagnose and repair Jarvis Autonomous Test Target.py",
    )
    task.evidence = [
        {
            "tool": "find_file",
            "target": "Jarvis Autonomous Test Target.py",
            "success": True,
            "verified": True,
            "detail": (
                "Found: C:\\project\\jarvis_autonomous_test_target.py"
            ),
        }
    ]

    assert (
        agent._latest_verified_source_target(task)
        == "Jarvis Autonomous Test Target.py"
    )

    phase_plan = agent._build_phase_fallback_plan(
        task,
        require_code_read=True,
    )

    assert phase_plan == {
        "goal": "inspect verified target source",
        "steps": [
            {
                "tool": "read_file",
                "argument": "Jarvis Autonomous Test Target.py",
            }
        ],
    }


def test_required_source_read_rejects_empty_plan_and_recovers_target_from_discovery():
    planner = MalformedRequiredReadPlanner()
    agent = JarvisAgent(planner=planner)

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )
    task.evidence = [
        {
            "attempt": 1,
            "tool": "code_search",
            "target": "browser controller",
            "success": True,
            "verified": True,
            "detail": (
                "browser_controller.py:705: "
                "print('JARVIS browser controller loaded.')"
            ),
        },
        {
            "attempt": 1,
            "tool": "list_files",
            "target": ".",
            "success": True,
            "verified": True,
            "detail": (
                "- planner.py\n"
                "- browser_controller.py\n"
                "- tool_executor.py"
            ),
        },
    ]

    planned = agent.plan_task(
        task,
        require_code_read=True,
    )

    assert planned.status == "ready"
    assert len(planner.calls) == 2
    assert [step.tool for step in planned.steps] == [
        "read_file",
    ]
    assert planned.steps[0].argument == "browser_controller.py"

class EvidencePhasePlanner:
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
                        "tool": "read_file",
                        "argument": "browser_controller.py",
                    },
                ],
            }

        if len(self.calls) == 2:
            return {
                "goal": "diagnostic validation",
                "steps": [
                    {
                        "tool": "code_diagnose",
                        "argument": (
                            '{"path":"browser_controller.py",'
                            '"run_tests":false,"run_lint":false,'
                            '"run_types":false}'
                        ),
                    },
                ],
            }

        return {
            "goal": "repair browser automation",
            "steps": [
                {
                    "tool": "code_checkpoint",
                    "argument": "",
                },
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


class EvidencePhaseExecutor:
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
        from tool_result import ToolResult

        self.calls.append(plan)
        steps = plan.get("steps", [])

        tool_executor.LAST_EXECUTION_TRACE = []

        for index, step in enumerate(steps, start=1):
            tool = step["tool"]
            argument = step.get("argument", "")

            if tool == "read_file":
                result = ToolResult(
                    success=True,
                    tool=tool,
                    data="from pathlib import Path\\n\\ndef browser_connect():\\n    return True\\n",
                )
            elif tool in {"code_test", "code_diagnose"}:
                result = ToolResult(
                    success=True,
                    tool=tool,
                    data={
                        "message": (
                            "Project diagnostic passed."
                            if tool == "code_diagnose"
                            else "Code validation passed."
                        ),
                        "mode": (
                            "diagnose"
                            if tool == "code_diagnose"
                            else "compile"
                        ),
                        "path": "browser_controller.py",
                    },
                )
            else:
                result = ToolResult(
                    success=True,
                    tool=tool,
                    data="browser_controller.py",
                )

            tool_executor.LAST_EXECUTION_TRACE.append(
                {
                    "index": index,
                    "tool": tool,
                    "argument": argument,
                    "status": "completed",
                    "success": True,
                    "verified": True,
                    "result": result,
                    "message": (
                        "Source inspection completed."
                        if tool == "read_file"
                        else
                        (
                            "Project diagnostic passed."
                            if tool == "code_diagnose"
                            else
                            "Code validation passed."
                            if tool == "code_test"
                            else
                            "Discovery completed."
                        )
                    ),
                }
            )

        return "done"


def test_clean_diagnostic_does_not_trigger_speculative_repair():
    planner = EvidencePhasePlanner()
    executor = EvidencePhaseExecutor()
    agent = JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )

    planned = agent.plan_task(task)

    completed = agent.execute_task(
        planned,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert len(planner.calls) == 1
    assert len(executor.calls) == 2
    assert all(
        step["tool"] != "edit_file"
        for execution in executor.calls
        for step in execution["steps"]
    )
    assert "no reproducible defect" in completed.execution_result.lower()


def test_verified_evidence_prevents_redundant_source_phase():
    planner = EvidencePhasePlanner()
    executor = EvidencePhaseExecutor()
    agent = JarvisAgent(
        planner=planner,
        executor=executor,
    )

    task = agent.create_task(
        "inspect the browser automation and fix the problem"
    )

    planned = agent.plan_task(task)
    completed = agent.execute_task(
        planned,
        {},
        TaskState(),
        lambda message: False,
    )

    assert completed.status == "completed"
    assert len(planner.calls) == 1
    assert len(executor.calls) == 2
    assert executor.calls[1]["steps"][0]["tool"] == "code_diagnose"
    assert (
        completed.execution_result
        == "Diagnostic validation passed; no reproducible defect was found, so no code change was made."
    )



def test_self_repair_requests_get_extended_bounded_budget():
    agent = JarvisAgent(
        planner=lambda *args, **kwargs: {"steps": []},
        executor=lambda *args, **kwargs: "done",
    )

    task = agent.create_task(
        "diagnose yourself and fix your own code",
    )

    assert is_software_repair_request(
        "diagnose yourself and fix your own code"
    ) is True
    assert is_software_diagnostic_request(
        "diagnose your own code"
    ) is True
    assert task.max_replans == 5


def test_failed_diagnostic_routes_directly_to_repair_handoff():
    class DiagnosticThenRepairPlanner:
        def __init__(self):
            self.calls = []

        def __call__(self, request, active_context=None, history_text=""):
            self.calls.append(request)

            if len(self.calls) == 1:
                return {
                    "goal": "inspect target",
                    "steps": [
                        {
                            "tool": "read_file",
                            "argument": "broken_module.py",
                        },
                        {
                            "tool": "code_diagnose",
                            "argument": '{"path":"broken_module.py"}',
                        },
                    ],
                }

            assert "[JARVIS_INTERNAL_PHASE:REPAIR]" in request
            assert "Actionable failures:" in request
            return {
                "goal": "repair broken module",
                "steps": [
                    {"tool": "code_checkpoint", "argument": ""},
                    {
                        "tool": "edit_file",
                        "argument": "broken_module.py|||old|||new",
                    },
                    {
                        "tool": "code_test",
                        "argument": '{"mode":"compile","path":"broken_module.py"}',
                    },
                ],
            }

    class DiagnosticFailingExecutor:
        def __init__(self):
            self.calls = []

        def __call__(self, plan, active_context, task_state, speak_callback):
            import tool_executor
            from tool_result import ToolResult

            self.calls.append(plan)
            tool_executor.LAST_EXECUTION_TRACE = []

            for index, step in enumerate(plan.get("steps", []), start=1):
                tool = step["tool"]
                argument = step.get("argument", "")

                if tool == "read_file":
                    result = ToolResult(
                        success=True,
                        tool=tool,
                        data="def broken(:\\n    pass\\n",
                    )
                    message = "Source inspection completed."
                    success = True
                    verified = True
                elif tool == "code_diagnose":
                    result = ToolResult(
                        success=False,
                        tool=tool,
                        data={
                            "success": False,
                            "verified": False,
                            "mode": "diagnose",
                            "path": "broken_module.py",
                            "failures": [
                                "compile:broken_module.py failed (exit 1): SyntaxError: invalid syntax"
                            ],
                        },
                        error="compile:broken_module.py failed (exit 1): SyntaxError: invalid syntax",
                    )
                    message = "Project diagnostic found actionable issues."
                    success = False
                    verified = False
                else:
                    result = ToolResult(
                        success=True,
                        tool=tool,
                        data="ok",
                    )
                    message = "completed"
                    success = True
                    verified = True

                tool_executor.LAST_EXECUTION_TRACE.append(
                    {
                        "index": index,
                        "tool": tool,
                        "argument": argument,
                        "status": "completed" if success else "failed",
                        "success": success,
                        "verified": verified,
                        "result": result,
                        "message": message,
                    }
                )

            return "failed" if any(
                not entry["success"]
                for entry in tool_executor.LAST_EXECUTION_TRACE
            ) else "done"

    import os
    from pathlib import Path
    import shutil

    test_root = Path(os.getcwd()) / ".pytest_autonomous_repair_fixture"
    test_root.mkdir(exist_ok=True)
    (test_root / "broken_module.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    original_cwd = Path.cwd()
    os.chdir(test_root)

    try:
        planner = DiagnosticThenRepairPlanner()
        executor = DiagnosticFailingExecutor()
        agent = JarvisAgent(planner=planner, executor=executor)

        task = agent.create_task(
            "diagnose and repair broken_module.py",
        )

        planned = agent.plan_task(task)
        completed = agent.execute_task(
            planned,
            {},
            TaskState(),
            lambda message: False,
        )

        assert completed.status == "completed"
        assert len(planner.calls) == 2
        assert len(executor.calls) == 2
        assert executor.calls[1]["steps"][0]["tool"] == "code_checkpoint"
    finally:
        os.chdir(original_cwd)
        shutil.rmtree(test_root, ignore_errors=True)

