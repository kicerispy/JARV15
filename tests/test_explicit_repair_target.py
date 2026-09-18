from agent_core import JarvisAgent


def test_infer_requested_file_target_handles_bug_in_phrase():
    agent = JarvisAgent(planner=lambda *args, **kwargs: {})

    assert (
        agent._infer_requested_file_target(
            "Fix the bug in jarvis_autonomous_test_target.py"
        )
        == "jarvis_autonomous_test_target.py"
    )


def test_infer_requested_file_target_handles_issue_and_article_variants():
    agent = JarvisAgent(planner=lambda *args, **kwargs: {})

    for request in (
        "Fix a bug in browser_controller.py",
        "Repair the issue in browser_controller.py",
        "Diagnose and repair the problem in browser_controller.py",
    ):
        assert agent._infer_requested_file_target(request) == "browser_controller.py"
