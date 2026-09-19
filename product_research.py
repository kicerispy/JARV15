"""Evidence-first product research for JARVIS."""
from __future__ import annotations
import requests
from html.parser import HTMLParser
import time
from concurrent.futures import ThreadPoolExecutor

import ast
import base64
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from browser_controller import (
    browser_goto,
    browser_page_info,
    browser_page_snapshot,
    browser_search_bing,
    browser_search_google,
)
from logger import logger
from model_manager import ModelManager
from product_price_checker import compare_products_prices

MAX_RESULTS_PER_QUERY = 3
MAX_SOURCES = 16
MAX_PAGE_CHARS = 8000
MIN_CONFIDENT_SOURCES = 4


_PRODUCT_BRANDS = {
    "apple", "sony", "bose", "sennheiser", "anker", "soundcore", "jbl",
    "marshall", "shokz", "beats", "google", "samsung", "jabra",
    "audio technica", "audio-technica", "bowers wilkins", "bowers & wilkins",
    "steelseries", "audeze", "nothing", "skullcandy", "technics",
    "beyerdynamic", "bang & olufsen", "master & dynamic", "master dynamic",
}

_GENERIC_PRODUCT_WORDS = {
    "wireless", "wired", "bluetooth", "headphone", "headphones", "earbud",
    "earbuds", "earphone", "earphones", "headset", "audio", "noise",
    "cancelling", "canceling", "cancellation", "active", "hybrid", "over",
    "on", "in", "ear", "premium", "budget", "best", "wireless", "anc",
}

def _is_specific_product_name(value: Any) -> bool:
    name = " ".join(str(value or "").split()).strip()
    if len(name) < 5 or len(name) > 140:
        return False

    normalized = _normalized_name(name) if "_normalized_name" in globals() else " ".join(name.lower().split())
    words = normalized.split()
    distinctive = [word for word in words if word not in _GENERIC_PRODUCT_WORDS]
    has_brand = any(
        brand in normalized
        for brand in _PRODUCT_BRANDS
    )
    has_model_token = any(
        re.search(r"\d", word) and len(word) >= 2
        for word in words
    )
    has_model_pattern = bool(
        re.search(r"\b[a-z]{1,8}[- ]?\d{1,5}[a-z0-9-]*\b", normalized, re.IGNORECASE)
        or re.search(r"\b[ivx]{2,4}\b", normalized, re.IGNORECASE)
    )

    # Category-only labels are not products, even when they contain useful
    # audio terminology. Concrete model/brand evidence is required.
    if not distinctive:
        return False
    if not has_brand and not has_model_token and not has_model_pattern:
        return False
    if len(distinctive) == 1 and not (has_brand and has_model_token):
        return False
    return True

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
    "crutchfield.com",
    "adorama.com",
    "samsclub.com",
    "woot.com",
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
    "headphones.com",
    "forum.headphones.com",
    "head-fi.org",
    "avsforum.com",
    "avforums.com",
    "slickdeals.net",
}

VIDEO_SOURCES = {
    "youtube.com",
    "youtu.be",
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

    if domain in VIDEO_SOURCES or any(
        domain.endswith("." + x)
        for x in VIDEO_SOURCES
    ):
        return "video"

    if domain in COMMUNITY:
        return "community"

    if domain in MANUFACTURERS or any(
        domain.endswith("." + x)
        for x in MANUFACTURERS
    ):
        return "manufacturer"

    return "web_source"


def _extract_item_and_budget(raw: str) -> tuple[str, float | None]:
    """Extract the product/category subject and optional budget from a request."""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return "", None

    item = re.sub(
        r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|help\s+me\s+|"
        r"find\s+me\s+|find\s+|research\s+|look\s+up\s+|"
        r"search\s+for\s+|compare\s+)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    budget = None
    budget_patterns = (
        r"(?:under|below|less\s+than|up\s+to|maximum(?:\s+budget)?(?:\s+of)?)"
        r"\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.\d+)?)\b",
        r"\$\s*([0-9][0-9,]*(?:\.\d+)?)"
        r"\s*(?:or\s+less|max(?:imum)?)?",
    )
    for pattern in budget_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                budget = float(match.group(1).replace(",", ""))
            except ValueError:
                budget = None
            break

    item = re.sub(
        r"\s+(?:under|below|less\s+than|up\s+to)"
        r"\s*\$?[0-9]+(?:,[0-9]{3})*(?:\.\d+)?"
        r"(?=\s*(?:[,.;:!?]|$)).*$",
        "",
        item,
        flags=re.IGNORECASE,
    ).strip()

    item = re.sub(
        r"\s+(?:and\s+)?(?:compare|reviews?|ratings?|look\s+at\s+the\s+reviews|"
        r"read\s+the\s+reviews|find\s+alternatives|find\s+similar\s+options|"
        r"cheaper\s+alternatives|best\s+value|tell\s+me\s+which\s+option"
        r"|which\s+option)\b.*$",
        "",
        item,
        flags=re.IGNORECASE,
    ).strip()

    # Search for the category/model, not the user's task instructions.
    item = re.sub(
        r"^the\s+best\s+",
        "",
        item,
        flags=re.IGNORECASE,
    ).strip()
    item = re.sub(
        r"^best\s+",
        "",
        item,
        flags=re.IGNORECASE,
    ).strip()

    return item, budget


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

        explicit_item = str(
            payload.get("item")
            or ""
        ).strip()

        if explicit_item:
            item, item_budget = _extract_item_and_budget(
                explicit_item
            )
            _, request_budget = _extract_item_and_budget(
                request or explicit_item
            )
            parsed_budget = (
                request_budget
                if request_budget is not None
                else item_budget
            )
        else:
            # "query" is a natural-language request field, not necessarily
            # a clean product name. Always run it through the extractor.
            item, parsed_budget = _extract_item_and_budget(
                request
            )

        budget = payload.get("budget")
        try:
            budget = float(budget) if budget is not None else parsed_budget
        except (TypeError, ValueError):
            budget = parsed_budget

        return {
            "request": request or item,
            "item": item,
            "budget": budget,
        }

    item, budget = _extract_item_and_budget(raw)

    return {
        "request": raw,
        "item": item,
        "budget": budget,
    }


def _queries(subject, budget):
    """Generate a compact set of high-information search queries."""
    subject = str(subject or "").strip()
    normalized_subject, normalized_budget = _extract_item_and_budget(subject)
    if normalized_subject:
        subject = normalized_subject
    if budget is None and normalized_budget is not None:
        budget = normalized_budget

    try:
        budget_text = f"${float(budget):g}"
    except Exception:
        budget_text = ""

    clean = subject.replace('"', "").strip()
    if not clean:
        return []

    phrase = f'"{clean}"'
    queries = [
        f"{phrase} reviews".strip(),
        f"{phrase} comparison".strip(),
        f"{phrase} expert review".strip(),
        f"{clean} official manufacturer specifications".strip(),
        f"{clean} official product page".strip(),
        f"{phrase} cheaper alternatives".strip(),
    ]
    if budget_text:
        queries.insert(0, f"{phrase} reviews under {budget_text}".strip())
        queries.insert(1, f"{phrase} best budget {budget_text}".strip())

    return list(dict.fromkeys(query for query in queries if query))

def _is_search_url(url: str) -> bool:
    """Return True only for search-engine result pages."""
    domain = _domain(url)

    return (
        domain.endswith("google.com")
        or domain.endswith("bing.com")
    )


def _search_engine_blocked(
    snapshot: dict[str, Any],
    engine: str,
) -> bool:
    """Return True when a search engine has presented a block/CAPTCHA page."""
    if engine.lower() != "google":
        return False

    if not isinstance(snapshot, dict):
        return False

    value = " ".join(
        str(
            snapshot.get(key, "")
            or ""
        )
        for key in (
            "url",
            "title",
            "readable_text",
        )
    ).lower()

    markers = (
        "google.com/sorry",
        "/sorry/index",
        "unusual traffic",
        "captcha",
        "recaptcha",
        "not a robot",
        "verify you are human",
        "our systems have detected unusual traffic",
    )

    return any(
        marker in value
        for marker in markers
    )


def _canonical_search_href(href: str) -> str:
    """Resolve common search-engine redirect hrefs into an absolute URL."""
    value = str(href or "").strip()
    if not value:
        return ""

    # Already a direct URL.
    if value.startswith(("http://", "https://")):
        try:
            parsed_direct = urlparse(value)
            query_direct = parse_qs(parsed_direct.query)

            # Bing commonly wraps outbound result URLs in:
            #   u=a1<urlsafe-base64>
            #
            # The a1 prefix is not part of the encoded URL.
            for target_raw in query_direct.get("u", []) or []:
                target = unquote(str(target_raw or "")).strip()

                if target.startswith("a1") and len(target) > 2:
                    encoded = target[2:]

                    try:
                        padding = "=" * (
                            (-len(encoded)) % 4
                        )
                        decoded = base64.urlsafe_b64decode(
                            encoded + padding
                        ).decode(
                            "utf-8",
                            errors="ignore",
                        ).strip()

                        if decoded.startswith(
                            ("http://", "https://")
                        ):
                            return decoded
                    except Exception:
                        pass

                if target.startswith(
                    ("http://", "https://")
                ):
                    return target
        except Exception:
            pass

    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)

        # Standard search-engine redirect parameters.
        for key in ("url", "q"):
            targets = query.get(key) or []
            for target_raw in targets:
                target = unquote(
                    str(target_raw or "")
                ).strip()

                if target.startswith(
                    ("http://", "https://")
                ):
                    return target

        # Bing outbound redirects.
        for target_raw in query.get("u", []) or []:
            target = unquote(
                str(target_raw or "")
            ).strip()

            if target.startswith("a1") and len(target) > 2:
                encoded = target[2:]

                try:
                    padding = "=" * (
                        (-len(encoded)) % 4
                    )
                    decoded = base64.urlsafe_b64decode(
                        encoded + padding
                    ).decode(
                        "utf-8",
                        errors="ignore",
                    ).strip()

                    if decoded.startswith(
                        ("http://", "https://")
                    ):
                        return decoded
                except Exception:
                    pass

            if target.startswith(
                ("http://", "https://")
            ):
                return target

    except Exception:
        pass

    return value if value.startswith(
        ("http://", "https://")
    ) else ""


def _fallback_results_from_links(
    snapshot: dict[str, Any],
    engine: str,
) -> list[dict[str, Any]]:
    """Recover external search candidates when dedicated result selectors miss."""
    links = (
        snapshot.get("links", [])
        if isinstance(snapshot, dict)
        else []
    )

    recovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for link in links:
        if not isinstance(link, dict):
            continue

        url = _canonical_search_href(
            str(link.get("href") or "")
        ).split("#", 1)[0]

        if not url or _is_search_url(url) or url in seen:
            continue

        title = " ".join(
            str(link.get("text") or "").split()
        ).strip()

        if len(title) < 8:
            continue

        seen.add(url)
        recovered.append({
            "url": url[:1000],
            "title": title[:300],
            "snippet": "",
            "engine": engine,
        })

        if len(recovered) >= MAX_RESULTS_PER_QUERY:
            break

    return recovered



# ============================================================
# HYBRID PRODUCT RESEARCH
# ============================================================

_RESEARCH_HTTP_TIMEOUT = 15
_RESEARCH_HEADLESS_TIMEOUT = 18
_RESEARCH_TEXT_LIMIT = 6000
_RESEARCH_MAX_DISCOVERY = max(
    int(MAX_SOURCES) * 4,
    48,
)

_RESEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7"
    ),
}

