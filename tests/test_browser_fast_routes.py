import json

from commands import build_search_first_result_plan, build_website_search_plan
from planner import create_plan


def test_google_search_uses_browser_search_tool():
    plan = build_website_search_plan(
        "Open Chrome and search Google for Iron Man trailer",
        "google",
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "open_program",
        "browser_search_google",
    ]
    assert plan["steps"][1]["argument"] == "Iron Man trailer"


def test_google_combined_search_and_first_result_uses_dom_click():
    plan = build_search_first_result_plan(
        "Open Chrome and search Google for Iron Man trailer and click the first result",
        "google",
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "open_program",
        "browser_search_google",
        "browser_click_first_result",
    ]
    assert "click_screen" not in [step["tool"] for step in plan["steps"]]
    assert json.loads(plan["steps"][2]["argument"]) == {"site": "google"}


def test_youtube_combined_search_and_first_result_uses_dom_click():
    plan = build_search_first_result_plan(
        "Search YouTube for Iron Man trailer and click the first result",
        "youtube",
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "search_website",
        "browser_click_first_result",
    ]
    assert json.loads(plan["steps"][1]["argument"]) == {"site": "youtube"}


def test_google_first_result_followup_stays_deterministic():
    plan = create_plan(
        "Click the first result",
        {
            "site": "google",
            "last_query": "Iron Man trailer",
        },
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "browser_click_first_result",
    ]
    assert json.loads(plan["steps"][0]["argument"]) == {
        "site": "google",
        "query": "Iron Man trailer",
    }
