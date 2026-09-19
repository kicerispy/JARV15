from product_research import (
    _choose_sources,
    _domain,
    _parse_argument,
    _queries,
)


def test_product_research_parses_plain_request_and_budget():
    parsed = _parse_argument(
        "Find me headphones under $150 and compare reviews."
    )

    assert parsed["item"].startswith("headphones")
    assert parsed["budget"] == 150.0


def test_product_research_parses_structured_argument():
    parsed = _parse_argument(
        '{"item":"4K OLED monitor","budget":300,"request":"find the best one under $300"}'
    )

    assert parsed == {
        "request": "find the best one under $300",
        "item": "4K OLED monitor",
        "budget": 300.0,
    }


def test_product_research_builds_multiple_research_angles():
    queries = _queries("wireless headphones")

    assert queries == [
        "wireless headphones reviews price",
        "wireless headphones best reviews",
        "wireless headphones alternatives",
        "wireless headphones cheaper alternatives",
        "wireless headphones comparison review",
    ]


def test_product_research_classifies_known_source_domains():
    from product_research import _source_type

    assert _source_type("https://www.bestbuy.com/site/example") == "retailer"
    assert _source_type("https://www.rtings.com/headphones/reviews/example") == "independent_review"
    assert _source_type("https://www.reddit.com/r/headphones/comments/example") == "community"
    assert _source_type("https://www.sony.com/electronics/headphones/example") == "manufacturer"


def test_product_research_prefers_domain_diversity():
    discovered = [
        {"domain": "rtings.com", "source_type": "independent_review", "url": "https://rtings.com/a"},
        {"domain": "rtings.com", "source_type": "independent_review", "url": "https://rtings.com/b"},
        {"domain": "bestbuy.com", "source_type": "retailer", "url": "https://bestbuy.com/a"},
        {"domain": "amazon.com", "source_type": "retailer", "url": "https://amazon.com/a"},
        {"domain": "reddit.com", "source_type": "community", "url": "https://reddit.com/a"},
        {"domain": "sony.com", "source_type": "manufacturer", "url": "https://sony.com/a"},
    ]

    selected = _choose_sources(discovered)

    assert len(selected) == 5
    assert len({item["domain"] for item in selected}) == 5
    assert selected[0]["domain"] == "sony.com"


def test_product_research_domain_normalization():
    assert _domain("https://www.example.com/product") == "example.com"


def test_product_research_tool_is_advertised():
    from planner import AVAILABLE_TOOLS

    assert "product_research" in AVAILABLE_TOOLS


def test_product_research_scope_is_narrow():
    from planner import _planner_tool_scope

    scope = _planner_tool_scope(
        "find the best headphones under $150 and compare reviews"
    )

    assert scope == {"product_research"}


def test_best_product_question_gets_research_scope():
    from planner import _planner_tool_scope

    scope = _planner_tool_scope(
        "What are the best headphones under $150?"
    )

    assert scope == {"product_research"}


def test_shopping_question_routes_to_agent():
    from smart_router import route_command

    decision = route_command(
        "What are the best headphones under $150?"
    )

    assert decision.kind == "agent"
    assert "product research" in decision.reason


def test_product_research_dispatches_through_public_tool(monkeypatch):
    import tools

    captured = {}

    def fake_research(argument):
        captured["argument"] = argument
        return {
            "success": True,
            "verified": True,
            "message": "Research complete.",
        }

    monkeypatch.setattr(
        "product_research.research_product",
        fake_research,
    )

    result = tools.run_tool(
        "product_research",
        '{"item":"wireless headphones","budget":150}',
    )

    assert result.success is True
    assert captured["argument"] == '{"item":"wireless headphones","budget":150}'
    assert result.data["message"] == "Research complete."
