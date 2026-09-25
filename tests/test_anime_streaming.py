import anime_streaming
import planner
import tools


def test_anime_streaming_filters_non_official_domains():
    assert anime_streaming._provider_for_url("https://www.crunchyroll.com/watch/abc") == "Crunchyroll"
    assert anime_streaming._provider_for_url("https://example.com/watch/abc") is None


def test_anime_streaming_deduplicates_and_combines_sources(monkeypatch):
    monkeypatch.setattr(
        anime_streaming,
        "_anilist_links",
        lambda anime, episode, limit: [
            {
                "anime": anime,
                "episode": episode,
                "provider": "Crunchyroll",
                "url": "https://www.crunchyroll.com/watch/abc",
                "source": "anilist",
                "official_domain": True,
            }
        ],
    )
    monkeypatch.setattr(
        anime_streaming,
        "_web_links",
        lambda anime, episode, limit: [
            {
                "anime": anime,
                "episode": episode,
                "provider": "Crunchyroll",
                "url": "https://www.crunchyroll.com/watch/abc",
                "source": "web_search",
                "official_domain": True,
            },
            {
                "anime": anime,
                "episode": episode,
                "provider": "HIDIVE",
                "url": "https://www.hidive.com/tv/example",
                "source": "web_search",
                "official_domain": True,
            },
        ],
    )

    result = anime_streaming.anime_streaming_links('{"anime":"Frieren","episode":5}')
    assert result["success"] is True
    links = result["data"]["links"]
    assert len(links) == 2
    assert result["data"]["providers"] == ["Crunchyroll", "HIDIVE"]


def test_anime_streaming_reports_clean_failure(monkeypatch):
    monkeypatch.setattr(
        anime_streaming,
        "_anilist_links",
        lambda anime, episode, limit: [],
    )
    monkeypatch.setattr(
        anime_streaming,
        "_web_links",
        lambda anime, episode, limit: [],
    )

    result = anime_streaming.anime_streaming_links("DefinitelyNotAnAnime")
    assert result["success"] is False
    assert "No official streaming pages found" in result["error"]


def test_planner_routes_streaming_link_requests():
    plan = planner.create_plan("find streaming links for Frieren")
    assert plan["steps"][0]["tool"] == "anime_streaming_links"
    assert plan["steps"][0]["argument"] == "Frieren"


def test_public_dispatcher_exposes_anime_streaming_tool(monkeypatch):
    monkeypatch.setattr(
        anime_streaming,
        "anime_streaming_links",
        lambda argument: {
            "success": True,
            "tool": "anime_streaming_links",
            "data": {"links": []},
        },
    )

    result = tools.run_tool("anime_streaming_links", "Frieren")
    assert result.success is True
    assert result.tool == "anime_streaming_links"