_RESEARCH_TELECOM_DOMAINS = {
    "verizon.com",
    "att.com",
    "t-mobile.com",
    "assurancewireless.com",
    "visible.com",
    "cricketwireless.com",
    "metrobyt-mobile.com",
    "boostmobile.com",
    "mintmobile.com",
    "uscellular.com",
    "spectrum.com",
    "xfinity.com",
    "straighttalk.com",
    "tracfone.com",
    "usmobile.com",
    "consumerwireless.com",
}

_RESEARCH_GENERIC_DOMAINS = {
    "wikipedia.org",
    "support.microsoft.com",
    "microsoft.com",
}

_RESEARCH_VIDEO_DOMAINS = {
    "youtube.com",
    "youtu.be",
}

_RESEARCH_COMMUNITY_DOMAINS = {
    "reddit.com",
    "head-fi.org",
    "avforums.com",
    "headphones.com",
    "forum.headphones.com",
    "forums.tomshardware.com",
    "linustechtips.com",
    "slickdeals.net",
}

_RESEARCH_RETAILER_DOMAINS = {
    "amazon.com",
    "bestbuy.com",
    "walmart.com",
    "target.com",
    "newegg.com",
    "bhphotovideo.com",
    "costco.com",
    "microcenter.com",
    "crutchfield.com",
    "adorama.com",
    "samsclub.com",
    "woot.com",
    "homedepot.com",
    "lowes.com",
    "ebay.com",
}

_RESEARCH_MANUFACTURER_DOMAINS = {
    "apple.com",
    "sony.com",
    "bose.com",
    "jbl.com",
    "sennheiser-hearing.com",
    "sennheiser.com",
    "soundcore.com",
    "anker.com",
    "skullcandy.com",
    "audio-technica.com",
    "beyerdynamic.com",
    "beatsbydre.com",
    "shure.com",
    "jabra.com",
    "bowerswilkins.com",
    "bang-olufsen.com",
    "marshall.com",
    "akg.com",
    "masterdynamic.com",
}

_RESEARCH_REVIEW_DOMAINS = {
    "rtings.com",
    "pcmag.com",
    "techradar.com",
    "soundguys.com",
    "cnet.com",
    "tomsguide.com",
    "whathifi.com",
    "wired.com",
    "forbes.com",
    "gizmodo.com",
    "pcworld.com",
    "digitaltrends.com",
    "trustedreviews.com",
}

_RESEARCH_PRODUCT_TERMS = (
    "headphone",
    "headphones",
    "earbud",
    "earbuds",
    "earphone",
    "earphones",
    "headset",
    "audio",
    "hi-fi",
    "hifi",
    "speaker",
    "speakers",
    "sound quality",
    "noise cancelling",
    "noise cancellation",
    "active noise cancellation",
    "anc",
    "bluetooth audio",
)

_RESEARCH_BAD_TERMS = (
    "phone plan",
    "cell phone",
    "cell phones",
    "mobile phone",
    "mobile phones",
    "5g network",
    "wireless service",
    "wireless services",
    "internet service",
    "internet provider",
    "government phone",
    "lifeline service",
    "unlimited data",
    "prepaid wireless",
    "phone services",
    "carrier",
    "wireless network",
    "wireless networking",
    "wifi",
    "wi-fi",
    "router",
    "routers",
    "modem",
    "modems",
)


class _ResearchHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )
        self.title_parts = []
        self.text_parts = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "template",
        }:
            self.skip_depth += 1
            return

        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "template",
        }:
            if self.skip_depth:
                self.skip_depth -= 1
            return

        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip_depth:
            return

        clean = " ".join(
            str(data or "").split()
        )

        if not clean:
            return

        if self.in_title:
            self.title_parts.append(clean)

        self.text_parts.append(clean)

    @property
    def title(self):
        return " ".join(self.title_parts).strip()

    @property
    def text(self):
        return " ".join(self.text_parts).strip()


def _research_domain(url):
    try:
        from urllib.parse import urlparse

        domain = urlparse(
            str(url or "")
        ).netloc.lower().strip()

        if domain.startswith("www."):
            domain = domain[4:]

        return domain
    except Exception:
        return ""


def _research_domain_matches(
    domain,
    known_domains,
):
    return any(
        domain == known
        or domain.endswith("." + known)
        for known in known_domains
    )


def _research_source_type(
    url,
    title="",
):
    domain = _research_domain(url)

    if _research_domain_matches(
        domain,
        _RESEARCH_VIDEO_DOMAINS,
    ):
        return "video"

    if _research_domain_matches(
        domain,
        _RESEARCH_COMMUNITY_DOMAINS,
    ):
        return "community"

    if _research_domain_matches(
        domain,
        _RESEARCH_RETAILER_DOMAINS,
    ):
        return "retailer"

    if _research_domain_matches(
        domain,
        _RESEARCH_MANUFACTURER_DOMAINS,
    ):
        return "manufacturer"

    if _research_domain_matches(
        domain,
        _RESEARCH_REVIEW_DOMAINS,
    ):
        return "independent_review"

    combined = (
        str(title or "")
        + " "
        + str(url or "")
    ).lower()

    if "official product page" in combined:
        return "manufacturer"

    return "web_source"


def _research_candidate_relevance(
    title,
    snippet,
    url,
):
    combined = " ".join(
        [
            str(title or ""),
            str(snippet or ""),
            str(url or ""),
        ]
    ).lower()

    score = 0

    for term in _RESEARCH_PRODUCT_TERMS:
        if term in str(title or "").lower():
            score += 8
        elif term in combined:
            score += 2

    for term in (
        "review",
        "reviews",
        "comparison",
        "compare",
        "tested",
        "best",
        "budget",
        "price",
        "pricing",
        "specifications",
        "specs",
        "battery life",
        "comfort",
        "microphone",
        "anc",
    ):
        if term in str(title or "").lower():
            score += 3
        elif term in combined:
            score += 1

    if any(
        path_part in str(url or "").lower()
        for path_part in (
            "/headphone",
            "/headphones",
            "/earbud",
            "/earbuds",
            "/audio",
            "/sound",
        )
    ):
        score += 6

    return score



_RESEARCH_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "best",
    "buy",
    "buying",
    "cheap",
    "cheaper",
    "compare",
    "comparison",
    "expert",
    "for",
    "from",
    "good",
    "guide",
    "hands",
    "in",
    "issues",
    "new",
    "of",
    "on",
    "owners",
    "page",
    "price",
    "problems",
    "review",
    "reviews",
    "shop",
    "spec",
    "specification",
    "specifications",
    "tested",
    "the",
    "under",
    "up",
    "with",
    "youtube",
    "reddit",
    "amazon",
    "walmart",
    "bestbuy",
    "best",
    "microcenter",
    "forum",
    "forums",
    "discussion",
    "discussions",
    "official",
    "manufacturer",
    "product",
    "products",
    "alternative",
    "alternatives",
    "hands",
    "on",
}

_RESEARCH_QUERY_AMBIGUOUS_TERMS = {
    "wireless",
    "wired",
    "best",
    "good",
    "cheap",
    "budget",
    "review",
    "reviews",
    "tested",
    "comparison",
    "compare",
    "price",
    "under",
    "over",
    "buy",
    "buying",
    "guide",
}

_RESEARCH_TELECOM_QUERY_TERMS = {
    "phone",
    "phones",
    "smartphone",
    "smartphones",
    "iphone",
    "android",
    "cell",
    "cellular",
    "mobile",
    "carrier",
    "carriers",
    "plan",
    "plans",
    "5g",
    "4g",
    "lte",
    "internet",
    "isp",
    "broadband",
    "fiber",
    "wifi",
    "wi-fi",
    "router",
    "routers",
    "modem",
    "modems",
    "hotspot",
    "data",
    "prepaid",
    "telecom",
    "network",
    "networking",
}

def _research_query_focus_terms(query):
    """
    Extract the meaningful subject terms from a search query.

    Search modifiers, retailer/provider names, budgets, and ambiguous
    words such as "wireless" are deliberately excluded.
    """
    value = str(query or "").lower().strip()

    quoted = re.findall(
        r'"([^"]+)"',
        value,
    )

    focus = (
        quoted[0]
        if quoted
        else value
    )

    tokens = re.findall(
        r"[a-z0-9]+(?:[.+-][a-z0-9]+)*",
        focus,
    )

    terms = []

    for token in tokens:
        token = token.strip("._-")

        if not token:
            continue

        if token in _RESEARCH_QUERY_STOPWORDS:
            continue

        if token in _RESEARCH_QUERY_AMBIGUOUS_TERMS:
            continue

        if token.isdigit():
            continue

        if len(token) < 2:
            continue

        if token not in terms:
            terms.append(token)

    return terms


def _research_query_is_telecom(query):
    """
    Return True only when the actual search topic is telecom-related.

    Word boundaries are important here:
        "phone" must not match "headphone"
        "phone" must not match "headphones"
    """
    value = str(query or "").lower().strip()

    tokens = set(
        re.findall(
            r"[a-z0-9]+(?:[.+-][a-z0-9]+)*",
            value,
        )
    )

    telecom_words = {
        "phone",
        "phones",
        "smartphone",
        "smartphones",
        "iphone",
        "android",
        "cell",
        "cellular",
        "mobile",
        "mobiles",
        "carrier",
        "carriers",
        "plan",
        "plans",
        "5g",
        "4g",
        "lte",
        "internet",
        "isp",
        "broadband",
        "fiber",
        "wifi",
        "router",
        "routers",
        "modem",
        "modems",
        "hotspot",
        "data",
        "telecom",
        "network",
        "networking",
        "provider",
        "providers",
    }

    if tokens.intersection(telecom_words):
        return True

    telecom_phrases = (
        "phone plan",
        "phone plans",
        "cell phone",
        "cell phones",
        "mobile phone",
        "mobile phones",
        "wireless service",
        "wireless services",
        "internet service",
        "internet services",
        "internet provider",
        "internet providers",
        "wireless network",
        "wireless networking",
        "prepaid wireless",
        "phone service",
        "phone services",
        "home internet",
        "home networking",
    )

    return any(
        re.search(
            rf"\b{re.escape(phrase)}\b",
            value,
        )
        for phrase in telecom_phrases
    )

