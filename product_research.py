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
