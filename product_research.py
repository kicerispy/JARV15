"""Evidence-first product research for JARVIS."""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from typing import Any

from browser_controller import (
    browser_goto,
    browser_page_info,
    browser_page_snapshot,
    browser_search_bing,
    browser_search_google,
)
from logger import logger
from model_manager import ModelManager

MAX_RESULTS_PER_QUERY = 3
MAX_SOURCES = 10
MAX_PAGE_CHARS = 8000
MIN_CONFIDENT_SOURCES = 4

RETAILERS = {
    "amazon.com",
    "bestbuy.com",
    "walmart.com",
    "target.com",
    "newegg.com",
    "bhphotovideo.com",
    "costco.com",
    "microcenter.com",
    "homedepot.com",
    "lowes.com",
    "ebay.com",
}

REVIEWS = {
    "rtings.com",
    "tomsguide.com",
    "tomshardware.com",
    "pcmag.com",
    "cnet.com",
    "techradar.com",
    "theverge.com",
    "wirecutter.com",
    "soundguys.com",
    "gsmarena.com",
    "notebookcheck.net",
    "consumerreports.org",
}

COMMUNITY = {
    "reddit.com",
    "forums.tomshardware.com",
    "linustechtips.com",
}

MANUFACTURERS = {
    "apple.com",
    "samsung.com",
    "sony.com",
    "lg.com",
    "dell.com",
    "lenovo.com",
    "asus.com",
    "acer.com",
    "hp.com",
    "bose.com",
    "jbl.com",
    "logitech.com",
    "nvidia.com",
    "amd.com",
    "intel.com",
}


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _source_type(url: str) -> str:
    domain = _domain(url)
    if domain in RETAILERS:
        return "retailer"
    if domain in REVIEWS:
        return "independent_review"
    if domain in COMMUNITY:
        return "community"
    if domain in MANUFACTURERS or any(domain.endswith("." + x) for x in MANUFACTURERS):
        return "manufacturer"
    return "web_source"


def _parse_argument(argument: str) -> dict[str, Any]:
    raw = str(argument or "").strip()
    if not raw:
        return {"request": "", "item": "", "budget": None}

    payload: dict[str, Any] = {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            payload = value
    except (json.JSONDecodeError, TypeError):
        try:
            value = ast.literal_eval(raw)
            if isinstance(value, dict):
                payload = value
        except (ValueError, SyntaxError, TypeError):
            pass

    if payload:
        request = str(
            payload.get("request")
            or payload.get("query")
            or payload.get("item")
            or ""
        ).strip()
        item = str(
            payload.get("item")
            or payload.get("query")
            or request
        ).strip()
        budget = payload.get("budget")
        try:
            budget = float(budget) if budget is not None else None
        except (TypeError, ValueError):
            budget = None
        return {
            "request": request or item,
            "item": item,
            "budget": budget,
        }

    item = re.sub(
        r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|help\s+me\s+|"
        r"find\s+me\s+|find\s+|research\s+|look\s+up\s+|"
        r"search\s+for\s+|compare\s+)",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()

    budget = None
    patterns = (
        r"(?:under|below|less\s+than|up\s+to|maximum(?:\s+budget)?(?:\s+of)?)"
        r"\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"\$\s*([0-9][0-9,]*(?:\.\d+)?)"
        r"\s*(?:or\s+less|max(?:imum)?)?",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            try:
                budget = float(match.group(1).replace(",", ""))
            except ValueError:
                budget = None
            break

    return {
        "request": raw,
        "item": item,
        "budget": budget,
    }


def _queries(item: str) -> list[str]:
    subject = " ".join(str(item or "").split()).strip()
    if not subject:
        return []
    return [
        f"{subject} reviews price",
        f"{subject} best reviews",
        f"{subject} alternatives",
        f"{subject} cheaper alternatives",
        f"{subject} comparison review",
    ]


def _is_search_url(url: str) -> bool:
    domain = _domain(url)
    return (
        domain.endswith("google.com")
        or domain.endswith("bing.com")
        or domain.endswith("youtube.com")
    )


def _discover(queries: list[str]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for query in queries:
        for engine, search in (
            ("google", browser_search_google),
            ("bing", browser_search_bing),
        ):
            try:
                search(query)
                snapshot = browser_page_snapshot()
                results = (
                    snapshot.get("results", [])
                    if isinstance(snapshot, dict)
                    else []
                )

                for result in results[:MAX_RESULTS_PER_QUERY]:
                    if not isinstance(result, dict):
                        continue

                    url = str(
                        result.get("url")
                        or result.get("href")
                        or ""
                    ).strip().split("#", 1)[0]

                    if not url or _is_search_url(url) or url in seen:
                        continue

                    seen.add(url)
                    discovered.append(
                        {
                            "url": url,
                            "domain": _domain(url),
                            "source_type": _source_type(url),
                            "title": " ".join(
                                str(
                                    result.get("title", "")
                                    or ""
                                ).split()
                            )[:300],
                            "snippet": " ".join(
                                str(
                                    result.get("snippet", "")
                                    or ""
                                ).split()
                            )[:800],
                            "engine": engine,
                            "query": query,
                        }
                    )

                    if len(discovered) >= MAX_SOURCES * 2:
                        return discovered

            except Exception as exc:
                logger.debug(
                    "JARVIS PRODUCT RESEARCH: "
                    f"discovery failed for {engine}/{query}: {exc}"
                )

    return discovered


def _choose_sources(
    discovered: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    domains: set[str] = set()

    for source_type in (
        "manufacturer",
        "independent_review",
        "retailer",
        "community",
        "web_source",
    ):
        for source in discovered:
            if len(selected) >= MAX_SOURCES:
                return selected

            if source.get("source_type") != source_type:
                continue

            domain = str(
                source.get("domain")
                or ""
            ).lower()

            if not domain or domain in domains:
                continue

            selected.append(source)
            domains.add(domain)

    return selected