def _research_query_relevance(
    title,
    snippet,
    url,
    query,
):
    """
    Score a result against the actual research topic.

    A result must match a meaningful query subject term before
    generic/product-specific relevance bonuses are considered.
    This prevents pages about wireless phone service from
    matching searches for wireless headphones.
    """
    title_text = str(title or "").lower()
    snippet_text = str(snippet or "").lower()
    url_text = str(url or "").lower()

    combined = " ".join(
        (
            title_text,
            snippet_text,
            url_text,
        )
    )

    terms = _research_query_focus_terms(query)

    if not terms:
        return 0

    def term_present(term, value):
        if re.search(
            rf"\b{re.escape(term)}\b",
            value,
        ):
            return True

        # Simple singular/plural tolerance.
        if term.endswith("s") and len(term) > 3:
            singular = term[:-1]

            if re.search(
                rf"\b{re.escape(singular)}\b",
                value,
            ):
                return True

        return False

    matched_terms = [
        term
        for term in terms
        if term_present(term, combined)
    ]

    # No meaningful subject match means this is not a useful
    # result, regardless of generic words like "wireless",
    # "best", "review", or "price".
    if not matched_terms:
        return 0

    score = 0

    quoted = re.findall(
        r'"([^"]+)"',
        str(query or "").lower(),
    )

    # Exact quoted subject is the strongest signal.
    for phrase in quoted:
        phrase = phrase.strip()

        if not phrase:
            continue

        if phrase in title_text:
            score += 12
        elif phrase in combined:
            score += 7

    for term in matched_terms:
        if term_present(term, title_text):
            score += 7
        elif term_present(term, snippet_text):
            score += 4
        elif term_present(term, url_text):
            score += 3

    if len(matched_terms) >= 2:
        score += 5

    # Existing specialist scoring is useful only AFTER the
    # result is proven to be about the requested subject.
    score += min(
        _research_candidate_relevance(
            title,
            snippet,
            url,
        ),
        8,
    )

    return score

def _research_telecom_domain_relevant(
    domain,
    query,
):
    """
    Telecom domains are allowed only for telecom-relevant topics.
    """
    return (
        _research_domain_matches(
            domain,
            _RESEARCH_TELECOM_DOMAINS,
        )
        and _research_query_is_telecom(query)
    )

def _research_candidate_allowed(
    title,
    snippet,
    url,
    query="",
):
    domain = _research_domain(url)

    if not domain:
        return False

    # Telecom sites are context-dependent rather than globally bad.
    if _research_domain_matches(
        domain,
        _RESEARCH_TELECOM_DOMAINS,
    ):
        if not _research_query_is_telecom(query):
            return False

    combined = " ".join(
        [
            str(title or ""),
            str(snippet or ""),
            str(url or ""),
        ]
    ).lower()

    has_product = any(
        term in combined
        for term in _RESEARCH_PRODUCT_TERMS
    )

    has_bad_term = any(
        term in combined
        for term in _RESEARCH_BAD_TERMS
    )

    if has_bad_term and not has_product and not query:
        return False

    if query:
        return (
            _research_query_relevance(
                title,
                snippet,
                url,
                query,
            )
            >= 3
        )

    return _research_candidate_relevance(
        title,
        snippet,
        url,
    ) >= 3

def _research_canonical_url(href):
    href = str(href or "").strip()

    if not href:
        return ""

    try:
        from urllib.parse import (
            parse_qs,
            unquote,
            urlparse,
        )
        import base64

        parsed = urlparse(href)
        query = parse_qs(
            parsed.query
        )

        # Google redirect.
        for key in (
            "q",
            "url",
        ):
            values = query.get(key)

            if values:
                target = unquote(
                    str(values[0])
                )

                if target.startswith(
                    (
                        "http://",
                        "https://",
                    )
                ):
                    return target

        # Bing redirect.
        values = query.get("u")

        if values:
            target = str(values[0])

            if target.startswith("a1"):
                encoded = target[2:]

                padding = "=" * (
                    (-len(encoded)) % 4
                )

                try:
                    decoded = base64.urlsafe_b64decode(
                        encoded + padding
                    ).decode(
                        "utf-8",
                        errors="ignore",
                    )

                    if decoded.startswith(
                        (
                            "http://",
                            "https://",
                        )
                    ):
                        return decoded
                except Exception:
                    pass

            target = unquote(target)

            if target.startswith(
                (
                    "http://",
                    "https://",
                )
            ):
                return target

    except Exception:
        pass

    if href.startswith(
        (
            "http://",
            "https://",
        )
    ):
        return href

    return ""


def _research_html_text(
    html_text,
):
    parser = _ResearchHTMLParser()

    try:
        parser.feed(
            str(html_text or "")
        )
        parser.close()
    except Exception:
        pass

    return (
        parser.title,
        parser.text[
            :_RESEARCH_TEXT_LIMIT
        ],
    )



class _ResearchLinkParser(HTMLParser):
    """
    Provider-independent HTML anchor parser.

    Search engines frequently change their surrounding result DOM,
    but their result links are still ordinary <a href="..."> elements.
    """

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.results = []
        self._href = None
        self._text_parts = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            if self._href is not None:
                self._depth += 1
            return

        if self._href is not None:
            self._depth += 1
            return

        attributes = dict(attrs)
        href = attributes.get("href")

        if href:
            self._href = href
            self._text_parts = []
            self._depth = 0

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            if self._depth > 0:
                self._depth -= 1
                return

            text = " ".join(
                " ".join(
                    self._text_parts
                ).split()
            )

            self.results.append(
                {
                    "href": self._href,
                    "text": text,
                }
            )

            self._href = None
            self._text_parts = []
            self._depth = 0

    def handle_data(self, data):
        if self._href is not None:
            clean = " ".join(
                str(data or "").split()
            )

            if clean:
                self._text_parts.append(
                    clean
                )



def _research_http_search(
    engine,
    query,
):
    """
    Search discovery using a hidden Playwright browser.

    Google is the primary provider.
    Bing is the fallback.

    Important:
    We extract actual search-result elements instead of treating every
    page anchor as a candidate. This avoids navigation/UI links
    overwhelming the relevance filter.
    """

    engine = str(
        engine or ""
    ).lower().strip()

    query = str(
        query or ""
    ).strip()

    if engine not in {
        "google",
        "bing",
    }:
        raise ValueError(
            f"Unsupported research search engine: {engine!r}"
        )

    endpoint = (
        "https://www.google.com/search"
        if engine == "google"
        else "https://www.bing.com/search"
    )

    encoded_query = requests.utils.quote(
        query,
        safe="",
    )

    search_url = (
        f"{endpoint}?q={encoded_query}"
        f"&hl=en&num=10"
    )

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        f"headless {engine} search: {query}"
    )

    try:
        from playwright.sync_api import (
            sync_playwright,
        )

        with sync_playwright() as playwright:

            browser = playwright.chromium.launch(
                headless=True,
            )

            try:
                context = browser.new_context(
                    viewport={
                        "width": 1440,
                        "height": 1000,
                    },
                    user_agent=_RESEARCH_HEADERS[
                        "User-Agent"
                    ],
                    locale="en-US",
                )

                page = context.new_page()

                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=(
                        _RESEARCH_HEADLESS_TIMEOUT
                        * 1000
                    ),
                )

                page.wait_for_timeout(
                    1800
                )

                current_url = (
                    page.url or ""
                )

                page_title = (
                    page.title() or ""
                )

                try:
                    body_text = (
                        page.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )
                        or ""
                    )
                except Exception:
                    body_text = ""

                combined = (
                    current_url
                    + "\n"
                    + page_title
                    + "\n"
                    + body_text
                ).lower()

                blocked_markers = (
                    "google.com/sorry",
                    "unusual traffic",
                    "captcha",
                    "recaptcha",
                    "not a robot",
                    "verify you are human",
                    "prove your humanity",
                    "access denied",
                    "checking your browser",
                    "before you continue",
                )

                if any(
                    marker in combined
                    for marker in blocked_markers
                ):
                    print(
                        "[JARVIS] JARVIS PRODUCT RESEARCH: "
                        f"headless {engine} search blocked."
                    )

                    return {
                        "blocked": True,
                        "results": [],
                    }

                # =================================================
                # Provider-specific result selectors
                # =================================================

                selectors = (
                    [
                        # Google current/legacy result links.
                        "div#search a:has(h3)",
                        "div#search h3",
                    ]
                    if engine == "google"
                    else [
                        # Bing standard organic results.
                        "li.b_algo h2 a",
                        "#b_results li.b_algo h2 a",
                        "#b_results h2 a",
                        "li.b_algo a[href]",
                    ]
                )

                result_elements = []

                for selector in selectors:
                    try:
                        locator = page.locator(
                            selector
                        )

                        count = locator.count()

                        if count:
                            print(
                                "[JARVIS] "
                                "JARVIS PRODUCT RESEARCH: "
                                f"{engine} selector "
                                f"{selector!r} found {count}"
                            )

                            for index in range(
                                min(
                                    count,
                                    20,
                                )
                            ):
                                result_elements.append(
                                    locator.nth(
                                        index
                                    )
                                )

                            if len(
                                result_elements
                            ) >= 10:
                                break

                    except Exception:
                        continue

                # =================================================
                # Generic fallback if provider selector changed.
                # =================================================

                if not result_elements:
                    try:
                        all_links = page.locator(
                            "a[href]"
                        )

                        count = all_links.count()

                        print(
                            "[JARVIS] "
                            "JARVIS PRODUCT RESEARCH: "
                            f"{engine} generic fallback "
                            f"found {count} links"
                        )

                        for index in range(
                            min(
                                count,
                                100,
                            )
                        ):
                            link = all_links.nth(
                                index
                            )

                            try:
                                href = (
                                    link.get_attribute(
                                        "href"
                                    )
                                    or ""
                                )

                                anchor_text = (
                                    link.inner_text()
                                    or ""
                                ).strip()

                            except Exception:
                                continue

                            if not href:
                                continue

                            if len(
                                anchor_text
                            ) < 5:
                                continue

                            # Only keep links that look like real
                            # search results.
                            if (
                                engine == "bing"
                                and not (
                                    _research_domain(
                                        href
                                    )
                                    or href.startswith(
                                        "/"
                                    )
                                )
                            ):
                                continue

                            class_text = ""

                            try:
                                class_text = (
                                    link.get_attribute(
                                        "class"
                                    )
                                    or ""
                                ).lower()
                            except Exception:
                                pass

                            if (
                                "nav" in class_text
                                or "header" in class_text
                                or "footer" in class_text
                            ):
                                continue

                            result_elements.append(
                                link
                            )

                            if len(
                                result_elements
                            ) >= 20:
                                break

                    except Exception:
                        pass

                print(
                    "[JARVIS] JARVIS PRODUCT RESEARCH: "
                    f"{engine} candidate result "
                    f"elements={len(result_elements)}"
                )

                results = []
                seen = set()

                from urllib.parse import (
                    urljoin,
                )
                from html import unescape

                for element in result_elements:

                    try:
                        href = (
                            element.get_attribute(
                                "href"
                            )
                            or ""
                        ).strip()

                        title = (
                            element.inner_text()
                            or ""
                        ).strip()

                    except Exception:
                        continue

                    if not href:
                        continue

                    href = unescape(
                        href
                    )

                    title = unescape(
                        " ".join(
                            title.split()
                        )
                    )

                    if href.startswith(
                        "/"
                    ):
                        href = urljoin(
                            search_url,
                            href,
                        )

                    elif href.startswith(
                        "//"
                    ):
                        href = (
                            "https:"
                            + href
                        )

                    canonical = (
                        _research_canonical_url(
                            href
                        )
                    )

                    if not canonical:
                        canonical = href

                    domain = _research_domain(
                        canonical
                    )

                    if not domain:
                        continue

                    # Bing can ignore site: operators. Enforce the
                    # requested domain ourselves so unrelated results never
                    # masquerade as site-constrained evidence.
                    requested_domain = _research_requested_domain(query)
                    if requested_domain and not (
                        domain == requested_domain
                        or domain.endswith("." + requested_domain)
                    ):
                        continue

                    if (
                        domain == "google.com"
                        or domain.endswith(
                            ".google.com"
                        )
                        or domain == "bing.com"
                        or domain.endswith(
                            ".bing.com"
                        )
                    ):
                        continue

                    # Telecom providers are context-dependent.
                    # They are valid for phone/internet/networking
                    # research, but not unrelated product topics.
                    if _research_domain_matches(
                        domain,
                        _RESEARCH_TELECOM_DOMAINS,
                    ):
                        if not _research_query_is_telecom(
                            query
                        ):
                            continue

                    if len(title) < 4:
                        title = domain

                    key = (
                        canonical
                        .lower()
                        .rstrip("/")
                    )

                    if key in seen:
                        continue

                    source_type = (
                        _research_source_type(
                            canonical,
                            title,
                        )
                    )

                    relevance = (
                        _research_query_relevance(
                            title,
                            "",
                            canonical,
                            query,
                        )
                    )

                    recognized_domain = (
                        _research_domain_matches(
                            domain,
                            _RESEARCH_VIDEO_DOMAINS,
                        )
                        or _research_domain_matches(
                            domain,
                            _RESEARCH_COMMUNITY_DOMAINS,
                        )
                        or _research_domain_matches(
                            domain,
                            _RESEARCH_RETAILER_DOMAINS,
                        )
                        or _research_domain_matches(
                            domain,
                            _RESEARCH_MANUFACTURER_DOMAINS,
                        )
                        or _research_domain_matches(
                            domain,
                            _RESEARCH_REVIEW_DOMAINS,
                        )
                    )

                    # Result-specific selectors are useful evidence,
                    # but the result still needs to match the query.
                    #
                    # Known retailers/community/video/manufacturer/review
                    # domains receive a small allowance, but arbitrary
                    # irrelevant pages do not.
                    if relevance < 3:
                        if not recognized_domain:
                            continue

                        if not any(
                            term in (
                                " ".join(
                                    (
                                        title,
                                        canonical,
                                    )
                                ).lower()
                            )
                            for term in _research_query_focus_terms(
                                query
                            )
                        ):
                            continue

                    seen.add(
                        key
                    )

                    results.append(
                        {
                            "title": title[:500],
                            "url": canonical,
                            "domain": domain,
                            "source_type": source_type,
                            "snippet": "",
                            "query": query,
                        }
                    )

                    if len(
                        results
                    ) >= 20:
                        break

                print(
                    "[JARVIS] JARVIS PRODUCT RESEARCH: "
                    f"{engine} produced "
                    f"{len(results)} candidate(s)"
                )

                if not results:
                    print(
                        "[JARVIS] "
                        "JARVIS PRODUCT RESEARCH: "
                        f"{engine} result extraction "
                        "returned no accepted links."
                    )

                    # Diagnostics: expose the first few actual
                    # result element href/title pairs.
                    for element in (
                        result_elements[:8]
                    ):
                        try:
                            print(
                                "[JARVIS] SEARCH RESULT DEBUG:",
                                (
                                    element.get_attribute(
                                        "href"
                                    )
                                    or ""
                                )[:300],
                                "|",
                                (
                                    element.inner_text()
                                    or ""
                                ).strip()[:200],
                            )
                        except Exception:
                            pass

                return {
                    "blocked": False,
                    "results": results,
                }

            finally:
                context.close()
                browser.close()

    except Exception as exc:
        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            f"headless {engine} search failed: {exc}"
        )

        return {
            "blocked": False,
            "results": [],
        }

