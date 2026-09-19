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
