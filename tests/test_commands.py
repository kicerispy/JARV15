"""
Tests for JARVIS command parsing utilities.
"""
import pytest

from commands import (
    normalize_command,
    is_cancel_command,
    is_end_conversation_command,
    is_shutdown_command,
    is_remember_command,
    should_resolve_context,
    CANCEL_COMMANDS,
    END_CONVERSATION_COMMANDS,
    DIRECT_PREFIXES,
    CONTEXTUAL_PHRASES,
    REFERENCE_WORDS,
)


class TestNormalizeCommand:
    """Tests for normalize_command function."""

    def test_strip_whitespace(self):
        assert normalize_command("  hello  ") == "hello"

    def test_remove_trailing_punctuation(self):
        assert normalize_command("hello.") == "hello"
        assert normalize_command("hello!") == "hello"
        assert normalize_command("hello?") == "hello"
        assert normalize_command("hello,") == "hello"

    def test_collapse_spaces(self):
        assert normalize_command("hello    world") == "hello world"

    def test_empty_string(self):
        assert normalize_command("") == ""
        assert normalize_command("   ") == ""

    def test_none_input(self):
        assert normalize_command(None) == ""


class TestIsCancelCommand:
    """Tests for is_cancel_command function."""

    @pytest.mark.parametrize("command", list(CANCEL_COMMANDS))
    def test_known_cancel_commands(self, command):
        assert is_cancel_command(command) is True

    def test_case_insensitive(self):
        assert is_cancel_command("STOP") is True
        assert is_cancel_command("Cancel") is True

    def test_not_cancel(self):
        assert is_cancel_command("hello") is False
        assert is_cancel_command("") is False


class TestIsEndConversationCommand:
    """Tests for is_end_conversation_command function."""

    @pytest.mark.parametrize("command", list(END_CONVERSATION_COMMANDS))
    def test_known_end_commands(self, command):
        assert is_end_conversation_command(command) is True

    def test_case_insensitive(self):
        assert is_end_conversation_command("SLEEP") is True

    def test_not_end(self):
        assert is_end_conversation_command("hello") is False


class TestIsShutdownCommand:
    """Tests for is_shutdown_command function."""

    def test_known_shutdown(self):
        assert is_shutdown_command("quit") is True
        assert is_shutdown_command("exit") is True
        assert is_shutdown_command("shutdown") is True
        assert is_shutdown_command("shut down") is True

    def test_case_insensitive(self):
        assert is_shutdown_command("QUIT") is True

    def test_not_shutdown(self):
        assert is_shutdown_command("hello") is False


class TestIsRememberCommand:
    """Tests for is_remember_command function."""

    def test_starts_with_remember(self):
        assert is_remember_command("remember my name") is True
        assert is_remember_command("remember") is True

    def test_not_remember(self):
        assert is_remember_command("hello") is False
        assert is_remember_command("reminder") is False


class TestShouldResolveContext:
    """Tests for should_resolve_context function."""

    def test_direct_prefixes_not_resolved(self):
        for prefix in DIRECT_PREFIXES:
            assert should_resolve_context(f"{prefix} something") is False

    def test_contextual_phrases_resolved(self):
        # Test contextual phrases that don't conflict with direct prefixes
        for phrase in CONTEXTUAL_PHRASES:
            if not any(phrase.startswith(dp) for dp in DIRECT_PREFIXES):
                assert should_resolve_context(f"{phrase} something") is True

    def test_reference_words_resolved(self):
        for word in REFERENCE_WORDS:
            assert should_resolve_context(f"do {word}") is True

    def test_empty_not_resolved(self):
        assert should_resolve_context("") is False

    def test_search_result_summary_followups_resolved(self):
        for command in (
            "What are the search results?",
            "Tell me the search results",
            "Show me the search results",
            "What did the search find?",
            "What did you find?",
        ):
            assert should_resolve_context(command) is True