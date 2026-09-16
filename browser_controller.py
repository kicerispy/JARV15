import asyncio
import atexit
import logging
import os
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="[JARVIS] %(message)s")

_playwright = None
_context = None
_page = None
_loop = None
_skipper_task = None

def get_event_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop

async def _auto_skip_ads(page):
    try:
        await page.evaluate("""() => {
            if (window._jarvisObserverActive) return;
            window._jarvisObserverActive = true;

            const observer = new MutationObserver((mutations) => {
                // 1. Click skip buttons instantly
                const skipBtn = document.querySelector('.ytp-ad-skip-button, .ytp-skip-ad-button, button.ytp-ad-skip-button-modern');
                if (skipBtn) {
                    skipBtn.click();
                }

                // 2. Close overlay ads
                const overlayClose = document.querySelector('.ytp-ad-overlay-close-button');
                if (overlayClose) {
                    overlayClose.click();
                }

                // 3. Handle video element speed/skipping during ad states
                const player = document.querySelector('.html5-video-player');
                const video = document.querySelector('video');
                
                if (player && video && player.classList.contains('ad-showing')) {
                    video.muted = true;
                    video.playbackRate = 16.0;
                    if (Number.isFinite(video.duration) && video.duration > 0) {
                        video.currentTime = video.duration;
                    }
                }
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['class']
            });
        }""")
    except Exception:
        pass

async def _init_browser():
    global _playwright, _context, _page, _skipper_task
    if _page is None or _page.is_closed():
        _playwright = await async_playwright().start()
        
        user_data_dir = os.path.abspath("./playwright_profile")
        os.makedirs(user_data_dir, exist_ok=True)

        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1920, "height": 1080},
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        pages = _context.pages
        _page = pages[0] if pages else await _context.new_page()
        _skipper_task = asyncio.create_task(_auto_skip_ads(_page))
    return _page

def get_page():
    loop = get_event_loop()
    return loop.run_until_complete(_init_browser())

def browser_navigate(url: str) -> str:
    loop = get_event_loop()
    async def _nav():
        page = await _init_browser()
        await page.goto(url, wait_until="domcontentloaded")
        await _auto_skip_ads(page)
    loop.run_until_complete(_nav())
    return f"Successfully navigated to {url}"

def browser_scroll(direction: str = "down", distance: int = 500) -> str:
    loop = get_event_loop()
    async def _scroll():
        page = await _init_browser()
        delta_y = distance if direction.lower() == "down" else -distance
        await page.mouse.wheel(0, delta_y)
    loop.run_until_complete(_scroll())
    return f"Scrolled {direction} by {distance}px"

def click_dom_element(target_text: str) -> bool:
    loop = get_event_loop()
    async def _click():
        page = await _init_browser()
        try:
            yt_titles = page.locator("ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title")
            count = await yt_titles.count()
            for i in range(min(count, 5)):
                elem = yt_titles.nth(i)
                text = await elem.inner_text()
                clean_target = target_text.replace("-", "").replace(" ", "").lower()
                clean_text = text.replace("-", "").replace(" ", "").lower()
                if clean_target in clean_text or "wifiskeleton" in clean_text:
                    await elem.click()
                    logging.info(f"DOM Click successful on YouTube video title: {text}")
                    await asyncio.sleep(2)
                    await _auto_skip_ads(page)
                    return True

            locator = page.get_by_text(target_text, exact=False).first
            if await locator.is_visible():
                await locator.click()
                logging.info(f"DOM Click successful on text: '{target_text}'")
                return True
        except Exception as e:
            logging.warning(f"DOM Click attempt failed: {e}")
        return False
    return loop.run_until_complete(_click())

def browser_media_control(action: str) -> str:
    """Controls YouTube video playback (play, pause, mute, unmute, volume_up, volume_down)."""
    loop = get_event_loop()
    async def _control():
        page = await _init_browser()
        result = await page.evaluate("""(action) => {
            const video = document.querySelector('video');
            if (!video) return "No video element found";

            switch(action) {
                case 'pause':
                    video.pause();
                    return "Video paused";
                case 'play':
                    video.play();
                    return "Video resumed";
                case 'mute':
                    video.muted = true;
                    return "Audio muted";
                case 'unmute':
                    video.muted = false;
                    return "Audio unmuted";
                case 'volume_up':
                    video.volume = Math.min(1.0, video.volume + 0.1);
                    return `Volume increased to ${Math.round(video.volume * 100)}%`;
                case 'volume_down':
                    video.volume = Math.max(0.0, video.volume - 0.1);
                    return `Volume decreased to ${Math.round(video.volume * 100)}%`;
                default:
                    return "Unknown media action";
            }
        }""", action)
        return result
    return loop.run_until_complete(_control())

def browser_add_to_queue(target_text: str) -> str:
    """Finds a video matching target_text and adds it to the YouTube queue."""
    loop = get_event_loop()
    async def _queue():
        page = await _init_browser()
        try:
            yt_titles = page.locator("ytd-video-renderer a#video-title, ytd-search ytd-video-renderer #video-title")
            count = await yt_titles.count()
            for i in range(min(count, 5)):
                elem = yt_titles.nth(i)
                text = await elem.inner_text()
                if target_text.lower() in text.lower():
                    renderer = elem.locator("ancestor::ytd-video-renderer").first
                    await renderer.hover()
                    
                    menu_btn = renderer.locator("yt-icon-button#button, button.dropdown-trigger").first
                    await menu_btn.click()
                    
                    queue_option = page.get_by_text("Add to queue", exact=True).first
                    await queue_option.click()
                    return f"Successfully added '{text}' to the YouTube queue."
            return f"Could not find video matching '{target_text}' to queue."
        except Exception as e:
            return f"Failed to queue video: {e}"
    return loop.run_until_complete(_queue())

def capture_screenshot() -> bytes:
    loop = get_event_loop()
    async def _shot():
        page = await _init_browser()
        return await page.screenshot(type="jpeg", quality=80)
    return loop.run_until_complete(_shot())

def click_at_coords(x: int, y: int) -> None:
    loop = get_event_loop()
    async def _click_xy():
        page = await _init_browser()
        await page.mouse.click(x, y)
    loop.run_until_complete(_click_xy())

def cleanup_browser():
    global _playwright, _context, _page, _skipper_task, _loop
    try:
        if _loop and not _loop.is_closed():
            async def _close():
                if _skipper_task:
                    _skipper_task.cancel()
                if _context:
                    await _context.close()
                if _playwright:
                    await _playwright.stop()
            _loop.run_until_complete(_close())
    except Exception as e:
        logging.debug(f"Browser cleanup exception: {e}")

atexit.register(cleanup_browser)