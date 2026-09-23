from __future__ import annotations

import asyncio
import atexit
import base64
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from typing import Any, Optional

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="[JARVIS] %(message)s")

CHROME_AUTOMATION_DIR = Path(os.path.abspath("./playwright_profile"))

try:
    JARVIS_CDP_PORT = int(os.getenv("JARVIS_CDP_PORT", "9222"))
except ValueError:
    JARVIS_CDP_PORT = 9222

_playwright = None
_context = None
_page = None
_loop = None
_skipper_task = None
_connection_task = None
_driver_process = None


def get_event_loop():
    """Return the single event loop owned by this controller."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


async def _auto_skip_ads(page):
    """Install the YouTube ad observer on the supplied page."""
    try:
        await page.evaluate(
            """() => {
                if (window._jarvisObserverActive) return;
                window._jarvisObserverActive = true;

                const handleAds = () => {
                    const skipBtn = document.querySelector(
                        '.ytp-ad-skip-button, .ytp-skip-ad-button, button.ytp-ad-skip-button-modern'
                    );
                    if (skipBtn) skipBtn.click();

                    const overlayClose = document.querySelector(
                        '.ytp-ad-overlay-close-button'
                    );
                    if (overlayClose) overlayClose.click();

                    const player = document.querySelector('.html5-video-player');
                    const video = document.querySelector('video');
                    if (player && video && player.classList.contains('ad-showing')) {
                        video.muted = true;
                        video.playbackRate = 16.0;
                        if (Number.isFinite(video.duration) && video.duration > 0) {
                            try { video.currentTime = video.duration; } catch (_) {}
                        }
                    }
                };

                const observer = new MutationObserver(handleAds);
                observer.observe(document.documentElement || document.body, {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: ['class']
                });

                window._jarvisHandleAds = handleAds;
                handleAds();
            }"""
        )
    except Exception:
        pass


async def _init_browser():
    """Start one persistent Playwright browser context and reuse it."""
    global _playwright, _context, _page, _skipper_task, _connection_task, _driver_process

    if _page is not None:
        try:
            if not _page.is_closed():
                try:
                    await _page.bring_to_front()
                except Exception:
                    pass
                return _page
        except Exception:
            pass

    _playwright = await async_playwright().start()

    # Playwright creates its Connection.run() task internally. Keep a direct
    # reference so shutdown can await that exact task instead of cancelling
    # arbitrary asyncio tasks on the shared Windows event loop.
    try:
        current = asyncio.current_task()
        _connection_task = next(
            (
                task
                for task in asyncio.all_tasks()
                if (
                    task is not current
                    and not task.done()
                    and "Connection.run" in task.get_coro().__qualname__
                )
            ),
            None,
        )
    except Exception:
        _connection_task = None

    connection = getattr(getattr(_playwright, "_impl_obj", None), "_connection", None)
    transport = getattr(connection, "_transport", None)
    _driver_process = getattr(transport, "_proc", None)

    user_data_dir = str(CHROME_AUTOMATION_DIR)
    CHROME_AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)

    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        viewport={"width": 1920, "height": 1080},
        # Keep Playwright's native debugging pipe while also exposing
        # the explicit TCP CDP endpoint used by Browser Use.
        args=[
            "--disable-blink-features=AutomationControlled",
            f"--remote-debugging-port={JARVIS_CDP_PORT}",
        ],
    )

    pages = _context.pages
    _page = pages[-1] if pages else await _context.new_page()
    try:
        await _page.bring_to_front()
    except Exception:
        pass
    _skipper_task = asyncio.create_task(_auto_skip_ads(_page))
    return _page


def ensure_browser() -> dict[str, Any]:
    """Ensure JARVIS's persistent Playwright Chromium session is running."""
    try:
        get_event_loop().run_until_complete(_init_browser())
        return {
            "success": True,
            "started": _context is not None,
            "message": "JARVIS Playwright Chromium is ready.",
        }
    except Exception as exc:
        return {
            "success": False,
            "started": False,
            "message": f"Could not initialize Playwright Chromium: {exc}",
        }


def ensure_cdp_chrome() -> dict[str, Any]:
    """Backward-compatible alias for the Playwright browser initializer."""
    return ensure_browser()


def browser_connect() -> dict[str, Any]:
    status = ensure_browser()
    if not status.get("success"):
        return status
    return browser_page_info()


def get_page():
    return get_event_loop().run_until_complete(_init_browser())


def browser_goto(url: str) -> dict[str, Any]:
    url = str(url or "").strip()
    if not url:
        return {"success": False, "error": "URL cannot be empty."}

    async def _goto():
        page = await _init_browser()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await _auto_skip_ads(page)
        return await browser_page_info_async(page)

    try:
        return get_event_loop().run_until_complete(_goto())
    except Exception as exc:
        return {"success": False, "error": str(exc), "url": url}


def browser_navigate(url: str) -> str:
    result = browser_goto(url)
    if result.get("success"):
        return f"Successfully navigated to {result.get('url', url)}"
    return f"Failed to navigate to {url}: {result.get('error', 'unknown error')}"


