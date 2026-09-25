from __future__ import annotations

import qol_tools


def test_resource_status_returns_bounded_machine_metrics():
    result = qol_tools.resource_status()

    assert result["success"] is True
    assert 0 <= result["cpu_percent"] <= 100
    assert 0 <= result["memory_percent"] <= 100
    assert result["disk_free_gb"] >= 0


def test_process_snapshot_limits_result_size():
    result = qol_tools.process_snapshot("3")

    assert result["success"] is True
    assert len(result["processes"]) <= 3


def test_service_status_rejects_unknown_service():
    result = qol_tools.service_status("definitely-not-a-service")
    assert result["success"] is False
    assert result["verified"] is False
