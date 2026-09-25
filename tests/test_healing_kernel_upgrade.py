from __future__ import annotations

import healing_kernel


def test_recovery_backoff_is_bounded_and_exponential():
    assert healing_kernel.recovery_backoff_seconds(1, base_seconds=0.25, max_seconds=4) == 0.25
    assert healing_kernel.recovery_backoff_seconds(2, base_seconds=0.25, max_seconds=4) == 0.5
    assert healing_kernel.recovery_backoff_seconds(4, base_seconds=0.25, max_seconds=4) == 2.0
    assert healing_kernel.recovery_backoff_seconds(8, base_seconds=0.25, max_seconds=4) == 4.0
    assert healing_kernel.recovery_backoff_seconds(1, base_seconds=0, max_seconds=4) == 0.0


def test_healing_hints_fail_closed(monkeypatch):
    class FailingPlaybook:
        @staticmethod
        def failure_hints(**kwargs):
            raise RuntimeError("playbook unavailable")

    monkeypatch.setitem(
        __import__("sys").modules,
        "healing_playbook",
        FailingPlaybook,
    )
    assert healing_kernel.healing_hints("unknown_tool") == []
