import json

from commands import get_fast_command, should_resolve_context
from context_resolver import _deterministic_followup
from planner import create_plan
from smart_router import route_command
from state import ActiveContext
from tool_executor import _update_browser_active_context
from tool_result import ToolResult


def make_context(site="google", query="Wi-Fi skeleton"):
    return {
        "site": site,
        "last_query": query,
    }


def test_second_result_followup_routes_to_browser_dom():
    decision = route_command("Click the second result")
    assert decision.kind == "contextual"

    resolved = _deterministic_followup(
        "Click the second result",
        make_context(),
    )
    assert resolved == "click the second browser result on google"

    plan = create_plan(resolved, make_context())
    assert plan["steps"] == [
        {
            "tool": "browser_click_result",
            "argument": json.dumps(
                {
                    "index": 2,
                    "site": "google",
                    "query": "Wi-Fi skeleton",
                }
            ),
        }
    ]


def test_third_result_and_last_result_are_deterministic():
    for command, expected_index in [
        ("Click the third result", 3),
        ("Open the last result", "last"),
    ]:
        assert should_resolve_context(command) is True
        resolved = _deterministic_followup(command, make_context())
        plan = create_plan(resolved, make_context())

        assert plan["steps"][0]["tool"] == "browser_click_result"
        assert json.loads(plan["steps"][0]["argument"]) == {
            "index": expected_index,
            "site": "google",
            "query": "Wi-Fi skeleton",
        }


def test_click_it_uses_first_result_when_search_context_has_no_selected_title():
    resolved = _deterministic_followup(
        "Click it",
        make_context("youtube", "Iron Man trailer"),
    )

    assert resolved == "click the first browser result on youtube"

    plan = create_plan(
        resolved,
        make_context("youtube", "Iron Man trailer"),
    )
    assert plan["steps"][0]["tool"] == "browser_click_first_result"
    assert json.loads(plan["steps"][0]["argument"]) == {
        "site": "youtube",
        "query": "Iron Man trailer",
    }


def test_read_this_page_stays_out_of_llm_planning():
    assert should_resolve_context("Read this page") is True

    resolved = _deterministic_followup(
        "Read this page",
        make_context(),
    )
    plan = create_plan(resolved, make_context())

    assert plan["steps"] == [
        {
            "tool": "browser_extract_text",
            "argument": json.dumps({"selector": "body"}),
        }
    ]


def test_browser_native_search_preserves_query_context():
    context = ActiveContext()

    result = ToolResult(
        success=True,
        tool="browser_search_google",
        data={
            "success": True,
            "url": "https://www.google.com/search?q=Wi-Fi+skeleton",
            "title": "Wi-Fi skeleton - Google Search",
        },
    )

    _update_browser_active_context(
        "browser_search_google",
        result,
        context,
        "Wi-Fi skeleton",
    )

    assert context.site == "google"
    assert context.last_query == "Wi-Fi skeleton"
    assert context.page_url == (
        "https://www.google.com/search?q=Wi-Fi+skeleton"
    )


def test_click_it_is_not_claimed_by_fast_click_handler():
    assert get_fast_command("Click it") is None


def test_click_it_after_selected_result_without_url_uses_dom_element():
    context = make_context("google", "Wi-Fi skeleton")
    context["last_result_title"] = "WiFi Skeleton"

    resolved = _deterministic_followup(
        "Click it",
        context,
    )
    assert resolved == "click the browser element with visible text 'WiFi Skeleton'"

    plan = create_plan(resolved, context)

    assert plan["steps"] == [
        {
            "tool": "browser_click_element",
            "argument": json.dumps({
                "text": "WiFi Skeleton",
            }),
        }
    ]


def test_click_it_after_navigation_reopens_selected_result_url():
    context = make_context("google", "Wi-Fi skeleton")
    context["last_result_title"] = "Wifiskeleton"
    context["last_result_url"] = "https://en.wikipedia.org/wiki/Wifiskeleton"
    # This fixture represents the browser after the result was opened.
    context["page_url"] = "https://en.wikipedia.org/wiki/Wifiskeleton"

    resolved = _deterministic_followup(
        "Click it",
        context,
    )
    assert resolved == "open the previously selected browser result"

    plan = create_plan(resolved, context)

    assert plan["steps"] == [
        {
            "tool": "browser_goto",
            "argument": "https://en.wikipedia.org/wiki/Wifiskeleton",
        }
    ]


def test_click_it_uses_clean_selected_result_title_when_still_on_result_page():
    context = make_context("google", "Wi-Fi skeleton")
    context["last_result_title"] = "Wifiskeleton"
    context["page_url"] = "https://www.google.com/search?q=Wi-Fi+skeleton"

    resolved = _deterministic_followup(
        "Click it",
        context,
    )
    assert resolved == "click the browser element with visible text 'Wifiskeleton'"

    plan = create_plan(resolved, context)
    assert plan["steps"][0]["tool"] == "browser_click_element"
    assert json.loads(plan["steps"][0]["argument"]) == {
        "text": "Wifiskeleton",
    }


def test_click_it_on_selected_result_page_still_uses_selected_url():
    context = make_context("google", "Wi-Fi skeleton")
    context["last_result_title"] = "Wifiskeleton"
    context["last_result_url"] = "https://en.wikipedia.org/wiki/Wifiskeleton"
    context["page_url"] = "https://en.wikipedia.org/wiki/Wifiskeleton"

    resolved = _deterministic_followup(
        "Click it",
        context,
    )
    assert resolved == "open the previously selected browser result"

    plan = create_plan(resolved, context)
    assert plan["steps"][0] == {
        "tool": "browser_goto",
        "argument": "https://en.wikipedia.org/wiki/Wifiskeleton",
    }