def _research_enough_sources(
    sources,
):
    types = {}

    for source in sources:
        source_type = source.get(
            "source_type"
        )
        types[source_type] = (
            types.get(
                source_type,
                0,
            )
            + 1
        )

    has_core_coverage = (
        len(sources) >= 12
        and types.get(
            "independent_review",
            0,
        ) >= 3
        and types.get(
            "retailer",
            0,
        ) >= 2
        and types.get(
            "manufacturer",
            0,
        ) >= 1
        and (
            types.get(
                "community",
                0,
            ) >= 1
            or types.get(
                "video",
                0,
            ) >= 1
        )
    )

    if has_core_coverage:
        return True

    # Reaching the candidate ceiling without core coverage should not
    # terminate discovery prematurely. Continue through the remaining
    # targeted queries so a missing manufacturer/community/video family
    # still has a chance to contribute.
    return False

    return False


def _research_requested_domain(query):
    """Return the normalized site: domain requested by a query, if any."""
    match = re.search(
        r"\bsite:\s*([a-z0-9.-]+)",
        str(query or "").lower(),
    )
    if not match:
        return ""
    return match.group(1).strip().removeprefix("www.")


def _research_add_results(
    discovered,
    results,
    seen_urls,
    *,
    engine="",
    query="",
):
    requested_domain = _research_requested_domain(query)

    for result in results:
        if not isinstance(result, dict):
            continue

        url = str(result.get("url") or "").strip()
        if not url or url in seen_urls:
            continue

        normalized = dict(result)
        normalized["engine"] = str(
            normalized.get("engine") or engine or ""
        ).strip().lower()
        normalized["query"] = str(
            normalized.get("query") or query or ""
        ).strip()
        normalized["requested_domain"] = requested_domain

        result_domain = str(
            normalized.get("domain") or _research_domain(url) or ""
        ).strip().lower().removeprefix("www.")
        normalized["domain"] = result_domain
        normalized["requested_domain_match"] = bool(
            requested_domain
            and (
                result_domain == requested_domain
                or result_domain.endswith("." + requested_domain)
            )
        )

        seen_urls.add(url)
        discovered.append(normalized)

        if len(discovered) >= _RESEARCH_MAX_DISCOVERY:
            break


def _research_http_fetch(url):
    try:
        response = requests.get(
            url,
            headers=_RESEARCH_HEADERS,
            timeout=_RESEARCH_HTTP_TIMEOUT,
            allow_redirects=True,
        )

    except Exception as exc:
        return {
            "success": False,
            "blocked": False,
            "status": None,
            "url": url,
            "title": "",
            "text": "",
            "method": "http",
            "error": str(exc),
        }

    body = response.text or ""

    lower = body.lower()

    block_markers = (
        "prove your humanity",
        "captcha",
        "recaptcha",
        "verify you are human",
        "not a robot",
        "unusual traffic",
        "access denied",
        "checking your browser",
        "checking you are a real head-fi'er",
        "help us keep head-fi secure",
        "looks like something is not right, please wait",
        "security check",
        "just a moment",
    )

    blocked = any(
        marker in lower
        for marker in block_markers
    )

    content_type = (
        response.headers.get(
            "content-type",
            "",
        ).lower()
    )

    if (
        "text/html" in content_type
        or "<html" in lower[:5000]
    ):
        title, readable = _research_html_text(
            body
        )
    else:
        title = ""
        readable = " ".join(
            body.split()
        )[:_RESEARCH_TEXT_LIMIT]

    return {
        "success": (
            response.status_code < 400
            and bool(readable)
            and not blocked
        ),
        "blocked": blocked,
        "status": response.status_code,
        "url": str(response.url or url),
        "title": title,
        "text": readable,
        "method": "http",
        "error": "",
    }


def _research_headless_fetch(url):
    """
    Hidden Playwright fallback.

    This is NOT the user's visible JARVIS browser.
    It exists only for pages that cannot be extracted cleanly with HTTP.
    """

    try:
        from playwright.sync_api import (
            sync_playwright,
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
            )

            try:
                page = browser.new_page(
                    viewport={
                        "width": 1440,
                        "height": 1000,
                    },
                    user_agent=_RESEARCH_HEADERS[
                        "User-Agent"
                    ],
                )

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=(
                        _RESEARCH_HEADLESS_TIMEOUT
                        * 1000
                    ),
                )

                page.wait_for_timeout(
                    1500
                )

                title = page.title() or ""

                try:
                    readable = page.locator(
                        "body"
                    ).inner_text(
                        timeout=5000
                    )
                except Exception:
                    readable = ""

                readable = " ".join(
                    readable.split()
                )[
                    :_RESEARCH_TEXT_LIMIT
                ]

                combined = (
                    title
                    + "\n"
                    + readable
                ).lower()

                blocked = any(
                    marker in combined
                    for marker in (
                        "prove your humanity",
                        "captcha",
                        "recaptcha",
                        "verify you are human",
                        "not a robot",
                        "unusual traffic",
                        "access denied",
                        "checking your browser",
                        "checking you are a real head-fi'er",
                        "help us keep head-fi secure",
                        "looks like something is not right, please wait",
                        "security check",
                        "just a moment",
                    )
                )

                final_url = page.url

                return {
                    "success": (
                        bool(readable)
                        and not blocked
                    ),
                    "blocked": blocked,
                    "status": None,
                    "url": final_url,
                    "title": title,
                    "text": readable,
                    "method": "headless",
                    "error": "",
                }

            finally:
                browser.close()

    except Exception as exc:
        return {
            "success": False,
            "blocked": False,
            "status": None,
            "url": url,
            "title": "",
            "text": "",
            "method": "headless",
            "error": str(exc),
        }


def _research_fetch_source(
    source,
):
    original_url = str(
        source.get("url") or ""
    ).strip()

    if not original_url:
        return {
            "success": False,
            "blocked": False,
            "status": None,
            "url": "",
            "title": source.get("title") or "",
            "text": "",
            "method": "none",
            "error": "Missing URL",
        }

    candidates = [original_url]

    # Preserve the Reddit fallback logic already added to this file.
    fallback_builder = globals().get(
        "_source_visit_urls"
    )

    if callable(
        fallback_builder
    ):
        try:
            candidates = list(
                fallback_builder(
                    source
                )
                or candidates
            )
        except Exception:
            pass

    attempted = []

    for candidate_url in candidates:
        attempted.append(
            candidate_url
        )

        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            f"HTTP fetch {candidate_url}"
        )

        fetched = _research_http_fetch(
            candidate_url
        )

        if fetched.get("success"):
            fetched[
                "original_url"
            ] = original_url
            return fetched

        if fetched.get("blocked"):
            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                f"HTTP blocked/challenged: "
                f"{candidate_url}"
            )
            continue

        # HTTP returned a legitimate but tiny page.
        # Try headless before declaring failure.
        if (
            fetched.get("status") is not None
            and fetched.get("status") < 400
            and not fetched.get("text")
        ):
            continue

    # JavaScript/browser fallback, still completely hidden.
    for candidate_url in attempted:
        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            f"headless fallback {candidate_url}"
        )

        fetched = _research_headless_fetch(
            candidate_url
        )

        if fetched.get("success"):
            fetched[
                "original_url"
            ] = original_url
            return fetched

        if fetched.get("blocked"):
            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                f"headless page blocked/challenged: "
                f"{candidate_url}"
            )

    return {
        "success": False,
        "blocked": False,
        "status": None,
        "url": original_url,
        "title": source.get("title") or "",
        "text": "",
        "method": "none",
        "error": "No usable research content",
        "original_url": original_url,
    }


