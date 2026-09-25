from __future__ import annotations

from tools import normalize_tool_result


def test_unverified_legacy_dict_is_treated_as_failure():
    result = normalize_tool_result(
        "example_tool",
        {
            "verified": False,
            "message": "The requested action could not be verified.",
            "retryable": True,
        },
    )

    assert result.success is False
    assert result.retryable is True
    assert "could not be verified" in (result.error or "")


def test_error_field_without_success_is_treated_as_failure():
    result = normalize_tool_result(
        "example_tool",
        {
            "error": "connection refused",
            "retryable": True,
        },
    )

    assert result.success is False
    assert result.retryable is True