def browser_scroll(direction: str = "down", distance: int = 500):
    try:
        distance = max(1, int(distance))
    except Exception:
        distance = 500

    async def _scroll():
        page = await _init_browser()
        delta_y = distance if str(direction).lower() == "down" else -distance
        await page.mouse.wheel(0, delta_y)
        return {"success": True, "direction": direction, "distance": distance}

    try:
        return get_event_loop().run_until_complete(_scroll())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _locator(
    page,
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    """Build a Playwright locator from an explicit DOM targeting strategy.

    name is an optional accessible name and is valid only with an ARIA role.
    """
    selector = str(selector or "").strip()
    text = str(text or "").strip()
    role = str(role or "").strip()
    name = str(name or "").strip()

    if name and not role:
        raise ValueError(
            "Accessible name targeting requires an ARIA role."
        )

    supplied = sum(bool(value) for value in (selector, text, role))

    if supplied == 0:
        raise ValueError(
            "A target is required. Provide selector, text, or role."
        )

    if supplied > 1:
        raise ValueError(
            "Provide only one target type at a time: selector, text, or role."
        )

    if selector:
        return page.locator(selector)

    if role:
        if name:
            primary = page.get_by_role(role, name=name, exact=False)
        else:
            primary = page.get_by_role(role)

        # Google and several modern SPAs expose search inputs as an ARIA
        # combobox instead of searchbox. Include that representation while
        # retaining the semantic searchbox as the primary target.
        if role.lower() == "searchbox" and not name:
            try:
                return primary.or_(page.get_by_role("combobox")).first
            except (AttributeError, TypeError):
                pass

        return primary

    return page.get_by_text(text, exact=False)


async def _dom_target_info(locator) -> dict[str, Any]:
    """Return useful information about the current DOM target."""
    count = await locator.count()

    if count == 0:
        return {
            "found": False,
            "visible": False,
            "count": 0,
            "element_text": "",
        }

    first = locator.first

    try:
        visible = await first.is_visible()
    except Exception:
        visible = False

    element_text = ""
    try:
        element_text = (await first.inner_text(timeout=2_000)).strip()
    except Exception:
        pass

    return {
        "found": True,
        "visible": bool(visible),
        "count": count,
        "element_text": element_text[:2_000],
    }


def _dom_target_args(
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
) -> dict[str, str]:
    return {
        "selector": str(selector or "").strip(),
        "text": str(text or "").strip(),
        "role": str(role or "").strip(),
        "name": str(name or "").strip(),
    }



async def browser_page_info_async(page) -> dict[str, Any]:
    open_pages = []
    if _context:
        for opened_page in _context.pages:
            try:
                open_pages.append({
                    "url": opened_page.url,
                    "title": await opened_page.title(),
                })
            except Exception:
                open_pages.append({
                    "url": getattr(opened_page, "url", ""),
                    "title": "",
                })

    return {
        "success": True,
        "url": page.url,
        "title": await page.title(),
        "pages": len(open_pages),
        "open_pages": open_pages,
    }


def browser_status() -> dict[str, Any]:
    """Return browser state without starting a new browser session."""
    try:
        if _context is None:
            return {
                "success": True,
                "connected": False,
                "pages": [],
                "message": "Browser is not connected.",
            }

        open_pages = []
        for opened_page in _context.pages:
            try:
                open_pages.append({
                    "url": opened_page.url,
                    "title": "",
                })
            except Exception:
                pass

        return {
            "success": True,
            "connected": True,
            "pages": open_pages,
            "message": "Browser is connected.",
        }
    except Exception as exc:
        return {
            "success": False,
            "connected": False,
            "error": str(exc),
        }


def browser_page_info() -> dict[str, Any]:
    try:
        page = get_event_loop().run_until_complete(_init_browser())
        return get_event_loop().run_until_complete(browser_page_info_async(page))
    except Exception as exc:
        return {"success": False, "error": str(exc)}



def _snapshot_clean_text(value: str, max_chars: int = 6000) -> str:
    """Normalize browser page text and remove common navigation boilerplate."""
    skip_lines = {
        "skip to main content",
        "accessibility help",
        "ai mode",
        "all",
        "news",
        "images",
        "shopping",
        "videos",
        "forums",
        "more",
        "tools",
        "page navigation",
        "footer links",
        "send feedback",
        "sign in to customize",
        "people also ask",
        "what people are saying",
    }

    lines = []
    seen = set()

    for raw_line in str(value or "").splitlines():
        line = " ".join(str(raw_line).split())
        if not line:
            continue

        if line.lower() in skip_lines:
            continue

        if line in seen:
            continue

        seen.add(line)
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    return cleaned[:max_chars]


async def _snapshot_texts(page, selector: str, limit: int = 20) -> list[str]:
    """Collect short text values from the first visible matching elements."""
    locator = page.locator(selector)
    count = await locator.count()
    values = []

    for index in range(min(count, limit)):
        item = locator.nth(index)

        try:
            if not await item.is_visible():
                continue
        except Exception:
            pass

        try:
            value = (await item.inner_text(timeout=1500)).strip()
        except Exception:
            try:
                value = (await item.text_content(timeout=1500) or "").strip()
            except Exception:
                value = ""

        value = " ".join(value.split())
        if value and value not in values:
            values.append(value)

    return values


async def _snapshot_links(page, selector: str, limit: int = 30) -> list[dict[str, str]]:
    """Collect visible link text and hrefs without walking the entire DOM."""
    locator = page.locator(selector)
    count = await locator.count()
    links = []

    for index in range(min(count, limit)):
        item = locator.nth(index)

        try:
            if not await item.is_visible():
                continue
        except Exception:
            pass

        try:
            label = " ".join((await item.inner_text(timeout=1500)).split())
        except Exception:
            label = ""

        try:
            href = (await item.get_attribute("href") or "").strip()
        except Exception:
            href = ""

        if not label and not href:
            continue

        candidate = {
            "text": label[:300],
            "href": href[:1000],
        }

        if candidate not in links:
            links.append(candidate)

    return links


def _snapshot_canonical_url(href: str) -> str:
    """Normalize common search-engine redirect URLs to their destination."""
    value = str(href or "").strip()
    if not value:
        return ""

    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)

        for key in ("url", "q", "u"):
            targets = query.get(key) or []
            if targets:
                target = unquote(str(targets[0] or "")).strip()
                if target.startswith(("http://", "https://")):
                    return target
    except Exception:
        pass

    return value





async def _get_google_organic_result_candidates(
    page,
    limit: int = 10,
    timeout_ms: int = 5_000,
    minimum_results: int = 1,
) -> list[dict[str, Any]]:
    """
    Discover Google organic results from the live DOM.

    Google may expose result anchors as opaque /goto?url=... controls rather
    than direct destination URLs. Those anchors are still legitimate DOM
    controls and can be clicked deterministically, so they must not be
    discarded merely because their href is Google-owned.
    """
    try:
        limit = max(1, min(int(limit), 50))
    except Exception:
        limit = 10

    try:
        timeout_ms = max(250, min(int(timeout_ms), 10_000))
    except Exception:
        timeout_ms = 5_000

    try:
        minimum_results = max(1, min(int(minimum_results), limit))
    except Exception:
        minimum_results = 1

    locator = page.locator("div#search a:has(h3)")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + (timeout_ms / 1000.0)

    while True:
        try:
            raw_candidates = await locator.evaluate_all(
                """
                anchors => anchors.map((anchor, index) => {
                    const heading = anchor.querySelector('h3');

                    if (!heading) {
                        return null;
                    }

                    const rect = anchor.getBoundingClientRect();
                    const style = window.getComputedStyle(anchor);

                    const href = (
                        anchor.href ||
                        anchor.getAttribute('href') ||
                        ''
                    ).trim();

                    return {
                        index,
                        visible: Boolean(
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.display !== 'none' &&
                            style.visibility !== 'hidden'
                        ),
                        title: (
                            heading.innerText ||
                            heading.textContent ||
                            ''
                        ).trim(),
                        href,
                    };
                }).filter(Boolean)
                """
            )
        except Exception:
            raw_candidates = []

        candidates: list[dict[str, Any]] = []
        seen_targets: set[str] = set()

        for raw in raw_candidates:
            try:
                if not raw.get("visible"):
                    continue

                title = " ".join(
                    str(raw.get("title") or "").split()
                ).strip()

                href = str(
                    raw.get("href") or ""
                ).strip()

                if not title or not href:
                    continue

                parsed_href = urlparse(href)
                host = (parsed_href.hostname or "").lower()
                path = (parsed_href.path or "").lower()

                # A result may be:
                #   1. a direct external URL, or
                #   2. Google's current opaque /goto result control.
                is_external = href.startswith(
                    ("http://", "https://")
                ) and not (
                    host == "google.com"
                    or host.endswith(".google.com")
                )

                is_google_result_redirect = (
                    (
                        href.startswith("/goto?")
                        or (
                            host in {"google.com", "www.google.com"}
                            and path.startswith("/goto")
                        )
                    )
                )

                if not (
                    is_external
                    or is_google_result_redirect
                ):
                    continue

                if href in seen_targets:
                    continue

                seen_targets.add(href)

                try:
                    dom_index = int(raw.get("index"))
                    candidate_locator = locator.nth(dom_index)
                except Exception:
                    continue

                candidates.append(
                    {
                        "locator": candidate_locator,
                        "title": title[:500],
                        "url": href[:4000],
                        "click_target": href[:4000],
                        "url_is_google_redirect": is_google_result_redirect,
                    }
                )

            except Exception:
                continue

        if len(candidates) >= minimum_results:
            return candidates[:limit]

        if loop.time() >= deadline:
            return candidates[:limit]

        await page.wait_for_timeout(125)


