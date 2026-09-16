from __future__ import annotations
from pathlib import Path

from typing import Any, Optional
from urllib.parse import quote_plus, parse_qs, urlparse, unquote

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)



CDP_URL = "http://127.0.0.1:9222"

CHROME_AUTOMATION_DIR = (
    r"C:\Users\Jordan\Desktop\Jarvis\chrome_automation"
)

CDP_STARTUP_TIMEOUT = 10.0
CDP_POLL_INTERVAL = 0.25


def find_chrome_executable():
    """
    Locate the normal Google Chrome executable on Windows.
    """

    candidates = [
        Path(
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        ),
        Path(
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ),
        Path(
            r"C:\Users\Jordan\AppData\Local\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def cdp_is_available():
    """
    Check whether Chrome's CDP endpoint is already responding.
    """

    try:
        import urllib.request

        with urllib.request.urlopen(
            f"{CDP_URL}/json/version",
            timeout=1.0,
        ) as response:

            return response.status == 200

    except Exception:
        return False


def start_cdp_chrome():
    """
    Start the dedicated JARVIS Chrome instance.

    This is intentionally separate from the user's normal
    Chrome profile so Playwright/CDP automation does not
    interfere with the normal browser session.
    """

    import os
    import subprocess

    if cdp_is_available():
        return {
            "success": True,
            "started": False,
            "message": "CDP Chrome is already running.",
        }

    chrome = find_chrome_executable()

    if not chrome:
        return {
            "success": False,
            "started": False,
            "message": (
                "Google Chrome could not be found."
            ),
        }

    automation_dir = Path(
        CHROME_AUTOMATION_DIR
    )

    automation_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        subprocess.Popen(
            [
                chrome,
                "--remote-debugging-port=9222",
                f"--user-data-dir={automation_dir}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )

    except Exception as exc:

        return {
            "success": False,
            "started": False,
            "message": (
                f"Failed to start Chrome: {exc}"
            ),
        }

    deadline = (
        __import__("time").monotonic()
        + CDP_STARTUP_TIMEOUT
    )

    while (
        __import__("time").monotonic()
        < deadline
    ):

        if cdp_is_available():

            return {
                "success": True,
                "started": True,
                "message": (
                    "JARVIS started the CDP Chrome instance."
                ),
            }

        __import__("time").sleep(
            CDP_POLL_INTERVAL
        )

    return {
        "success": False,
        "started": True,
        "message": (
            "Chrome started, but the CDP endpoint "
            "did not become available."
        ),
    }


def ensure_cdp_chrome():
    """
    Ensure the dedicated Chrome/CDP endpoint is available.
    """

    if cdp_is_available():
        return {
            "success": True,
            "started": False,
            "message": "CDP Chrome is ready.",
        }

    return start_cdp_chrome()




class BrowserController:
    def __init__(self, cdp_url: str = CDP_URL):
        self.cdp_url = cdp_url
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # =========================================================
    # Connection
    # =========================================================

    def connect(self) -> Page:
        if self.page and not self.page.is_closed():
            return self.page

        # -----------------------------------------------------
        # Make sure JARVIS's dedicated CDP Chrome is running
        # before Playwright attempts to connect.
        # -----------------------------------------------------

        cdp_status = ensure_cdp_chrome()

        if not cdp_status.get("success"):
            raise RuntimeError(
                cdp_status.get(
                    "message",
                    "Could not start CDP Chrome.",
                )
            )

        self.playwright = sync_playwright().start()

        try:
            self.browser = self.playwright.chromium.connect_over_cdp(
                self.cdp_url
            )
        except Exception:
            self.close()
            raise RuntimeError(
                f"Could not connect to Chrome on {self.cdp_url}. "
                "Start Chrome with --remote-debugging-port=9222."
            )

        contexts = self.browser.contexts

        if not contexts:
            raise RuntimeError("Chrome connected but has no browser context.")

        self.context = contexts[0]

        if self.context.pages:
            self.page = self.context.pages[-1]
        else:
            self.page = self.context.new_page()

        return self.page

    def ensure_connected(self) -> Page:
        if self.page is None or self.page.is_closed():
            return self.connect()

        return self.page

    def get_page(self) -> Page:
        return self.ensure_connected()

    # =========================================================
    # Navigation
    # =========================================================

    def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
    ) -> dict[str, Any]:

        page = self.ensure_connected()

        page.goto(
            url,
            wait_until=wait_until,
            timeout=30_000,
        )

        return self.page_info()

    # =========================================================
    # Search
    # =========================================================

    def search_google(self, query: str) -> dict[str, Any]:
        page = self.ensure_connected()

        url = "https://www.google.com/search?q=" + quote_plus(query)

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        return {
            "success": True,
            "engine": "google",
            "query": query,
            "url": page.url,
            "title": page.title(),
        }

    def search_bing(self, query: str) -> dict[str, Any]:
        page = self.ensure_connected()

        url = "https://www.bing.com/search?q=" + quote_plus(query)

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=5_000,
            )
        except Exception:
            pass

        return {
            "success": True,
            "engine": "bing",
            "query": query,
            "url": page.url,
            "title": page.title(),
        }

    # =========================================================
    # URL decoding helpers
    # =========================================================

    @staticmethod
    def decode_bing_href(href: str) -> str:
        """
        Bing frequently wraps result URLs in:

            https://www.bing.com/ck/a?...&u=a1...

        Decode the 'u' parameter when possible.
        """

        if not href:
            return ""

        try:
            parsed = urlparse(href)
            query = parse_qs(parsed.query)

            encoded_u = query.get("u", [None])[0]

            if encoded_u:
                value = unquote(encoded_u)

                # Bing commonly prefixes the destination with a1
                if value.startswith("a1"):
                    value = value[2:]

                    try:
                        import base64

                        padding = "=" * (-len(value) % 4)

                        decoded = base64.urlsafe_b64decode(
                            value + padding
                        ).decode(
                            "utf-8",
                            errors="ignore",
                        )

                        if decoded.startswith(("http://", "https://")):
                            return decoded

                    except Exception:
                        pass

                if value.startswith(("http://", "https://")):
                    return value

        except Exception:
            pass

        return href

    # =========================================================
    # Bing first result
    # =========================================================

    def get_bing_results(self) -> list[dict[str, Any]]:
        """
        Extract Bing search results from the DOM.

        Uses result containers rather than simply taking the
        first external <a>, because Bing uses tracking URLs.
        """

        page = self.ensure_connected()

        results: list[dict[str, Any]] = []

        # Standard Bing organic result container.
        containers = page.locator("li.b_algo")

        count = containers.count()

        for i in range(count):
            container = containers.nth(i)

            try:
                link = container.locator("h2 a").first

                if link.count() == 0:
                    continue

                text = (link.inner_text() or "").strip()
                href = (link.get_attribute("href") or "").strip()

                if not text or not href:
                    continue

                decoded_href = self.decode_bing_href(href)

                results.append(
                    {
                        "index": i,
                        "title": text,
                        "href": href,
                        "url": decoded_href,
                    }
                )

            except Exception:
                continue

        return results

    def click_first_bing_result(
        self,
        query: Optional[str] = None,
    ) -> dict[str, Any]:

        page = self.ensure_connected()

        if query:
            search_result = self.search_bing(query)

            if not search_result.get("success"):
                return search_result

        results = self.get_bing_results()

        if not results:
            return {
                "success": False,
                "action": "click_first_bing_result",
                "query": query,
                "reason": "No Bing organic results were found in the DOM.",
                "url": page.url,
                "title": page.title(),
            }

        first = results[0]

        container = page.locator("li.b_algo").nth(first["index"])
        link = container.locator("h2 a").first

        before_url = page.url
        expected_url = first["url"]
        expected_title = first["title"]

        try:
            link.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass

        popup_page = None
        click_error = None

        # First try a real DOM click.
        try:
            with page.expect_popup(timeout=3_000) as popup_info:
                link.click(timeout=5_000)

            try:
                popup_page = popup_info.value
                popup_page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10_000,
                )
            except Exception:
                popup_page = popup_info.value

        except Exception as exc:
            click_error = str(exc)

            # Normal same-tab DOM click attempt.
            try:
                link.click(timeout=5_000)
            except Exception as exc2:
                click_error = f"{exc}; second click: {exc2}"

        page.wait_for_timeout(1_000)

        # If a popup/page was opened, use it as the destination.
        if popup_page is not None and not popup_page.is_closed():
            destination_page = popup_page

            try:
                destination_page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10_000,
                )
            except Exception:
                pass

            after_url = destination_page.url
            after_title = destination_page.title()

            navigated = (
                bool(after_url)
                and after_url != before_url
            )

            return {
                "success": navigated,
                "action": "click_first_bing_result",
                "query": query,
                "result_title": expected_title,
                "result_url": expected_url,
                "before_url": before_url,
                "after_url": after_url,
                "title": after_title,
                "navigated": navigated,
                "opened_new_page": True,
                "click_error": click_error,
            }

        # Same-tab navigation.
        after_url = page.url

        if after_url != before_url:
            return {
                "success": True,
                "action": "click_first_bing_result",
                "query": query,
                "result_title": expected_title,
                "result_url": expected_url,
                "before_url": before_url,
                "after_url": after_url,
                "title": page.title(),
                "navigated": True,
                "opened_new_page": False,
                "click_error": click_error,
            }

        # -----------------------------------------------------
        # Reliable fallback:
        #
        # We already inspected the DOM and resolved Bing's
        # tracking URL to the real destination. If Bing's
        # tracking wrapper consumes the click without navigating,
        # go directly to the destination we already identified.
        #
        # This is still DOM-aware automation; we are not using
        # screen coordinates or guessing.
        # -----------------------------------------------------

        if expected_url.startswith(("http://", "https://")):
            try:
                page.goto(
                    expected_url,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=5_000,
                    )
                except Exception:
                    pass

                page.wait_for_timeout(750)

                after_url = page.url
                navigated = after_url != before_url

                return {
                    "success": navigated,
                    "action": "click_first_bing_result",
                    "query": query,
                    "result_title": expected_title,
                    "result_url": expected_url,
                    "before_url": before_url,
                    "after_url": after_url,
                    "title": page.title(),
                    "navigated": navigated,
                    "opened_new_page": False,
                    "used_resolved_url_fallback": True,
                    "click_error": click_error,
                }

            except Exception as exc:
                return {
                    "success": False,
                    "action": "click_first_bing_result",
                    "query": query,
                    "reason": f"DOM click did not navigate and resolved URL fallback failed: {exc}",
                    "result_title": expected_title,
                    "result_url": expected_url,
                    "before_url": before_url,
                    "after_url": page.url,
                    "title": page.title(),
                    "navigated": False,
                    "click_error": click_error,
                }

        return {
            "success": False,
            "action": "click_first_bing_result",
            "query": query,
            "reason": "DOM click produced no navigation and no usable destination URL was available.",
            "result_title": expected_title,
            "result_url": expected_url,
            "before_url": before_url,
            "after_url": page.url,
            "title": page.title(),
            "navigated": False,
            "click_error": click_error,
        }

    # =========================================================
    # Generic page inspection
    # =========================================================


    # ==========================================================
    # Generic DOM Actions
    # ==========================================================

    def find_element(
        self,
        selector: str = "",
        text: str = "",
        role: str = "",
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        if selector:
            locator = page.locator(selector).first
        elif role:
            locator = page.get_by_role(role).first
        elif text:
            locator = page.get_by_text(
                text,
                exact=False,
            ).first
        else:
            raise ValueError(
                "find_element requires selector, text, or role."
            )

        try:
            count = locator.count()
        except Exception as exc:
            return {
                "success": False,
                "found": False,
                "error": str(exc),
            }

        if count == 0:
            return {
                "success": True,
                "found": False,
                "visible": False,
            }

        try:
            visible = locator.is_visible()
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

    def click_element(
        self,
        selector: str = "",
        text: str = "",
        role: str = "",
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        if selector:
            locator = page.locator(selector).first
        elif role:
            locator = page.get_by_role(role).first
        elif text:
            locator = page.get_by_text(
                text,
                exact=False,
            ).first
        else:
            raise ValueError(
                "click_element requires selector, text, or role."
            )

        if locator.count() == 0:
            return {
                "success": False,
                "error": "No matching element found.",
            }

        before_url = page.url
        before_title = page.title()

        try:
            locator.click(timeout=5000)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "before_url": before_url,
                "after_url": page.url,
                "before_title": before_title,
                "after_title": page.title(),
            }

        try:
            page.wait_for_load_state(
                "domcontentloaded",
                timeout=5000,
            )
        except Exception:
            pass

        return {
            "success": True,
            "action": "click",
            "before_url": before_url,
            "after_url": page.url,
            "before_title": before_title,
            "after_title": page.title(),
            "navigated": page.url != before_url,
        }

    def fill_element(
        self,
        value: str,
        selector: str = "",
        text: str = "",
        role: str = "",
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        if selector:
            locator = page.locator(selector).first
        elif role:
            locator = page.get_by_role(role).first
        elif text:
            locator = page.get_by_text(
                text,
                exact=False,
            ).first
        else:
            raise ValueError(
                "fill_element requires selector, text, or role."
            )

        if locator.count() == 0:
            return {
                "success": False,
                "error": "No matching element found.",
            }

        try:
            locator.fill(
                value,
                timeout=5000,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

        return {
            "success": True,
            "action": "fill",
        }

    def press_key(
        self,
        key: str,
        selector: str = "",
        text: str = "",
        role: str = "",
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        if selector:
            locator = page.locator(selector).first
        elif role:
            locator = page.get_by_role(role).first
        elif text:
            locator = page.get_by_text(
                text,
                exact=False,
            ).first
        else:
            locator = page.locator("body")

        try:
            locator.press(
                key,
                timeout=5000,
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

        return {
            "success": True,
            "action": "press",
            "key": key,
        }

    def wait_for_element(
        self,
        selector: str = "",
        text: str = "",
        role: str = "",
        timeout: int = 10000,
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        try:
            if selector:
                locator = page.locator(selector).first
            elif role:
                locator = page.get_by_role(role).first
            elif text:
                locator = page.get_by_text(
                    text,
                    exact=False,
                ).first
            else:
                raise ValueError(
                    "wait_for_element requires selector, "
                    "text, or role."
                )

            locator.wait_for(
                state="visible",
                timeout=timeout,
            )

            return {
                "success": True,
                "action": "wait_for_element",
                "found": True,
            }

        except Exception as exc:
            return {
                "success": False,
                "found": False,
                "error": str(exc),
            }

    def extract_text(
        self,
        selector: str = "",
        text: str = "",
        role: str = "",
    ):
        page = self.ensure_connected()

        selector = (selector or "").strip()
        text = (text or "").strip()
        role = (role or "").strip()

        try:
            if selector:
                locator = page.locator(selector).first
            elif role:
                locator = page.get_by_role(role).first
            elif text:
                locator = page.get_by_text(
                    text,
                    exact=False,
                ).first
            else:
                locator = page.locator("body")

            content = locator.inner_text(
                timeout=5000,
            )

            return {
                "success": True,
                "action": "extract_text",
                "text": content,
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    def page_info(self) -> dict[str, Any]:
        page = self.ensure_connected()

        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
            "pages": (
                len(self.context.pages)
                if self.context
                else 0
            ),
        }

    # =========================================================
    # Cleanup
    # =========================================================

    def close(self) -> None:
        self.page = None
        self.context = None
        self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass

        self.playwright = None


# =============================================================
# Module-level singleton
# =============================================================

_controller = BrowserController()


def browser_connect() -> dict[str, Any]:
    page = _controller.connect()

    return {
        "success": True,
        "action": "browser_connect",
        "url": page.url,
        "title": page.title(),
    }


def browser_search_google(query: str) -> dict[str, Any]:
    return _controller.search_google(query)


def browser_search_bing(query: str) -> dict[str, Any]:
    return _controller.search_bing(query)


def browser_click_first_bing_result(
    query: Optional[str] = None,
) -> dict[str, Any]:
    return _controller.click_first_bing_result(query)


def browser_goto(url: str) -> dict[str, Any]:
    return _controller.goto(url)


def browser_find_element(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    return _controller.find_element(
        selector=selector,
        text=text,
        role=role,
    )


def browser_click_element(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    return _controller.click_element(
        selector=selector,
        text=text,
        role=role,
    )


def browser_fill_element(
    value: str,
    selector: str = "",
    text: str = "",
    role: str = "",
):
    return _controller.fill_element(
        value=value,
        selector=selector,
        text=text,
        role=role,
    )


def browser_press_key(
    key: str,
    selector: str = "",
    text: str = "",
    role: str = "",
):
    return _controller.press_key(
        key=key,
        selector=selector,
        text=text,
        role=role,
    )


def browser_wait_for_element(
    selector: str = "",
    text: str = "",
    role: str = "",
    timeout: int = 10000,
):
    return _controller.wait_for_element(
        selector=selector,
        text=text,
        role=role,
        timeout=timeout,
    )


def browser_extract_text(
    selector: str = "",
    text: str = "",
    role: str = "",
):
    return _controller.extract_text(
        selector=selector,
        text=text,
        role=role,
    )


def browser_page_info() -> dict[str, Any]:
    return _controller.page_info()


if __name__ == "__main__":
    print("JARVIS browser controller loaded.")
    print(f"CDP: {CDP_URL}")

