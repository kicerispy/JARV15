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
):
    """Build a Playwright locator from one explicit targeting strategy.

    JARVIS should never silently target the entire page when no target was
    supplied. Callers must provide selector, text, or role.
    """
    selector = str(selector or "").strip()
    text = str(text or "").strip()
    role = str(role or "").strip()

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


def browser_find_element(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    async def _find():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        info = await _dom_target_info(locator)

        return {
            "success": True,
            "verified": bool(info["found"] and info["visible"]),
            "action": "find_element",
            **info,
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
        }


def browser_click_element(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    async def _click():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "click",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role),
            }

        before_url = page.url
        before_title = await page.title()

        await locator.first.click(timeout=5_000)

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
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
        }


def browser_fill_element(
    value: str,
    selector: str = "",
    text: str = "",
    role: str = "",
):
    async def _fill():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "fill",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
        }


def browser_press_key(
    key: str,
    selector: str = "",
    text: str = "",
    role: str = "",
):
    async def _press():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "press",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role),
            }

        requested_key = str(key or "").strip()
        if not requested_key:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "action": "press",
                "error": "Key cannot be empty.",
                **_dom_target_args(selector, text, role),
            }

        before_url = page.url
        before_title = await page.title()

        await locator.first.press(requested_key, timeout=5_000)
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
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
        }


def browser_wait_for_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    timeout: int = 10_000,
):
    async def _wait():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)

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
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
        }


def browser_extract_text(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    async def _extract():
        page = await _init_browser()
        locator = _locator(page, selector, text, role)
        info = await _dom_target_info(locator)

        if not info["found"]:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "action": "extract_text",
                "error": "No matching element found.",
                **info,
                **_dom_target_args(selector, text, role),
            }

        extracted = (await locator.first.inner_text(timeout=5_000)).strip()

        return {
            "success": True,
            "verified": True,
            "action": "extract_text",
            "text": extracted,
            "characters": len(extracted),
            "target_count": info["count"],
            **_dom_target_args(selector, text, role),
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
            **_dom_target_args(selector, text, role),
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