async def _snapshot_result_snippet(link, site: str) -> str:
    """Extract a short result snippet without walking the whole page."""
    selectors = {
        "google": (
            ".VwiC3b",
            ".aCOpRe",
            "[data-sncf]",
        ),
        "bing": (
            ".b_caption p",
        ),
        "youtube": (
            "#description-text",
            "yt-formatted-string#description-text",
        ),
    }.get(site, ())

    try:
        snippet = await link.evaluate(
            """(el, selectors) => {
                const roots = [
                    el.closest('div.MjjYud'),
                    el.closest('li.b_algo'),
                    el.closest('ytd-video-renderer'),
                    el.parentElement,
                ].filter(Boolean);

                for (const root of roots) {
                    for (const selector of selectors) {
                        const node = root.querySelector(selector);
                        if (!node) continue;
                        const value = (node.innerText || node.textContent || '').trim();
                        if (value) return value;
                    }
                }
                return '';
            }""",
            list(selectors),
        )
        return " ".join(str(snippet or "").split())[:500]
    except Exception:
        return ""


async def _snapshot_search_results(page) -> list[dict[str, str]]:
    """Extract lightweight search-result identities for common search pages."""
    url = str(getattr(page, "url", "") or "").lower()
    candidates = []

    if "google." in url:
        google_results = await _get_google_organic_result_candidates(
            page,
            limit=10,
            timeout_ms=5_000,
            minimum_results=1,
        )

        for index, item in enumerate(google_results):
            link = item["locator"]
            title = str(item.get("title") or "").strip()
            href = str(item.get("url") or "").strip()
            snippet = await _snapshot_result_snippet(link, "google")

            if title and href:
                candidates.append({
                    "index": str(index + 1),
                    "title": title[:300],
                    "snippet": snippet,
                    "url": href[:1000],
                })

    elif "bing.com" in url:
        locator = page.locator("li.b_algo h2 a")
        try:
            await locator.first.wait_for(state="visible", timeout=5_000)
        except Exception:
            pass
        for index in range(min(await locator.count(), 10)):
            link = locator.nth(index)
            try:
                title = " ".join((await link.inner_text(timeout=1500)).split())
                href = (await link.get_attribute("href") or "").strip()
                snippet = await _snapshot_result_snippet(link, "bing")
            except Exception:
                continue

            if title:
                candidates.append({
                    "index": str(index + 1),
                    "title": title[:300],
                    "snippet": snippet,
                    "url": _snapshot_canonical_url(href)[:1000],
                })

    elif "youtube.com" in url:
        locator = page.locator(
            "ytd-video-renderer a#video-title, "
            "ytd-search ytd-video-renderer #video-title"
        )
        try:
            await locator.first.wait_for(state="visible", timeout=5_000)
        except Exception:
            pass
        for index in range(min(await locator.count(), 10)):
            item = locator.nth(index)
            try:
                title = " ".join((await item.inner_text(timeout=1500)).split())
                href = (await item.get_attribute("href") or "").strip()
                snippet = await _snapshot_result_snippet(item, "youtube")
            except Exception:
                continue

            if title:
                candidates.append({
                    "index": str(index + 1),
                    "title": title[:300],
                    "snippet": snippet,
                    "url": _snapshot_canonical_url(href)[:1000],
                })

    return candidates


def _snapshot_spoken_preview(
    readable_text: str,
    results: list[dict[str, str]],
) -> str:
    """Build a compact spoken summary while preserving full structured results."""
    spoken_preview = str(readable_text or "")[:900]

    result_titles = []
    for item in results[:3]:
        if not isinstance(item, dict):
            continue

        title_text = " ".join(
            str(item.get("title", "") or "").split()
        ).strip()

        if title_text and title_text not in result_titles:
            result_titles.append(title_text)

    if result_titles:
        ordinal_names = ("First", "Second", "Third")
        spoken_parts = [
            f"I found {len(results)} result{'s' if len(results) != 1 else ''}."
        ]

        for ordinal, title_text in zip(
            ordinal_names,
            result_titles,
        ):
            compact_title = title_text[:90].rstrip()
            spoken_parts.append(
                f"{ordinal}: {compact_title}."
            )

        spoken_preview = " ".join(spoken_parts)[:600]

    return spoken_preview


def browser_page_snapshot(
    max_links: int = 30,
) -> dict[str, Any]:
    """Return a bounded, structured observation of the current browser page."""
    async def _snapshot():
        page = await _init_browser()

        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=2_000,
            )
        except Exception:
            pass

        await page.wait_for_timeout(150)

        title = (await page.title()).strip()
        url = str(page.url or "").strip()

        body_text = ""
        try:
            body_text = await page.locator("body").evaluate(
                """el => (
                    el.innerText ||
                    el.textContent ||
                    ""
                ).trim()"""
            )
        except Exception:
            pass

        readable_text = _snapshot_clean_text(body_text)

        headings = await _snapshot_texts(
            page,
            "h1,h2,h3,h4,h5,h6",
            limit=20,
        )

        buttons = await _snapshot_texts(
            page,
            "button",
            limit=20,
        )

        try:
            link_limit = max(1, min(int(max_links), 200))
        except Exception:
            link_limit = 30

        links = await _snapshot_links(
            page,
            "a",
            limit=link_limit,
        )

        inputs = []
        fields = page.locator("input, textarea, select")
        field_count = await fields.count()

        for index in range(min(field_count, 20)):
            field = fields.nth(index)

            try:
                if not await field.is_visible():
                    continue
            except Exception:
                pass

            try:
                field_type = (
                    await field.get_attribute("type")
                    or "text"
                ).strip()
            except Exception:
                field_type = "text"

            try:
                field_name = (
                    await field.get_attribute("name")
                    or ""
                ).strip()
            except Exception:
                field_name = ""

            try:
                placeholder = (
                    await field.get_attribute("placeholder")
                    or ""
                ).strip()
            except Exception:
                placeholder = ""

            try:
                aria_label = (
                    await field.get_attribute("aria-label")
                    or ""
                ).strip()
            except Exception:
                aria_label = ""

            if any((field_name, placeholder, aria_label, field_type)):
                inputs.append({
                    "type": field_type[:80],
                    "name": field_name[:200],
                    "placeholder": placeholder[:200],
                    "aria_label": aria_label[:200],
                })

        results = await _snapshot_search_results(page)

        spoken_preview = _snapshot_spoken_preview(
            readable_text,
            results,
        )
        return {
            "success": True,
            "verified": True,
            "action": "page_snapshot",
            "snapshot_version": 1,
            "title": title,
            "url": url,
            "headings": headings,
            "results": results,
            "buttons": buttons,
            "inputs": inputs,
            "links": links,
            "readable_text": readable_text,
            "spoken_preview": spoken_preview,
            "characters": len(readable_text),
            "has_more": len(readable_text) > len(spoken_preview),
            "element_counts": {
                "headings": len(headings),
                "results": len(results),
                "buttons": len(buttons),
                "inputs": len(inputs),
                "links": len(links),
            },
        }

    try:
        return get_event_loop().run_until_complete(_snapshot())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "page_snapshot",
            "error": str(exc),
        }

def browser_search_google(query: str) -> dict[str, Any]:
    """Search Google and verify that organic result DOM state is available."""
    query = str(query or "").strip()

    async def _search():
        page = await _init_browser()
        target_url = (
            "https://www.google.com/search?q="
            + quote_plus(query)
        )

        await page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await _auto_skip_ads(page)

        organic_results = await _get_google_organic_result_candidates(
            page,
            limit=10,
            timeout_ms=5_000,
            minimum_results=1,
        )

        info = await browser_page_info_async(page)

        results = [
            {
                "index": index + 1,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
            }
            for index, item in enumerate(organic_results)
        ]

        info.update(
            {
                "action": "browser_search_google",
                "query": query,
                "search_url": target_url,
                "results_ready": bool(results),
                "result_count": len(results),
                "results": results,
                "verified": True,
            }
        )

        return info

    try:
        return get_event_loop().run_until_complete(_search())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "browser_search_google",
            "query": query,
            "error": str(exc),
        }