def _discover(queries):
    """
    Google-first research discovery with deterministic coverage seeds.

    Google is the default provider.
    Bing is used after Google is blocked or accumulated coverage is still
    insufficient. Direct retailer/community/video search seeds are inserted
    first so search-engine quirks cannot starve those source categories.
    """

    discovered = []
    seen_urls = set()

    seed_item = ""
    if queries:
        # The first query may contain research instructions such as
        # "reviews under $150". Prefer the quoted subject when present so
        # direct store/community/video seeds search for the actual item.
        quoted_subjects = re.findall(
            r'"([^"]+)"',
            str(queries[0] or ""),
        )
        if quoted_subjects:
            seed_item = str(
                quoted_subjects[0]
                or ""
            ).strip()
        else:
            seed_item = str(
                _extract_item_and_budget(
                    queries[0]
                )[0]
                or ""
            ).strip()

    # --------------------------------------------------------
    # Coverage seeds
    # --------------------------------------------------------
    #
    # Search providers have repeatedly ignored site: operators in this
    # environment. Seed the important source families directly before
    # general discovery so they are guaranteed a chance to be selected.
    # The seeds are candidates only; evidence is still fetched and must
    # pass the normal content-quality checks later.
    # --------------------------------------------------------

    if seed_item:
        encoded_item = requests.utils.quote(
            seed_item,
            safe="",
        )

        retailer_seeds = (
            ("amazon.com", "https://www.amazon.com/s?k={q}"),
            ("bestbuy.com", "https://www.bestbuy.com/site/searchpage.jsp?st={q}"),
            ("walmart.com", "https://www.walmart.com/search?q={q}"),
            ("bhphotovideo.com", "https://www.bhphotovideo.com/c/search?q={q}&sts=ma"),
        )

        for domain, template in retailer_seeds:
            _research_add_results(
                discovered,
                [
                    {
                        "title": f"{seed_item} {domain} search results",
                        "url": template.format(q=encoded_item),
                        "domain": domain,
                        "source_type": "retailer",
                        "snippet": "",
                    }
                ],
                seen_urls,
                engine="seed",
                query=f"{seed_item} retailer",
            )

        community_seeds = (
            (
                "reddit.com",
                f"https://www.reddit.com/search/?q={encoded_item}&type=link",
                "reddit discussions",
            ),
        )

        for domain, url, label in community_seeds:
            _research_add_results(
                discovered,
                [
                    {
                        "title": f"{seed_item} {label}",
                        "url": url,
                        "domain": domain,
                        "source_type": "community",
                        "snippet": "",
                    }
                ],
                seen_urls,
                engine="seed",
                query=f"{seed_item} community discussion",
            )

        _research_add_results(
            discovered,
            [
                {
                    "title": f"{seed_item} YouTube reviews and comparisons",
                    "url": (
                        "https://www.youtube.com/results"
                        f"?search_query={encoded_item}%20review"
                    ),
                    "domain": "youtube.com",
                    "source_type": "video",
                    "snippet": "",
                }
            ],
            seen_urls,
            engine="seed",
            query=f"{seed_item} video review",
        )

    google_blocked = False

    # --------------------------------------------------------
    # Phase 1: Google
    # --------------------------------------------------------

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        "discovery provider = Google"
    )

    for query in queries:
        if google_blocked:
            break

        result = _research_http_search(
            "google",
            query,
        )

        if result.get("blocked"):
            google_blocked = True

            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                "Google HTTP search is blocked; "
                "switching to Bing fallback."
            )

            break

        candidates = result.get(
            "results",
            [],
        )

        _research_add_results(
            discovered,
            candidates,
            seen_urls,
            engine="google",
            query=query,
        )

        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            f"google returned "
            f"{len(candidates)} relevant candidate(s) "
            f"for query={query!r}"
        )

        if _research_enough_sources(
            discovered
        ):
            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                "Google produced sufficient source coverage."
            )
            break

    # --------------------------------------------------------
    # Phase 2: Bing fallback
    # --------------------------------------------------------

    if not _research_enough_sources(
        discovered
    ):
        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            "Google coverage insufficient; "
            "using Bing fallback."
        )

        for query in queries:
            result = _research_http_search(
                "bing",
                query,
            )

            candidates = result.get(
                "results",
                [],
            )

            _research_add_results(
                discovered,
                candidates,
                seen_urls,
                engine="bing",
                query=query,
            )

            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                f"bing returned "
                f"{len(candidates)} relevant candidate(s) "
                f"for query={query!r}"
            )

            if _research_enough_sources(
                discovered
            ):
                break

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        f"discovery complete: "
        f"{len(discovered)} candidate source(s)"
    )

    return discovered

def _choose_sources(discovered):
    """
    Select relevant, diverse product-research sources.

    Known review, manufacturer, community, video, and retailer domains are
    preferred over arbitrary web-source domains. Unknown web sources remain
    available as fallback evidence, but cannot consume most of the research
    budget when stronger source families are present.
    """

    quotas = {
        "manufacturer": 2,
        "independent_review": 4,
        "retailer": 2,
        "video": 1,
        "community": 1,
    }

    max_generic_web_sources = 2

    selected = []
    domains = set()

    known_video = {
        "youtube.com",
        "youtu.be",
    }

    known_community = {
        "reddit.com",
        "head-fi.org",
        "avforums.com",
        "headphones.com",
        "forum.headphones.com",
        "forums.tomshardware.com",
        "linustechtips.com",
        "slickdeals.net",
    }

    known_retailers = {
        "amazon.com",
        "bestbuy.com",
        "walmart.com",
        "target.com",
        "newegg.com",
        "bhphotovideo.com",
        "costco.com",
        "microcenter.com",
        "crutchfield.com",
        "adorama.com",
        "samsclub.com",
        "woot.com",
        "homedepot.com",
        "lowes.com",
        "ebay.com",
    }

    known_manufacturers = set(
        _RESEARCH_MANUFACTURER_DOMAINS
    )

    known_reviews = set(
        _RESEARCH_REVIEW_DOMAINS
    )

    telecom_domains = {
        "verizon.com",
        "att.com",
        "t-mobile.com",
        "assurancewireless.com",
        "visible.com",
        "cricketwireless.com",
        "metrobyt-mobile.com",
        "boostmobile.com",
        "mintmobile.com",
        "uscellular.com",
        "spectrum.com",
        "xfinity.com",
        "straighttalk.com",
        "tracfone.com",
        "usmobile.com",
        "consumerwireless.com",
    }

    def normalize_domain(source):
        domain = str(
            source.get("domain") or ""
        ).strip().lower()

        if not domain:
            url = str(
                source.get("url") or ""
            ).strip().lower()

            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except Exception:
                domain = ""

        if domain.startswith("www."):
            domain = domain[4:]

        return domain

    def domain_matches(domain, known_domains):
        return any(
            domain == known
            or domain.endswith("." + known)
            for known in known_domains
        )

    def forced_source_type(source, current_type):
        domain = normalize_domain(source)

        if domain_matches(domain, known_video):
            return "video"

        if domain_matches(domain, known_community):
            return "community"

        if domain_matches(domain, known_retailers):
            return "retailer"

        if domain_matches(domain, known_manufacturers):
            return "manufacturer"

        if domain_matches(domain, known_reviews):
            return "independent_review"

        return current_type or "web_source"

    def source_relevance(source):
        return _research_query_relevance(
            source.get("title"),
            source.get("snippet"),
            source.get("url"),
            source.get("query") or "",
        )

    def source_priority(source):
        """
        Deterministic quality-aware priority.

        This is intentionally not a product recommendation score. It only
        controls which source families are trusted first when building the
        evidence packet for synthesis.
        """
        source_type = str(
            source.get("source_type") or "web_source"
        )

        domain = normalize_domain(source)
        relevance = source.get(
            "_relevance_score",
            0,
        )

        if source_type == "independent_review":
            base = 100
        elif source_type == "manufacturer":
            base = 95
        elif source_type == "community":
            base = 90
        elif source_type == "video":
            base = 85
        elif source_type == "retailer":
            base = 80
        else:
            base = 0

        if domain_matches(
            domain,
            known_reviews,
        ):
            base += 15

        if domain_matches(
            domain,
            known_manufacturers,
        ):
            base += 12

        if domain_matches(
            domain,
            known_community,
        ):
            base += 10

        if domain_matches(
            domain,
            known_video,
        ):
            base += 8

        if domain_matches(
            domain,
            known_retailers,
        ):
            base += 8

        if source.get("requested_domain_match"):
            base += 4

        return base + float(
            relevance or 0
        )

    def is_irrelevant(source):
        domain = normalize_domain(source)

        if not domain:
            return True

        query = str(
            source.get("query") or ""
        )

        if domain_matches(
            domain,
            telecom_domains,
        ):
            if not _research_query_is_telecom(
                query
            ):
                return True

        return source_relevance(source) < 3

    clean_sources = []

    for source in discovered:
        if not isinstance(source, dict):
            continue

        if is_irrelevant(source):
            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                f"filtered irrelevant source: "
                f"{normalize_domain(source)} | "
                f"{source.get('title')}"
            )
            continue

        normalized = dict(source)

        normalized["domain"] = normalize_domain(
            source
        )

        normalized["source_type"] = forced_source_type(
            source,
            source.get("source_type"),
        )

        normalized["_relevance_score"] = source_relevance(
            normalized
        )

        normalized["_priority_score"] = source_priority(
            normalized
        )

        clean_sources.append(
            normalized
        )

    by_type = {}

    for source in clean_sources:
        by_type.setdefault(
            source.get("source_type"),
            []
        ).append(source)

    # Prefer the strongest known source within each category. Unknown
    # web_source candidates are handled separately as a fallback.
    for source_type in by_type:
        by_type[source_type].sort(
            key=lambda item: (
                item.get(
                    "_priority_score",
                    0,
                ),
                item.get(
                    "_relevance_score",
                    0,
                ),
            ),
            reverse=True,
        )

    # Satisfy the source-family quotas first.
    for source_type, quota in quotas.items():
        count = 0

        for source in by_type.get(source_type, []):
            if len(selected) >= MAX_SOURCES:
                break

            domain = normalize_domain(source)

            if not domain or domain in domains:
                continue

            selected.append(source)
            domains.add(domain)
            count += 1

            if count >= quota:
                break

        if len(selected) >= MAX_SOURCES:
            break

    # Fill every remaining slot with another recognized source before
    # allowing arbitrary web_source fallback pages. This prevents low-quality
    # SEO/specification aggregators from displacing useful review/community/
    # retailer/manufacturer evidence.
    if len(selected) < MAX_SOURCES:
        remaining = [
            source
            for source in clean_sources
            if (
                normalize_domain(source) not in domains
                and source.get("source_type") != "web_source"
            )
        ]

        remaining.sort(
            key=lambda item: (
                item.get(
                    "_priority_score",
                    0,
                ),
                item.get(
                    "_relevance_score",
                    0,
                ),
            ),
            reverse=True,
        )

        for source in remaining:
            if len(selected) >= MAX_SOURCES:
                break

            domain = normalize_domain(source)

            if not domain or domain in domains:
                continue

            selected.append(source)
            domains.add(domain)

    # Only use arbitrary web_source candidates as a final fallback.
    generic_candidates = [
        source
        for source in by_type.get(
            "web_source",
            [],
        )
        if normalize_domain(source) not in domains
    ]

    generic_candidates.sort(
        key=lambda item: (
            item.get(
                "_priority_score",
                0,
            ),
            item.get(
                "_relevance_score",
                0,
            ),
        ),
        reverse=True,
    )

    generic_count = 0

    for source in generic_candidates:
        if len(selected) >= MAX_SOURCES:
            break

        if generic_count >= max_generic_web_sources:
            break

        domain = normalize_domain(source)

        if not domain or domain in domains:
            continue

        selected.append(source)
        domains.add(domain)
        generic_count += 1

    for source in selected:
        source.pop(
            "_relevance_score",
            None,
        )
        source.pop(
            "_priority_score",
            None,
        )

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



