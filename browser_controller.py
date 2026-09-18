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
    global _playwright, _context, _page, _skipper_task

    if _page is not None:
        try:
            if not _page.is_closed():
                return _page
        except Exception:
            pass

    _playwright = await async_playwright().start()
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


def _locator(page, selector: str = "", text: str = "", role: str = ""):
    selector = (selector or "").strip()
    text = (text or "").strip()
    role = (role or "").strip()

    if selector:
        return page.locator(selector).first
    if role:
        return page.get_by_role(role).first
    if text:
        return page.get_by_text(text, exact=False).first
    return page.locator("body")


async def browser_page_info_async(page) -> dict[str, Any]:
    return {
        "success": True,
        "url": page.url,
        "title": await page.title(),
        "pages": len(_context.pages) if _context else 0,
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


def browser_find_element(selector: str = "", text: str = "", role: str = ""):
    async def _find():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        count = await locator.count()
        if count == 0:
            return {"success": True, "found": False, "visible": False}
        try:
            visible = await locator.is_visible()
        except Exception:
            visible = False
        return {
            "success": True,
            "found": True,
            "visible": visible,
            "selector": selector,
            "text": text,
            "role": role,
        }

    try:
        return get_event_loop().run_until_complete(_find())
    except Exception as exc:
        return {"success": False, "found": False, "error": str(exc)}


def browser_click_element(selector: str = "", text: str = "", role: str = ""):
    async def _click():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        if await locator.count() == 0:
            return {"success": False, "error": "No matching element found."}
        before_url = page.url
        before_title = await page.title()
        try:
            await locator.click(timeout=5_000)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "before_url": before_url,
                "after_url": page.url,
                "before_title": before_title,
                "after_title": await page.title(),
            }
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        return {
            "success": True,
            "action": "click",
            "before_url": before_url,
            "after_url": page.url,
            "before_title": before_title,
            "after_title": await page.title(),
            "navigated": page.url != before_url,
        }

    try:
        return get_event_loop().run_until_complete(_click())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def browser_fill_element(value: str, selector: str = "", text: str = "", role: str = ""):
    async def _fill():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        if await locator.count() == 0:
            return {"success": False, "error": "No matching element found."}
        await locator.fill(str(value or ""), timeout=5_000)
        return {"success": True, "action": "fill"}

    try:
        return get_event_loop().run_until_complete(_fill())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def browser_press_key(key: str, selector: str = "", text: str = "", role: str = ""):
    async def _press():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        await locator.press(str(key or ""), timeout=5_000)
        return {"success": True, "action": "press", "key": key}

    try:
        return get_event_loop().run_until_complete(_press())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def browser_wait_for_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    timeout: int = 10000,
):
    async def _wait():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        await locator.wait_for(state="visible", timeout=int(timeout))
        return {"success": True, "action": "wait_for_element", "found": True}

    try:
        return get_event_loop().run_until_complete(_wait())
    except Exception as exc:
        return {"success": False, "found": False, "error": str(exc)}


def browser_extract_text(selector: str = "", text: str = "", role: str = ""):
    async def _extract():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        return {"success": True, "action": "extract_text", "text": await locator.inner_text(timeout=5_000)}

    try:
        return get_event_loop().run_until_complete(_extract())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def click_dom_element(target_text: str) -> bool:
    async def _click():
        page = await _init_browser()
        try:
            target = str(target_text or "").strip()
            if not target:
                return False
            yt_titles = page.locator(
                "ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title"
            )
            count = await yt_titles.count()
            clean_target = target.replace("-", "").replace(" ", "").lower()
            for index in range(min(count, 5)):
                elem = yt_titles.nth(index)
                text = (await elem.inner_text()).strip()
                clean_text = text.replace("-", "").replace(" ", "").lower()
                if clean_target in clean_text:
                    await elem.click()
                    logging.info(f"DOM Click successful on YouTube video title: {text}")
                    await asyncio.sleep(1)
                    await _auto_skip_ads(page)
                    return True

            locator = page.get_by_text(target, exact=False).first
            if await locator.count() and await locator.is_visible():
                await locator.click()
                logging.info(f"DOM Click successful on text: '{target}'")
                return True
        except Exception as exc:
            logging.warning(f"DOM Click attempt failed: {exc}")
        return False

    try:
        return bool(get_event_loop().run_until_complete(_click()))
    except Exception:
        return False


def browser_media_control(action: str) -> str:
    async def _control():
        page = await _init_browser()
        return await page.evaluate(
            """(action) => {
                const video = document.querySelector('video');
                if (!video) return 'No video element found';
                switch (action) {
                    case 'pause': video.pause(); return 'Video paused';
                    case 'play': video.play(); return 'Video resumed';
                    case 'mute': video.muted = true; return 'Audio muted';
                    case 'unmute': video.muted = false; return 'Audio unmuted';
                    case 'volume_up':
                        video.volume = Math.min(1.0, video.volume + 0.1);
                        return `Volume increased to ${Math.round(video.volume * 100)}%`;
                    case 'volume_down':
                        video.volume = Math.max(0.0, video.volume - 0.1);
                        return `Volume decreased to ${Math.round(video.volume * 100)}%`;
                    default: return 'Unknown media action';
                }
            }""",
            action,
        )

    try:
        return str(get_event_loop().run_until_complete(_control()))
    except Exception as exc:
        return f"Media control failed: {exc}"


