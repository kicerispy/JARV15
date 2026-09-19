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
        args=["--disable-blink-features=AutomationControlled"],
    )

    pages = _context.pages
    _page = pages[-1] if pages else await _context.new_page()
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
            return page.get_by_role(role, name=name, exact=False)
        return page.get_by_role(role)

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
) -> dict[str, str]:
    return {
        "selector": str(selector or "").strip(),
        "text": str(text or "").strip(),
        "role": str(role or "").strip(),
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


def browser_search_google(query: str) -> dict[str, Any]:
    return browser_goto("https://www.google.com/search?q=" + quote_plus(str(query or "").strip()))


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
        if resolved_site == "youtube":
            results = page.locator(
                "ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title"
            )
        elif resolved_site == "google":
            results = page.locator("div#search a:has(h3)")
        else:
            return {
                "success": False,
                "verified": False,
                "error": f"Unsupported result site: {resolved_site or site}",
                "url": page.url,
            }

        count = await results.count()
        if count == 0:
            return {
                "success": False,
                "verified": False,
                "error": "No organic browser results were found.",
                "url": page.url,
            }

        selected_index = count - 1 if index < 0 else index - 1
        if selected_index < 0 or selected_index >= count:
            return {
                "success": False,
                "verified": False,
                "error": f"Result number {index} is out of range; {count} result(s) are available.",
                "url": page.url,
            }

        locator = results.nth(selected_index)
        await locator.wait_for(state="visible", timeout=10_000)

        before_url = page.url
        before_title = await page.title()
        result_title = ""
        try:
            heading = locator.locator("h3").first
            if await heading.count():
                result_title = (await heading.inner_text()).strip()
        except Exception:
            pass

        if not result_title:
            result_title = (await locator.inner_text()).strip()

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
                    "verified": False,
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
        try:
            actual = await target.input_value()
        except Exception:
            try:
                actual = await target.text_content() or ""
            except Exception:
                actual = ""

        actual = str(actual)

        return {
            "success": True,
            "verified": actual == requested,
            "action": "fill",
            "value": actual,
            "requested_value": requested,
            "characters": len(actual),
            "target_count": info["count"],
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
            await locator.first.press(requested_key, timeout=5_000)
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
                ),
            }

        extracted = ""

        try:
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
            **_dom_target_args(
                selector_value,
                text_value,
                role_value,
                "",
            ),
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
    except Exception as exc:
        logging.debug(f"Browser cleanup exception: {exc}")
    finally:
        _playwright = None
        _context = None
        _page = None
        _skipper_task = None
        _connection_task = None
        _driver_process = None
        _loop = None


atexit.register(cleanup_browser)
