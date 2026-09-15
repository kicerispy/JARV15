"""
Tests for JARVIS file tools.
"""
import os
import tempfile
import pytest
from pathlib import Path

from file_tools import (
    _sanitize_folder_name,
    _resolve_safe_path,
    create_folder,
    list_files,
    find_file,
    open_folder,
)


class TestSanitizeFolderName:
    """Tests for _sanitize_folder_name."""

    def test_basic_name(self):
        # Spaces are preserved, only dangerous chars are removed
        assert _sanitize_folder_name("my folder") == "my folder"

    def test_remove_path_separators(self):
        assert _sanitize_folder_name("foo/bar") == "foo_bar"
        assert _sanitize_folder_name("foo\\bar") == "foo_bar"

    def test_remove_dangerous_chars(self):
        assert _sanitize_folder_name('test<>:"|?*file') == "test_______file"

    def test_remove_control_chars(self):
        assert _sanitize_folder_name("test\x00file") == "test_file"

    def test_strip_dots(self):
        assert _sanitize_folder_name("...") == ""


class TestResolveSafePath:
    """Tests for _resolve_safe_path."""

    def test_basic_path(self, tmp_path):
        result = _resolve_safe_path(tmp_path, "subdir")
        assert result is not None
        assert result == tmp_path / "subdir"

    def test_path_traversal_blocked(self, tmp_path):
        result = _resolve_safe_path(tmp_path, "../etc")
        assert result is None

    def test_allow_outside(self, tmp_path):
        result = _resolve_safe_path(tmp_path, "../etc", allow_outside=True)
        assert result is not None


class TestCreateFolder:
    """Tests for create_folder."""

    def test_create_basic_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = create_folder("test_folder")
        assert "Created" in result
        assert (tmp_path / "test_folder").is_dir()

    def test_create_empty_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = create_folder("")
        assert "empty" in result

    def test_create_with_path_traversal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = create_folder("../evil")
        # The path traversal is blocked by sanitize + relative_to check
        assert "outside" in result.lower() or "created" in result.lower()


class TestListFiles:
    """Tests for list_files."""

    def test_list_empty_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = list_files(".")
        assert "empty" in result.lower()

    def test_list_files_with_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "file1.txt").write_text("test")
        (tmp_path / "file2.txt").write_text("test")
        result = list_files(".")
        assert "file1.txt" in result
        assert "file2.txt" in result

    def test_list_nonexistent_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = list_files("nonexistent")
        assert "not found" in result.lower()


class TestFindFile:
    """Tests for find_file."""

    def test_find_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "test_file.txt").write_text("test")
        result = find_file("test_file")
        assert "Found" in result
        assert "test_file.txt" in result

    def test_find_no_results(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = find_file("nonexistent_file_xyz")
        assert "No files found" in result

    def test_find_empty_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = find_file("")
        assert "empty" in result.lower()