def browser_add_to_queue(target_text: str) -> str:
    async def _queue():
        page = await _init_browser()
        target = str(target_text or "").strip().lower()
        yt_titles = page.locator(
            "ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title"
        )
        count = await yt_titles.count()
        for index in range(min(count, 10)):
            elem = yt_titles.nth(index)
            text = (await elem.inner_text()).strip()
            if target and target in text.lower():
                renderer = elem.locator("xpath=ancestor::ytd-video-renderer").first
                await renderer.hover()
                menu_btn = renderer.locator("yt-icon-button#button, button.dropdown-trigger").first
                await menu_btn.click(timeout=5_000)
                option = page.get_by_text("Add to queue", exact=True).first
                await option.click(timeout=5_000)
                return f"Successfully added '{text}' to the YouTube queue."
        return f"Could not find video matching '{target_text}' to queue."

    try:
        return get_event_loop().run_until_complete(_queue())
    except Exception as exc:
        return f"Failed to queue video: {exc}"



def browser_self_test() -> dict[str, Any]:
    """Run a focused runtime smoke test of JARVIS browser automation."""
    async def _test():
        page = await _init_browser()
        test_page = await _context.new_page()
        original_url = page.url

        try:
            # 1) Exercise the generic DOM locator path on a controlled page.
            await test_page.set_content(
                """<!doctype html>
<html><body>
<input aria-label="Search" id="search">
<button type="button" id="go" onclick="document.body.dataset.clicked='1'; document.querySelector('#result').textContent=document.querySelector('#search').value;">Go</button>
<div id="result"></div>
</body></html>"""
            )

            search = test_page.get_by_role("textbox", name="Search")
            if await search.count() == 0:
                return {
                    "success": False,
                    "verified": False,
                    "mode": "browser_smoke",
                    "message": "Browser DOM smoke test failed: search textbox role was not found.",
                }

            await search.fill("JARVIS browser test")
            await search.press("Enter")

            # Enter has no submit handler in this fixture; verify the fill
            # path directly before exercising the click/wait/extract path.
            button = test_page.locator("#go").first
            await button.click(timeout=5_000)
            result = test_page.locator("#result").first
            await result.wait_for(state="visible", timeout=5_000)
            extracted = (await result.inner_text()).strip()

            if extracted != "JARVIS browser test":
                return {
                    "success": False,
                    "verified": False,
                    "mode": "browser_smoke",
                    "message": (
                        "Browser DOM smoke test failed: fill/click/extract "
                        f"returned {extracted!r} instead of the expected text."
                    ),
                }

            # 2) Verify the live Google first-result selector still resolves.
            await test_page.goto(
                "https://www.google.com/search?q=JARVIS+browser+automation",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            google_result = test_page.locator("div#search a:has(h3)").first
            await google_result.wait_for(state="visible", timeout=10_000)
            google_title = (await google_result.inner_text()).strip()

            if not google_title:
                return {
                    "success": False,
                    "verified": False,
                    "mode": "browser_smoke",
                    "message": "Browser smoke test failed: Google first-result selector matched an empty result.",
                }

            return {
                "success": True,
                "verified": True,
                "mode": "browser_smoke",
                "message": "Browser automation smoke test passed.",
                "dom_test": "fill/click/wait/extract passed",
                "google_first_result": google_title[:300],
                "google_selector": "div#search a:has(h3)",
                "original_url": original_url,
            }

        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "mode": "browser_smoke",
                "message": f"Browser automation smoke test failed: {exc}",
                "error": str(exc),
                "original_url": original_url,
            }
        finally:
            try:
                await test_page.close()
            except Exception:
                pass

    try:
        return get_event_loop().run_until_complete(_test())
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "mode": "browser_smoke",
            "message": f"Browser automation smoke test failed to start: {exc}",
            "error": str(exc),
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
    global _playwright, _context, _page, _skipper_task, _loop
    try:
        if _loop and not _loop.is_closed():
            async def _close():
                current_task = asyncio.current_task()
                pending = []

                if _skipper_task:
                    _skipper_task.cancel()
                    pending.append(_skipper_task)

                if _context:
                    await _context.close()

                if _playwright:
                    await _playwright.stop()

                # Playwright owns an internal connection task. Await any
                # remaining tasks before the event loop is released so Python
                # does not report "Task was destroyed but it is pending!".
                for task in asyncio.all_tasks():
                    if (
                        task is not current_task
                        and not task.done()
                        and task not in pending
                    ):
                        task.cancel()
                        pending.append(task)

                if pending:
                    await asyncio.gather(
                        *pending,
                        return_exceptions=True,
                    )

            _loop.run_until_complete(_close())
    except Exception as exc:
        logging.debug(f"Browser cleanup exception: {exc}")
    finally:
        _playwright = None
        _context = None
        _page = None
        _skipper_task = None


atexit.register(cleanup_browser)
