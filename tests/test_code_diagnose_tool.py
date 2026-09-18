from types import SimpleNamespace
from unittest.mock import patch

from planner import assess_plan
from tools import code_diagnose


def test_project_diagnostic_compiles_discovered_files_not_project_root():
    completed = SimpleNamespace(
        returncode=0,
        stdout="",
        stderr="",
    )

    with patch("tools.subprocess.run", return_value=completed) as mocked_run:
        result = code_diagnose(
            '{"run_tests":false,"run_lint":false,"run_types":false}'
        )

    assert result["success"] is True
    command = mocked_run.call_args.args[0]
    assert command[:4] == [
        command[0],
        "-m",
        "compileall",
        "-q",
    ]
    assert "." not in command[4:]
    assert not any(
        ".jarvis_checkpoints" in str(arg)
        for arg in command[4:]
    )


def test_repair_quality_gate_rejects_checkpoint_targets():
    request = "Fix the browser automation bug."
    plan = {
        "goal": "repair",
        "steps": [
            {
                "tool": "read_file",
                "argument": ".jarvis_checkpoints/latest/browser_controller.py",
            },
            {
                "tool": "code_checkpoint",
                "argument": "",
            },
            {
                "tool": "edit_file",
                "argument": (
                    ".jarvis_checkpoints/latest/browser_controller.py"
                    "|||old|||new"
                ),
            },
            {
                "tool": "code_test",
                "argument": (
                    '{"mode":"compile",'
                    '"path":".jarvis_checkpoints/latest/browser_controller.py"}'
                ),
            },
        ],
    }

    issues = assess_plan(
        request,
        plan,
        require_modification=True,
    )

    assert any(
        "internal/generated path" in issue
        for issue in issues
    )
