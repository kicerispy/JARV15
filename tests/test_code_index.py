from __future__ import annotations

import code_index


def test_code_index_rebuild_and_status(monkeypatch, tmp_path):
    monkeypatch.setattr(
        code_index,
        "INDEX_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        code_index,
        "INDEX_PATH",
        tmp_path / "code_index.sqlite3",
    )
    result = code_index.rebuild()
    assert result["verified"] is True

    status = code_index.status()
    assert status["success"] is True
    assert status["indexed_files"] >= 0


def test_code_index_search_rejects_empty_query():
    result = code_index.search("")
    assert result["success"] is False
    assert result["verified"] is False
