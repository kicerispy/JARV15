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