def browser_search_bing(query: str) -> dict[str, Any]:
    return browser_goto("https://www.bing.com/search?q=" + quote_plus(str(query or "").strip()))


def decode_bing_href(href: str) -> str:
    if not href:
        return ""
    try:
        parsed = urlparse(href)
        encoded_u = parse_qs(parsed.query).get("u", [None])[0]
        if not encoded_u:
            return href
        value = unquote(encoded_u)
        if value.startswith("a1"):
            encoded = value[2:]
            try:
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode(
                    "utf-8", errors="ignore"
                )
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except Exception:
                pass
        return value if value.startswith(("http://", "https://")) else href
    except Exception:
        return href


async def _get_bing_results_async(page) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    containers = page.locator("li.b_algo")
    count = await containers.count()
    for index in range(count):
        try:
            container = containers.nth(index)
            link = container.locator("h2 a").first
            if await link.count() == 0:
                continue
            title = (await link.inner_text()).strip()
            href = (await link.get_attribute("href") or "").strip()
            if not title or not href:
                continue
            results.append(
                {
                    "index": index,
                    "title": title,
                    "href": href,
                    "url": decode_bing_href(href),
                }
            )
        except Exception:
            continue
    return results


def browser_click_first_bing_result(query: Optional[str] = None) -> dict[str, Any]:
    async def _click():
        page = await _init_browser()
        if query:
            await page.goto(
                "https://www.bing.com/search?q=" + quote_plus(query),
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        results = await _get_bing_results_async(page)
        if not results:
            return {
                "success": False,
                "action": "click_first_bing_result",
                "query": query,
                "reason": "No Bing organic results were found in the DOM.",
                "url": page.url,
                "title": await page.title(),
            }

        first = results[0]
        before_url = page.url
        link = page.locator("li.b_algo").nth(first["index"]).locator("h2 a").first

        try:
            await link.scroll_into_view_if_needed(timeout=5_000)
            await link.click(timeout=5_000)
        except Exception:
            target = first["url"]
            if target.startswith(("http://", "https://")):
                await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            else:
                raise

        await page.wait_for_timeout(750)
        return {
            "success": page.url != before_url,
            "action": "click_first_bing_result",
            "query": query,
            "result_title": first["title"],
            "result_url": first["url"],
            "before_url": before_url,
            "after_url": page.url,
            "title": await page.title(),
            "navigated": page.url != before_url,
        }

    try:
        return get_event_loop().run_until_complete(_click())
    except Exception as exc:
        return {
            "success": False,
            "action": "click_first_bing_result",
            "query": query,
            "error": str(exc),
        }


def _infer_site(site: str, page_url: str) -> str:
    site = str(site or "").strip().lower()
    if site:
        return site
    lowered = str(page_url or "").lower()
    if "youtube.com" in lowered:
        return "youtube"
    if "google." in lowered:
        return "google"
    return ""


def browser_back() -> dict[str, Any]:
    """Navigate the current browser page back and verify the URL changed."""
    async def _back():
        page = await _init_browser()
        before_url = page.url
        before_title = await page.title()
        try:
            response = await page.go_back(
                wait_until="domcontentloaded",
                timeout=15_000,
            )
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "error": str(exc),
                "before_url": before_url,
                "before_title": before_title,
            }

        await page.wait_for_timeout(300)
        after_url = page.url
        after_title = await page.title()

        return {
            "success": response is not None or after_url != before_url,
            "verified": after_url != before_url,
            "action": "browser_back",
            "before_url": before_url,
            "after_url": after_url,
            "before_title": before_title,
            "after_title": after_title,
            "url": after_url,
            "title": after_title,
        }

    try:
        return get_event_loop().run_until_complete(_back())
    except Exception as exc:
        return {"success": False, "verified": False, "error": str(exc)}


def browser_refresh() -> dict[str, Any]:
    """Refresh the active browser tab and return its resulting state."""
    async def _refresh():
        page = await _init_browser()
        before_url = page.url
        before_title = await page.title()
        await page.reload(wait_until="domcontentloaded", timeout=30_000)
        await _auto_skip_ads(page)
        after_url = page.url
        after_title = await page.title()
        return {
            "success": True, "verified": True, "action": "browser_refresh",
            "before_url": before_url, "after_url": after_url,
            "before_title": before_title, "after_title": after_title,
            "url": after_url, "title": after_title,
        }
    try:
        return get_event_loop().run_until_complete(_refresh())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_refresh", "error": str(exc)}


def browser_forward() -> dict[str, Any]:
    """Navigate forward in the active browser tab."""
    async def _forward():
        page = await _init_browser()
        before_url = page.url
        before_title = await page.title()
        response = await page.go_forward(wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(300)
        after_url = page.url
        after_title = await page.title()
        changed = after_url != before_url
        return {
            "success": bool(response is not None or changed),
            "verified": bool(changed), "action": "browser_forward",
            "before_url": before_url, "after_url": after_url,
            "before_title": before_title, "after_title": after_title,
            "url": after_url, "title": after_title,
        }
    try:
        return get_event_loop().run_until_complete(_forward())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_forward", "error": str(exc)}


def browser_new_tab(url: str = "") -> dict[str, Any]:
    """Open a new controlled browser tab and optionally navigate to a URL."""
    global _page
    requested_url = str(url or "").strip()
    async def _new_tab():
        global _page
        await _init_browser()
        page = await _context.new_page()
        _page = page
        try:
            await page.bring_to_front()
        except Exception:
            pass
        if requested_url:
            await page.goto(requested_url, wait_until="domcontentloaded", timeout=30_000)
            await _auto_skip_ads(page)
        info = await browser_page_info_async(page)
        info.update({"action": "browser_new_tab", "tab_index": len(_context.pages)})
        return info
    try:
        return get_event_loop().run_until_complete(_new_tab())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_new_tab", "error": str(exc), "url": requested_url}


def _resolve_tab_index(
    index: Any,
    count: int,
    current_index: int = 0,
) -> int:
    if count <= 0:
        raise ValueError("No browser tabs are open.")
    raw = str(index if index is not None else "current").strip().lower()
    if raw in {"current", "active"}:
        return max(0, min(int(current_index), count - 1))
    if raw in {"last", "final"}:
        return count - 1
    try:
        numeric = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tab index must be a number, 'current', or 'last'.") from exc
    if numeric < 1 or numeric > count:
        raise ValueError(f"Tab {numeric} is out of range; {count} tab(s) are open.")
    return numeric - 1


def browser_switch_tab(index: Any = "current") -> dict[str, Any]:
    """Focus a browser tab by 1-based index."""
    global _page
    async def _switch():
        global _page
        await _init_browser()
        pages = list(_context.pages)
        try:
            current_index = pages.index(_page)
        except ValueError:
            current_index = 0
        target_index = _resolve_tab_index(index, len(pages), current_index)
        _page = pages[target_index]
        try:
            await _page.bring_to_front()
        except Exception:
            pass
        info = await browser_page_info_async(_page)
        info.update({"action": "browser_switch_tab", "tab_index": target_index + 1})
        return info
    try:
        return get_event_loop().run_until_complete(_switch())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_switch_tab", "error": str(exc)}


def browser_current_tab() -> dict[str, Any]:
    """Return the active browser tab and its index."""
    global _page
    async def _current():
        global _page
        page = await _init_browser()
        pages = list(_context.pages)
        try:
            tab_index = pages.index(page) + 1
        except ValueError:
            tab_index = 1
        info = await browser_page_info_async(page)
        info.update({"action": "browser_current_tab", "tab_index": tab_index})
        return info
    try:
        return get_event_loop().run_until_complete(_current())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_current_tab", "error": str(exc)}


def browser_close_tab(index: Any = "current") -> dict[str, Any]:
    """Close a browser tab while preserving JARVIS's final page."""
    global _page
    async def _close():
        global _page
        await _init_browser()
        pages = list(_context.pages)
        if len(pages) <= 1:
            return {
                "success": False, "verified": False, "action": "browser_close_tab",
                "error": "The final JARVIS browser tab cannot be closed.",
            }
        try:
            current_index = pages.index(_page)
        except ValueError:
            current_index = 0
        target_index = _resolve_tab_index(index, len(pages), current_index)
        target = pages[target_index]
        closed_url = target.url
        closed_title = await target.title()
        await target.close()
        remaining = list(_context.pages)
        new_index = min(target_index, len(remaining) - 1)
        _page = remaining[new_index]
        try:
            await _page.bring_to_front()
        except Exception:
            pass
        info = await browser_page_info_async(_page)
        info.update({
            "success": True, "verified": True, "action": "browser_close_tab",
            "closed_url": closed_url, "closed_title": closed_title,
            "tab_index": new_index + 1,
        })
        return info
    try:
        return get_event_loop().run_until_complete(_close())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_close_tab", "error": str(exc)}


def browser_get_links(limit: int = 30) -> dict[str, Any]:
    """Return visible links from the current page."""
    async def _links():
        page = await _init_browser()
        try:
            bounded = max(1, min(int(limit), 100))
        except Exception:
            bounded = 30
        links = await _snapshot_links(page, "a", limit=bounded)
        return {
            "success": True, "verified": True, "action": "browser_get_links",
            "url": page.url, "title": (await page.title()).strip(),
            "links": links, "count": len(links),
        }
    try:
        return get_event_loop().run_until_complete(_links())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_get_links", "error": str(exc)}


def _resolve_list_index(index: Any, count: int, label: str = "Item") -> int:
    if count <= 0:
        raise ValueError(f"No {label.lower()}s are available.")
    raw = str(index if index is not None else "1").strip().lower()
    if raw in {"last", "final"}:
        return count - 1
    try:
        numeric = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} index must be a number or 'last'.") from exc
    if numeric < 1 or numeric > count:
        raise ValueError(f"{label} {numeric} is out of range; {count} item(s) are available.")
    return numeric - 1


