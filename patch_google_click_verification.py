from pathlib import Path
import shutil


path = Path("screen_vision.py")
backup = Path("screen_vision.py.before_google_click_verification.py")

text = path.read_text(encoding="utf-8")
shutil.copy2(path, backup)


# ==========================================================
# Add screen-signature helper
# ==========================================================

if "def google_click_screen_signature(" not in text:

    marker = "def click_screen_target(\n"

    insert_at = text.find(marker)

    if insert_at == -1:
        raise SystemExit(
            "ERROR: click_screen_target() not found."
        )

    helper = '''
# ==========================================================
# Google Click Verification
# ==========================================================

def google_click_screen_signature():
    try:
        image = pyautogui.screenshot()

        image = image.resize(
            (
                max(1, image.width // 10),
                max(1, image.height // 10),
            )
        )

        return hashlib.sha256(
            image.tobytes()
        ).hexdigest()

    except Exception:
        return None


'''

    text = (
        text[:insert_at]
        + helper
        + text[insert_at:]
    )


# ==========================================================
# Capture state immediately before click
# ==========================================================

capture_anchor = '''    logging.info(
        f"Clicking: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
'''

capture_replacement = '''    # --------------------------------------------------
    # Google click verification.
    #
    # A Google organic result should navigate to a new page.
    # Capture the visible screen before the click so we can
    # detect a click that landed on non-navigating text.
    # --------------------------------------------------

    google_click_target = (
        "organic google result" in target_text
        or "google result" in target_text
    )

    google_before_signature = None

    if google_click_target:
        google_before_signature = (
            google_click_screen_signature()
        )

        logging.info(
            "JARVIS: Captured pre-click Google screen signature."
        )

    logging.info(
        f"Clicking: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
'''

if capture_anchor not in text:
    shutil.copy2(backup, path)
    raise SystemExit(
        "ERROR: pre-click insertion point not found."
    )

text = text.replace(
    capture_anchor,
    capture_replacement,
    1,
)


# ==========================================================
# Verify screen after click
# ==========================================================

click_anchor = '''    pyautogui.click()

    time.sleep(
        0.5
    )

    return {
'''

click_replacement = '''    pyautogui.click()

    time.sleep(
        0.75
    )

    # --------------------------------------------------
    # Post-click Google verification.
    # --------------------------------------------------

    if google_click_target:

        google_after_signature = (
            google_click_screen_signature()
        )

        if (
            google_before_signature
            and google_after_signature
            and
            google_before_signature
            == google_after_signature
        ):

            logging.warning(
                "JARVIS: Google click verification FAILED."
            )

            logging.warning(
                "The screen did not change after clicking "
                "the Google result title."
            )

            return {
                "success": False,
                "confidence": result.get(
                    "confidence",
                    0
                ),
                "message": (
                    "Google result click was not verified. "
                    "The screen did not change."
                ),
                "x": mouse_x,
                "y": mouse_y,
            }

        logging.info(
            "JARVIS: Google click verification PASSED."
        )

    return {
'''

if click_anchor not in text:
    shutil.copy2(backup, path)
    raise SystemExit(
        "ERROR: click insertion point not found."
    )

text = text.replace(
    click_anchor,
    click_replacement,
    1,
)


path.write_text(
    text,
    encoding="utf-8",
)

print("PATCH_OK")