def _source_visit_blocked(snapshot):
    """
    Detect pages that were reached successfully but did not provide
    usable research content because an anti-bot / CAPTCHA page was shown.
    """
    snapshot = snapshot or {}

    url = str(snapshot.get("url") or "").lower()
    title = str(snapshot.get("title") or "").lower()
    readable = str(snapshot.get("readable_text") or "").lower()

    combined = f"{url}\n{title}\n{readable}"

    blocked_markers = (
        "prove your humanity",
        "captcha",
        "recaptcha",
        "verify you are human",
        "not a robot",
        "checking your browser",
        "checking you are a real head-fi'er",
        "help us keep head-fi secure",
        "looks like something is not right, please wait",
        "security check",
        "unusual traffic",
        "access denied",
        "just a moment",
    )

    return any(marker in combined for marker in blocked_markers)


def _source_visit_urls(source):
    """
    Return browser URLs to try for a source.

    Reddit gets alternate endpoints because the normal Reddit HTML page
    may present an anti-bot challenge even though the source itself is valid.
    """
    url = str(source.get("url") or "").strip()

    if not url:
        return []

    urls = [url]

    source_type = str(source.get("source_type") or "").lower()

    if source_type == "community" and "reddit.com/" in url.lower():
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)

            path = (parsed.path or "").rstrip("/")

            if path:
                # Old Reddit HTML fallback.
                urls.append(
                    f"https://old.reddit.com{path}"
                )

                # Reddit JSON fallback.
                if "/comments/" in path:
                    urls.append(
                        f"https://www.reddit.com{path}.json"
                    )
                    urls.append(
                        f"https://old.reddit.com{path}.json"
                    )

        except Exception:
            pass

    # De-duplicate while retaining order.
    return list(dict.fromkeys(urls))




def _wait_for_research_page(
    timeout=12.0,
    poll_interval=0.75,
):
    """
    Wait for the currently loaded browser page to produce meaningful
    readable content.

    Some sites return control from browser_goto() before the page's
    useful DOM/text has finished rendering. Polling the snapshot avoids
    capturing an almost-empty page too early.
    """

    started = time.monotonic()

    best_snapshot = {}

    previous_text = ""
    stable_count = 0

    while (time.monotonic() - started) < timeout:
        try:
            snapshot = browser_page_snapshot() or {}
        except Exception:
            snapshot = {}

        if snapshot:
            best_snapshot = snapshot

        readable = str(
            snapshot.get("readable_text") or ""
        ).strip()

        title = str(
            snapshot.get("title") or ""
        ).strip()

        # Stop immediately for known anti-bot / CAPTCHA pages.
        if _source_visit_blocked(snapshot):
            return snapshot

        # Meaningful page content.
        if len(readable) >= 800:
            if readable == previous_text:
                stable_count += 1
            else:
                stable_count = 0

            previous_text = readable

            # Two consecutive identical snapshots means the page has
            # probably finished changing.
            if stable_count >= 1:
                return snapshot

        # A page may have a meaningful title but need more time to
        # populate the readable DOM.
        elif title and len(readable) >= 250:
            previous_text = readable

        time.sleep(poll_interval)

    return best_snapshot


def _research_evidence_has_core_coverage(evidence):
    types = {}
    for source in evidence:
        source_type = str(source.get("source_type") or "")
        types[source_type] = types.get(source_type, 0) + 1
    return (
        len(evidence) >= 8
        and types.get("independent_review", 0) >= 3
        and types.get("retailer", 0) >= 2
        and types.get("manufacturer", 0) >= 1
        and (
            types.get("video", 0) >= 1
            or types.get("community", 0) >= 1
        )
    )


def _collect_one_evidence(index, source):
    domain = str(source.get("domain") or "")
    source_type = str(
        source.get("source_type")
        or _research_source_type(
            source.get("url"),
            source.get("title"),
        )
    )

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        f"researching source {index} [{source_type}] {domain}"
    )

    fetched = _research_fetch_source(source)
    readable = " ".join(str(fetched.get("text") or "").split())[:_RESEARCH_TEXT_LIMIT]
    title = str(fetched.get("title") or source.get("title") or "").strip()
    final_url = str(fetched.get("url") or source.get("url") or "").strip()
    success = bool(fetched.get("success")) and len(readable) >= 200

    if success and source_type == "community":
        lower_text = readable.lower()
        discussion_markers = (
            "reply", "replies", "comments", "posted", "thread",
            "threads", "user review", "owner review", "discussion", "members",
        )
        has_discussion = any(marker in lower_text for marker in discussion_markers)
        has_product_context = any(marker in lower_text for marker in _RESEARCH_PRODUCT_TERMS)
        if not (has_discussion and has_product_context):
            success = False

    if not success:
        print(
            "[JARVIS] JARVIS PRODUCT RESEARCH: "
            f"NO USABLE EVIDENCE [{source_type}] {domain}"
        )
        return None

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        f"EVIDENCE OK [{source_type}] {domain} method={fetched.get('method')} chars={len(readable)}"
    )

    return {
        "id": index,
        "engine": str(source.get("engine") or "").strip(),
        "query": str(source.get("query") or "").strip(),
        "requested_domain": str(source.get("requested_domain") or "").strip(),
        "requested_domain_match": bool(source.get("requested_domain_match")),
        "source_type": source_type,
        "domain": domain,
        "title": title,
        "url": final_url,
        "original_url": source.get("url"),
        "access_status": "visited",
        "research_method": fetched.get("method") or "none",
        "text": readable,
        "snippet": source.get("snippet") or "",
        "numeric_hints": _numeric_hints(" ".join([title, str(source.get("title") or ""), str(source.get("snippet") or ""), readable])),
    }


def _collect_evidence(sources):
    """Collect research evidence in concurrent waves and stop once coverage is sufficient."""
    evidence = []
    indexed = list(enumerate(sources, 1))
    batch_size = 4

    for offset in range(0, len(indexed), batch_size):
        batch = indexed[offset:offset + batch_size]
        with ThreadPoolExecutor(max_workers=min(batch_size, len(batch))) as executor:
            futures = [
                executor.submit(_collect_one_evidence, index, source)
                for index, source in batch
            ]
            results = []
            for future in futures:
                try:
                    result = future.result()
                except Exception as exc:
                    result = None
                    print(
                        "[JARVIS] JARVIS PRODUCT RESEARCH: source fetch worker failed: "
                        f"{exc}"
                    )
                if result:
                    results.append(result)

        evidence.extend(sorted(results, key=lambda item: item["id"]))

        if _research_evidence_has_core_coverage(evidence):
            print(
                "[JARVIS] JARVIS PRODUCT RESEARCH: "
                f"core evidence coverage satisfied after {len(evidence)} source(s)."
            )
            break

    return evidence

def _response_text(response: Any) -> str:
    """Extract assistant text from Ollama mappings or response objects."""
    if response is None:
        return ""

    message = (
        response.get("message")
        if isinstance(response, dict)
        else getattr(response, "message", None)
    )

    if message is None:
        return ""

    if isinstance(message, dict):
        return str(
            message.get("content")
            or message.get("response")
            or ""
        ).strip()

    content = getattr(message, "content", None)
    if content:
        return str(content).strip()

    return str(
        getattr(response, "response", "")
        or ""
    ).strip()


