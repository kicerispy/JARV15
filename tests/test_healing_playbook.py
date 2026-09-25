from __future__ import annotations

import pathlib

import healing_playbook


def test_failure_playbook_records_and_surfaces_resolved_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(healing_playbook, "_DB_DIR", pathlib.Path(tmp_path))
    monkeypatch.setattr(
        healing_playbook,
        "_DB_PATH",
        pathlib.Path(tmp_path) / "playbook.sqlite3",
    )

    healing_playbook.record_failure(
        signature="abc123",
        tool="browser_click_element",
        category="browser_drift",
        error="Element not found",
        argument='{"text":"Search"}',
        action="replan",
        reason="Target drifted.",
    )
    healing_playbook.mark_recovered(
        tool="browser_click_element",
        signature="abc123",
    )

    hints = healing_playbook.failure_hints(
        tool="browser_click_element",
        category="browser_drift",
        error="Element not found again",
    )

    assert hints
    assert hints[0]["signature"] == "abc123"
    assert hints[0]["occurrences"] == 1
    assert hints[0]["resolved_count"] == 1

    status = healing_playbook.playbook_status()
    assert status["records"] == 1
    assert status["observations"] == 1
    assert status["recoveries"] == 1


def test_failure_playbook_deduplicates_by_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(healing_playbook, "_DB_DIR", pathlib.Path(tmp_path))
    monkeypatch.setattr(
        healing_playbook,
        "_DB_PATH",
        pathlib.Path(tmp_path) / "playbook.sqlite3",
    )

    for _ in range(3):
        healing_playbook.record_failure(
            signature="same",
            tool="ollama",
            category="transient_transport",
            error="connection refused",
        )

    status = healing_playbook.playbook_status()
    assert status["records"] == 1
    assert status["observations"] == 3