def browser_open_link(index: Any = 1, text: str = "", href: str = "") -> dict[str, Any]:
    """Open a link by visible text, href, or 1-based visible-link index."""
    async def _open():
        page = await _init_browser()
        before_url = page.url
        before_title = await page.title()
        target_href = str(href or "").strip()
        target_text = str(text or "").strip()
        if target_href:
            await page.goto(target_href, wait_until="domcontentloaded", timeout=30_000)
        else:
            if target_text:
                locator = page.get_by_role("link", name=target_text, exact=False).first
            else:
                links = page.locator("a:visible")
                count = await links.count()
                link_index = _resolve_list_index(index, count, "Link")
                locator = links.nth(link_index)
            await locator.wait_for(state="visible", timeout=10_000)
            await locator.scroll_into_view_if_needed(timeout=5_000)
            link_href = (await locator.get_attribute("href") or "").strip()
            try:
                await locator.click(timeout=5_000)
            except Exception:
                if link_href.startswith(("http://", "https://")):
                    await page.goto(link_href, wait_until="domcontentloaded", timeout=30_000)
                else:
                    raise
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        await page.wait_for_timeout(300)
        after_url = page.url
        after_title = await page.title()
        navigated = after_url != before_url
        return {
            "success": True, "verified": bool(navigated),
            "action": "browser_open_link",
            "before_url": before_url, "after_url": after_url,
            "before_title": before_title, "after_title": after_title,
            "url": after_url, "title": after_title, "navigated": navigated,
        }
    try:
        return get_event_loop().run_until_complete(_open())
    except Exception as exc:
        return {"success": False, "verified": False, "action": "browser_open_link", "error": str(exc)}


