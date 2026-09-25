from __future__ import annotations

from pathlib import Path

import qol_tools


def test_dependency_status_reports_declared_environment(monkeypatch):
    monkeypatch.setattr(
        qol_tools,
        "config",
        type("Config", (), {"BASE_DIR": Path.cwd()})(),
    )
    result = qol_tools.dependency_status()
    assert result["success"] in {True, False}
    assert result["verified"] is True
    assert isinstance(result["missing"], list)
    assert isinstance(result["installed"], list)
