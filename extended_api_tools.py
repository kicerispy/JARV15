"""Extended low-friction public APIs for JARVIS.

All providers in this module are read-only and require no personal API key at
runtime, except where the provider itself documents a public development key.
The module intentionally returns small normalized payloads so tools.py can wrap
them in JARVIS's ToolResult contract.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from typing import Any

import requests

USER_AGENT = "JARVIS/1.0 (local personal assistant)"

API_TOOLS = {
    "country_info",
    "crypto_price",
    "trivia_question",
    "joke",
    "meal_search",
    "tv_search",
    "music_search",
    "musicbrainz_search",
    "anime_search",
    "anime_episodes",
    "ghibli_search",
    "openalex_search",
    "pubchem_lookup",
    "art_search",
    "nasa_eonet",
    "spacex_lookup",
    "sunrise_sunset",
    "topo_elevation",
    "public_ip",
    "reverse_geocode",
    "news_search",
    "cat_fact",
    "dog_image",
    "osm_search",
    "pokemon_lookup",
    "food_product",
    "cocktail_search",
    "openverse_search",
    "iss_location",
}


def _get_json(url: str, *, params: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None,
              timeout: float = 12.0) -> Any:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    response = requests.get(
        url,
        params=params,
        headers=request_headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _success(tool: str, data: Any, message: str) -> dict[str, Any]:
    return {
        "success": True,
        "tool": tool,
        "data": data,
        "message": message,
    }


def _error(tool: str, message: str, *, retryable: bool = True) -> dict[str, Any]:
    lowered = str(message).lower()
    transient = retryable and any(
        marker in lowered
        for marker in (
            "timeout", "timed out", "connection", "502", "503", "504",
            "429", "temporarily unavailable", "name resolution",
        )
    )
    return {
        "success": False,
        "tool": tool,
        "error": message,
        "message": message,
        "retryable": transient,
    }


def _clean(value: Any, limit: int = 400) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."
    return text


def _parse_lat_lon(value: str) -> tuple[float, float] | None:
    raw = str(value or "").strip()
    parts = raw.split(",", 1) if "," in raw else raw.split()
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _geocode(query: str) -> dict[str, Any]:
    coords = _parse_lat_lon(query)
    if coords:
        lat, lon = coords
        return {
            "name": "Requested coordinates",
            "latitude": lat,
            "longitude": lon,
            "country": None,
            "admin1": None,
        }

    data = _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": query,
            "count": 1,
            "language": "en",
            "format": "json",
        },
    )
    results = data.get("results") or []
    if not results:
        raise ValueError(f"No location found for '{query}'.")
    top = results[0]
    return {
        "name": top.get("name"),
        "latitude": float(top["latitude"]),
        "longitude": float(top["longitude"]),
        "country": top.get("country"),
        "admin1": top.get("admin1"),
    }


# ---------------------------------------------------------------------------
# WORLD / LOCATION
# ---------------------------------------------------------------------------

_COUNTRY_ALIASES = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "canada": "CA",
    "mexico": "MX",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "australia": "AU",
    "new zealand": "NZ",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "japan": "JP",
    "china": "CN",
    "india": "IN",
    "brazil": "BR",
    "south korea": "KR",
}


def country_info(argument: str = "") -> dict[str, Any]:
    tool = "country_info"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a country name or two-letter country code.", retryable=False)

    code = _COUNTRY_ALIASES.get(query.lower(), query.upper() if len(query) == 2 else "")
    try:
        if code:
            url = f"https://api.worldbank.org/v2/country/{code}"
            params = {"format": "json", "per_page": 1}
        else:
            url = "https://api.worldbank.org/v2/country"
            params = {"format": "json", "per_page": 10, "search": query}

        payload = _get_json(url, params=params)
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        if not rows:
            return _error(tool, f"No country found for '{query}'.", retryable=False)

        row = rows[0]
        result = {
            "name": row.get("name"),
            "iso2Code": row.get("iso2Code"),
            "capital": row.get("capitalCity"),
            "region": (row.get("region") or {}).get("value"),
            "income_level": (row.get("incomeLevel") or {}).get("value"),
            "lending_type": (row.get("lendingType") or {}).get("value"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
        }
        return _success(tool, result, f"Country information found for {result['name'] or query}.")
    except Exception as exc:
        return _error(tool, f"Country lookup failed: {exc}")


# ---------------------------------------------------------------------------
# CRYPTO
# ---------------------------------------------------------------------------

_CRYPTO_ALIASES = {
    "btc": "btc-bitcoin",
    "bitcoin": "btc-bitcoin",
    "eth": "eth-ethereum",
    "ethereum": "eth-ethereum",
    "sol": "sol-solana",
    "solana": "sol-solana",
    "doge": "doge-dogecoin",
    "dogecoin": "doge-dogecoin",
    "xrp": "xrp-xrp",
    "ada": "ada-cardano",
    "cardano": "ada-cardano",
    "dot": "dot-polkadot",
    "polkadot": "dot-polkadot",
    "link": "link-chainlink",
    "chainlink": "link-chainlink",
}


def crypto_price(argument: str = "") -> dict[str, Any]:
    tool = "crypto_price"
    raw = str(argument or "").strip()
    if not raw:
        return _error(tool, "Provide a cryptocurrency such as Bitcoin or BTC.", retryable=False)

    parts = raw.split()
    symbol_query = parts[0].lower()
    coin_id = _CRYPTO_ALIASES.get(symbol_query)

    try:
        if not coin_id:
            search = _get_json(
                "https://api.coinpaprika.com/v1/search",
                params={"q": parts[0], "c": "currencies", "modifier": "symbol_search"},
            )
            currencies = search.get("currencies") or []
            if not currencies:
                search = _get_json(
                    "https://api.coinpaprika.com/v1/search",
                    params={"q": parts[0]},
                )
                currencies = search.get("currencies") or []
            if not currencies:
                return _error(tool, f"No cryptocurrency found for '{parts[0]}'.", retryable=False)
            coin_id = currencies[0].get("id")

        data = _get_json(
            f"https://api.coinpaprika.com/v1/tickers/{coin_id}",
            params={"quotes": "USD"},
        )
        usd = (data.get("quotes") or {}).get("USD") or {}
        item = {
            "id": data.get("id"),
            "name": data.get("name"),
            "symbol": data.get("symbol"),
            "price_usd": usd.get("price"),
            "percent_change_24h": usd.get("percent_change_24h"),
            "market_cap_usd": usd.get("market_cap"),
            "volume_24h_usd": usd.get("volume_24h"),
            "rank": data.get("rank"),
        }
        return _success(tool, {"results": [item]}, f"{item['name'] or raw} price data retrieved.")
    except Exception as exc:
        return _error(tool, f"Crypto lookup failed: {exc}")


# ---------------------------------------------------------------------------
# FUN / MEDIA
# ---------------------------------------------------------------------------

def trivia_question(argument: str = "") -> dict[str, Any]:
    tool = "trivia_question"
    try:
        payload = _get_json(
            "https://opentdb.com/api.php",
            params={"amount": 1, "type": "multiple"},
        )
        rows = payload.get("results") or []
        if not rows:
            return _error(tool, "Trivia service returned no questions.")
        q = rows[0]
        question = html.unescape(q.get("question", ""))
        correct = html.unescape(q.get("correct_answer", ""))
        choices = [html.unescape(x) for x in (q.get("incorrect_answers") or [])]
        choices.append(correct)
        item = {
            "question": question,
            "category": html.unescape(q.get("category", "")),
            "difficulty": q.get("difficulty"),
            "correct_answer": correct,
            "choices": choices,
        }
        return _success(tool, {"items": [item]}, "Trivia question retrieved.")
    except Exception as exc:
        return _error(tool, f"Trivia lookup failed: {exc}")


def joke(argument: str = "") -> dict[str, Any]:
    tool = "joke"
    try:
        payload = _get_json(
            "https://v2.jokeapi.dev/joke/Any",
            params={"type": "single", "safe-mode": ""},
        )
        text = payload.get("joke")
        if not text:
            return _error(tool, "Joke service returned no joke.", retryable=False)
        return _success(tool, {"items": [{"text": text}]}, "Joke retrieved.")
    except Exception as exc:
        return _error(tool, f"Joke lookup failed: {exc}")


def meal_search(argument: str = "") -> dict[str, Any]:
    tool = "meal_search"
    query = str(argument or "").strip()
    endpoint = (
        "https://www.themealdb.com/api/json/v1/1/random.php"
        if not query
        else "https://www.themealdb.com/api/json/v1/1/search.php"
    )
    try:
        payload = _get_json(endpoint, params={"s": query} if query else None)
        meals = payload.get("meals") or []
        items = []
        for meal in meals[:5]:
            ingredients = []
            for idx in range(1, 21):
                ing = _clean(meal.get(f"strIngredient{idx}"), 80)
                measure = _clean(meal.get(f"strMeasure{idx}"), 60)
                if ing:
                    ingredients.append(f"{measure} {ing}".strip())
            items.append({
                "id": meal.get("idMeal"),
                "name": meal.get("strMeal"),
                "category": meal.get("strCategory"),
                "area": meal.get("strArea"),
                "tags": meal.get("strTags"),
                "instructions": _clean(meal.get("strInstructions"), 500),
                "thumbnail": meal.get("strMealThumb"),
                "ingredients": ingredients[:12],
            })
        if not items:
            return _error(tool, f"No meals found for '{query}'.", retryable=False)
        return _success(tool, {"meals": items}, f"Found {len(items)} meal result(s).")
    except Exception as exc:
        return _error(tool, f"Meal lookup failed: {exc}")


def tv_search(argument: str = "") -> dict[str, Any]:
    tool = "tv_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a TV show name.", retryable=False)
    try:
        payload = _get_json(
            "https://api.tvmaze.com/search/shows",
            params={"q": query},
        )
        shows = []
        for row in payload[:5]:
            show = row.get("show") or {}
            shows.append({
                "name": show.get("name"),
                "type": show.get("type"),
                "language": show.get("language"),
                "genres": show.get("genres") or [],
                "premiered": show.get("premiered"),
                "status": show.get("status"),
                "rating": (show.get("rating") or {}).get("average"),
                "summary": _clean(re.sub(r"<[^>]+>", " ", show.get("summary") or ""), 500),
                "url": show.get("url"),
            })
        return _success(tool, {"shows": shows}, f"Found {len(shows)} TV result(s).")
    except Exception as exc:
        return _error(tool, f"TV search failed: {exc}")


def music_search(argument: str = "") -> dict[str, Any]:
    tool = "music_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a song, artist, or album.", retryable=False)
    try:
        payload = _get_json(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "song", "limit": 5},
        )
        tracks = []
        for item in payload.get("results") or []:
            tracks.append({
                "title": item.get("trackName"),
                "artist": item.get("artistName"),
                "album": item.get("collectionName"),
                "release_date": item.get("releaseDate"),
                "genre": item.get("primaryGenreName"),
                "url": item.get("trackViewUrl"),
                "artwork": item.get("artworkUrl100"),
            })
        return _success(tool, {"tracks": tracks}, f"Found {len(tracks)} music result(s).")
    except Exception as exc:
        return _error(tool, f"Music search failed: {exc}")


_musicbrainz_lock = threading.Lock()
_musicbrainz_last_call = 0.0


def musicbrainz_search(argument: str = "") -> dict[str, Any]:
    tool = "musicbrainz_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a song, recording, or artist.", retryable=False)

    global _musicbrainz_last_call
    with _musicbrainz_lock:
        delay = 1.05 - (time.monotonic() - _musicbrainz_last_call)
        if delay > 0:
            time.sleep(delay)
        _musicbrainz_last_call = time.monotonic()

    try:
        payload = _get_json(
            "https://musicbrainz.org/ws/2/recording/",
            params={"query": query, "fmt": "json", "limit": 5},
            headers={
                "User-Agent": USER_AGENT,
            },
        )
        recordings = []
        for item in payload.get("recordings") or []:
            artists = []
            for credit in item.get("artist-credit") or []:
                artist = credit.get("artist") or {}
                if artist.get("name"):
                    artists.append(artist["name"])
            releases = []
            for release in (item.get("releases") or [])[:3]:
                if release.get("title"):
                    releases.append(release["title"])
            recordings.append({
                "title": item.get("title"),
                "artists": artists,
                "releases": releases,
                "score": item.get("score"),
                "id": item.get("id"),
                "url": f"https://musicbrainz.org/recording/{item.get('id')}" if item.get("id") else None,
            })
        return _success(tool, {"recordings": recordings}, f"Found {len(recordings)} MusicBrainz result(s).")
    except Exception as exc:
        return _error(tool, f"MusicBrainz search failed: {exc}")


def anime_search(argument: str = "") -> dict[str, Any]:
    tool = "anime_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide an anime title.", retryable=False)
    try:
        payload = _get_json(
            "https://api.jikan.moe/v4/anime",
            params={"q": query, "limit": 5, "sfw": "true"},
        )
        rows = payload.get("data") or []
    except Exception:
        # Jikan can transiently gateway-timeout. AniList exposes a public
        # GraphQL API and provides an independent no-key fallback.
        try:
            graphql = {
                "query": """
                    query ($search: String) {
                      Page(perPage: 5) {
                        media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
                          id
                          title { romaji english native }
                          type
                          episodes
                          status
                          averageScore
                          startDate { year }
                          description(asHtml: false)
                          siteUrl
                        }
                      }
                    }
                """,
                "variables": {"search": query},
            }
            response = requests.post(
                "https://graphql.anilist.co",
                json=graphql,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            rows = ((payload.get("data") or {}).get("Page") or {}).get("media") or []
        except Exception as exc:
            return _error(tool, f"Anime search failed on both Jikan and AniList: {exc}")

    anime = []
    for item in rows:
        raw_title = item.get("title") or {}
        title_data = raw_title if isinstance(raw_title, dict) else {}
        title_text = (
            title_data.get("english")
            or title_data.get("romaji")
            or title_data.get("native")
            or (raw_title if isinstance(raw_title, str) else "")
        )
        anime.append({
            "title": title_text,
            "title_english": title_data.get("english") or (item.get("title_english") if isinstance(item.get("title_english"), str) else None),
            "type": item.get("type"),
            "episodes": item.get("episodes"),
            "status": item.get("status"),
            "score": item.get("score") if item.get("score") is not None else item.get("averageScore"),
            "year": item.get("year") if item.get("year") is not None else ((item.get("startDate") or {}).get("year")),
            "synopsis": _clean(item.get("synopsis") or item.get("description"), 500),
            "url": item.get("url") or item.get("siteUrl"),
        })
    return _success(tool, {"anime": anime}, f"Found {len(anime)} anime result(s).")


def anime_episodes(argument: str = "") -> dict[str, Any]:
    """Return anime episodes, preferring AniAPI and falling back to Jikan."""
    tool = "anime_episodes"
    raw = str(argument or "").strip()
    if not raw:
        return _error(tool, "Provide an anime title.", retryable=False)

    query = raw
    page = 1
    per_page = 100

    try:
        options = json.loads(raw)
        if isinstance(options, dict):
            query = str(
                options.get("anime")
                or options.get("title")
                or options.get("query")
                or ""
            ).strip()
            page = max(1, int(options.get("page", 1)))
            per_page = min(100, max(1, int(options.get("per_page", 100))))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    if not query:
        return _error(tool, "Provide an anime title.", retryable=False)

    normalized_query = re.sub(r"\s+", " ", query).strip().lower()

    def candidates(row: dict[str, Any]) -> list[str]:
        values: list[str] = []
        titles = row.get("titles") or {}
        if isinstance(titles, dict):
            values.extend(str(v).strip() for v in titles.values() if v)
        for key in ("title", "title_english", "title_romaji", "title_native"):
            if row.get(key):
                values.append(str(row[key]).strip())
        return [value for value in values if value]

    def choose(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        for row in rows:
            normalized = {
                re.sub(r"\s+", " ", value).strip().lower()
                for value in candidates(row)
            }
            if normalized_query in normalized:
                return row
        return rows[0]

    try:
        response = requests.get(
            "https://api.aniapi.com/v1/anime",
            params={
                "title": query,
                "locale": "en",
                "nsfw": "false",
                "page": 1,
                "per_page": 5,
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        anime_data = payload.get("data") if isinstance(payload, dict) else None
        rows = (
            anime_data.get("documents")
            if isinstance(anime_data, dict)
            else []
        ) or []
        selected = choose(rows)
        anime_id = selected.get("id") if isinstance(selected, dict) else None

        if anime_id:
            episode_response = requests.get(
                "https://api.aniapi.com/v1/episode",
                params={
                    "anime_id": anime_id,
                    "locale": "en",
                    "page": page,
                    "per_page": per_page,
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=12.0,
            )
            episode_response.raise_for_status()
            episode_payload = episode_response.json()
            episode_data = (
                episode_payload.get("data")
                if isinstance(episode_payload, dict)
                else None
            )
            documents = (
                episode_data.get("documents")
                if isinstance(episode_data, dict)
                else []
            ) or []

            if documents:
                titles = selected.get("titles") if isinstance(selected.get("titles"), dict) else {}
                title = (
                    titles.get("en")
                    or selected.get("title")
                    or query
                )
                episodes = []
                for item in documents:
                    episodes.append({
                        "number": item.get("number"),
                        "title": item.get("title"),
                        "aired": item.get("aired") or item.get("release_date"),
                        "locale": item.get("locale"),
                        "quality": item.get("quality"),
                        "format": item.get("format"),
                        "is_dub": item.get("is_dub"),
                        "id": item.get("id"),
                    })
                return _success(
                    tool,
                    {
                        "anime": {
                            "id": anime_id,
                            "title": title,
                            "anilist_id": selected.get("anilist_id"),
                            "mal_id": selected.get("mal_id"),
                        },
                        "source": "aniapi",
                        "page": page,
                        "per_page": per_page,
                        "total_episodes": episode_data.get("count"),
                        "last_page": episode_data.get("last_page"),
                        "episodes": episodes,
                    },
                    "Found episode data for " + str(title) + ".",
                )
    except Exception:
        pass

    # Kitsu is a second live no-key fallback. Its public JSON:API exposes
    # anime episodes as a first-class relationship and is independent of Jikan.
    try:
        kitsu_response = requests.get(
            "https://kitsu.io/api/edge/anime",
            params={
                "filter[text]": query,
                "page[limit]": 5,
                "page[offset]": 0,
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.api+json",
            },
            timeout=12.0,
        )
        kitsu_response.raise_for_status()
        kitsu_payload = kitsu_response.json()
        kitsu_rows = kitsu_payload.get("data") or []
        selected = None
        for row in kitsu_rows:
            attrs = row.get("attributes") or {}
            title_values = [
                attrs.get("canonicalTitle"),
                attrs.get("slug"),
            ]
            localized_titles = attrs.get("titles")
            if isinstance(localized_titles, dict):
                title_values.extend(localized_titles.values())
            normalized_titles = {
                re.sub(r"\\s+", " ", str(value)).strip().lower()
                for value in title_values
                if value
            }
            if normalized_query in normalized_titles:
                selected = row
                break
        if selected is None and kitsu_rows:
            selected = kitsu_rows[0]

        kitsu_id = selected.get("id") if isinstance(selected, dict) else None
        if kitsu_id:
            offset = (page - 1) * per_page
            episode_kitsu_response = requests.get(
                "https://kitsu.io/api/edge/anime/" + str(kitsu_id) + "/episodes",
                params={
                    "page[limit]": per_page,
                    "page[offset]": offset,
                    "sort": "number",
                },
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.api+json",
                },
                timeout=12.0,
            )
            episode_kitsu_response.raise_for_status()
            episode_payload = episode_kitsu_response.json()
            episode_rows = episode_payload.get("data") or []
            episodes = []
            for item in episode_rows:
                attrs = item.get("attributes") or {}
                episodes.append({
                    "number": attrs.get("number") or attrs.get("episodeNumber"),
                    "title": attrs.get("canonicalTitle") or attrs.get("title"),
                    "aired": attrs.get("airdate") or attrs.get("airDate"),
                    "synopsis": _clean(attrs.get("synopsis"), 400),
                    "length": attrs.get("length"),
                    "thumbnail": attrs.get("thumbnail"),
                    "kitsu_id": item.get("id"),
                })

            if episodes:
                anime_attrs = selected.get("attributes") or {}
                total = None
                meta = episode_payload.get("meta") or {}
                if isinstance(meta, dict):
                    total = (meta.get("count") or meta.get("total"))
                if total is None:
                    total = anime_attrs.get("episodeCount")
                last_page = None
                if total is not None and per_page:
                    try:
                        last_page = (int(total) + per_page - 1) // per_page
                    except (TypeError, ValueError):
                        last_page = None

                title = (
                    anime_attrs.get("canonicalTitle")
                    or query
                )
                return _success(
                    tool,
                    {
                        "anime": {
                            "id": kitsu_id,
                            "title": title,
                            "kitsu_id": kitsu_id,
                        },
                        "source": "kitsu",
                        "page": page,
                        "per_page": len(episodes),
                        "total_episodes": total,
                        "last_page": last_page,
                        "episodes": episodes,
                    },
                    "Found " + str(len(episodes)) + " episode(s) for " + str(title) + ".",
                )
    except Exception:
        pass

    # Jikan is the live no-key fallback and exposes paginated episode lists.
    try:
        search_response = requests.get(
            "https://api.jikan.moe/v4/anime",
            params={"q": query, "limit": 5, "sfw": "true"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=12.0,
        )
        search_response.raise_for_status()
        search_payload = search_response.json()
        search_rows = search_payload.get("data") or []
        if not search_rows:
            return _error(tool, "No anime found for '" + query + "'.", retryable=False)

        selected = search_rows[0]
        mal_id = selected.get("mal_id")
        if not mal_id:
            return _error(tool, "No usable anime identifier found for '" + query + "'.", retryable=False)

        episode_response = requests.get(
            "https://api.jikan.moe/v4/anime/" + str(mal_id) + "/episodes",
            params={"page": page},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=12.0,
        )
        episode_response.raise_for_status()
        episode_payload = episode_response.json()

        episodes = []
        for item in episode_payload.get("data") or []:
            episodes.append({
                "number": item.get("mal_id"),
                "title": item.get("title"),
                "aired": item.get("aired"),
                "score": item.get("score"),
                "filler": item.get("filler"),
                "recap": item.get("recap"),
                "url": item.get("url"),
            })

        pagination = episode_payload.get("pagination") or {}
        title_data = selected.get("title")
        title = query
        if isinstance(title_data, dict):
            title = (
                title_data.get("english")
                or title_data.get("romaji")
                or title_data.get("native")
                or query
            )
        elif title_data:
            title = str(title_data)

        return _success(
            tool,
            {
                "anime": {
                    "id": mal_id,
                    "title": title,
                    "mal_id": mal_id,
                },
                "source": "jikan",
                "page": page,
                "per_page": len(episodes),
                "total_episodes": (pagination.get("items") or {}).get("total"),
                "last_page": pagination.get("last_visible_page"),
                "episodes": episodes,
            },
            "Found " + str(len(episodes)) + " episode(s) for " + str(title) + ".",
        )
    except Exception as exc:
        return _error(
            tool,
            "Anime episode lookup failed on AniAPI and Jikan: " + str(exc),
        )



_ghibli_cache: list[dict[str, Any]] | None = None
_ghibli_cache_time = 0.0


def ghibli_search(argument: str = "") -> dict[str, Any]:
    tool = "ghibli_search"
    query = str(argument or "").strip().lower()
    global _ghibli_cache, _ghibli_cache_time
    try:
        if _ghibli_cache is None or time.monotonic() - _ghibli_cache_time > 3600:
            _ghibli_cache = _get_json("https://ghibliapi.vercel.app/films")
            _ghibli_cache_time = time.monotonic()
        rows = _ghibli_cache or []
        if query:
            rows = [
                row for row in rows
                if query in " ".join(
                    str(row.get(k) or "")
                    for k in ("title", "original_title", "description", "director")
                ).lower()
            ]
        films = []
        for row in rows[:8]:
            films.append({
                "title": row.get("title"),
                "original_title": row.get("original_title"),
                "director": row.get("director"),
                "producer": row.get("producer"),
                "release_date": row.get("release_date"),
                "rt_score": row.get("rt_score"),
                "description": _clean(row.get("description"), 600),
                "url": row.get("movie_banner") or row.get("image"),
            })
        return _success(tool, {"films": films}, f"Found {len(films)} Studio Ghibli film result(s).")
    except Exception as exc:
        return _error(tool, f"Ghibli lookup failed: {exc}")


# ---------------------------------------------------------------------------
# SCIENCE / RESEARCH
# ---------------------------------------------------------------------------

def openalex_search(argument: str = "") -> dict[str, Any]:
    tool = "openalex_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a research topic.", retryable=False)
    try:
        payload = _get_json(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per-page": 5,
                "select": "id,display_name,publication_year,cited_by_count,doi,authorships,primary_location",
            },
        )
        works = []
        for item in payload.get("results") or []:
            authors = []
            for auth in (item.get("authorships") or [])[:4]:
                author = auth.get("author") or {}
                if author.get("display_name"):
                    authors.append(author["display_name"])
            location = item.get("primary_location") or {}
            works.append({
                "title": item.get("display_name"),
                "authors": authors,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count"),
                "doi": item.get("doi"),
                "url": location.get("landing_page_url") or item.get("doi") or item.get("id"),
            })
        return _success(tool, {"works": works}, f"Found {len(works)} OpenAlex research result(s).")
    except Exception as exc:
        return _error(tool, f"OpenAlex search failed: {exc}")


def pubchem_lookup(argument: str = "") -> dict[str, Any]:
    tool = "pubchem_lookup"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a chemical name or compound.", retryable=False)

    def pubchem_get(url: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=12.0,
                )
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else None
                if status not in {429, 500, 502, 503, 504} or attempt >= 3:
                    raise
                retry_after = 0.0
                if exc.response is not None:
                    try:
                        retry_after = float(
                            exc.response.headers.get("Retry-After", "0") or 0
                        )
                    except (TypeError, ValueError):
                        retry_after = 0.0
                time.sleep(max(retry_after, 1.25 * (2 ** attempt)))
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= 3:
                    raise
                time.sleep(0.75 * (2 ** attempt))
        raise last_exc or RuntimeError("PubChem request failed.")

    try:
        encoded = requests.utils.quote(query, safe="")
        property_path = (
            "property/MolecularFormula,MolecularWeight,IUPACName/JSON"
        )

        try:
            payload = pubchem_get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                + encoded
                + "/"
                + property_path
            )
            props = (
                (payload.get("PropertyTable") or {}).get("Properties")
                or []
            )
        except Exception:
            props = []

        if not props:
            cid_payload = pubchem_get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                + encoded
                + "/cids/JSON"
            )
            cids = (
                (cid_payload.get("IdentifierList") or {}).get("CID")
                or []
            )
            if not cids:
                return _error(
                    tool,
                    "No compound found for '" + query + "'.",
                    retryable=False,
                )

            cid = cids[0]
            payload = pubchem_get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                + str(cid)
                + "/"
                + property_path
            )
            props = (
                (payload.get("PropertyTable") or {}).get("Properties")
                or []
            )

        if not props:
            return _error(
                tool,
                "No compound found for '" + query + "'.",
                retryable=False,
            )

        item = props[0]
        result = {
            "cid": item.get("CID"),
            "name": query,
            "molecular_formula": item.get("MolecularFormula"),
            "molecular_weight": item.get("MolecularWeight"),
            "iupac_name": item.get("IUPACName"),
            "url": (
                "https://pubchem.ncbi.nlm.nih.gov/compound/"
                + str(item.get("CID"))
                if item.get("CID")
                else None
            ),
        }
        return _success(
            tool,
            {"results": [result]},
            "PubChem data retrieved for " + query + ".",
        )
    except Exception as exc:
        # Final fallback: NCI/CADD CACTUS is a separate public resolver and
        # can provide the core chemical properties when PubChem is temporarily busy.
        try:
            encoded = requests.utils.quote(query, safe="")

            def cactus_get(representation: str) -> str:
                response = requests.get(
                    "https://cactus.nci.nih.gov/chemical/structure/"
                    + encoded
                    + "/"
                    + representation,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/plain",
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.text.strip()

            formula = None
            molecular_weight = None
            iupac_name = None
            for representation, target in (
                ("formula", "formula"),
                ("mw", "weight"),
                ("iupac_name", "iupac"),
            ):
                try:
                    value = cactus_get(representation)
                except Exception:
                    value = ""
                if not value:
                    continue
                if target == "formula":
                    formula = value
                elif target == "weight":
                    molecular_weight = value
                else:
                    iupac_name = value

            if formula or molecular_weight or iupac_name:
                result = {
                    "cid": None,
                    "name": query,
                    "molecular_formula": formula,
                    "molecular_weight": molecular_weight,
                    "iupac_name": iupac_name,
                    "url": (
                        "https://cactus.nci.nih.gov/chemical/structure/"
                        + encoded
                        + "/formula"
                    ),
                }
                return _success(
                    tool,
                    {"results": [result]},
                    "Chemical data retrieved for " + query + " via NCI CACTUS.",
                )
        except Exception:
            pass

        return _error(tool, "PubChem lookup failed: " + str(exc))


def art_search(argument: str = "") -> dict[str, Any]:
    tool = "art_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide an artist, title, or art subject.", retryable=False)
    try:
        payload = _get_json(
            "https://api.artic.edu/api/v1/artworks/search",
            params={
                "q": query,
                "limit": 5,
                "fields": "id,title,artist_display,date_display,image_id,thumbnail",
            },
            headers={"AIC-User-Agent": "JARVIS/1.0"},
        )
        artworks = []
        for item in payload.get("data") or []:
            image_id = item.get("image_id")
            artworks.append({
                "title": item.get("title"),
                "artist": item.get("artist_display"),
                "date": item.get("date_display"),
                "image_id": image_id,
                "description": _clean((item.get("thumbnail") or {}).get("alt_text"), 350),
                "url": (
                    f"https://www.artic.edu/artworks/{item.get('id')}"
                    if item.get("id")
                    else None
                ),
                "image": (
                    f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
                    if image_id
                    else None
                ),
            })
        return _success(tool, {"artworks": artworks}, f"Found {len(artworks)} Art Institute result(s).")
    except Exception as exc:
        return _error(tool, f"Art search failed: {exc}")


def nasa_eonet(argument: str = "") -> dict[str, Any]:
    tool = "nasa_eonet"
    category_aliases = {
        "wildfire": "wildfires",
        "wildfires": "wildfires",
        "fire": "wildfires",
        "fires": "wildfires",
        "storm": "severeStorms",
        "storms": "severeStorms",
        "severe storm": "severeStorms",
        "volcano": "volcanoes",
        "volcanoes": "volcanoes",
        "earthquake": "earthquakes",
        "earthquakes": "earthquakes",
        "flood": "floods",
        "floods": "floods",
        "landslide": "landslides",
        "landslides": "landslides",
    }
    query = str(argument or "").strip()
    params = {"status": "open", "limit": 10}
    if query.lower() in category_aliases:
        params["category"] = category_aliases[query.lower()]
    try:
        payload = _get_json(
            "https://eonet.gsfc.nasa.gov/api/v3/events",
            params=params,
        )
        events = []
        for item in payload.get("events") or []:
            categories = [str(c.get("title") or c.get("id") or "") for c in (item.get("categories") or [])]
            geometries = item.get("geometry") or []
            latest = geometries[-1] if geometries else {}
            coords = latest.get("coordinates")
            events.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "description": item.get("description"),
                "categories": categories,
                "date": latest.get("date"),
                "coordinates": coords,
                "url": item.get("link"),
            })
        return _success(tool, {"events": events}, f"Found {len(events)} open NASA natural-event(s).")
    except Exception as exc:
        return _error(tool, f"NASA EONET lookup failed: {exc}")


def spacex_lookup(argument: str = "") -> dict[str, Any]:
    tool = "spacex_lookup"
    mode = str(argument or "").strip().lower()
    limit = 1 if mode in {"", "latest", "last"} else 8
    try:
        payload = _get_json(
            "https://ll.thespacedevs.com/2.3.0/launches/previous/",
            params={
                "limit": limit,
                "search": "SpaceX",
                "ordering": "-net",
            },
        )
        rows = payload.get("results") or []
        launches = []
        for item in rows:
            status = item.get("status") or {}
            mission = item.get("mission") or {}
            pad = item.get("pad") or {}
            launches.append({
                "name": item.get("name"),
                "date_utc": item.get("net"),
                "status": status.get("name") if isinstance(status, dict) else status,
                "success": (status.get("id") == 3) if isinstance(status, dict) else None,
                "details": _clean(mission.get("description") if isinstance(mission, dict) else "", 500),
                "location": (pad.get("location") or {}).get("name") if isinstance(pad, dict) and isinstance(pad.get("location"), dict) else None,
                "image": item.get("image"),
                "url": item.get("webcast_live"),
            })
        return _success(
            tool,
            {"launches": launches, "source_status": "launch_library_2"},
            f"Retrieved {len(launches)} SpaceX launch record(s).",
        )
    except Exception as exc:
        return _error(tool, f"SpaceX launch lookup failed: {exc}")


# ---------------------------------------------------------------------------
# GEO / ENVIRONMENT
# ---------------------------------------------------------------------------

def sunrise_sunset(argument: str = "") -> dict[str, Any]:
    tool = "sunrise_sunset"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a city or coordinates.", retryable=False)
    try:
        location = _geocode(query)
        payload = _get_json(
            "https://api.sunrise-sunset.org/json",
            params={
                "lat": location["latitude"],
                "lng": location["longitude"],
                "formatted": 0,
            },
        )
        result = {
            "location": location,
            "sunrise": (payload.get("results") or {}).get("sunrise"),
            "sunset": (payload.get("results") or {}).get("sunset"),
            "solar_noon": (payload.get("results") or {}).get("solar_noon"),
            "day_length_seconds": (payload.get("results") or {}).get("day_length"),
            "civil_twilight_begin": (payload.get("results") or {}).get("civil_twilight_begin"),
            "civil_twilight_end": (payload.get("results") or {}).get("civil_twilight_end"),
        }
        return _success(tool, result, f"Sunrise and sunset data retrieved for {location['name']}.")
    except Exception as exc:
        return _error(tool, f"Sunrise/sunset lookup failed: {exc}")


def topo_elevation(argument: str = "") -> dict[str, Any]:
    tool = "topo_elevation"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a place or coordinates.", retryable=False)
    try:
        location = _geocode(query)
        locations = f"{location['latitude']},{location['longitude']}"
        datasets = ("aster30m", "srtm90m")
        last_error = None
        for dataset in datasets:
            try:
                payload = _get_json(
                    f"https://api.opentopodata.org/v1/{dataset}",
                    params={"locations": locations},
                )
                rows = payload.get("results") or []
                if rows:
                    result = {
                        "location": location,
                        "elevation_meters": rows[0].get("elevation"),
                        "dataset": dataset,
                    }
                    if result["elevation_meters"] is not None:
                        result["elevation_feet"] = round(
                            float(result["elevation_meters"]) * 3.280839895, 2
                        )
                    return _success(tool, result, f"Topographic elevation retrieved for {location['name']}.")
            except Exception as exc:
                last_error = exc
        raise RuntimeError(last_error or "No topographic dataset returned a result.")
    except Exception as exc:
        return _error(tool, f"Topographic elevation lookup failed: {exc}")


def public_ip(argument: str = "") -> dict[str, Any]:
    tool = "public_ip"
    try:
        payload = _get_json("https://api.ipify.org", params={"format": "json"})
        ip = payload.get("ip")
        if not ip:
            return _error(tool, "Public IP service returned no address.")
        return _success(tool, {"ip": ip}, f"Public IP address is {ip}.")
    except Exception as exc:
        return _error(tool, f"Public IP lookup failed: {exc}")


def reverse_geocode(argument: str = "") -> dict[str, Any]:
    tool = "reverse_geocode"
    query = str(argument or "").strip()
    coords = _parse_lat_lon(query)
    if not coords:
        return _error(tool, "Provide coordinates as latitude,longitude.", retryable=False)
    lat, lon = coords
    try:
        payload = _get_json(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat,
                "lon": lon,
                "zoom": 18,
                "addressdetails": 1,
            },
            headers={"User-Agent": USER_AGENT},
        )
        address = payload.get("address") or {}
        result = {
            "display_name": payload.get("display_name"),
            "latitude": payload.get("lat"),
            "longitude": payload.get("lon"),
            "address": address,
            "type": payload.get("type"),
            "category": payload.get("category"),
            "url": payload.get("poladdrs") or f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}",
        }
        return _success(tool, {"results": [result]}, "Reverse geocoding completed.")
    except Exception as exc:
        return _error(tool, f"Reverse geocoding failed: {exc}")


def osm_search(argument: str = "") -> dict[str, Any]:
    tool = "osm_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a place, address, landmark, or map search.", retryable=False)
    try:
        payload = _get_json(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 5,
            },
            headers={"User-Agent": USER_AGENT},
        )
        results = []
        for row in payload:
            results.append({
                "name": row.get("display_name"),
                "type": row.get("type"),
                "category": row.get("category"),
                "latitude": row.get("lat"),
                "longitude": row.get("lon"),
                "importance": row.get("importance"),
                "url": f"https://www.openstreetmap.org/?mlat={row.get('lat')}&mlon={row.get('lon')}",
            })
        return _success(tool, {"results": results}, f"Found {len(results)} OpenStreetMap result(s).")
    except Exception as exc:
        return _error(tool, f"OpenStreetMap search failed: {exc}")


# ---------------------------------------------------------------------------
# NEWS / SIMPLE FACTS
# ---------------------------------------------------------------------------

def news_search(argument: str = "") -> dict[str, Any]:
    tool = "news_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide a news topic or search phrase.", retryable=False)

    try:
        payload = _get_json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 5,
                "sort": "HybridRel",
                "timespan": "24h",
            },
        )
        articles = []
        for item in payload.get("articles") or []:
            articles.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "domain": item.get("domain"),
                "source_country": item.get("sourcecountry"),
                "language": item.get("language"),
                "seen_date": item.get("seendate"),
            })
        return _success(tool, {"articles": articles, "timespan": "24h", "source": "GDELT"}, f"Found {len(articles)} recent news result(s).")
    except Exception:
        # GDELT can rate-limit bursts. Google News' RSS search feed is a
        # keyless fallback and keeps this capability useful without another API key.
        try:
            import xml.etree.ElementTree as ET

            response = requests.get(
                "https://news.google.com/rss/search",
                params={
                    "q": query,
                    "hl": "en-US",
                    "gl": "US",
                    "ceid": "US:en",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=12,
            )
            response.raise_for_status()
            root = ET.fromstring(response.text)
            articles = []
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title") or ""
                url = item.findtext("link") or ""
                source = item.findtext("source") or ""
                seen_date = item.findtext("pubDate") or ""
                articles.append({
                    "title": title,
                    "url": url,
                    "domain": source,
                    "source_country": "US",
                    "language": "en",
                    "seen_date": seen_date,
                })
            return _success(tool, {"articles": articles, "timespan": "rss", "source": "Google News RSS"}, f"Found {len(articles)} recent news result(s).")
        except Exception as exc:
            return _error(tool, f"News search failed on GDELT and Google News RSS: {exc}")


def cat_fact(argument: str = "") -> dict[str, Any]:
    tool = "cat_fact"
    try:
        payload = _get_json("https://catfact.ninja/fact")
        fact = _clean(payload.get("fact"), 500)
        return _success(tool, {"items": [{"fact": fact}]}, "Cat fact retrieved.")
    except Exception as exc:
        return _error(tool, f"Cat fact lookup failed: {exc}")


def dog_image(argument: str = "") -> dict[str, Any]:
    tool = "dog_image"
    try:
        payload = _get_json("https://dog.ceo/api/breeds/image/random")
        url = payload.get("message")
        return _success(tool, {"items": [{"url": url, "status": payload.get("status")}]}, "Random dog image retrieved.")
    except Exception as exc:
        return _error(tool, f"Dog image lookup failed: {exc}")



def pokemon_lookup(argument: str = "") -> dict[str, Any]:
    tool = "pokemon_lookup"
    query = str(argument or "").strip().split()[0] if str(argument or "").strip() else ""
    if not query:
        return _error(tool, "Provide a Pokémon name or number.", retryable=False)
    try:
        payload = _get_json(f"https://pokeapi.co/api/v2/pokemon/{requests.utils.quote(query.lower(), safe='')}")
        stats = {}
        for item in payload.get("stats") or []:
            stat = item.get("stat") or {}
            if stat.get("name"): stats[stat["name"]] = item.get("base_stat")
        item = {
            "name": payload.get("name"),
            "id": payload.get("id"),
            "types": [x.get("type", {}).get("name") for x in payload.get("types") or []],
            "abilities": [x.get("ability", {}).get("name") for x in payload.get("abilities") or []],
            "height": payload.get("height"),
            "weight": payload.get("weight"),
            "stats": stats,
            "image": ((payload.get("sprites") or {}).get("front_default")),
            "url": f"https://pokeapi.co/api/v2/pokemon/{payload.get('id')}" if payload.get("id") else None,
        }
        return _success(tool, {"results": [item]}, f"Pokémon data retrieved for {item['name'] or query}.")
    except Exception as exc:
        return _error(tool, f"Pokémon lookup failed: {exc}")

def food_product(argument: str = "") -> dict[str, Any]:
    tool = "food_product"
    barcode = "".join(ch for ch in str(argument or "").strip() if ch.isdigit())
    if not barcode:
        return _error(tool, "Provide a product barcode.", retryable=False)
    try:
        payload = _get_json(
            f"https://world.openfoodfacts.org/api/v3/product/{barcode}.json",
            params={"fields": "product_name,brands,nutriscore_data,nutriments,image_front_url,ingredients_text"},
            headers={"User-Agent": "JARVIS/1.0 (local assistant)"},
        )
        product = payload.get("product") or {}
        status_value = payload.get("status")
        status_code = payload.get("status_code")
        found = bool(product) or status_value in {"success", "1", 1} or status_code in {1, "1"}
        if not found:
            return _error(tool, f"No food product found for barcode {barcode}.", retryable=False)
        nutriments = product.get("nutriments") or {}
        item = {
            "name": product.get("product_name") or barcode,
            "brand": product.get("brands"),
            "nutriscore": (product.get("nutriscore_data") or {}).get("grade"),
            "energy_kcal_100g": nutriments.get("energy-kcal_100g"),
            "sugars_100g": nutriments.get("sugars_100g"),
            "fat_100g": nutriments.get("fat_100g"),
            "salt_100g": nutriments.get("salt_100g"),
            "ingredients": _clean(product.get("ingredients_text"), 500),
            "image": product.get("image_front_url"),
            "url": f"https://world.openfoodfacts.org/product/{barcode}",
        }
        return _success(tool, {"results": [item]}, f"Food product data retrieved for {item['name']}.")
    except Exception as exc:
        return _error(tool, f"Food product lookup failed: {exc}")

def cocktail_search(argument: str = "") -> dict[str, Any]:
    tool = "cocktail_search"
    query = str(argument or "").strip()
    endpoint = "https://www.thecocktaildb.com/api/json/v1/1/random.php" if not query else "https://www.thecocktaildb.com/api/json/v1/1/search.php"
    try:
        payload = _get_json(endpoint, params={"s": query} if query else None)
        cocktails = []
        for item in (payload.get("drinks") or [])[:5]:
            ingredients = []
            for idx in range(1, 16):
                ingredient = _clean(item.get(f"strIngredient{idx}"), 60)
                measure = _clean(item.get(f"strMeasure{idx}"), 60)
                if ingredient: ingredients.append(f"{measure} {ingredient}".strip())
            cocktails.append({
                "name": item.get("strDrink"),
                "category": item.get("strCategory"),
                "glass": item.get("strGlass"),
                "instructions": _clean(item.get("strInstructions"), 450),
                "ingredients": ingredients,
                "image": item.get("strDrinkThumb"),
            })
        if not cocktails:
            return _error(tool, f"No cocktails found for '{query}'.", retryable=False)
        return _success(tool, {"items": cocktails}, f"Found {len(cocktails)} cocktail result(s).")
    except Exception as exc:
        return _error(tool, f"Cocktail lookup failed: {exc}")

def openverse_search(argument: str = "") -> dict[str, Any]:
    tool = "openverse_search"
    query = str(argument or "").strip()
    if not query:
        return _error(tool, "Provide an image search phrase.", retryable=False)
    try:
        payload = _get_json(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 5},
        )
        results = []
        for item in payload.get("results") or []:
            results.append({
                "title": item.get("title"),
                "creator": item.get("creator"),
                "license": item.get("license"),
                "source": item.get("source"),
                "url": item.get("foreign_landing_url"),
                "image": item.get("url"),
                "thumbnail": item.get("thumbnail"),
            })
        return _success(tool, {"results": results}, f"Found {len(results)} Openverse image result(s).")
    except Exception as exc:
        return _error(tool, f"Openverse image search failed: {exc}")

def iss_location(argument: str = "") -> dict[str, Any]:
    tool = "iss_location"
    try:
        payload = _get_json("https://api.wheretheiss.at/v1/satellites/25544")
        item = {
            "name": "International Space Station",
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "altitude_km": payload.get("altitude"),
            "velocity_km_h": payload.get("velocity"),
            "visibility": payload.get("visibility"),
            "timestamp": payload.get("timestamp"),
            "url": "https://wheretheiss.at/",
        }
        return _success(tool, {"results": [item]}, "Current ISS position retrieved.")
    except Exception as exc:
        return _error(tool, f"ISS location lookup failed: {exc}")
DISPATCH = {
    name: globals()[name]
    for name in API_TOOLS
}


def run_extended_api_tool(tool_name: str, argument: str = "") -> Any:
    function = DISPATCH.get(str(tool_name or "").strip())
    if function is None:
        return _error(tool_name, f"Unknown extended API tool: {tool_name}", retryable=False)
    return function(argument)