def browser_click_result(
    index: int = 1,
    site: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Click an ordinal Google or YouTube result through the DOM."""
    if isinstance(index, str) and index.strip().lower() in {"last", "final"}:
        index = -1
    else:
        try:
            index = int(index)
        except Exception:
            index = 1

    async def _click():
        page = await _init_browser()

        if query:
            inferred = _infer_site(site, page.url)
            if inferred == "youtube":
                await page.goto(
                    "https://www.youtube.com/results?search_query=" + quote_plus(query),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
            elif inferred == "google":
                await page.goto(
                    "https://www.google.com/search?q=" + quote_plus(query),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
            else:
                return {
                    "success": False,
                    "verified": False,
                    "error": f"Unsupported result site: {inferred or site}",
                }

        resolved_site = _infer_site(site, page.url)

        result_candidates: list[dict[str, Any]] = []

        if resolved_site == "google":
            required_results = (
                1
                if index < 0
                else max(1, min(index, 10))
            )
            result_candidates = await _get_google_organic_result_candidates(
                page,
                limit=50,
                timeout_ms=5_000,
                minimum_results=required_results,
            )

        elif resolved_site == "youtube":
            results = page.locator(
                "ytd-video-renderer a#video-title, "
                "ytd-search ytd-video-renderer #video-title"
            )
            count = await results.count()

            for position in range(min(count, 50)):
                locator = results.nth(position)
                try:
                    if not await locator.is_visible():
                        continue

                    title = " ".join(
                        (await locator.inner_text(timeout=1500)).split()
                    ).strip()
                    href = (
                        await locator.get_attribute("href")
                        or ""
                    ).strip()

                    if title and href:
                        result_candidates.append({
                            "locator": locator,
                            "title": title[:500],
                            "url": _snapshot_canonical_url(href)[:2000],
                        })
                except Exception:
                    continue

        else:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "failure_reason": "unsupported_result_site",
                "error": (
                    f"Unsupported result site: "
                    f"{resolved_site or site}"
                ),
                "url": page.url,
            }

        count = len(result_candidates)

        if count == 0:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "failure_reason": "no_organic_results",
                "error": (
                    "No active organic search results were found "
                    "in the browser DOM."
                ),
                "site": resolved_site,
                "url": page.url,
                "title": await page.title(),
            }

        selected_index = (
            count - 1
            if index < 0
            else index - 1
        )

        if selected_index < 0 or selected_index >= count:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "failure_reason": "result_index_out_of_range",
                "error": (
                    f"Result number {index} is out of range; "
                    f"{count} result(s) are available."
                ),
                "site": resolved_site,
                "url": page.url,
            }

        selected = result_candidates[selected_index]
        locator = selected["locator"]

        await locator.wait_for(
            state="visible",
            timeout=5_000,
        )

        before_url = page.url
        before_title = await page.title()
        result_title = str(
            selected.get("title")
            or ""
        ).strip()
        result_url = str(
            selected.get("url")
            or ""
        ).strip()

        if not result_url.startswith(("http://", "https://")):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "failure_reason": "result_has_no_usable_url",
                "error": "The selected browser result has no usable URL.",
                "before_url": before_url,
                "before_title": before_title,
                "result_title": result_title,
            }

        interaction_mode = "dom_click"

        try:
            await locator.scroll_into_view_if_needed(timeout=3_000)
            await locator.click(timeout=5_000)
        except Exception:
            # The exact URL came from the selected DOM element. Navigating to
            # that URL is deterministic and remains browser/DOM-native.
            interaction_mode = "dom_href_navigation"
            await page.goto(
                result_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=5_000,
            )
        except Exception:
            pass

        await page.wait_for_timeout(500)
        after_url = page.url
        after_title = await page.title()

        verified = after_url != before_url
        if resolved_site == "youtube":
            verified = verified and "/watch" in after_url

        return {
            "success": bool(after_url != before_url),
            "verified": bool(verified),
            "action": "browser_click_result",
            "site": resolved_site,
            "index": index,
            "query": query,
            "result_title": result_title,
            "result_url": result_url,
            "before_url": before_url,
            "after_url": after_url,
            "before_title": before_title,
            "after_title": after_title,
            "navigated": after_url != before_url,
            "interaction_mode": interaction_mode,
            "dom_control": True,
        }

    try:
        return get_event_loop().run_until_complete(_click())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "action": "browser_click_result",
            "index": index,
            "site": site,
            "query": query,
            "error": str(exc),
        }


def browser_click_first_result(site: str = "", query: str = "") -> dict[str, Any]:
    """Click the first organic result using Playwright DOM controls."""
    site = str(site or "").strip().lower()
    query = str(query or "").strip()

    if site == "google":
        result = browser_click_result(
            index=1,
            site="google",
            query=query,
        )

        if isinstance(result, dict):
            result = dict(result)
            result["action"] = "click_first_result"

        return result

    async def _click():
        page = await _init_browser()

        if query:
            if site == "youtube":
                target_url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
            elif site == "google":
                target_url = "https://www.google.com/search?q=" + quote_plus(query)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported first-result site: {site}",
                }

            await page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

        if site == "youtube":
            locator = page.locator(
                "ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title"
            ).first
        elif site == "google":
            locator = page.locator("div#search a:has(h3)").first
        else:
            return {
                "success": False,
                "error": f"Unsupported first-result site: {site}",
                "url": page.url,
            }

        try:
            await locator.wait_for(
                state="visible",
                timeout=10_000,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": f"First organic result was not found in the DOM: {exc}",
                "url": page.url,
                "title": await page.title(),
            }

        before_url = page.url
        before_title = await page.title()

        result_title = ""
        try:
            # Google result anchors contain the clean result title in h3;
            # using the whole anchor text also captures breadcrumbs/snippets.
            heading = locator.locator("h3").first
            if await heading.count():
                result_title = (await heading.inner_text()).strip()
        except Exception:
            result_title = ""

        if not result_title:
            try:
                result_title = (await locator.inner_text()).strip()
            except Exception:
                result_title = ""

        result_url = (await locator.get_attribute("href") or "").strip()

        try:
            await locator.scroll_into_view_if_needed(timeout=5_000)
            await locator.click(timeout=5_000)
        except Exception:
            if result_url.startswith(("http://", "https://")):
                await page.goto(
                    result_url,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
            else:
                return {
                    "success": False,
                    "error": "DOM click failed and the result had no usable URL.",
                    "before_url": before_url,
                    "before_title": before_title,
                }

        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=5_000,
            )
        except Exception:
            pass

        await page.wait_for_timeout(750)

        after_url = page.url
        after_title = await page.title()

        expected_navigation = (
            after_url != before_url
            and (
                site != "youtube"
                or "/watch" in after_url
                or "youtube.com/watch" in after_url
            )
        )

        return {
            "success": bool(after_url != before_url),
            "verified": bool(expected_navigation),
            "action": "click_first_result",
            "site": site,
            "query": query,
            "result_title": result_title,
            "result_url": result_url,
            "before_url": before_url,
            "after_url": after_url,
            "before_title": before_title,
            "after_title": after_title,
            "navigated": after_url != before_url,
            "dom_control": True,
            "verification_status": (
                "verified"
                if expected_navigation
                else "failed"
            ),
        }

    try:
        return get_event_loop().run_until_complete(_click())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "error": str(exc),
            "site": site,
            "query": query,
        }


def browser_find_text(
    query: str,
    context_chars: int = 120,
    max_matches: int = 3,
) -> dict[str, Any]:
    """Find a text phrase in the current page and return nearby readable context."""
    requested = " ".join(str(query or "").split()).strip()

    if not requested:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "action": "find_text",
            "error": "Text query cannot be empty.",
        }

    try:
        context_chars = max(20, min(int(context_chars), 400))
    except Exception:
        context_chars = 120

    try:
        max_matches = max(1, min(int(max_matches), 10))
    except Exception:
        max_matches = 3

    async def _find():
        page = await _init_browser()

        try:
            body_text = await page.locator("body").evaluate(
                """el => (
                    el.innerText ||
                    el.textContent ||
                    ""
                ).trim()"""
            )
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "find_text",
                "query": requested,
                "error": f"Could not read browser page text: {exc}",
            }

        readable = _snapshot_clean_text(body_text, max_chars=12000)
        lowered = readable.lower()
        needle = requested.lower()

        matches = []
        start = 0

        while len(matches) < max_matches:
            position = lowered.find(needle, start)
            if position < 0:
                break

            left = max(0, position - context_chars)
            right = min(
                len(readable),
                position + len(requested) + context_chars,
            )

            excerpt = " ".join(readable[left:right].split())
            matches.append({
                "match": requested,
                "excerpt": excerpt[: max(40, context_chars * 2 + len(requested))],
            })

            next_start = position + max(len(requested), 1)
            if next_start <= start:
                break
            start = next_start

        return {
            "success": True,
            "verified": bool(matches),
            "action": "find_text",
            "query": requested,
            "found": bool(matches),
            "match_count": len(matches),
            "matches": matches,
            "url": page.url,
            "title": (await page.title()).strip(),
        }

    try:
        return get_event_loop().run_until_complete(_find())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "find_text",
            "query": requested,
            "error": str(exc),
        }


def browser_find_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    async def _find():
        page = await _init_browser()
        locator = _locator(page, selector, text, role, name)
        info = await _dom_target_info(locator)

        return {
            "success": True,
            "verified": bool(info["found"] and info["visible"]),
            "action": "find_element",
            **info,
            **_dom_target_args(selector, text, role, name),
        }

    try:
        return get_event_loop().run_until_complete(_find())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "found": False,
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }


def browser_click_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    async def _click():
        page = await _init_browser()
        locator = _locator(page, selector, text, role, name)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "click",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role, name),
            }

        before_url = page.url
        before_title = await page.title()

        try:
            await locator.first.click(timeout=5_000)
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "click",
                "error": str(exc),
                **_dom_target_args(selector, text, role, name),
            }

        await page.wait_for_timeout(350)

        after_url = page.url
        after_title = await page.title()

        navigated = after_url != before_url
        title_changed = after_title != before_title

        return {
            "success": True,
            "verified": True,
            "action": "click",
            "retryable": False,
            "target_count": info["count"],
            "target_text": info["element_text"],
            "before_url": before_url,
            "after_url": after_url,
            "before_title": before_title,
            "after_title": after_title,
            "navigated": navigated,
            "title_changed": title_changed,
            "verification_status": (
                "navigation"
                if navigated
                else "title_change"
                if title_changed
                else "click_accepted"
            ),
            **_dom_target_args(selector, text, role, name),
        }

    try:
        return get_event_loop().run_until_complete(_click())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "click",
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }


def browser_fill_element(
    value: str,
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    async def _fill():
        page = await _init_browser()
        locator = _locator(page, selector, text, role, name)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "fill",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role, name),
            }

        requested = str(value or "")
        target = locator.first

        await target.fill(requested, timeout=5_000)

        actual = ""
        verification_status = "exact_value"

        try:
            actual = str(await target.input_value())
        except Exception:
            try:
                actual = str(await target.text_content() or "")
            except Exception:
                actual = ""

        if actual != requested:
            try:
                dom_value = await target.evaluate(
                    """el => {
                        if (typeof el.value === "string") return el.value;
                        return el.textContent || "";
                    }"""
                )
                actual = str(dom_value or "")
            except Exception:
                pass

        verified = actual == requested

        # Playwright's fill() already succeeded without throwing. Some
        # custom combobox/contenteditable controls do not expose their value
        # through input_value(), so do not trigger a costly LLM replan when
        # the target is confirmed editable.
        if not verified:
            try:
                if await target.is_editable():
                    verified = True
                    verification_status = "fill_applied"
            except Exception:
                pass

        return {
            "success": True,
            "verified": verified,
            "action": "fill",
            "value": actual,
            "requested_value": requested,
            "characters": len(actual),
            "target_count": info["count"],
            "verification_status": verification_status,
            **_dom_target_args(selector, text, role, name),
        }

    try:
        return get_event_loop().run_until_complete(_fill())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "fill",
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }


def browser_press_key(
    key: str,
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    async def _press():
        page = await _init_browser()
        locator = _locator(page, selector, text, role, name)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "press",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role, name),
            }

        requested_key = str(key or "").strip()
        if not requested_key:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "action": "press",
                "error": "Key cannot be empty.",
                **_dom_target_args(selector, text, role, name),
            }

        before_url = page.url
        before_title = await page.title()

        try:
            # Send the key through the target locator so Playwright targets
            # the element directly. no_wait_after keeps Enter-driven navigation
            # from making the tool block on a full navigation lifecycle.
            await locator.first.press(
                requested_key,
                timeout=5_000,
                no_wait_after=True,
            )
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "press",
                "error": str(exc),
                **_dom_target_args(selector, text, role, name),
            }

        await page.wait_for_timeout(250)

        after_url = page.url
        after_title = await page.title()

        return {
            "success": True,
            "verified": True,
            "action": "press",
            "key": requested_key,
            "target_count": info["count"],
            "before_url": before_url,
            "after_url": after_url,
            "before_title": before_title,
            "after_title": after_title,
            "navigated": after_url != before_url,
            "title_changed": after_title != before_title,
            **_dom_target_args(selector, text, role, name),
        }

    try:
        return get_event_loop().run_until_complete(_press())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "press",
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }


def browser_wait_for_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
    timeout: int = 10_000,
):
    async def _wait():
        page = await _init_browser()
        locator = _locator(page, selector, text, role, name)

        timeout_ms = max(1, int(timeout))

        await locator.first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )

        info = await _dom_target_info(locator)

        return {
            "success": True,
            "verified": bool(info["found"] and info["visible"]),
            "action": "wait_for_element",
            "retryable": False,
            "timeout": timeout_ms,
            **info,
            **_dom_target_args(selector, text, role, name),
        }

    try:
        return get_event_loop().run_until_complete(_wait())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "wait_for_element",
            "found": False,
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }


def browser_extract_text(
    selector: str = "",
    text: str = "",
    role: str = "",
    name: str = "",
):
    async def _extract():
        page = await _init_browser()

        # A blank target means "read the current page". This makes the tool
        # useful both from the deterministic router and from direct calls.
        selector_value = str(selector or "").strip()
        text_value = str(text or "").strip()
        role_value = str(role or "").strip()
        name_value = str(name or "").strip()

        if not selector_value and not text_value and not role_value:
            selector_value = "body"

        # Give client-rendered pages a chance to populate after
        # navigation. Google and other SPAs can settle their visible DOM
        # well after domcontentloaded.
        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=5_000,
            )
        except Exception:
            pass

        try:
            await page.wait_for_function(
                """() => {
                    const body = document.body;
                    if (!body) return false;
                    const text = (
                        body.innerText ||
                        body.textContent ||
                        ""
                    ).trim();
                    return text.length > 20;
                }""",
                timeout=5_000,
            )
        except Exception:
            await page.wait_for_timeout(750)

        locator = _locator(
            page,
            selector_value,
            text_value,
            role_value,
            name_value,
        )
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "extract_text",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(
                    selector_value,
                    text_value,
                    role_value,
                    name_value,
                ),
            }

        extracted = ""

        # For whole-page reads, use the same locator.evaluate path that
        # diagnostics use below. The live DOM has proven this call can see
        # thousands of characters even when locator.inner_text() is empty.
        if (
            selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                direct_body_text = await page.locator("body").evaluate(
                    """el => (
                        el.innerText ||
                        el.textContent ||
                        ""
                    ).trim()"""
                )
                if isinstance(direct_body_text, str) and direct_body_text:
                    extracted = direct_body_text
            except Exception:
                pass

        try:
            if not extracted:
                extracted = (
                    await locator.first.inner_text(timeout=5_000)
                ).strip()
        except Exception:
            pass

        # Some applications expose readable text through textContent even
        # when Playwright's inner_text is empty.
        if not extracted:
            try:
                extracted = (
                    await locator.first.text_content(timeout=3_000)
                or ""
                ).strip()
            except Exception:
                pass

        # If the requested target is the page body, inspect child frames too.
        # Embedded applications sometimes render their useful DOM inside an
        # iframe while the top-level body remains nearly empty.
        frame_texts = []
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            for frame in page.frames:
                try:
                    frame_body = frame.locator("body")
                    if await frame_body.count() == 0:
                        continue

                    frame_text = (
                        await frame_body.first.inner_text(timeout=2_000)
                    ).strip()

                    if frame_text:
                        frame_texts.append(frame_text)
                except Exception:
                    continue

            if frame_texts:
                unique = []
                seen = set()
                for value in frame_texts:
                    if value in seen:
                        continue
                    seen.add(value)
                    unique.append(value)
                extracted = "\n\n".join(unique)

        # Pull visible text from common semantic elements as a fallback
        # when a browser page paints content but body.innerText is empty.
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                semantic_text = await page.evaluate(
                    """() => Array.from(
                        document.querySelectorAll(
                            "h1,h2,h3,h4,h5,h6,p,a,button,li,td,th,label,summary"
                        )
                    )
                    .map(el => (el.innerText || el.textContent || "").trim())
                    .filter(Boolean)
                    .join("\n")
                    """,
                )
                extracted = str(semantic_text or "").strip()
            except Exception:
                pass

        # Walk open shadow roots as well. Some modern web apps render
        # their visible text inside shadow DOM, which body.innerText does not
        # always expose to Playwright.
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                shadow_text = await page.evaluate(
                    """() => {
                        const chunks = [];
                        const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT"]);

                        const walk = (root) => {
                            if (!root) return;

                            for (const node of root.childNodes || []) {
                                if (node.nodeType === Node.TEXT_NODE) {
                                    const value = (node.textContent || "").trim();
                                    if (value) chunks.push(value);
                                    continue;
                                }

                                if (node.nodeType !== Node.ELEMENT_NODE) {
                                    continue;
                                }

                                if (skip.has(node.tagName)) {
                                    continue;
                                }

                                const shadow = node.shadowRoot;
                                if (shadow) {
                                    walk(shadow);
                                }

                                walk(node);
                            }
                        };

                        walk(document.body);
                        return chunks.join("\n");
                    }""",
                )
                extracted = str(shadow_text or "").strip()
            except Exception:
                pass

        # Use Playwright's accessibility snapshot when available. This
        # captures rendered/accessible text from controls and content that
        # may not be exposed by body.innerText on highly dynamic pages.
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                snapshot = await locator.first.aria_snapshot(
                    timeout=5_000
                )
                extracted = str(snapshot or "").strip()
            except (AttributeError, TypeError):
                pass
            except Exception:
                pass

        # Final top-level DOM fallback for heavily client-rendered pages.
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                extracted = (
                    await page.evaluate(
                        """() => {
                            const body = document.body;
                            if (!body) return "";
                            return (
                                body.innerText ||
                                body.textContent ||
                                document.documentElement?.innerText ||
                                document.documentElement?.textContent ||
                                ""
                            );
                        }"""
                    )
                ).strip()
            except Exception:
                pass

        # Last-resort HTML fallback. This catches pages where the
        # browser visibly contains text but the layout tree exposes little
        # through innerText/textContent.
        if (
            not extracted
            and selector_value.lower() == "body"
            and not text_value
            and not role_value
        ):
            try:
                import html as html_module
                import re as regex_module

                markup = await page.content()
                stripped = regex_module.sub(
                    r"<script\b[^>]*>[\s\S]*?</script>|<style\b[^>]*>[\s\S]*?</style>",
                    " ",
                    markup,
                    flags=regex_module.IGNORECASE,
                )
                stripped = regex_module.sub(
                    r"<[^>]+>",
                    " ",
                    stripped,
                )
                stripped = html_module.unescape(stripped)
                stripped = regex_module.sub(
                    r"\s+",
                    " ",
                    stripped,
                ).strip()

                if len(stripped) > 20:
                    extracted = stripped
            except Exception:
                pass

        diagnostics = {}
        try:
            diagnostics["body_text_length"] = int(
                await page.locator("body").evaluate(
                    "el => ((el.innerText || el.textContent || '').trim().length)"
                )
            )
        except Exception:
            diagnostics["body_text_length"] = -1

        try:
            diagnostics["document_text_length"] = int(
                await page.evaluate(
                    """() => (
                        document.documentElement?.innerText ||
                        document.documentElement?.textContent ||
                        ""
                    ).trim().length"""
                )
            )
        except Exception:
            diagnostics["document_text_length"] = -1

        try:
            diagnostics["html_length"] = int(
                len(await page.content())
            )
        except Exception:
            diagnostics["html_length"] = -1

        try:
            diagnostics["body_text_preview"] = str(
                await page.locator("body").evaluate(
                    """el => (
                        el.innerText ||
                        el.textContent ||
                        ""
                    ).trim().slice(0, 300)"""
                )
            )
        except Exception:
            diagnostics["body_text_preview"] = ""

        # Final verified extraction checkpoint. The diagnostics above
        # already prove that this exact locator/evaluate path can see the
        # page text, so use it one last time immediately before deciding
        # that the page has no readable content.
        if not extracted:
            try:
                final_body_text = await page.locator("body").evaluate(
                    """el => (
                        el.innerText ||
                        el.textContent ||
                        ""
                    ).trim()"""
                )

                if final_body_text:
                    extracted = str(final_body_text).strip()
            except Exception:
                pass

        metadata_only = False
        if not extracted:
            try:
                title = (await page.title()).strip()
            except Exception:
                title = ""

            url = str(getattr(page, "url", "") or "").strip()

            metadata_lines = []
            if title:
                metadata_lines.append(f"Page title: {title}")
            if url:
                metadata_lines.append(f"URL: {url}")

            extracted = "\n".join(metadata_lines)
            metadata_only = bool(extracted)

        return {
            "success": True,
            "verified": bool(extracted) and not metadata_only,
            "action": "extract_text",
            "text": extracted,
            "characters": len(extracted),
            "target_count": info["count"],
            "metadata_only": metadata_only,
            "diagnostics": diagnostics,
            "selector": selector_value,
            "target_text": text_value,
            "role": role_value,
            "name": name_value,
        }

    try:
        return get_event_loop().run_until_complete(_extract())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "action": "extract_text",
            "error": str(exc),
            **_dom_target_args(selector, text, role, name),
        }

def capture_screenshot() -> bytes:
    async def _shot():
        page = await _init_browser()
        return await page.screenshot(type="jpeg", quality=80)

    return get_event_loop().run_until_complete(_shot())


def click_at_coords(x: int, y: int) -> None:
    async def _click_xy():
        page = await _init_browser()
        await page.mouse.click(int(x), int(y))

    get_event_loop().run_until_complete(_click_xy())


def cleanup_browser():
    global _playwright, _context, _page, _skipper_task, _loop, _connection_task, _driver_process

    loop_to_close = _loop

    try:
        if loop_to_close and not loop_to_close.is_closed():
            async def _close():
                if _skipper_task and not _skipper_task.done():
                    _skipper_task.cancel()
                    await asyncio.gather(
                        _skipper_task,
                        return_exceptions=True,
                    )

                if _context:
                    try:
                        await _context.close()
                    except Exception as exc:
                        logging.debug(
                            f"Browser context close exception: {exc}"
                        )

                if _playwright:
                    try:
                        await _playwright.stop()
                    except Exception as exc:
                        logging.debug(
                            f"Playwright stop exception: {exc}"
                        )

                # Playwright owns the driver process and its Connection.run()
                # task. On Windows, process EOF can race interpreter teardown.
                # Force the child process down if it remains alive, then cancel
                # and await only Playwright's own connection task.
                process = _driver_process
                if process is not None:
                    try:
                        if process.returncode is None:
                            process.terminate()
                            await asyncio.wait_for(
                                process.wait(),
                                timeout=2.0,
                            )
                    except asyncio.TimeoutError:
                        try:
                            process.kill()
                            await asyncio.wait_for(
                                process.wait(),
                                timeout=2.0,
                            )
                        except Exception as exc:
                            logging.debug(
                                f"Playwright driver kill exception: {exc}"
                            )
                    except Exception as exc:
                        logging.debug(
                            f"Playwright driver termination exception: {exc}"
                        )

                    # The Process wrapper can retain a Windows subprocess
                    # transport after the child exits. Close that transport
                    # explicitly so its __del__ hook never runs against a
                    # closed event loop.
                    process_transport = getattr(process, "_transport", None)
                    if process_transport is not None:
                        try:
                            process_transport.close()
                        except Exception:
                            pass

                if _connection_task and not _connection_task.done():
                    _connection_task.cancel()
                    await asyncio.gather(
                        _connection_task,
                        return_exceptions=True,
                    )

                await asyncio.sleep(0)

            loop_to_close.run_until_complete(_close())

            # Do not leave Playwright's internal connection task (or any
            # controller-owned async task) alive when the loop is closed.
            # Explicit cancellation here prevents Python 3.12's Windows
            # Proactor cleanup from reporting "Task was destroyed while it is
            # pending" during interpreter shutdown.
            pending = [
                task
                for task in asyncio.all_tasks(loop=loop_to_close)
                if not task.done()
            ]

            if pending:
                for task in pending:
                    task.cancel()

                loop_to_close.run_until_complete(
                    asyncio.gather(
                        *pending,
                        return_exceptions=True,
                    )
                )

            loop_to_close.run_until_complete(
                loop_to_close.shutdown_asyncgens()
            )
            loop_to_close.close()

    finally:
        _playwright = None
        _context = None
        _page = None
        _skipper_task = None
        _connection_task = None
        _driver_process = None
        _loop = None


atexit.register(cleanup_browser)
