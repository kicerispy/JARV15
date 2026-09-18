import os
from pathlib import Path


def test_list_files_filters_runtime_and_backup_noise(tmp_path, monkeypatch):
    import file_tools

    monkeypatch.chdir(tmp_path)

    (tmp_path / "browser_controller.py").write_text("pass", encoding="utf-8")
    (tmp_path / "browser_controller.py.before_dom_tools").write_text(
        "backup",
        encoding="utf-8",
    )
    (tmp_path / "screen_vision_backup.txt").write_text(
        "backup",
        encoding="utf-8",
    )
    (tmp_path / "input.wav").write_bytes(b"audio")
    (tmp_path / "jarvis_cuda").mkdir()
    (tmp_path / ".git").mkdir()

    result = file_tools.list_files(".")

    assert "browser_controller.py" in result
    assert "before_dom_tools" not in result
    assert "screen_vision_backup" not in result
    assert "input.wav" not in result
    assert "jarvis_cuda" not in result
    assert ".git" not in result


def test_context_project_analysis_filters_backup_artifacts(tmp_path, monkeypatch):
    import context_aware

    monkeypatch.chdir(tmp_path)

    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "main.py.before_change").write_text(
        "backup",
        encoding="utf-8",
    )
    (tmp_path / "main_backup.py").write_text(
        "backup",
        encoding="utf-8",
    )
    (tmp_path / "notes.md").write_text(
        "notes",
        encoding="utf-8",
    )
    (tmp_path / "input.wav").write_bytes(b"audio")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "junk.txt").write_text(
        "cache",
        encoding="utf-8",
    )

    context = object.__new__(context_aware.JarvisContext)
    info = context._analyze_project()

    names = {Path(path).name for path in info["files"]}

    assert "main.py" in names
    assert "notes.md" in names
    assert "main.py.before_change" not in names
    assert "main_backup.py" not in names
    assert "input.wav" not in names
    assert "junk.txt" not in names


def test_task_progress_is_reserved_for_complex_plans():
    from agent_core import AgentStep, JarvisAgent

    agent = JarvisAgent()

    task = agent.create_task("fix the browser automation")

    task.steps = [
        AgentStep(tool="list_files"),
        AgentStep(tool="read_file"),
        AgentStep(tool="code_test"),
    ]

    assert agent._should_report_progress(task) is False

    task.steps.append(AgentStep(tool="edit_file"))

    assert agent._should_report_progress(task) is True


def test_voice_source_uses_runtime_onnx_provider_detection():
    source = Path("voice.py").read_text(encoding="utf-8-sig")

    assert "import onnxruntime as ort" in source
    assert 'ort.get_available_providers()' in source
    assert '"CUDAExecutionProvider"' in source
    assert "use_cuda=_using_cuda" in source
    assert "Piper inference provider" in source
