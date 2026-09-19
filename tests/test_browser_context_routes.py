import json

from planner import create_plan


def test_resolved_google_browser_result_does_not_call_llm():
    plan = create_plan(
        "click the first browser result on google",
        {
            "site": "google",
            "last_query": "Wi-Fi skeleton",
        },
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "browser_click_first_result",
    ]
    assert json.loads(plan["steps"][0]["argument"]) == {
        "site": "google",
        "query": "Wi-Fi skeleton",
    }


def test_resolved_youtube_browser_result_uses_active_context():
    plan = create_plan(
        "click the first browser result on youtube",
        {
            "site": "youtube",
            "last_query": "Iron Man trailer",
        },
    )

    assert [step["tool"] for step in plan["steps"]] == [
        "browser_click_first_result",
    ]
    assert json.loads(plan["steps"][0]["argument"]) == {
        "site": "youtube",
        "query": "Iron Man trailer",
    }
