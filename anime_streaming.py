"""Legal anime streaming-page discovery for JARVIS.

This module intentionally discovers *watch pages* on established streaming
services. It does not resolve/bypass DRM, scrape player tokens, extract direct
media manifests, or download protected streams.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests

from web_tools import web_search

USER_AGENT = "JARVIS/1.0 (local personal assistant)"

# Restrict web-discovered links to known consumer streaming services. This is
# deliberately a small allowlist so generic search results cannot turn into
# arbitrary mirror/host extraction.
OFFICIAL_STREAMING_DOMAINS = {
    "crunchyroll.com": "Crunchyroll",
    "hidive.com": "HIDIVE",
    "netflix.com": "Netflix",
    "hulu.com": "Hulu",
    "max.com": "Max",
    "disneyplus.com": "Disney+",
    "primevideo.com": "Prime Video",
    "adultswim.com": "Adult Swim",
    "tubitv.com": "Tubi",
    "pluto.tv": "Pluto TV",
    "aniplus-asia.com": "Ani-One / ANIPLUS",
    "retrocrush.tv": "RetroCrush",
}

# Providers that currently document a free/ad-supported offering. A title is
# only reported as free when search evidence also indicates the specific title
# or watch page is free; the catalog itself is not treated as proof.
FREE_STREAMING_DOMAINS = {
    "tubitv.com": {
        "provider": "Tubi",
        "access": "free_with_ads",
        "region_note": "availability varies by title and region",
    },
    "pluto.tv": {
        "provider": "Pluto TV",
        "access": "free_with_ads",
        "region_note": "availability varies by title and region",
    },
    "retrocrush.tv": {
        "provider": "RetroCrush",
        "access": "free_with_ads",
        "region_note": "US/Canada availability; catalog varies",
    },
    "crunchyroll.com": {
        "provider": "Crunchyroll Channel",
        "access": "free_linear_channel",
        "region_note": "select platforms; curated lineup, not full Crunchyroll library",
    },
}



def _error(message: str, *, retryable: bool = True, tool: str = "anime_streaming_links") -> dict:
    return {
        "success": False,
        "tool": tool,
        "error": str(message),
        "retryable": retryable,
    }


def _success(data: dict, message: str) -> dict:
    return {
        "success": True,
        "tool": "anime_streaming_links",
        "data": data,
        "message": message,
    }


def _domain_match(host: str, domain: str) -> bool:
    host = host.lower().split(":", 1)[0].rstrip(".")
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith("." + domain)


def _provider_for_url(url: str) -> str | None:
    try:
        host = urlparse(url).netloc
    except ValueError:
        return None
    for domain, provider in OFFICIAL_STREAMING_DOMAINS.items():
        if _domain_match(host, domain):
            return provider
    return None


def _parse_argument(argument: str) -> tuple[str, int | None, int]:
    raw = str(argument or "").strip()
    if not raw:
        raise ValueError("Provide an anime title.")

    anime = raw
    episode: int | None = None
    limit = 10

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
        anime = str(
            payload.get("anime")
            or payload.get("title")
            or payload.get("query")
            or ""
        ).strip()

        raw_episode = payload.get("episode")
        if raw_episode not in (None, ""):
            episode = max(1, int(raw_episode))

        limit = min(20, max(1, int(payload.get("limit", 10))))
    else:
        match = re.match(r"^(.+?)\s+episode\s+(\d+)\s*$", raw, re.I)
        if match:
            anime = match.group(1).strip()
            episode = max(1, int(match.group(2)))

    if not anime:
        raise ValueError("Provide an anime title.")

    return anime, episode, limit


def _anilist_links(anime: str, episode: int | None, limit: int) -> list[dict]:
    query = """
        query ($search: String) {
            Media(search: $search, type: ANIME) {
                id
                idMal
                title { romaji english native }
                siteUrl
                streamingEpisodes {
                    title
                    thumbnail
                    url
                    site
                }
            }
        }
    """

    response = requests.post(
        "https://graphql.anilist.co",
        json={"query": query, "variables": {"search": anime}},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=12.0,
    )
    response.raise_for_status()

    payload = response.json()
    media = ((payload.get("data") or {}).get("Media"))
    if not isinstance(media, dict):
        return []

    title_data = media.get("title") or {}
    canonical_title = (
        title_data.get("english")
        or title_data.get("romaji")
        or title_data.get("native")
        or anime
    )

    links: list[dict] = []
    for item in media.get("streamingEpisodes") or []:
        if not isinstance(item, dict):
            continue

        url = str(item.get("url") or "").strip()
        provider = _provider_for_url(url)
        if not url or not provider:
            continue

        title = str(item.get("title") or "").strip()
        if episode is not None:
            match = re.search(r"(?:episode|ep\.?|#)\s*(\d+)", title, re.I)
            if match and int(match.group(1)) != episode:
                continue

        links.append({
            "anime": canonical_title,
            "episode": episode,
            "title": title,
            "provider": provider,
            "url": url,
            "thumbnail": item.get("thumbnail"),
            "source": "anilist",
            "official_domain": True,
        })

        if len(links) >= limit:
            break

    return links


def _web_links(anime: str, episode: int | None, limit: int) -> list[dict]:
    episode_text = f" episode {episode}" if episode is not None else ""
    query = f'"{anime}"{episode_text} watch anime official streaming'

    results = web_search(query, max_results=max(8, min(20, limit * 2)))
    links: list[dict] = []

    for result in results:
        url = str(result.get("url") or "").strip()
        provider = _provider_for_url(url)
        if not provider:
            continue

        title = str(result.get("title") or "").strip()
        snippet = str(result.get("snippet") or "").strip()

        links.append({
            "anime": anime,
            "episode": episode,
            "title": title,
            "provider": provider,
            "url": url,
            "snippet": snippet[:400],
            "source": "web_search",
            "official_domain": True,
        })

        if len(links) >= limit:
            break

    return links


def anime_streaming_links(argument: str = "") -> dict:
    """Find official streaming watch pages for an anime.

    Accepts:
      - "Frieren"
      - "Frieren episode 12"
      - JSON: {"anime":"Frieren","episode":12,"limit":10}
    """
    try:
        anime, episode, limit = _parse_argument(argument)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), retryable=False)

    combined: list[dict] = []
    errors: list[str] = []

    try:
        combined.extend(_anilist_links(anime, episode, limit))
    except Exception as exc:
        errors.append(f"AniList: {exc}")

    try:
        combined.extend(_web_links(anime, episode, limit))
    except Exception as exc:
        errors.append(f"web search: {exc}")

    deduped: list[dict] = []
    seen: set[str] = set()

    for item in combined:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    providers = []
    seen_providers = set()
    for item in deduped:
        provider = item.get("provider")
        if provider and provider not in seen_providers:
            seen_providers.add(provider)
            providers.append(provider)

    if not deduped:
        if errors:
            return _error(
                "No official streaming pages found. " + " | ".join(errors[:2]),
            )
        return _error(
            f"No official streaming pages found for '{anime}'.",
            retryable=False,
        )

    return _success(
        {
            "anime": anime,
            "episode": episode,
            "providers": providers,
            "links": deduped,
            "count": len(deduped),
            "official_only": True,
        },
        f"Found {len(deduped)} official streaming page(s) for {anime}.",
    )


def anime_availability(argument: str = "") -> dict:
    """Return an anime's known official watch providers/pages.

    This is an availability/discovery layer, not a media extractor. It may
    include public JustWatch discovery pages plus known official provider
    landing pages returned by AniList/web search.
    """
    try:
        anime, episode, limit = _parse_argument(argument)
    except (TypeError, ValueError) as exc:
        return {
            "success": False,
            "tool": "anime_availability",
            "error": str(exc),
            "retryable": False,
        }

    combined: list[dict] = []
    errors: list[str] = []

    try:
        # AniList gives the strongest structured signal when streaming
        # metadata is available.
        anilist = _anilist_links(anime, episode, min(limit, 10))
        combined.extend(anilist)
    except Exception as exc:
        errors.append(f"AniList: {exc}")

    try:
        justwatch_results = web_search(
            f'site:justwatch.com "{anime}" anime where to watch',
            max_results=max(6, min(12, limit + 3)),
        )
        for result in justwatch_results:
            url = str(result.get("url") or "").strip()
            if "justwatch.com" not in url.lower():
                continue
            combined.append({
                "anime": anime,
                "episode": episode,
                "title": str(result.get("title") or "").strip(),
                "provider": "JustWatch",
                "url": url,
                "snippet": str(result.get("snippet") or "").strip()[:400],
                "source": "justwatch_search",
                "official_domain": False,
                "availability_page": True,
            })
    except Exception as exc:
        errors.append(f"JustWatch search: {exc}")

    try:
        official = _web_links(anime, episode, limit)
        combined.extend(official)
    except Exception as exc:
        errors.append(f"web search: {exc}")

    deduped: list[dict] = []
    seen: set[str] = set()

    for item in combined:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    providers: list[str] = []
    seen_providers: set[str] = set()
    for item in deduped:
        provider = str(item.get("provider") or "").strip()
        if provider and provider not in seen_providers:
            seen_providers.add(provider)
            providers.append(provider)

    if not deduped:
        detail = "No availability pages or official watch links found."
        if errors:
            detail += " " + " | ".join(errors[:2])
        return {
            "success": False,
            "tool": "anime_availability",
            "error": detail,
            "retryable": bool(errors),
        }

    return {
        "success": True,
        "tool": "anime_availability",
        "data": {
            "anime": anime,
            "episode": episode,
            "providers": providers,
            "results": deduped,
            "count": len(deduped),
            "official_only_for_watch_links": True,
        },
        "message": f"Found {len(deduped)} anime availability/watch page result(s) for {anime}.",
    }


def anime_provider_catalog(argument: str = "") -> dict:
    """Return the official streaming providers JARVIS can discover."""
    query = str(argument or "").strip().lower()
    providers = [
        {
            "provider": provider,
            "domain": domain,
            "watch_page_discovery": True,
        }
        for domain, provider in OFFICIAL_STREAMING_DOMAINS.items()
        if not query or query in provider.lower() or query in domain.lower()
    ]

    return {
        "success": True,
        "tool": "anime_provider_catalog",
        "data": {
            "providers": providers,
            "count": len(providers),
        },
        "message": f"JARVIS knows {len(providers)} official anime-capable streaming provider domain(s).",
    }


def _free_provider_for_url(url: str) -> dict | None:
    try:
        host = urlparse(url).netloc
    except ValueError:
        return None

    for domain, info in FREE_STREAMING_DOMAINS.items():
        if _domain_match(host, domain):
            return {
                "domain": domain,
                **info,
            }
    return None


def _free_evidence(item: dict) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "snippet", "url")
    ).lower()

    return any(
        marker in text
        for marker in (
            "watch free",
            "free to watch",
            "free streaming",
            "stream free",
            "free anime",
            "no subscription",
            "without subscription",
            "free with ads",
        )
    )


def _free_search(anime: str, episode: int | None, limit: int) -> list[dict]:
    episode_text = f" episode {episode}" if episode is not None else ""
    combined: list[dict] = []

    queries = (
        f'site:tubitv.com "{anime}"{episode_text} watch free',
        f'site:pluto.tv "{anime}"{episode_text} watch free',
        f'site:retrocrush.tv "{anime}"{episode_text} free',
        f'site:crunchyroll.com "{anime}" Crunchyroll Channel free',
    )

    for query in queries:
        try:
            results = web_search(query, max_results=8)
        except Exception:
            continue

        for result in results:
            url = str(result.get("url") or "").strip()
            provider = _free_provider_for_url(url)
            if not provider:
                continue

            item = {
                "anime": anime,
                "episode": episode,
                "title": str(result.get("title") or "").strip(),
                "provider": provider["provider"],
                "access": provider["access"],
                "region_note": provider["region_note"],
                "url": url,
                "snippet": str(result.get("snippet") or "").strip()[:500],
                "source": "web_search",
                "free_evidence": _free_evidence(result),
            }

            # Never label a result "free" merely because it belongs to a
            # provider with some free catalog. Require result-level evidence.
            if item["free_evidence"]:
                combined.append(item)

            if len(combined) >= limit:
                return combined

    return combined


def anime_free_watch(argument: str = "") -> dict:
    """Find currently discoverable free/ad-supported official anime watch pages.

    Inspired by anipy-cli's provider-selection model, but intentionally limited
    to watch/availability pages rather than direct media manifests.
    """
    try:
        anime, episode, limit = _parse_argument(argument)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), retryable=False, tool="anime_free_watch")

    candidates = _free_search(anime, episode, limit)

    # Deduplicate while preserving provider diversity and result order.
    results: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(item)
        if len(results) >= limit:
            break

    providers: list[str] = []
    seen_providers: set[str] = set()
    for item in results:
        provider = item.get("provider")
        if provider and provider not in seen_providers:
            seen_providers.add(provider)
            providers.append(provider)

    if not results:
        return _error(
            f"No currently discoverable free/ad-supported official watch page was found for '{anime}'.",
            retryable=False,
            tool="anime_free_watch",
        )

    return {
        "success": True,
        "tool": "anime_free_watch",
        "data": {
            "anime": anime,
            "episode": episode,
            "providers": providers,
            "results": results,
            "count": len(results),
            "free_only": True,
            "direct_media_extraction": False,
        },
        "message": f"Found {len(results)} free/ad-supported official watch option(s) for {anime}.",
    }
