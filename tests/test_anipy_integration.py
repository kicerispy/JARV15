import json
import subprocess

import pytest

from commands import build_anipy_plan
from tool_registry import ANIPY_TOOLS, validate_known_tools


def test_anipy_tools_are_registered():
    expected = {
        "anipy_cli",
        "anipy_providers",
        "anipy_search",
        "anipy_info",
        "anipy_episodes",
        "anipy_get_video",
        "anipy_download",
    }

    assert expected <= set(ANIPY_TOOLS)
    assert validate_known_tools(expected) == []


def test_anipy_explicit_cli_passthrough():
    plan = build_anipy_plan("run anipy-cli -D -s \"One Piece:1-3:sub\"")

    assert plan == {
        "steps": [{
            "tool": "anipy_cli",
            "argument": '-D -s "One Piece:1-3:sub"',
        }]
    }


def test_anipy_cli_prefix_without_verb():
    plan = build_anipy_plan("anipy-cli -H")
    assert plan == {
        "steps": [{
            "tool": "anipy_cli",
            "argument": "-H",
        }]
    }


def test_anipy_download_routes_to_structured_downloader():
    plan = build_anipy_plan("download One Piece episodes 1-3 sub")

    assert plan["steps"][0]["tool"] == "anipy_download"

    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["query"] == "One Piece"
    assert payload["episodes"] == "1-3"
    assert payload["language"] == "sub"


def test_anipy_watch_range_uses_native_binge_mode():
    plan = build_anipy_plan("watch One Piece episodes 1-3 sub")

    assert plan["steps"][0]["tool"] == "anipy_cli"
    payload = json.loads(plan["steps"][0]["argument"])
    assert payload["args"] == ["-B", "-s", "One Piece:1-3:sub"]


def test_native_cli_args_are_forwarded_without_shell_execution(monkeypatch):
    from anipy_integration import _native_cli_args, _run_native_cli

    assert _native_cli_args(
        json.dumps({"args": ["-D", "-s", "One Piece:1-3:sub"]})
    ) == ["-D", "-s", "One Piece:1-3:sub"]

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        "anipy_integration.subprocess.run",
        fake_run,
    )

    result = _run_native_cli(
        json.dumps({"args": ["-D", "-s", "One Piece:1:sub"]})
    )

    assert result["success"] is True
    assert captured["command"][1:4] == [
        "-m",
        "anipy_cli.cli",
        "-D",
    ]
    assert captured["kwargs"].get("shell", False) is not True


@pytest.mark.parametrize(
    "user_request",
    [
        "search anime One Piece",
        "list episodes for Cowboy Bebop",
        "get stream link for Naruto episode 12",
        "download Demon Slayer episodes 1-3",
    ],
)
def test_anime_requests_do_not_fall_into_generic_browser_route(user_request):
    plan = build_anipy_plan(user_request)
    assert plan is not None
    assert plan["steps"][0]["tool"].startswith("anipy_")



def test_numeric_quality_matches_native_cli_parsing():
    from anipy_integration import _quality

    assert _quality("720") == 720
    assert _quality(1080) == 1080
    assert _quality("best") == "best"
    assert _quality("") is None
