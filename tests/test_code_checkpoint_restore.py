from pathlib import Path


def test_checkpoint_restore_removes_source_files_created_after_checkpoint(
    tmp_path,
    monkeypatch,
):
    import tools

    monkeypatch.chdir(tmp_path)

    original = tmp_path / "main.py"
    original.write_text("print('before')\n", encoding="utf-8")

    checkpoint = tools.code_checkpoint("")
    assert checkpoint["success"] is True

    created_after = tmp_path / "new_feature.py"
    created_after.write_text("print('new')\n", encoding="utf-8")

    original.write_text("print('broken')\n", encoding="utf-8")

    restored = tools.code_restore_checkpoint("")

    assert restored["success"] is True
    assert not created_after.exists()
    assert original.read_text(encoding="utf-8") == "print('before')\n"
    assert restored["removed_new_source_files"] == 1
