from project_fs import iter_project_files


def test_iter_project_files_prunes_heavy_directories_before_descent(tmp_path):
    (tmp_path / "jarvis_cuda" / "site-packages" / "pkg").mkdir(parents=True)
    (tmp_path / "jarvis_cuda" / "site-packages" / "pkg" / "target.py").write_text(
        "from jarvis import package\n",
        encoding="utf-8",
    )

    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "hidden.py").write_text(
        "ignored = True\n",
        encoding="utf-8",
    )

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.py").write_text(
        "print('project source')\n",
        encoding="utf-8",
    )

    discovered = {
        path.relative_to(tmp_path).as_posix()
        for path in iter_project_files(tmp_path)
    }

    assert "src/target.py" in discovered
    assert "jarvis_cuda/site-packages/pkg/target.py" not in discovered
    assert ".git/objects/hidden.py" not in discovered


def test_iter_project_files_supports_suffix_filtering_without_recursing_into_ignored_dirs(
    tmp_path,
):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "notes.txt").write_text(
        "not python\n",
        encoding="utf-8",
    )
    (tmp_path / "jarvis_cuda" / "package").mkdir(parents=True)
    (tmp_path / "jarvis_cuda" / "package" / "module.py").write_text(
        "ignored = True\n",
        encoding="utf-8",
    )

    discovered = {
        path.relative_to(tmp_path).as_posix()
        for path in iter_project_files(tmp_path, suffixes={".py"})
    }

    assert discovered == {"src/module.py"}