def _parse_json(text: str) -> dict[str, Any]:
    """Parse strict JSON plus common model wrappers/fallback representations."""
    raw = str(text or "").strip()
    if not raw:
        return {}

    candidates = [raw]

    if "```" in raw:
        unfenced = re.sub(
            r"^\s*```(?:json)?\s*|\s*```\s*$",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        if unfenced and unfenced != raw:
            candidates.append(unfenced)

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        value = ast.literal_eval(candidates[-1])
        if isinstance(value, dict):
            return value
    except (ValueError, SyntaxError, TypeError):
        pass

    preview = " ".join(raw.split())
    logger.warning(
        "JARVIS PRODUCT RESEARCH: synthesis returned unparseable JSON: "
        f"{preview[:500]!r}"
    )
    return {}



def _research_relevant_excerpt(
    source: dict[str, Any],
    max_chars: int,
) -> str:
    """
    Keep the product-bearing parts of a page instead of blindly taking the
    first N characters. Many modern sites put thousands of navigation words
    before the actual product list.
    """
    text = " ".join(
        str(source.get("text") or "").split()
    ).strip()

    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    source_type = str(
        source.get("source_type") or ""
    ).lower()

    anchors = (
        "best overall",
        "best budget",
        "best mid-range",
        "best cheap",
        "top pick",
        "top picks",
        "our picks",
        "recommended",
        "quick answer",
        "in-depth answer",
        "price",
        "msrp",
        "see price",
        "save",
        "battery life",
        "noise cancellation",
        "active noise cancellation",
        "anc",
        "tested",
        "rating",
        "reviews",
        "$",
    )

    lowered = text.lower()
    windows: list[tuple[int, int, int]] = []

    for anchor in anchors:
        start = 0
        while True:
            index = lowered.find(anchor, start)
            if index < 0:
                break

            left = max(0, index - 380)
            right = min(
                len(text),
                index + max(520, len(anchor) + 260),
            )

            # Slightly favor source-category-specific evidence.
            score = 1
            if source_type == "retailer" and anchor in {
                "price",
                "msrp",
                "rating",
                "reviews",
                "$",
            }:
                score += 4
            elif source_type == "manufacturer" and anchor in {
                "battery life",
                "noise cancellation",
                "active noise cancellation",
                "anc",
                "price",
                "msrp",
            }:
                score += 4
            elif source_type == "independent_review" and anchor in {
                "best overall",
                "best budget",
                "best mid-range",
                "top picks",
                "tested",
                "recommended",
            }:
                score += 4
            elif source_type == "video" and anchor in {
                "review",
                "tested",
                "battery life",
                "anc",
            }:
                score += 3
            elif source_type == "community" and anchor in {
                "reviews",
                "rating",
                "battery life",
                "anc",
            }:
                score += 3

            windows.append((left, right, score))
            start = index + max(1, len(anchor))

    # Merge overlaps so one source does not waste its entire budget repeating
    # the same sentence from many nearby anchors.
    windows.sort(key=lambda item: (item[0], -item[2]))

    merged: list[list[int]] = []
    for left, right, score in windows:
        if not merged or left > merged[-1][1] + 80:
            merged.append([left, right, score])
        else:
            merged[-1][1] = max(merged[-1][1], right)
            merged[-1][2] += score

    # Start with the highest-value windows, then restore document order.
    merged.sort(key=lambda item: item[2], reverse=True)

    selected: list[list[int]] = []
    used_chars = 0

    for left, right, _score in merged:
        span = right - left
        if selected and used_chars + span > max_chars:
            continue
        if not selected and span > max_chars:
            right = left + max_chars
            span = max_chars

        selected.append([left, right, 0])
        used_chars += span

        if used_chars >= max_chars:
            break

    # Always retain a little page context when possible.
    if not selected:
        return text[:max_chars]

    selected.sort(key=lambda item: item[0])

    parts = []
    for left, right, _ in selected:
        chunk = text[left:right].strip(" -:;,.")
        if chunk:
            parts.append(chunk)

    excerpt = " ... ".join(parts)

    # Fill unused budget from the start only when the relevant excerpts are
    # still short. This keeps source identity/context without restoring all
    # of the navigation boilerplate.
    if len(excerpt) < min(700, max_chars):
        prefix = text[:max_chars]
        excerpt = prefix + " ... " + excerpt

    return excerpt[:max_chars]


def _compact_evidence_for_synthesis(
    evidence: list[dict[str, Any]],
    per_source_chars: int = 2800,
) -> list[dict[str, Any]]:
    """
    Reduce navigation boilerplate while preserving product-bearing excerpts.
    """
    compact = []

    for source in evidence:
        if not isinstance(source, dict):
            continue

        compact.append(
            {
                "id": source.get("id"),
                "source_type": source.get("source_type"),
                "domain": source.get("domain"),
                "title": source.get("title"),
                "url": source.get("url"),
                "query": source.get("query"),
                "requested_domain": source.get("requested_domain"),
                "requested_domain_match": source.get(
                    "requested_domain_match"
                ),
                "snippet": " ".join(
                    str(source.get("snippet") or "").split()
                )[:800],
                "numeric_hints": source.get(
                    "numeric_hints"
                ) or {},
                "text": _research_relevant_excerpt(
                    source,
                    per_source_chars,
                ),
            }
        )

    return compact


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

    compact_evidence = _compact_evidence_for_synthesis(
        evidence,
        per_source_chars=1500,
    )

    prompt = f"""
You are JARVIS's evidence-constrained product research analyst.

USER REQUEST: {request}
ITEM / CATEGORY: {item}
{budget_note}

SOURCE EVIDENCE:
{json.dumps(
    compact_evidence,
    ensure_ascii=False,
)}

Use only the supplied evidence.
Never invent product names, prices, ratings, review counts,
specifications, or capabilities.
- A product must be a concrete identifiable model, not a category label.
- Never output generic names such as "Active Noise Cancelling Headphones",
  "Bluetooth Headphones", or "Wireless Headphones".
- Product names should normally include a brand plus model/family identifier
  (for example Sony WH-1000XM6 or Soundcore Space Q45).
Evidence rules:
- Manufacturer sources are strongest for specifications.
- Retailers are strongest for observed price and customer ratings.
- Independent reviews are strongest for testing/comparative analysis.
- Video and community sources are supporting evidence, not proof.
- Prefer agreement across independent domains and source types.
- State conflicts or stale pricing.
- When a maximum budget is supplied, it is a hard constraint. Do not
  designate a product as best_match, best_value, or another budget-oriented
  choice when its relevant listed/current price exceeds that maximum.
- For a hard-budget request, prioritize products explicitly described as
  budget/cheap picks or supported by an explicit non-MSRP price at or below
  the budget. Ignore stray dollar values near MSRP, savings, coupons, or ads.
- The best_match must come from the evidence-supported budget set. If the
  evidence only supports premium products above budget, leave best_match null
  rather than promoting a premium flagship.
- Include at least two budget-eligible candidates when the evidence supports
  them, so deterministic retailer verification has alternatives to check.
- Prefer a current verified retailer price at or below the budget over MSRP.
- Use null when evidence is missing.
- Cite factual claims with source IDs.

Keep the response compact. Return ONLY one valid JSON object.
Do not use markdown fences.
Do not add commentary before or after the JSON.
Limit products to the 4 most relevant models.
Limit comparisons to 2.
Keep pros/cons to at most 3 items each.
Keep tradeoffs and warnings to at most 3 items each.
Keep summary to 2 sentences.

JSON shape:
{{
  "summary": "",
  "confidence": "high|medium|low",
  "products": [
    {{
      "name": "",
      "model_number": null,
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
  "comparisons": [
    {{"product_a": "", "product_b": "", "comparison": "", "source_ids": []}}
  ],
  "tradeoffs": [],
  "warnings": []
}}
"""

    def run_synthesis(
        synthesis_prompt: str,
    ) -> dict[str, Any]:
        try:
            response = ModelManager().product_research(
                [
                    {
                        "role": "system",
                        "content": (
                            "Output one compact, valid JSON object only. "
                            "No markdown and no prose outside the JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": synthesis_prompt,
                    },
                ]
            )
        except Exception as exc:
            logger.warning(
                "JARVIS PRODUCT RESEARCH: synthesis failed: "
                f"{exc}"
            )
            return {}

        raw_text = _response_text(response)
        parsed = _parse_json(raw_text)

        if parsed:
            return parsed

        # A 9B-class local model can still truncate a larger JSON response
        # after a large evidence packet. Retry with a deliberately tiny
        # evidence packet and output contract so the research pipeline can
        # continue to price verification instead of failing closed.
        logger.warning(
            "JARVIS PRODUCT RESEARCH: retrying synthesis with compact schema "
            "after invalid/truncated JSON."
        )

        retry_evidence = _compact_evidence_for_synthesis(
            evidence,
            per_source_chars=1600,
        )

        retry_prompt = f"""
Synthesize this product research using ONLY the evidence below.

Request: {request}
Item: {item}
{budget_note}

Evidence:
{json.dumps(
    retry_evidence,
    ensure_ascii=False,
)}

Return ONLY this compact JSON object. No markdown. No extra text.
Do not invent facts. Cite claims with source IDs.
Keep products to at most 3 and comparisons to at most 1.
Keep every reason to one short sentence.

{{
  "summary": "",
  "confidence": "high|medium|low",
  "products": [
    {{
      "name": "",
      "price": null,
      "rating": null,
      "review_count": null,
      "source_ids": [],
      "fit": "best_match|strong_alternative|budget_alternative|mixed|poor_fit"
    }}
  ],
  "best_match": {{"name": null, "reason": "", "source_ids": []}},
  "best_value": {{"name": null, "reason": "", "source_ids": []}},
  "cheapest_credible_option": {{"name": null, "reason": "", "source_ids": []}},
  "better_reviewed_alternative": {{"name": null, "reason": "", "source_ids": []}},
  "comparisons": [
    {{"product_a": "", "product_b": "", "comparison": "", "source_ids": []}}
  ],
  "tradeoffs": [],
  "warnings": []
}}
"""
        try:
            response = ModelManager().product_research(
                [
                    {
                        "role": "system",
                        "content": (
                            "Return only one valid JSON object. "
                            "Be extremely concise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": retry_prompt,
                    },
                ]
            )
        except Exception as exc:
            logger.warning(
                "JARVIS PRODUCT RESEARCH: compact synthesis retry failed: "
                f"{exc}"
            )
            return {}

        return _parse_json(
            _response_text(response)
        )

    return run_synthesis(prompt)

def _sanitize_analysis_product_identity(analysis: dict[str, Any]) -> dict[str, Any]:
    """Remove category-only model outputs before retailer verification."""
    if not isinstance(analysis, dict):
        return {}

    products = analysis.get("products")
    if isinstance(products, list):
        clean = []
        seen = set()
        for product in products:
            if not isinstance(product, dict):
                continue
            name = str(product.get("name") or product.get("product") or "").strip()
            key = " ".join(name.lower().split())
            if not _is_specific_product_name(name) or key in seen:
                continue
            seen.add(key)
            clean.append(product)
        analysis["products"] = clean

    valid_names = {
        " ".join(str(product.get("name") or "").lower().split())
        for product in (analysis.get("products") or [])
        if isinstance(product, dict)
    }

    for field in (
        "best_match",
        "best_value",
        "cheapest_credible_option",
        "better_reviewed_alternative",
    ):
        choice = analysis.get(field)
        if not isinstance(choice, dict):
            continue
        name = " ".join(str(choice.get("name") or "").lower().split())
        if name not in valid_names:
            choice["name"] = None
            choice["reason"] = "No concrete evidence-backed product identity survived validation."
            choice["source_ids"] = []

    return analysis

def _normalized_name(value: Any) -> str:
    return " ".join(
        str(value or "").lower().split()
    ).strip()


def _find_analysis_product(
    analysis: dict[str, Any],
    name: str,
) -> dict[str, Any] | None:
    wanted = _normalized_name(name)
    if not wanted:
        return None

    for product in analysis.get("products") or []:
        if not isinstance(product, dict):
            continue

        candidate = _normalized_name(
            product.get("name")
            or product.get("product")
        )

        if candidate == wanted:
            return product

    for product in analysis.get("products") or []:
        if not isinstance(product, dict):
            continue

        candidate = _normalized_name(
            product.get("name")
            or product.get("product")
        )

        if candidate and (
            wanted in candidate
            or candidate in wanted
        ):
            return product

    return None


def _enrich_product_price_comparisons(
    analysis: dict[str, Any],
    budget: float | None = None,
) -> dict[str, Any]:
    """
    Add best-effort cross-store price evidence to synthesized products.
    """
    if not isinstance(analysis, dict):
        return {}

    products = analysis.get("products")
    if not isinstance(products, list) or not products:
        return analysis

    try:
        enriched = compare_products_prices(
            products,
            stores=("amazon", "bestbuy", "walmart", "target", "bhphoto"),
            max_products=min(4, len(products)),
            max_stores=5,
        )
    except Exception as exc:
        logger.warning(
            "JARVIS PRODUCT RESEARCH: price comparison failed: "
            f"{exc}"
        )
        enriched = products

    analysis["products"] = enriched

    # A synthesized price is only a hint until the retailer checker ties it
    # to an exact direct product page. Clear stale/MSRP/snippet-derived prices
    # that were not independently verified, and prefer the current verified
    # retailer price for the user's actual budget context.
    for product in enriched:
        if not isinstance(product, dict):
            continue

        comparison = product.get("price_comparison") or {}
        # At this point the budget-specific offer list has not been built yet.
        # Start from exact-product verified offers, then apply the budget gate
        # below and replace the displayed price with budget-qualified pricing.
        eligible_offers = comparison.get("verified_offers") or []

        verified_price = None
        for offer in eligible_offers:
            if not isinstance(offer, dict):
                continue
            candidate_price = offer.get("price")
            if isinstance(candidate_price, (int, float)):
                verified_price = float(candidate_price)
                break

        product["price"] = (
            round(verified_price, 2)
            if verified_price is not None
            else None
        )

    cheapest_by_name = {}
    for product in enriched:
        if not isinstance(product, dict):
            continue

        name = str(
            product.get("name")
            or product.get("product")
            or ""
        ).strip()

        if not name:
            continue

        comparison = product.get("price_comparison") or {}
        cheapest = comparison.get("cheapest")

        if isinstance(cheapest, dict):
            cheapest_by_name[_normalized_name(name)] = cheapest

    best_value = analysis.get("best_value") or {}
    best_value_name = str(
        best_value.get("name") or ""
    ).strip()

    best_key = _normalized_name(best_value_name)
    best_offer = cheapest_by_name.get(best_key)
    best_price = (
        best_offer.get("price")
        if isinstance(best_offer, dict)
        else None
    )

    cheaper_alternatives = []
    if isinstance(best_price, (int, float)):
        for product in enriched:
            if not isinstance(product, dict):
                continue

            name = str(
                product.get("name")
                or product.get("product")
                or ""
            ).strip()

            if not name or _normalized_name(name) == best_key:
                continue

            offer = cheapest_by_name.get(_normalized_name(name))
            price = (
                offer.get("price")
                if isinstance(offer, dict)
                else None
            )

            if isinstance(price, (int, float)) and price < best_price:
                cheaper_alternatives.append(
                    {
                        "name": name,
                        "price": price,
                        "seller": offer.get("label"),
                        "url": offer.get("url"),
                        "savings_vs_best_value": round(
                            best_price - price,
                            2,
                        ),
                    }
                )

    analysis["cheaper_alternatives"] = cheaper_alternatives[:4]

    if isinstance(budget, (int, float)) and budget >= 0:
        budget_value = float(budget)

        for product in enriched:
            if not isinstance(product, dict):
                continue

            comparison = product.get("price_comparison") or {}
            verified_offers = comparison.get("verified_offers") or []

            budget_offers = [
                offer
                for offer in verified_offers
                if isinstance(offer, dict)
                and isinstance(offer.get("price"), (int, float))
                and float(offer.get("price")) <= budget_value
            ]

            budget_offers.sort(
                key=lambda offer: float(offer.get("price"))
            )

            comparison["budget_verified_offers"] = budget_offers
            comparison["budget_eligible"] = bool(budget_offers)
            comparison["budget_cheapest"] = budget_offers[0] if budget_offers else None

            # For budget-constrained research, never leave an over-budget
            # verified price in the product record as though it qualified.
            if budget_offers:
                product["price"] = round(
                    float(budget_offers[0].get("price")),
                    2,
                )
            else:
                product["price"] = None

            product["price_comparison"] = comparison

        def product_is_budget_eligible(name: str) -> bool:
            record = _find_analysis_product(analysis, name)
            if not record:
                return False

            comparison = record.get("price_comparison") or {}
            if comparison.get("budget_eligible"):
                return True

            listed_price = record.get("price")
            return (
                isinstance(listed_price, (int, float))
                and float(listed_price) <= budget_value
            )

        # A maximum budget is a hard constraint. Never expose a named
        # recommendation whose known/listed price exceeds the limit.
        for field in (
            "best_match",
            "best_value",
            "cheapest_credible_option",
            "better_reviewed_alternative",
        ):
            choice = analysis.get(field)
            if not isinstance(choice, dict):
                continue

            name = str(choice.get("name") or "").strip()
            if not name or product_is_budget_eligible(name):
                continue

            # For best_match, use the model's own best_value candidate when
            # it satisfies the hard budget. Do not invent a new ranking for
            # the other recommendation roles; clear them instead.
            if field == "best_match":
                best_value = analysis.get("best_value") or {}
                best_value_name = str(best_value.get("name") or "").strip()
                if best_value_name and product_is_budget_eligible(best_value_name):
                    choice["name"] = best_value_name
                    choice["reason"] = (
                        "The synthesized best-value candidate is used as the "
                        "budget-constrained best match because its listed or "
                        "verified retailer price meets the maximum budget."
                    )
                    choice["source_ids"] = best_value.get("source_ids") or []
                    continue

            choice["name"] = None
            choice["reason"] = (
                "The synthesized choice exceeded the hard maximum budget, "
                "and no verified under-budget replacement was established."
            )
            choice["source_ids"] = []

        analysis["budget_constraint"] = {
            "maximum": budget_value,
            "enforced": True,
        }

        analysis["cheaper_alternatives"] = [
            alternative
            for alternative in (analysis.get("cheaper_alternatives") or [])
            if isinstance(alternative, dict)
            and isinstance(alternative.get("price"), (int, float))
            and float(alternative.get("price")) <= budget_value
        ][:4]

        # Replace the model's free-form budget summary after enforcement so
        # it cannot continue claiming that an over-budget product is the
        # selected match after the deterministic budget gate has run.
        budget_match = analysis.get("best_match") or {}
        budget_match_name = str(budget_match.get("name") or "").strip()

        if budget_match_name:
            reason = " ".join(
                str(budget_match.get("reason") or "").split()
            ).strip()
            if reason:
                analysis["summary"] = (
                    f"Within the maximum budget of ${budget_value:,.2f}, "
                    f"{budget_match_name} is the budget-qualified match "
                    f"based on the available review evidence and verified "
                    f"retailer pricing. {reason}"
                )
            else:
                analysis["summary"] = (
                    f"Within the maximum budget of ${budget_value:,.2f}, "
                    f"{budget_match_name} is the budget-qualified match "
                    "based on the available review evidence and verified "
                    "retailer pricing."
                )
        else:
            analysis["summary"] = (
                f"No currently verified retailer price at or below "
                f"${budget_value:,.2f} was established for the researched "
                "models."
            )
            analysis["confidence"] = "low"

        analysis["price_check_status"] = "completed_best_effort"
    return analysis


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

        price_note = ""
        product_record = _find_analysis_product(
            analysis,
            name,
        )
        if product_record:
            comparison = product_record.get("price_comparison") or {}
            cheapest = (
                comparison.get("budget_cheapest")
                if comparison.get("budget_cheapest") is not None
                else comparison.get("cheapest")
            )
            if isinstance(cheapest, dict):
                store = str(cheapest.get("label") or "").strip()
                price = cheapest.get("price")
                if isinstance(price, (int, float)) and store:
                    price_note = (
                        f" Verified price check found it at {store} "
                        f"for ${price:,.2f}. The direct purchase link "
                        "is included in the research result."
                    )

        if reason:
            parts.append(
                f"{label}: {name}. {reason}{price_note}"
            )
        else:
            parts.append(
                f"{label}: {name}.{price_note}"
            )

    comparisons = analysis.get("comparisons") or []
    for comparison in list(comparisons)[:2]:
        if not isinstance(comparison, dict):
            continue

        product_a = str(comparison.get("product_a") or "").strip()
        product_b = str(comparison.get("product_b") or "").strip()
        comparison_text = " ".join(
            str(comparison.get("comparison") or "").split()
        ).strip()

        if product_a and product_b and comparison_text:
            parts.append(
                f"Comparison: {product_a} versus {product_b}. "
                f"{comparison_text}"
            )

    cheaper = analysis.get("cheaper_alternatives") or []
    for alternative in list(cheaper)[:2]:
        if not isinstance(alternative, dict):
            continue
        name = str(alternative.get("name") or "").strip()
        price = alternative.get("price")
        savings = alternative.get("savings_vs_best_value")
        if name and isinstance(price, (int, float)):
            if isinstance(savings, (int, float)) and savings > 0:
                parts.append(
                    f"Cheaper alternative: {name} at ${price:,.2f}, "
                    f"about ${savings:,.2f} less than the best-value option "
                    "based on verified prices."
                )
            else:
                parts.append(
                    f"Cheaper alternative: {name} at ${price:,.2f}."
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

    # Final defensive normalization at the public entry point.
    normalized_item, normalized_budget = _extract_item_and_budget(item or request)
    if normalized_item:
        item = normalized_item
    if budget is None and normalized_budget is not None:
        budget = normalized_budget

    print(
        "[JARVIS] JARVIS PRODUCT RESEARCH: "
        f"parsed item={item!r} budget={budget!r}"
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
            "retryable": False,
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

    analysis = _sanitize_analysis_product_identity(analysis)

    analysis = _enrich_product_price_comparisons(
        analysis,
        budget=budget,
    )

    best_match = analysis.get("best_match") or {}
    best_value = analysis.get("best_value") or {}

    verified = bool(
        analysis
        and (
            str(best_match.get("name") or "").strip()
            or str(best_value.get("name") or "").strip()
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
                "engine": source.get("engine"),
                "query": source.get("query"),
            }
            for source in evidence
        ],
        "evidence": evidence,
        "analysis": analysis,
        "purchase_links": [
            {
                "product": str(product.get("name") or product.get("product") or "").strip(),
                "seller": (((product.get("price_comparison") or {}).get("budget_cheapest") or {}).get("label"))
                    if budget is not None
                    else (((product.get("price_comparison") or {}).get("cheapest") or {}).get("label")),
                "price": (((product.get("price_comparison") or {}).get("budget_cheapest") or {}).get("price"))
                    if budget is not None
                    else (((product.get("price_comparison") or {}).get("cheapest") or {}).get("price")),
                "url": (((product.get("price_comparison") or {}).get("budget_cheapest") or {}).get("url"))
                    if budget is not None
                    else (((product.get("price_comparison") or {}).get("cheapest") or {}).get("url")),
            }
            for product in (analysis.get("products") or [])[:4]
            if isinstance(product, dict)
            and (
                (
                    budget is None
                    and (((product.get("price_comparison") or {}).get("cheapest") or {}).get("url"))
                )
                or (
                    budget is not None
                    and (((product.get("price_comparison") or {}).get("budget_cheapest") or {}).get("url"))
                )
            )
        ],
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
