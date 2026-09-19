"""
JARVIS product price cross-checker.

This module is intentionally independent of the planner/task controller.
It uses the existing JARVIS browser controller + DOM tools to inspect retailer
search pages and, when possible, product pages. It never bypasses CAPTCHAs,
logins, paywalls, or anti-bot controls.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

try:
    from logger import logger
except Exception:  # pragma: no cover - standalone use
    import logging
    logger = logging.getLogger("jarvis.product_price_checker")


# ---------------------------------------------------------------------------
# Store profiles
# ---------------------------------------------------------------------------

STORE_PROFILES: Dict[str, Dict[str, Any]] = {
    "amazon": {
        "label": "Amazon",
        "domain": "amazon.com",
        "search_url": "https://www.amazon.com/s?k={query}",
        "kind": "retailer",
        "price_selectors": ["#corePriceDisplay_desktop_feature_div .a-offscreen", "#corePrice_feature_div .a-offscreen", "span.a-price span.a-offscreen"],
    },
    "bestbuy": {
        "label": "Best Buy",
        "domain": "bestbuy.com",
        "search_url": "https://www.bestbuy.com/site/searchpage.jsp?st={query}",
        "kind": "retailer",
        "price_selectors": ["div[data-testid=\"customerPrice\"]", "[data-test-id=\"price\"]", "div.priceView-hero-price span"],
    },
    "walmart": {
        "label": "Walmart",
        "domain": "walmart.com",
        "search_url": "https://www.walmart.com/search?q={query}",
        "kind": "retailer",
        "price_selectors": ["[data-automation-id=\"product-price\"]", "[itemprop=\"price\"]", "span[data-automation-id=\"product-price\"]"],
    },
    "target": {
        "label": "Target",
        "domain": "target.com",
        "search_url": "https://www.target.com/s?searchTerm={query}",
        "kind": "retailer",
        "price_selectors": ["[data-test=\"product-price\"]", "[data-test=\"currentPrice\"]", "[itemprop=\"price\"]"],
    },
    "newegg": {
        "label": "Newegg",
        "domain": "newegg.com",
        "search_url": "https://www.newegg.com/p/pl?d={query}",
        "kind": "retailer",
        "price_selectors": [".price-current", ".price-current strong", ".price-current-num"],
    },
    "bhphoto": {
        "label": "B&H Photo",
        "domain": "bhphotovideo.com",
        "search_url": "https://www.bhphotovideo.com/c/search?Ntt={query}",
        "kind": "retailer",
        "price_selectors": ["#pricing .price", "div[id*=\"pricing\"] .price", ".price_ourprice", "[data-selenium=\"pricing\"]"],
    },
    "microcenter": {
        "label": "Micro Center",
        "domain": "microcenter.com",
        "search_url": "https://www.microcenter.com/search/search_results.aspx?Ntt={query}",
        "kind": "retailer",
        "price_selectors": ["[itemprop=\"price\"]", "span[class*=\"price\"]"],
    },
    "costco": {
        "label": "Costco",
        "domain": "costco.com",
        "search_url": "https://www.costco.com/CatalogSearch?keyword={query}",
        "kind": "retailer",
    },
    "crutchfield": {
        "label": "Crutchfield",
        "domain": "crutchfield.com",
        "search_url": "https://www.crutchfield.com/S-kLzEwLJ4/search.asp?search={query}",
        "kind": "retailer",
    },
    "adorama": {
        "label": "Adorama",
        "domain": "adorama.com",
        "search_url": "https://www.adorama.com/search/site/?text={query}",
        "kind": "retailer",
    },
    "bose": {
        "label": "Bose",
        "domain": "bose.com",
        "search_url": "https://www.google.com/search?q={query}",
        "kind": "manufacturer",
    },
    "sennheiser": {
        "label": "Sennheiser",
        "domain": "sennheiser-hearing.com",
        "search_url": "https://www.google.com/search?q={query}",
        "kind": "manufacturer",
    },
}

DEFAULT_RETAILERS = [
    "amazon",
    "bestbuy",
    "walmart",
    "target",
    "microcenter",
    "costco",
    "newegg",
    "bhphoto",
]

BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "verify youre human",
    "access denied",
    "robot check",
    "unusual traffic",
    "automated access",
)

_PRICE_CACHE_TTL = 180.0
_PRICE_CACHE = {}


def _price_cache_key(store_key, product_name, model_number=""):
    return (
        str(store_key or "").strip().lower(),
        normalize_product_text(product_name),
        normalize_product_text(model_number),
    )

PRICE_RE = re.compile(
    r"(?<![\w])(?:US\s*)?\$\s*([0-9]{1,4}(?:,[0-9]{3})*(?:\.\d{2})?)(?![\w])"
)

_PRICE_NEGATIVE_CONTEXT = (
    "save",
    "savings",
    "you save",
    "was",
    "list price",
    "list:",
    "coupon",
    "discount",
    "off",
    "msrp",
    "rrp",
    "original price",
)

_PRICE_POSITIVE_CONTEXT = (
    "current price",
    "sale price",
    "price:",
    "price",
    "now",
    "buy",
    "add to cart",
    "our price",
)


def _price_candidates(text: str):
    for match in PRICE_RE.finditer(str(text or "")):
        raw = match.group(1).replace(",", "")
        try:
            value = round(float(raw), 2)
        except ValueError:
            continue

        left = str(text[max(0, match.start() - 100):match.start()]).lower()
        right = str(text[match.end():match.end() + 100]).lower()
        context = f"{left} {right}"

        score = 0.0
        for marker in _PRICE_POSITIVE_CONTEXT:
            if marker in context:
                score += 2.0

        for marker in _PRICE_NEGATIVE_CONTEXT:
            if marker in context:
                score -= 5.0

        # Very small dollar values on a premium product are commonly coupon,
        # savings, shipping, or other secondary numbers. Treat them as weak
        # candidates unless the context explicitly identifies them as a price.
        if value < 10.0 and "price" not in context and "now" not in context:
            score -= 4.0

        yield value, match.start(), match.end(), score


def _select_best_price(text: str) -> Optional[float]:
    candidates = list(_price_candidates(text))
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item[3],
            -item[1],
        ),
        reverse=True,
    )
    return candidates[0][0]


MODEL_RE = re.compile(
    r"\b(?:[A-Z]{1,5}[- ]?[A-Z0-9]{2,}(?:[- ][A-Z0-9]{1,}){0,3})\b"
)


@dataclass
class PriceOffer:
    store: str
    label: str
    url: str
    price: Optional[float]
    currency: str = "USD"
    condition: str = "unknown"
    exact_match: bool = False
    match_score: float = 0.0
    membership_required: Optional[bool] = None
    shipping_known: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Pure helpers -- these are deliberately easy to unit test.
# ---------------------------------------------------------------------------

def normalize_product_text(value: str) -> str:
    value = str(value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def product_tokens(value: str) -> List[str]:
    stop = {
        "the", "and", "with", "for", "wireless", "headphones",
        "headphone", "bluetooth", "new", "black", "white", "sale",
    }
    return [
        token
        for token in normalize_product_text(value).split()
        if len(token) >= 2 and token not in stop
    ]


def extract_prices(text: str) -> List[float]:
    prices: List[float] = []
    for match in PRICE_RE.finditer(str(text or "")):
        raw = match.group(1).replace(",", "")
        try:
            prices.append(round(float(raw), 2))
        except ValueError:
            continue
    return prices


def best_nearby_price(
    text: str,
    query: str,
    model_number: str = "",
    window: int = 500,
) -> Optional[float]:
    """Find the most plausible price associated with a product mention.

    Prefer an exact model-number neighborhood when a model is known. Otherwise
    score individual lines by how many product tokens they contain and inspect
    only a small line neighborhood instead of taking the minimum price on the
    whole page.
    """
    text = str(text or "")
    if not text.strip():
        return None

    # Strongest signal: exact model number on the page.
    if model_number:
        model_norm = normalize_product_text(model_number)
        compact = re.sub(r"[^a-z0-9]+", "", text.lower())
        compact_model = re.sub(r"[^a-z0-9]+", "", model_norm)
        if compact_model and compact_model in compact:
            # Use the original text for a price window. Several formatting
            # variants (WH-CH720N / WH CH720N) are common.
            lower = text.lower()
            for raw_variant in (model_number, model_number.replace("-", " ")):
                idx = lower.find(raw_variant.lower())
                if idx >= 0:
                    nearby = text[max(0, idx - window): idx + window]
                    selected = _select_best_price(nearby)
                    if selected is not None:
                        return selected

    tokens = product_tokens(query)
    if not tokens:
        return _select_best_price(text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    best: Optional[tuple[float, float]] = None

    for i, line in enumerate(lines):
        line_tokens = set(product_tokens(line))
        overlap = len(set(tokens) & line_tokens) / max(len(set(tokens)), 1)
        if overlap < 0.50:
            continue

        neighborhood = " ".join(lines[max(0, i - 1): min(len(lines), i + 2)])
        for value, _start, _end, price_context_score in _price_candidates(
            neighborhood
        ):
            # Combine product-token overlap with explicit price-context
            # signals. Savings/list/MSRP/coupon values are strongly penalized.
            same_line = bool(extract_prices(line))
            distance_bonus = 1.0 if same_line else 0.25
            score = overlap + distance_bonus + (price_context_score * 0.15)
            candidate = (score, value)
            if best is None or candidate[0] > best[0]:
                best = candidate

    return best[1] if best else None


def _canonical_retailer_url(
    store_key: str,
    url: str,
) -> str:
    """Resolve common retailer tracking redirects to a clean product URL."""
    value = str(url or "").strip()
    if not value:
        return ""

    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)

        for key in (
            "r",
            "rd",
            "url",
            "u",
            "redirect",
            "redirect_url",
            "dest",
            "destination",
        ):
            for target in query.get(key) or []:
                candidate = unquote(str(target or "")).strip()
                if candidate.startswith(("http://", "https://")):
                    value = candidate
                    parsed = urlparse(value)
                    break
            else:
                continue
            break

        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path or ""

        if store_key == "amazon" and host == "amazon.com":
            asin_match = re.search(
                r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})",
                path,
                re.IGNORECASE,
            )
            if asin_match:
                return (
                    "https://www.amazon.com/dp/"
                    + asin_match.group(1).upper()
                )

        return value
    except Exception:
        return value


def _host_is_expected(host: str, expected_domain: str) -> bool:
    host = str(host or "").lower().strip().removeprefix("www.")
    expected = str(expected_domain or "").lower().strip().removeprefix("www.")
    return bool(expected and host == expected)


def _is_direct_product_url(store_key: str, url: str) -> bool:
    """Reject search/tracking/redirect URLs before they become product pages."""
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "").lower()
    except Exception:
        return False

    profile = STORE_PROFILES.get(store_key) or {}
    expected_domain = str(profile.get("domain") or "").lower().strip()
    if not _host_is_expected(host, expected_domain):
        return False

    blocked_path_fragments = (
        "/search",
        "/searchpage",
        "/catalogsearch",
        "/newsearch",
        "/cart",
        "/checkout",
        "/account",
        "/signin",
        "/login",
        "/p/pl",
        "/c/search",
    )
    if any(fragment in path for fragment in blocked_path_fragments):
        return False

    route_hints = {
        "amazon": ("/dp/", "/gp/product/", "/gp/aw/d/"),
        "bestbuy": ("/product/", "/site/"),
        "walmart": ("/ip/",),
        "target": ("/p/",),
        "microcenter": ("/product/",),
        "costco": ("/product",),
        "newegg": ("/p/",),
        "bhphoto": ("/c/product/",),
    }
    hints = route_hints.get(store_key)
    if hints:
        return any(path.startswith(hint) for hint in hints)

    return bool(path and path != "/")


def _direct_identity_score(product_name: str, snapshot: dict[str, Any]) -> float:
    """Require the final product page title/headings to identify the product."""
    if not isinstance(snapshot, dict):
        return 0.0

    candidates = [
        " ".join(str(snapshot.get("title") or "").split())
    ]
    headings = snapshot.get("headings") or []
    candidates.extend(
        " ".join(str(value or "").split())
        for value in headings
        if str(value or "").strip()
    )

    valid_candidates = [
        candidate for candidate in candidates
        if candidate and not _product_type_conflict(product_name, candidate)
    ]
    return max(
        (match_score(product_name, candidate) for candidate in valid_candidates),
        default=0.0,
    )


def _product_type_conflict(product_name: str, observed_text: str) -> bool:
    wanted = normalize_product_text(product_name)
    observed = normalize_product_text(observed_text)

    wants_headphones = any(term in wanted for term in ("headphone", "headphones", "over ear", "on ear"))
    wants_earbuds = any(term in wanted for term in ("earbud", "earbuds", "in ear", "tws"))
    observed_headphones = any(term in observed for term in ("headphone", "headphones", "over ear", "on ear"))
    observed_earbuds = any(term in observed for term in ("earbud", "earbuds", "in ear", "tws"))

    if wants_headphones and observed_earbuds and not observed_headphones:
        return True
    if wants_earbuds and observed_headphones and not observed_earbuds:
        return True
    return False



def match_score(product_name: str, observed_text: str, model_number: str = "") -> float:
    """Score whether observed text appears to describe the same product."""
    observed = normalize_product_text(observed_text)
    if not observed:
        return 0.0

    if model_number:
        model_norm = normalize_product_text(model_number)
        if model_norm and model_norm in observed:
            return 1.0

    wanted = set(product_tokens(product_name))
    if not wanted:
        return 0.0

    observed_tokens = set(product_tokens(observed_text))
    overlap = len(wanted & observed_tokens) / max(len(wanted), 1)
    return round(overlap, 3)


def is_blocked(text: str) -> bool:
    lowered = normalize_product_text(text)
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _coerce_text(result: Any) -> str:
    """Accept raw strings, dict payloads, or ToolResult-like objects."""
    if result is None:
        return ""

    if isinstance(result, str):
        return result

    if hasattr(result, "data"):
        data = getattr(result, "data", None)
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return _coerce_text(data)

    if isinstance(result, dict):
        for key in ("text", "content", "message", "observation", "data"):
            value = result.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = _coerce_text(value)
                if nested:
                    return nested
    return str(result)


# ---------------------------------------------------------------------------
# Browser-backed comparison
# ---------------------------------------------------------------------------

class BrowserPriceChecker:
    """Cross-check a known product across public retailer search pages."""

    def __init__(
        self,
        browser_goto: Optional[Callable[[str], Any]] = None,
        browser_extract_text: Optional[Callable[..., Any]] = None,
        browser_wait_for_element: Optional[Callable[..., Any]] = None,
        browser_page_snapshot: Optional[Callable[..., Any]] = None,
        max_stores: int = 8,
    ) -> None:
        if browser_goto is None or browser_extract_text is None:
            try:
                from browser_controller import browser_goto as controller_goto
                from browser_controller import browser_extract_text as controller_extract
                from browser_controller import browser_wait_for_element as controller_wait
                from browser_controller import browser_page_snapshot as controller_snapshot
                browser_goto = controller_goto
                browser_extract_text = controller_extract
                browser_wait_for_element = controller_wait
                if browser_page_snapshot is None:
                    browser_page_snapshot = controller_snapshot
            except Exception as exc:
                raise RuntimeError(
                    "JARVIS browser controller is unavailable for price checking."
                ) from exc

        self.browser_goto = browser_goto
        self.browser_extract_text = browser_extract_text
        self.browser_wait_for_element = browser_wait_for_element
        self.browser_page_snapshot = browser_page_snapshot
        self.max_stores = max(1, int(max_stores))

    def _search_url(self, store_key: str, query: str) -> str:
        profile = STORE_PROFILES[store_key]
        rendered_query = quote_plus(query)

        # Manufacturer profiles use Google site-restricted discovery.
        if profile["kind"] == "manufacturer":
            restricted = f'site:{profile["domain"]} "{query}"'
            return profile["search_url"].format(query=quote_plus(restricted))

        return profile["search_url"].format(query=rendered_query)

    def _direct_product_url(
        self,
        store_key: str,
        search_url: str,
        product_name: str,
        model_number: str = "",
    ) -> str:
        """Try to resolve the retailer search page to a direct product URL."""
        if self.browser_page_snapshot is None:
            return search_url

        try:
            try:
                snapshot = self.browser_page_snapshot(max_links=120) or {}
            except TypeError:
                # Compatibility with older snapshot wrappers that do not
                # accept the optional link limit.
                snapshot = self.browser_page_snapshot() or {}
        except Exception:
            return search_url

        links = snapshot.get("links", []) if isinstance(snapshot, dict) else []
        if not isinstance(links, list):
            return search_url

        profile = STORE_PROFILES.get(store_key, {})
        expected_domain = str(profile.get("domain") or "").lower().strip()
        wanted = set(product_tokens(product_name))
        model_norm = normalize_product_text(model_number)
        best = None

        for link in links:
            if not isinstance(link, dict):
                continue

            href = str(link.get("href") or "").strip()
            text = " ".join(str(link.get("text") or "").split()).strip()
            if not href:
                continue

            try:
                absolute = urljoin(search_url, href)
                absolute = _canonical_retailer_url(
                    store_key,
                    absolute,
                )
                host = (urlparse(absolute).hostname or "").lower()
                if host.startswith("www."):
                    host = host[4:]
            except Exception:
                continue

            if expected_domain and not (
                host == expected_domain or host.endswith("." + expected_domain)
            ):
                continue

            haystack = f"{text} {absolute}".lower()
            if _product_type_conflict(product_name, haystack):
                continue
            product_score = match_score(product_name, haystack, model_number)

            model_hit = bool(
                model_norm
                and normalize_product_text(haystack).find(model_norm) >= 0
            )

            token_overlap = 0.0
            if wanted:
                observed = set(product_tokens(text))
                token_overlap = len(wanted & observed) / max(len(wanted), 1)

            score = (
                100.0 if model_hit else 0.0
            ) + (product_score * 10.0) + (token_overlap * 5.0)

            # Empty-anchor product URLs are still useful when the URL itself
            # contains the requested product/model terms.
            if len(text) < 4 and score < 5.0:
                continue

            if not _is_direct_product_url(store_key, absolute):
                # Search pages, tracking redirects, sponsored-ad links, and
                # other non-product routes are not direct product evidence.
                continue

            if best is None or score > best[0]:
                best = (score, absolute)

        return best[1] if best and best[0] >= 5.0 else search_url

    def _scan_store(
        self,
        store_key: str,
        product_name: str,
        model_number: str = "",
    ) -> PriceOffer:
        cache_key = _price_cache_key(store_key, product_name, model_number)
        cached = _PRICE_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _PRICE_CACHE_TTL:
            return PriceOffer(**asdict(cached[1]))

        profile = STORE_PROFILES[store_key]
        label = profile["label"]
        url = self._search_url(
            store_key,
            f"{product_name} {model_number}".strip(),
        )

        try:
            self.browser_goto(url)
        except Exception as exc:
            return PriceOffer(
                store=store_key,
                label=label,
                url=url,
                price=None,
                notes=f"Navigation failed: {exc}",
            )

        if self.browser_wait_for_element is not None:
            try:
                self.browser_wait_for_element(
                    selector="body",
                    timeout=5000,
                )
            except Exception:
                pass

        try:
            raw = self.browser_extract_text(selector="body")
            body = _coerce_text(raw)
        except TypeError:
            # Compatibility with wrappers that accept a positional selector.
            raw = self.browser_extract_text("body")
            body = _coerce_text(raw)
        except Exception as exc:
            return PriceOffer(
                store=store_key,
                label=label,
                url=url,
                price=None,
                notes=f"DOM extraction failed: {exc}",
            )

        if is_blocked(body):
            return PriceOffer(
                store=store_key,
                label=label,
                url=url,
                price=None,
                notes="Retailer page appears to be blocked or protected; JARVIS did not bypass it.",
            )

        score = match_score(product_name, body, model_number)

        # Prices taken from a retailer search page are not sufficiently tied
        # to the exact product. Keep the search-page match only as a signal
        # for resolving a direct product page; never treat its price as a
        # verified offer.
        price = None
        direct_product_page_seen = False

        direct_url = self._direct_product_url(
            store_key,
            url,
            product_name,
            model_number,
        )

        # A search-result page can contain several products and unrelated
        # prices. When we can resolve an exact product link, inspect that
        # public product page too so the price is tied to the product itself.
        if direct_url and direct_url != url and score >= 0.80:
            try:
                self.browser_goto(direct_url)

                if self.browser_wait_for_element is not None:
                    try:
                        self.browser_wait_for_element(
                            selector="body",
                            timeout=5000,
                        )
                    except Exception:
                        pass

                direct_snapshot = {}
                if self.browser_page_snapshot is not None:
                    try:
                        direct_snapshot = self.browser_page_snapshot(
                            max_links=20
                        ) or {}
                    except TypeError:
                        direct_snapshot = self.browser_page_snapshot() or {}

                final_url = str(
                    direct_snapshot.get("url") or direct_url
                ).strip()

                direct_raw = self.browser_extract_text(selector="body")
                direct_body = _coerce_text(direct_raw)

                if (
                    not is_blocked(direct_body)
                    and _is_direct_product_url(store_key, final_url)
                ):
                    direct_score = match_score(
                        product_name,
                        direct_body,
                        model_number,
                    )
                    identity_score = _direct_identity_score(
                        product_name,
                        direct_snapshot,
                    )
                    direct_price = None
                    for selector in profile.get("price_selectors", []) or []:
                        try:
                            selector_raw = self.browser_extract_text(selector=selector)
                        except TypeError:
                            selector_raw = self.browser_extract_text(selector)
                        except Exception:
                            continue
                        candidate_price = _select_best_price(_coerce_text(selector_raw))
                        if candidate_price is not None:
                            direct_price = candidate_price
                            break

                    if direct_price is None:
                        lower_direct = direct_body.lower()
                        anchor_index = -1
                        for lookup in (model_number, product_name):
                            needle = str(lookup or "").strip().lower()
                            if needle:
                                anchor_index = lower_direct.find(needle)
                                if anchor_index >= 0:
                                    break
                        if anchor_index >= 0:
                            nearby = direct_body[anchor_index:anchor_index + 900]
                            direct_price = _select_best_price(nearby)

                    if direct_score >= score:
                        score = direct_score

                    if (
                        identity_score >= 0.80
                        and direct_score >= 0.80
                    ):
                        direct_product_page_seen = True

                    if (
                        direct_product_page_seen
                        and direct_price is not None
                    ):
                        price = direct_price
                        direct_url = final_url

            except TypeError:
                try:
                    self.browser_goto(direct_url)

                    if self.browser_wait_for_element is not None:
                        try:
                            self.browser_wait_for_element(
                                selector="body",
                                timeout=5000,
                            )
                        except Exception:
                            pass

                    direct_snapshot = {}
                    if self.browser_page_snapshot is not None:
                        try:
                            direct_snapshot = self.browser_page_snapshot(
                                max_links=20
                            ) or {}
                        except TypeError:
                            direct_snapshot = self.browser_page_snapshot() or {}

                    final_url = str(
                        direct_snapshot.get("url") or direct_url
                    ).strip()

                    direct_raw = self.browser_extract_text("body")
                    direct_body = _coerce_text(direct_raw)

                    if (
                        not is_blocked(direct_body)
                        and _is_direct_product_url(store_key, final_url)
                    ):
                        direct_score = match_score(
                            product_name,
                            direct_body,
                            model_number,
                        )
                        identity_score = _direct_identity_score(
                            product_name,
                            direct_snapshot,
                        )
                        direct_price = None
                        for selector in profile.get("price_selectors", []) or []:
                            try:
                                selector_raw = self.browser_extract_text(selector=selector)
                            except TypeError:
                                selector_raw = self.browser_extract_text(selector)
                            except Exception:
                                continue
                            candidate_price = _select_best_price(_coerce_text(selector_raw))
                            if candidate_price is not None:
                                direct_price = candidate_price
                                break

                        if direct_price is None:
                            lower_direct = direct_body.lower()
                            anchor_index = -1
                            for lookup in (model_number, product_name):
                                needle = str(lookup or "").strip().lower()
                                if needle:
                                    anchor_index = lower_direct.find(needle)
                                    if anchor_index >= 0:
                                        break
                            if anchor_index >= 0:
                                nearby = direct_body[anchor_index:anchor_index + 900]
                                direct_price = _select_best_price(nearby)

                        if direct_score >= score:
                            score = direct_score

                        if (
                            identity_score >= 0.80
                            and direct_score >= 0.80
                        ):
                            direct_product_page_seen = True

                        if (
                            direct_product_page_seen
                            and direct_price is not None
                        ):
                            price = direct_price
                            direct_url = final_url
                except Exception:
                    pass
            except Exception:
                # Search-page evidence remains usable when the direct product
                # page is protected or otherwise unavailable.
                pass

        notes = ""
        if not direct_product_page_seen:
            # Search-page prices can belong to a different SKU, variant,
            # marketplace seller, coupon, or nearby result. Do not promote
            # them into verified price evidence without a direct product page.
            if score < 0.55:
                notes = "Search page returned text, but an exact product match was not verified."
            else:
                notes = (
                    "Exact product was indicated on the search page, but a direct "
                    "product page was not resolved; search-page pricing was not "
                    "treated as verified."
                )
        elif price is None:
            notes = "Product page appears to match, but a reliable visible USD price was not found."

        exact_match = bool(direct_product_page_seen)

        offer = PriceOffer(
            store=store_key,
            label=label,
            url=direct_url,
            price=price,
            exact_match=exact_match,
            match_score=score,
            notes=notes,
        )

        if offer.exact_match and offer.price is not None:
            _PRICE_CACHE[cache_key] = (time.monotonic(), PriceOffer(**asdict(offer)))

        return offer

    def compare(
        self,
        product_name: str,
        model_number: str = "",
        stores: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        store_keys = list(stores or DEFAULT_RETAILERS)
        valid = [key for key in store_keys if key in STORE_PROFILES]
        valid = valid[: self.max_stores]

        offers: List[PriceOffer] = []
        for store_key in valid:
            offer = self._scan_store(
                store_key,
                product_name,
                model_number,
            )
            offers.append(offer)
            logger.info(
                "JARVIS PRICE CHECK: %s | price=%s | match=%.2f | exact=%s",
                offer.label,
                offer.price,
                offer.match_score,
                offer.exact_match,
            )

        verified = [
            offer for offer in offers
            if offer.price is not None and offer.exact_match
        ]
        verified.sort(key=lambda offer: offer.price or float("inf"))

        cheapest = verified[0] if verified else None
        comparison_prices = [offer.price for offer in verified if offer.price is not None]
        baseline = max(comparison_prices) if comparison_prices else None
        savings = None
        if cheapest and baseline is not None and baseline > cheapest.price:
            savings = round(baseline - cheapest.price, 2)

        return {
            "success": bool(verified),
            "product": product_name,
            "model_number": model_number,
            "offers": [offer.to_dict() for offer in offers],
            "verified_offers": [offer.to_dict() for offer in verified],
            "cheapest": cheapest.to_dict() if cheapest else None,
            "savings_vs_highest_verified": savings,
            "message": (
                f"Lowest verified price found at {cheapest.label}: ${cheapest.price:.2f}."
                if cheapest
                else "No exact, verifiable price match was found."
            ),
        }


def compare_product_prices(
    product_name: str,
    model_number: str = "",
    stores: Optional[Iterable[str]] = None,
    max_stores: int = 8,
) -> Dict[str, Any]:
    """Convenience wrapper used by JARVIS product-research code."""
    checker = BrowserPriceChecker(max_stores=max_stores)
    return checker.compare(
        product_name=product_name,
        model_number=model_number,
        stores=stores,
    )


def _get_product_value(product: Any, *keys: str) -> str:
    if not isinstance(product, dict):
        return ""
    for key in keys:
        value = product.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def compare_products_prices(
    products: Iterable[Dict[str, Any]],
    stores: Optional[Iterable[str]] = None,
    max_products: int = 4,
    max_stores: int = 8,
) -> List[Dict[str, Any]]:
    """Add cross-store price evidence to a small set of discovered products.

    The caller can pass the current product-research records without changing
    their schema. Each record receives a `price_comparison` field.
    """
    checker = BrowserPriceChecker(max_stores=max_stores)
    output: List[Dict[str, Any]] = []

    for product in list(products)[: max(1, int(max_products))]:
        record = dict(product)
        name = _get_product_value(
            record,
            "name",
            "product_name",
            "title",
            "product",
        )
        model = _get_product_value(
            record,
            "model_number",
            "model",
            "mpn",
            "sku",
        )

        if not name:
            record["price_comparison"] = {
                "success": False,
                "message": "Product record has no recognizable product name.",
                "offers": [],
                "verified_offers": [],
                "cheapest": None,
            }
        else:
            try:
                record["price_comparison"] = checker.compare(
                    product_name=name,
                    model_number=model,
                    stores=stores,
                )
            except Exception as exc:
                # Price checking must never make the main research task fail.
                record["price_comparison"] = {
                    "success": False,
                    "message": f"Price comparison failed: {exc}",
                    "offers": [],
                    "verified_offers": [],
                    "cheapest": None,
                }

        output.append(record)

    return output


__all__ = [
    "STORE_PROFILES",
    "DEFAULT_RETAILERS",
    "PriceOffer",
    "BrowserPriceChecker",
    "compare_product_prices",
    "compare_products_prices",
    "normalize_product_text",
    "product_tokens",
    "extract_prices",
    "best_nearby_price",
    "match_score",
]