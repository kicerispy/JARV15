from browser_controller import _dom_target_args, _locator


class FakePage:
    def __init__(self):
        self.calls = []

    def get_by_role(self, *args, **kwargs):
        self.calls.append(("get_by_role", args, kwargs))
        return "role-locator"

    def get_by_text(self, *args, **kwargs):
        self.calls.append(("get_by_text", args, kwargs))
        return "text-locator"

    def locator(self, *args, **kwargs):
        self.calls.append(("locator", args, kwargs))
        return "selector-locator"


def test_locator_supports_aria_role_and_accessible_name():
    page = FakePage()

    result = _locator(
        page,
        role="button",
        name="Sign in",
    )

    assert result == "role-locator"
    assert page.calls == [
        (
            "get_by_role",
            ("button",),
            {"name": "Sign in", "exact": False},
        )
    ]


def test_locator_rejects_accessible_name_without_role():
    page = FakePage()

    try:
        _locator(page, name="Sign in")
    except ValueError as exc:
        assert "requires an ARIA role" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_existing_text_and_selector_targets_remain_compatible():
    page = FakePage()

    assert _locator(page, text="Sign in") == "text-locator"
    assert _locator(page, selector="button[type=submit]") == "selector-locator"


def test_dom_target_metadata_preserves_accessible_name():
    assert _dom_target_args(
        role="button",
        name="Sign in",
    ) == {
        "selector": "",
        "text": "",
        "role": "button",
        "name": "Sign in",
    }


def test_planner_prompt_explicitly_prefers_semantic_dom_controls():
    from planner import _planner_prompt

    prompt = _planner_prompt()

    assert "ARIA role plus accessible name" in prompt
    assert "Do not use screen coordinates for browser interaction" in prompt


def test_browser_dispatcher_passes_accessible_name(monkeypatch):
    import browser_controller
    import tools

    captured = {}

    def fake_click_element(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "verified": True,
        }

    monkeypatch.setattr(
        browser_controller,
        "browser_click_element",
        fake_click_element,
    )

    result = tools.run_browser_tool(
        "browser_click_element",
        '{"role":"button","name":"Sign in"}',
    )

    assert result.success is True
    assert captured == {
        "selector": "",
        "text": "",
        "role": "button",
        "name": "Sign in",
    }


def test_find_search_box_routes_to_dom_role():
    from commands import get_fast_command

    plan = get_fast_command("Find the search box")

    assert plan["steps"] == [{
        "tool": "browser_find_element",
        "argument": '{"role": "searchbox"}',
    }]


def test_fill_search_box_routes_to_dom_role():
    from commands import get_fast_command

    plan = get_fast_command("Fill the search box with ChatGPT")

    assert plan["steps"] == [{
        "tool": "browser_fill_element",
        "argument": '{"role": "searchbox", "value": "ChatGPT"}',
    }]


def test_press_enter_in_search_box_routes_to_dom_role():
    from commands import get_fast_command

    plan = get_fast_command("Press Enter in the search box")

    assert plan["steps"] == [{
        "tool": "browser_press_key",
        "argument": '{"role": "searchbox", "key": "Enter"}',
    }]


def test_wait_for_results_routes_to_dom_text():
    from commands import get_fast_command

    plan = get_fast_command("Wait for the results")

    assert plan["steps"] == [{
        "tool": "browser_wait_for_element",
        "argument": '{"text": "Results"}',
    }]


def test_click_named_button_routes_to_dom_role_and_name():
    from commands import get_fast_command

    plan = get_fast_command("Click the Sign in button")

    assert plan["steps"] == [{
        "tool": "browser_click_element",
        "argument": '{"role": "button", "name": "Sign in"}',
    }]


def test_dom_router_does_not_steal_contextual_result_clicks():
    from commands import get_fast_command

    assert get_fast_command("Click the first result") is None


def test_open_chrome_remains_a_desktop_launch_command():
    from commands import get_fast_command

    plan = get_fast_command("Open Chrome")

    assert plan["steps"] == [{
        "tool": "open_program",
        "argument": "chrome",
    }]



def test_read_page_routes_to_browser_snapshot():
    from commands import get_fast_command

    plan = get_fast_command("Read this page")

    assert plan["steps"] == [{
        "tool": "browser_page_snapshot",
        "argument": "",
    }]


def test_read_current_browser_page_routes_to_browser_snapshot():
    from commands import get_fast_command

    plan = get_fast_command("read the current browser page")

    assert plan["steps"] == [{
        "tool": "browser_page_snapshot",
        "argument": "",
    }]


def test_snapshot_canonical_url_unwraps_search_redirects():
    from browser_controller import _snapshot_canonical_url

    assert _snapshot_canonical_url(
        "/goto?url=https%3A%2F%2Fexample.com%2Fdocs"
    ) == "https://example.com/docs"

    assert _snapshot_canonical_url(
        "https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fnews"
    ) == "https://example.com/news"


def test_snapshot_speech_preview_is_bounded():
    from tool_executor import format_browser_result

    result = {
        "title": "Example Search",
        "spoken_preview": (
            "I found 4 search results. First: Alpha. Second: Beta. Third: Gamma."
        ),
        "results": [
            {"index": "1", "title": "Alpha", "snippet": "A useful snippet.", "url": "https://example.com/a"},
            {"index": "2", "title": "Beta", "snippet": "Another useful snippet.", "url": "https://example.com/b"},
            {"index": "3", "title": "Gamma", "snippet": "More useful context.", "url": "https://example.com/c"},
            {"index": "4", "title": "Delta", "snippet": "Additional context.", "url": "https://example.com/d"},
        ],
    }

    spoken = format_browser_result("browser_page_snapshot", result)
    assert spoken == result["spoken_preview"]
    assert len(spoken) < 200


def test_browser_snapshot_is_in_browser_dispatcher(monkeypatch):
    import browser_controller
    import tools

    monkeypatch.setattr(
        browser_controller,
        "browser_page_snapshot",
        lambda: {
            "success": True,
            "verified": True,
            "action": "page_snapshot",
            "title": "Example",
        },
    )

    result = tools.run_browser_tool(
        "browser_page_snapshot",
        "",
    )

    assert result.success is True
    assert result.data["action"] == "page_snapshot"


def test_browser_snapshot_is_in_executor_dispatcher():
    import tool_executor

    assert "browser_page_snapshot" in tool_executor.BROWSER_TOOLS


def test_planner_advertises_browser_snapshot():
    from planner import AVAILABLE_TOOLS

    assert "browser_page_snapshot" in AVAILABLE_TOOLS
