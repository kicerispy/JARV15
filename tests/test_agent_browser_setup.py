def test_agent_browser_setup_reports_missing_npm(monkeypatch):
    import adaptive_runtime

    monkeypatch.setattr(
        adaptive_runtime,
        "_agent_browser_executable",
        lambda: "",
    )
    monkeypatch.setattr(
        adaptive_runtime.shutil,
        "which",
        lambda name: None,
    )

    result = adaptive_runtime.agent_browser_setup(
        '{"action":"install"}'
    )

    assert result["success"] is False
    assert "npm" in result["message"].lower()


def test_agent_browser_setup_rejects_unknown_action():
    import adaptive_runtime

    result = adaptive_runtime.agent_browser_setup(
        '{"action":"destroy"}'
    )

    assert result["success"] is False
    assert "install" in result["message"].lower()
    assert "upgrade" in result["message"].lower()
