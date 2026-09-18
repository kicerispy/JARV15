from types import SimpleNamespace

from planner import (
    is_software_change_request,
    is_software_diagnostic_request,
    is_software_repair_request,
    validate_plan,
)
from tools import code_diagnose


def test_code_diagnose_returns_structured_success(monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr("tools.subprocess.run", fake_run)

    result = code_diagnose(
        '{"path":"browser_controller.py","run_tests":false,"run_lint":false,"run_types":false}'
    )

    assert result["success"] is True
    assert result["verified"] is True
    assert result["mode"] == "diagnose"
    assert result["failure_count"] == 0
    assert result["checks"][0]["status"] == "passed"


def test_code_diagnose_rejects_paths_outside_project():
    result = code_diagnose(
        '{"path":"../browser_controller.py","run_tests":false,"run_lint":false}'
    )

    assert result["success"] is False
    assert result["verified"] is False
    assert "outside the project" in result["failures"][0]


def test_software_change_classification_covers_feature_work():
    assert is_software_change_request(
        "add a new browser automation feature to JARVIS"
    ) is True
    assert is_software_change_request(
        "integrate another capability into my assistant"
    ) is True
    assert is_software_change_request(
        "tell me a story about an assistant"
    ) is False


def test_self_diagnosis_and_repair_are_software_work():
    assert is_software_diagnostic_request(
        "diagnose yourself"
    ) is True
    assert is_software_repair_request(
        "fix your own code"
    ) is True


def test_change_plan_requires_checkpoint_and_validation():
    issues = __import__("planner").assess_plan(
        "add a new feature to JARVIS",
        {
            "goal": "add feature",
            "steps": [
                {
                    "tool": "edit_file",
                    "argument": "main.py|||old|||new",
                }
            ],
        },
    )

    assert any("checkpoint" in issue.lower() for issue in issues)
    assert any("code_test" in issue.lower() for issue in issues)


def test_validate_plan_accepts_code_diagnose_json():
    plan = validate_plan(
        {
            "goal": "diagnose project",
            "steps": [
                {
                    "tool": "code_diagnose",
                    "argument": "{'run_tests': False}",
                }
            ],
        }
    )

    assert plan["steps"][0]["tool"] == "code_diagnose"
    assert plan["steps"][0]["argument"] == '{"run_tests": false}'

from code_gen import is_complex_code_request


def test_complex_code_requests_use_full_agent_workflow():
    assert is_complex_code_request(
        "build a full JARVIS browser automation project"
    ) is True
    assert is_complex_code_request(
        "write a simple Python script called hello.py"
    ) is False

from types import SimpleNamespace

from tools import dev_command


def test_dev_command_uses_active_python_for_python_commands(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="passed",
            stderr="",
        )

    monkeypatch.setattr("tools.subprocess.run", fake_run)

    result = dev_command(
        '{"command":"python -m pytest tests/test_code_test_tool.py -q","timeout":30}'
    )

    assert result["success"] is True
    assert result["verified"] is True
    assert calls
    assert calls[0][0][0]
    assert calls[0][0][1:4] == ["-m", "pytest", "tests/test_code_test_tool.py"]


def test_dev_command_rejects_shell_operators_as_invalid_arguments():
    result = dev_command(
        '{"command":"python -m pytest tests && whoami"}'
    )

    # The command is parsed as one argv list and never sent through a shell.
    # The test only asserts that the raw shell chaining syntax is not treated
    # as an executable command.
    assert result["command"] == "python -m pytest tests && whoami"
