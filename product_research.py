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

    # Keep search discovery focused on the item. Preserve constraints in
    # the full request and parse the budget separately.
    item = re.sub(
        r"\s+(?:under|below|less\s+than|up\s+to)\s*\$?[0-9][0-9,]*(?:\.\d+)?\b.*$",
        "",
        item,
        flags=re.IGNORECASE,
    ).strip()

    item = re.sub(
        r"\s+(?:and\s+)?(?:compare|review|reviews|look\s+at\s+the\s+reviews|"
        r"read\s+the\s+reviews|find\s+alternatives|find\s+similar\s+options)\b.*$",
        "",
        item,
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


def _queries(
    item: str,
    budget: float | None = None,
) -> list[str]:
    subject = " ".join(
        str(item or "").split()
    ).strip()

    if not subject:
        return []

    budget_suffix = (
        " under $"
        + format(budget, ",.2f")
        if budget is not None
        else ""
    )

    return [
        f"{subject} reviews price{budget_suffix}",
        f"{subject} best reviews{budget_suffix}",
        f"{subject} alternatives",
        f"{subject} cheaper alternatives",
        f"{subject} comparison review{budget_suffix}",
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


def _numeric_hints(text: str) -> dict[str, list[Any]]:
    value = str(text or "")
    prices = []
    for raw in re.findall(
        r"(?<![\w])\$\s*([0-9]{1,6}(?:,[0-9]{3})*(?:\.\d{1,2})?)",
        value,
    ):
        try:
            number = float(raw.replace(",", ""))
            if 1 <= number <= 100000:
                prices.append(number)
        except ValueError:
            pass

    ratings = []
    for raw in re.findall(
        r"(?<![\d])(\d(?:\.\d)?)\s*(?:/\s*5|out\s+of\s+5|stars?)",
        value,
        re.IGNORECASE,
    ):
        try:
            number = float(raw)
            if 0 <= number <= 5:
                ratings.append(number)
        except ValueError:
            pass

    review_counts = []
    for raw in re.findall(
        r"([0-9][0-9,]*)\s+(?:customer\s+)?(?:ratings?|reviews?)\b",
        value,
        re.IGNORECASE,
    ):
        try:
            number = int(raw.replace(",", ""))
            if 1 <= number <= 100000000:
                review_counts.append(number)
        except ValueError:
            pass

    return {
        "prices": prices[:8],
        "ratings": ratings[:8],
        "review_counts": review_counts[:8],
    }


def _collect_evidence(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = []
    original = browser_page_info()
    original_url = (
        str(original.get("url", "") or "").strip()
        if isinstance(original, dict)
        else ""
    )

    try:
        for index, source in enumerate(sources, 1):
            url = str(source.get("url") or "").strip()
            if not url:
                continue

            try:
                navigation = browser_goto(url)
            except Exception as exc:
                navigation = {
                    "title": "",
                    "url": url,
                }
                logger.debug(
                    "JARVIS PRODUCT RESEARCH: "
                    f"navigation failed for {url}: {exc}"
                )

            try:
                snapshot = browser_page_snapshot()
            except Exception:
                snapshot = {}

            readable = (
                " ".join(
                    str(
                        snapshot.get(
                            "readable_text",
                            "",
                        )
                        or ""
                    ).split()
                )[:MAX_PAGE_CHARS]
                if isinstance(snapshot, dict)
                else ""
            )

            title = " ".join(
                str(
                    (
                        snapshot.get("title")
                        if isinstance(snapshot, dict)
                        else ""
                    )
                    or (
                        navigation.get("title")
                        if isinstance(navigation, dict)
                        else ""
                    )
                    or source.get("title")
                    or ""
                ).split()
            )[:300]

            evidence.append(
                {
                    "id": index,
                    "url": url,
                    "domain": source.get("domain") or _domain(url),
                    "source_type": (
                        source.get("source_type")
                        or _source_type(url)
                    ),
                    "title": title,
                    "snippet": source.get("snippet", ""),
                    "text": readable,
                    "query": source.get("query", ""),
                    "engine": source.get("engine", ""),
                    "numeric_hints": _numeric_hints(
                        " ".join(
                            [
                                source.get("title", ""),
                                source.get("snippet", ""),
                                readable,
                            ]
                        )
                    ),
                }
            )
    finally:
        if original_url:
            try:
                browser_goto(original_url)
            except Exception:
                pass

    return evidence


def _response_text(response: Any) -> str:
    message = getattr(
        response,
        "message",
        None,
    )

    if isinstance(message, dict):
        return str(
            message.get("content")
            or ""
        ).strip()

    if message is not None:
        return str(
            getattr(
                message,
                "content",
                "",
            )
            or ""
        ).strip()

    if (
        isinstance(response, dict)
        and isinstance(
            response.get("message"),
            dict,
        )
    ):
        return str(
            response["message"].get(
                "content"
            )
            or ""
        ).strip()

    return ""


def _parse_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()

    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        try:
            value = json.loads(
                raw[start : end + 1]
            )
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            pass

    return {}


def _synthesize(
    request: str,
    item: str,
    budget: float | None,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if budget is not None:
        budget_note = (
            "Maximum budget: $"
            + format(budget, ",.2f")
            + "."
        )
    else:
        budget_note = "No explicit maximum budget."

    prompt = f"""
You are JARVIS's evidence-constrained product research analyst.

USER REQUEST: {request}
ITEM / CATEGORY: {item}
{budget_note}

SOURCE EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}

Use only the supplied evidence.
Never invent product names, prices, ratings, review counts,
specifications, or capabilities.

Evidence rules:
- Manufacturer sources are strongest for specifications.
- Retailers are strongest for observed price and customer ratings.
- Independent reviews are strongest for testing and comparative analysis.
- Community sources are anecdotal.
- Prefer agreement across independent domains.
- Do not treat a tiny rating sample like a large one.
- State conflicts or potentially stale pricing.
- A cheaper product is not automatically better value.
- An alternative must reasonably serve the same use case.
- Use null when evidence is missing.
- Cite factual claims with source IDs.

Separate these outcomes:
1. best match for the requested item/use case
2. best value
3. cheapest credible option
4. better-reviewed alternative
These may be the same product or different products.

Return ONLY JSON:
{{
  "summary": "2-5 sentence conclusion",
  "confidence": "high|medium|low",
  "products": [
    {{
      "name": "product",
      "price": null,
      "rating": null,
      "review_count": null,
      "source_ids": [],
      "pros": [],
      "cons": [],
      "fit": "best_match|strong_alternative|budget_alternative|mixed|poor_fit"
    }}
  ],
  "best_match": {{"name": null, "reason": "", "source_ids": []}},
  "best_value": {{"name": null, "reason": "", "source_ids": []}},
  "cheapest_credible_option": {{"name": null, "reason": "", "source_ids": []}},
  "better_reviewed_alternative": {{"name": null, "reason": "", "source_ids": []}},
  "tradeoffs": [],
  "warnings": []
}}
"""

    try:
        response = ModelManager().planner(
            [
                {
                    "role": "system",
                    "content": (
                        "Output valid JSON only. "
                        "Be strict about evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        )
    except Exception as exc:
        logger.warning(
            "JARVIS PRODUCT RESEARCH: synthesis failed: "
            f"{exc}"
        )
        return {}

    return _parse_json(
        _response_text(response)
    )


def _summary(
    analysis: dict[str, Any],
    source_count: int,
) -> str:
    parts = []

    summary = " ".join(
        str(
            analysis.get(
                "summary",
                "",
            )
            or ""
        ).split()
    ).strip()

    if summary:
        parts.append(summary)

    for field, label in (
        ("best_match", "Best match"),
        ("best_value", "Best value"),
        ("cheapest_credible_option", "Cheapest credible option"),
        ("better_reviewed_alternative", "Better-reviewed alternative"),
    ):
        choice = analysis.get(field) or {}
        name = str(
            choice.get(
                "name",
                "",
            )
            or ""
        ).strip()
        reason = " ".join(
            str(
                choice.get(
                    "reason",
                    "",
                )
                or ""
            ).split()
        ).strip()

        if not name:
            continue

        if reason:
            parts.append(
                f"{label}: {name}. {reason}"
            )
        else:
            parts.append(
                f"{label}: {name}."
            )

    tradeoffs = analysis.get("tradeoffs") or []
    for tradeoff in list(tradeoffs)[:2]:
        text = " ".join(
            str(tradeoff or "").split()
        ).strip()
        if text:
            parts.append(
                f"Tradeoff: {text}"
            )

    if not parts:
        parts.append(
            "I found online sources, but not enough "
            "evidence for a confident conclusion."
        )

    confidence = str(
        analysis.get(
            "confidence",
            "low",
        )
        or "low"
    ).lower()

    if confidence in {
        "high",
        "medium",
        "low",
    }:
        parts.append(
            f"Confidence is {confidence}."
        )

    if source_count < MIN_CONFIDENT_SOURCES:
        parts.append(
            f"Only {source_count} usable independent "
            "sources were available."
        )

    return " ".join(parts)[:2200]

def research_product(
    argument: str = "",
) -> dict[str, Any]:
    """Research an item online and compare credible alternatives."""
    parsed = _parse_argument(argument)

    request = str(
        parsed.get("request")
        or ""
    ).strip()

    item = str(
        parsed.get("item")
        or ""
    ).strip()

    budget = parsed.get(
        "budget"
    )

    if not item:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": (
                "Product research needs "
                "an item or category."
            ),
        }

    queries = _queries(
        item,
        budget=budget,
    )
    discovered = _discover(queries)
    sources = _choose_sources(discovered)
    evidence = _collect_evidence(sources)

    if not evidence:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": (
                "I could not collect usable "
                "online sources for that item."
            ),
            "item": item,
            "queries": queries,
            "sources": [],
        }

    analysis = _synthesize(
        request or item,
        item,
        budget,
        evidence,
    )

    verified = bool(
        analysis
        and (
            analysis.get("best_match")
            or analysis.get("best_value")
        )
    )

    summary = _summary(
        analysis,
        len(evidence),
    )

    return {
        "success": True,
        "verified": verified,
        "retryable": False,
        "action": "product_research",
        "request": request or item,
        "item": item,
        "budget": budget,
        "queries": queries,
        "source_count": len(evidence),
        "sources": [
            {
                "id": source["id"],
                "domain": source["domain"],
                "source_type": source["source_type"],
                "title": source["title"],
                "url": source["url"],
                "engine": source["engine"],
                "query": source["query"],
            }
            for source in evidence
        ],
        "evidence": evidence,
        "analysis": analysis,
        "summary": summary,
        "confidence": str(
            analysis.get(
                "confidence",
                "low",
            )
            or "low"
        ).lower(),
        "observed_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "message": summary,
    }
