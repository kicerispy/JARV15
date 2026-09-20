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
        anime = []
        for item in payload.get("data") or []:
            anime.append({
                "title": item.get("title"),
                "title_english": item.get("title_english"),
                "type": item.get("type"),
                "episodes": item.get("episodes"),
                "status": item.get("status"),
                "score": item.get("score"),
                "year": (item.get("year") or (item.get("aired") or {}).get("prop", {}).get("from", "") or "") ,
                "synopsis": _clean(item.get("synopsis"), 500),
                "url": item.get("url"),
            })
        return _success(tool, {"anime": anime}, f"Found {len(anime)} anime result(s).")
    except Exception as exc:
        return _error(tool, f"Anime search failed: {exc}")


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
    try:
        encoded = requests.utils.quote(query, safe="")
        endpoint = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{encoded}/property/MolecularFormula,MolecularWeight,IUPACName/JSON"
        )
        payload = _get_json(endpoint)
        props = (payload.get("PropertyTable") or {}).get("Properties") or []
        if not props:
            return _error(tool, f"No compound found for '{query}'.", retryable=False)
        item = props[0]
        result = {
            "cid": item.get("CID"),
            "name": query,
            "molecular_formula": item.get("MolecularFormula"),
            "molecular_weight": item.get("MolecularWeight"),
            "iupac_name": item.get("IUPACName"),
            "url": (
                f"https://pubchem.ncbi.nlm.nih.gov/compound/{item.get('CID')}"
                if item.get("CID")
                else None
            ),
        }
        return _success(tool, {"results": [result]}, f"PubChem data retrieved for {query}.")
    except Exception as exc:
        return _error(tool, f"PubChem lookup failed: {exc}")


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
    endpoint = (
        "https://api.spacexdata.com/v4/launches/latest"
        if mode in {"", "latest", "last"}
        else "https://api.spacexdata.com/v4/launches"
    )
    try:
        if endpoint.endswith("/latest"):
            payload = _get_json(endpoint)
            rows = [payload]
        else:
            payload = _get_json(endpoint)
            rows = payload[-8:]
        launches = []
        for item in rows:
            links = item.get("links") or {}
            launches.append({
                "name": item.get("name"),
                "date_utc": item.get("date_utc"),
                "success": item.get("success"),
                "details": _clean(item.get("details"), 500),
                "webcast": (links.get("webcast") if isinstance(links, dict) else None),
                "patch": ((links.get("patch") or {}).get("small") if isinstance(links, dict) else None),
            })
        return _success(
            tool,
            {"launches": launches, "source_status": "historical_community_api"},
            f"Retrieved {len(launches)} SpaceX launch record(s).",
        )
    except Exception as exc:
        return _error(tool, f"SpaceX lookup failed: {exc}")


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
        return _success(tool, {"articles": articles, "timespan": "24h"}, f"Found {len(articles)} recent news result(s).")
    except Exception as exc:
        return _error(tool, f"News search failed: {exc}")


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


DISPATCH = {
    name: globals()[name]
    for name in API_TOOLS
}


def run_extended_api_tool(tool_name: str, argument: str = "") -> Any:
    function = DISPATCH.get(str(tool_name or "").strip())
    if function is None:
        return _error(tool_name, f"Unknown extended API tool: {tool_name}", retryable=False)
    return function(argument)
