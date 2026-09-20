"""Structured commerce API clients for JARVIS product research.

The clients in this module are optional accelerators. They never bypass retailer
protections, and callers should continue using browser verification before
treating an offer as purchase-ready evidence.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

from logger import logger


_BESTBUY_BASE_URL = "https://api.bestbuy.com/v1/products"
_DEFAULT_TIMEOUT = 12


def _normalize_condition(value: Any) -> str:
    text = " ".join(str(value or "").lower().split())
    if any(token in text for token in ("refurb", "renewed", "remanufactured")):
        return "refurbished"
    if any(token in text for token in ("open box", "open-box")):
        return "open_box"
    if "used" in text:
        return "used"
    if text == "new" or text.startswith("new "):
        return "new"
    return "unknown"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


@dataclass
class CommerceProduct:
    provider: str
    product_id: str
    sku: str
    name: str
    manufacturer: str = ""
    model_number: str = ""
    price: Optional[float] = None
    regular_price: Optional[float] = None
    condition: str = "unknown"
    availability: Optional[bool] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BestBuyAPI:
    """Small synchronous wrapper around the Best Buy Products API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = str(
            api_key or os.getenv("BBY_API_KEY") or ""
        ).strip()
        self.timeout = max(3, int(timeout))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search_products(
        self,
        query: str,
        *,
        max_results: int = 8,
        budget: Optional[float] = None,
    ) -> list[CommerceProduct]:
        if not self.available:
            return []

        clean_query = " ".join(str(query or "").split()).strip()
        if not clean_query:
            return []

        # Best Buy's product API supports query expressions. We keep the
        # initial lookup broad, then apply JARVIS-side filtering so the API
        # remains a discovery source rather than becoming the final arbiter.
        expression = f"(search={clean_query})"

        show = ",".join(
            [
                "sku",
                "name",
                "manufacturer",
                "modelNumber",
                "salePrice",
                "regularPrice",
                "onlineAvailability",
                "customerReviewAverage",
                "customerReviewCount",
                "condition",
                "url",
            ]
        )

        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": show,
            "pageSize": min(max(int(max_results) * 2, 8), 25),
        }

        url = (
            f"{_BESTBUY_BASE_URL}"
            f"{quote_plus(expression)}"
        )

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "JARVIS/1.0",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(
                "JARVIS COMMERCE API: Best Buy lookup failed: %s",
                exc,
            )
            return []

        products = payload.get("products", [])
        if not isinstance(products, list):
            return []

        results: list[CommerceProduct] = []

        for item in products:
            if not isinstance(item, dict):
                continue

            name = " ".join(
                str(item.get("name") or "").split()
            ).strip()
            sku = str(item.get("sku") or "").strip()
            if not name or not sku:
                continue

            price = _safe_float(item.get("salePrice"))
            regular_price = _safe_float(item.get("regularPrice"))
            condition = _normalize_condition(item.get("condition"))

            rating = _safe_float(
                item.get("customerReviewAverage")
            )

            review_count = None
            try:
                if item.get("customerReviewCount") is not None:
                    review_count = int(
                        item.get("customerReviewCount")
                    )
            except (TypeError, ValueError):
                review_count = None

            availability_value = item.get("onlineAvailability")
            availability = (
                bool(availability_value)
                if isinstance(availability_value, bool)
                else None
            )

            result = CommerceProduct(
                provider="bestbuy",
                product_id=sku,
                sku=sku,
                name=name,
                manufacturer=str(
                    item.get("manufacturer") or ""
                ).strip(),
                model_number=str(
                    item.get("modelNumber") or ""
                ).strip(),
                price=price,
                regular_price=regular_price,
                condition=condition,
                availability=availability,
                rating=rating,
                review_count=review_count,
                url=str(item.get("url") or "").strip(),
            )

            # A budget is a discovery filter only. Final eligibility still
            # belongs to product_price_checker.py after identity verification.
            if budget is not None and (
                result.price is None
                or result.price > float(budget)
            ):
                continue

            results.append(result)

            if len(results) >= int(max_results):
                break

        return results


_bestbuy_client = BestBuyAPI()


def bestbuy_search(
    query: str,
    *,
    max_results: int = 8,
    budget: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Convenience wrapper used by JARVIS product research."""
    return [
        product.to_dict()
        for product in _bestbuy_client.search_products(
            query,
            max_results=max_results,
            budget=budget,
        )
    ]
