import os
import json
import time
import ctypes
import logging
import re
import hashlib

import pyautogui
from ollama import chat


# ==========================================================
# JARVIS VISION ENGINE
# ==========================================================


# ==========================================================
# Configuration
# ==========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

SCREENSHOT_FILE = os.path.join(
    BASE_DIR,
    "jarvis_screen.png"
)

VISION_CROP_FILE = os.path.join(
    BASE_DIR,
    "jarvis_vision_crop.png"
)

VISION_MODEL = "qwen2.5vl:3b"
VERIFY_MODEL = "qwen3.5:9b"

MIN_CONFIDENCE = 0.70

VISION_NUM_PREDICT = 96
VERIFY_NUM_PREDICT = 48

MAX_VISION_WIDTH = 1280


# ==========================================================
# Browser / Page Stability
# ==========================================================

# Maximum amount of time to wait for a page to settle.
PAGE_STABLE_TIMEOUT = 5.0

# Time between screen comparisons.
PAGE_STABLE_INTERVAL = 0.35

# Number of consecutive unchanged frames required.
PAGE_STABLE_CHECKS = 2


# ==========================================================
# YouTube Crop
# ==========================================================

YOUTUBE_CROP_LEFT = 300
YOUTUBE_CROP_TOP = 100

YOUTUBE_CROP_RIGHT_MARGIN = 0
YOUTUBE_CROP_BOTTOM_MARGIN = 20


# ==========================================================
# Mouse Calibration
# ==========================================================

MOUSE_OFFSET_X = 0
MOUSE_OFFSET_Y = 0

CLICK_BIAS_X = 0
CLICK_BIAS_Y = 0

YOUTUBE_CLICK_BIAS_X = 0
YOUTUBE_CLICK_BIAS_Y = 0


# ==========================================================
# Logging
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[JARVIS] %(message)s"
)


# ==========================================================
# Safe Ollama Vision Call
# ==========================================================

def vision_chat(
    model,
    messages,
    json_mode=False,
    num_predict=128
):

    try:

        options = {
            "model": model,
            "messages": messages,
            "keep_alive": -1,

            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
            },
        }

        if json_mode:

            options["format"] = "json"

        return chat(
            **options
        )

    except Exception as e:

        logging.error(
            f"Ollama failure: {e}"
        )

        return None


# ==========================================================
# Extract Ollama Response Text
# ==========================================================

def get_response_text(
    response
):

    if not response:

        return ""

    try:

        message = response.get(
            "message",
            {}
        )

    except Exception:

        return ""

    if not message:

        return ""

    content = message.get(
        "content",
        ""
    )

    if content:

        return str(
            content
        ).strip()

    thinking = message.get(
        "thinking",
        ""
    )

    if thinking:

        return str(
            thinking
        ).strip()

    return ""


# ==========================================================
# Capture Screen
# ==========================================================

def capture_screen():

    try:

        screenshot = pyautogui.screenshot()

        screenshot.save(
            SCREENSHOT_FILE
        )

        return {
            "success": True,
            "file": SCREENSHOT_FILE
        }

    except Exception as e:

        return {
            "success": False,
            "error":
            str(e)
        }


# ==========================================================
# Fast Screen Fingerprint
# ==========================================================

def screen_fingerprint(
    screenshot
):

    try:

        # Downsample before hashing.
        # This makes the comparison much cheaper than
        # hashing the entire full-resolution screenshot.
        reduced = screenshot.resize(
            (160, 90)
        )

        return hashlib.md5(
            reduced.tobytes()
        ).hexdigest()

    except Exception:

        return None


# ==========================================================
# Wait Until Browser/Page Is Stable
# ==========================================================

def wait_for_page_stable(
    timeout=PAGE_STABLE_TIMEOUT,
    interval=PAGE_STABLE_INTERVAL,
    stable_checks=PAGE_STABLE_CHECKS
):

    start = time.perf_counter()

    try:

        previous = pyautogui.screenshot()

    except Exception as e:

        logging.warning(
            f"Initial stability screenshot failed: {e}"
        )

        return False

    previous_hash = screen_fingerprint(
        previous
    )

    if not previous_hash:

        return False

    stable_count = 0

    while (
        time.perf_counter() - start
        <
        timeout
    ):

        time.sleep(
            interval
        )

        try:

            current = pyautogui.screenshot()

        except Exception:

            return False

        current_hash = screen_fingerprint(
            current
        )

        if not current_hash:

            continue

        if current_hash == previous_hash:

            stable_count += 1

        else:

            stable_count = 0

            previous_hash = current_hash

        if stable_count >= stable_checks:

            elapsed = (
                time.perf_counter()
                -
                start
            )

            logging.info(
                f"Page stable after "
                f"{elapsed:.3f}s"
            )

            return True

    elapsed = (
        time.perf_counter()
        -
        start
    )

    logging.info(
        f"Page stability timeout after "
        f"{elapsed:.3f}s; continuing."
    )

    return False


# ==========================================================
# Create Optimized Vision Image
# ==========================================================

def create_vision_image(
    target=None
):

    try:

        screenshot = pyautogui.screenshot()

        screen_width, screen_height = (
            screenshot.size
        )

        left = 0
        top = 0
        right = screen_width
        bottom = screen_height

        # --------------------------------------------------
        # Only apply the aggressive browser crop when this
        # is actually a YouTube-style screen target.
        # --------------------------------------------------

        youtube_target = (
            target is not None
            and
            is_youtube_target(
                target
            )
        )

        if youtube_target and screen_width >= 1000:

            left = min(
                YOUTUBE_CROP_LEFT,
                screen_width - 1
            )

            top = min(
                YOUTUBE_CROP_TOP,
                screen_height - 1
            )

            right = (
                screen_width
                -
                YOUTUBE_CROP_RIGHT_MARGIN
            )

            bottom = (
                screen_height
                -
                YOUTUBE_CROP_BOTTOM_MARGIN
            )

        if right <= left:

            left = 0
            right = screen_width

        if bottom <= top:

            top = 0
            bottom = screen_height

        crop = screenshot.crop(
            (
                left,
                top,
                right,
                bottom
            )
        )

        crop_width, crop_height = (
            crop.size
        )

        scale = 1.0

        # --------------------------------------------------
        # Resize large images.
        # --------------------------------------------------

        if crop_width > MAX_VISION_WIDTH:

            scale = (
                MAX_VISION_WIDTH
                /
                float(crop_width)
            )

            new_width = (
                MAX_VISION_WIDTH
            )

            new_height = max(
                1,
                int(
                    round(
                        crop_height
                        *
                        scale
                    )
                )
            )

            crop = crop.resize(
                (
                    new_width,
                    new_height
                )
            )

        crop.save(
            VISION_CROP_FILE
        )

        final_width, final_height = (
            crop.size
        )

        logging.info(
            "Vision crop: "
            f"screen={screen_width}x{screen_height} "
            f"origin={left},{top} "
            f"source={crop_width}x{crop_height} "
            f"sent={final_width}x{final_height}"
        )

        return {

            "success":
            True,

            "file":
            VISION_CROP_FILE,

            "screen_width":
            screen_width,

            "screen_height":
            screen_height,

            "crop_left":
            left,

            "crop_top":
            top,

            "crop_width":
            crop_width,

            "crop_height":
            crop_height,

            "sent_width":
            final_width,

            "sent_height":
            final_height,

            "scale":
            scale

        }

    except Exception as e:

        logging.error(
            f"Vision image creation failed: {e}"
        )

        return {
            "success": False,
            "error":
            str(e)
        }


# ==========================================================
# Crop Coordinates -> Full Screen
# ==========================================================

def crop_to_screen_box(
    box,
    vision_info
):

    try:

        scale = float(
            vision_info.get(
                "scale",
                1.0
            )
        )

        if scale <= 0:

            scale = 1.0

        crop_left = int(
            vision_info.get(
                "crop_left",
                0
            )
        )

        crop_top = int(
            vision_info.get(
                "crop_top",
                0
            )
        )

        return {

            "left":
            int(
                round(
                    (
                        box["left"]
                        /
                        scale
                    )
                    +
                    crop_left
                )
            ),

            "top":
            int(
                round(
                    (
                        box["top"]
                        /
                        scale
                    )
                    +
                    crop_top
                )
            ),

            "right":
            int(
                round(
                    (
                        box["right"]
                        /
                        scale
                    )
                    +
                    crop_left
                )
            ),

            "bottom":
            int(
                round(
                    (
                        box["bottom"]
                        /
                        scale
                    )
                    +
                    crop_top
                )
            )

        }

    except Exception:

        return None


# ==========================================================
# Screen Size
# ==========================================================

def get_screen_size():

    try:

        width, height = pyautogui.size()

        return {

            "width":
            width,

            "height":
            height

        }

    except Exception as e:

        return {
            "error":
            str(e)
        }


# ==========================================================
# Active Window
# ==========================================================

def get_active_window():

    try:

        hwnd = (
            ctypes.windll.user32
            .GetForegroundWindow()
        )

        if not hwnd:

            return "Unknown window"

        length = (
            ctypes.windll.user32
            .GetWindowTextLengthW(hwnd)
        )

        buffer = (
            ctypes.create_unicode_buffer(
                length + 1
            )
        )

        ctypes.windll.user32.GetWindowTextW(
            hwnd,
            buffer,
            length + 1
        )

        title = buffer.value.strip()

        return (
            title
            if title
            else
            "Unknown window"
        )

    except Exception as e:

        return (
            f"Window error: {e}"
        )


# ==========================================================
# Analyze Entire Screen
# ==========================================================

def analyze_screen(
    question="Describe my screen."
):

    result = capture_screen()

    if not result["success"]:

        return result

    response = vision_chat(

        VISION_MODEL,

        [

            {
                "role":
                "system",

                "content":
"""
You are JARVIS computer vision.

Analyze only information actually visible
in the supplied screenshot.

Identify:

- applications
- browser pages
- windows
- buttons
- text
- menus
- dialogs
- videos
- icons
- clickable elements

Never invent anything.
"""
            },

            {
                "role":
                "user",

                "content":
                question,

                "images": [
                    SCREENSHOT_FILE
                ]
            }

        ],

        num_predict=
        VISION_NUM_PREDICT
    )

    if not response:

        return "Vision failed."

    text = get_response_text(
        response
    )

    return (
        text
        if text
        else
        "Vision failed."
    )


# ==========================================================
# Extract JSON
# ==========================================================

def extract_json(
    text
):

    if not text:

        return None

    text = str(
        text
    ).strip()

    try:

        return json.loads(
            text
        )

    except Exception:

        pass

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        flags=
        re.IGNORECASE |
        re.DOTALL
    )

    if fenced:

        try:

            return json.loads(
                fenced.group(1)
            )

        except Exception:

            pass

    start = text.find("{")
    end = text.rfind("}")

    if (
        start != -1
        and
        end != -1
        and
        end > start
    ):

        try:

            return json.loads(
                text[
                    start:
                    end + 1
                ]
            )

        except Exception:

            pass

    return None


# ==========================================================
# YouTube Target Detection
# ==========================================================

def is_youtube_target(
    target
):

    target = str(
        target
    ).lower()

    keywords = [

        "youtube",
        "first video",
        "first result",
        "video result",
        "first youtube",
        "organic result",
        "normal result"

    ]

    return any(
        word in target
        for word in keywords
    )


# ==========================================================
# Build Locator Prompt
# ==========================================================

def build_locator_prompt(
    target,
    image_width,
    image_height
):

    if is_youtube_target(
        target
    ):

        return f"""
You are JARVIS precision visual locator.

Find the FIRST ORGANIC YOUTUBE VIDEO RESULT.

Target:
{target}

The image has already been cropped to the main
browser content area.

Image size:
width={image_width}
height={image_height}

Choose the first normal organic video result.

SKIP:

- Sponsored
- Sponsored content
- Ad
- Advertisement
- Promoted
- Paid promotion
- shopping cards
- product cards
- advertiser cards
- business advertisements
- Shorts
- sidebars
- navigation
- menus
- browser controls
- browser tabs
- search box

A valid organic video result normally contains:

- video thumbnail
- video title
- channel name
- standard YouTube metadata

IMPORTANT:

The first visible card may be an advertisement.

Do NOT select an advertisement.

Choose the first ORGANIC video result below
any sponsored or advertising content.

Return ONLY JSON:

{{
  "found": true,
  "confidence": 0.90,
  "box_2d": [x1, y1, x2, y2],
  "description": "first organic YouTube video result"
}}

box_2d coordinates are normalized from 0 to 1000:

[x1, y1, x2, y2]

If an organic result is visible, identify its
actual visible bounding box.

If no organic result is visible:

{{
  "found": false,
  "confidence": 0.0,
  "box_2d": [0, 0, 0, 0],
  "description": "no organic result"
}}

Return ONLY JSON.
"""

    return f"""
You are JARVIS visual locator.

Find:

{target}

Image size:
width={image_width}
height={image_height}

Return ONLY JSON:

{{
  "found": true,
  "confidence": 0.90,
  "box_2d": [x1, y1, x2, y2],
  "description": "target"
}}

box_2d is normalized from 0 to 1000.

[x1, y1, x2, y2]

Do not guess.
Return ONLY JSON.
"""


# ==========================================================
# Normalize Qwen box
# ==========================================================

def normalize_box_2d(
    box,
    width,
    height
):

    if not isinstance(
        box,
        (list, tuple)
    ):

        return None

    if len(box) < 4:

        return None

    try:

        x1 = float(
            box[0]
        )

        y1 = float(
            box[1]
        )

        x2 = float(
            box[2]
        )

        y2 = float(
            box[3]
        )

    except Exception:

        return None

    maximum = max(
        abs(x1),
        abs(y1),
        abs(x2),
        abs(y2)
    )

    if maximum <= 1.0:

        x1 *= width
        x2 *= width

        y1 *= height
        y2 *= height

    elif maximum <= 1000:

        x1 = (
            x1
            /
            1000.0
        ) * width

        x2 = (
            x2
            /
            1000.0
        ) * width

        y1 = (
            y1
            /
            1000.0
        ) * height

        y2 = (
            y2
            /
            1000.0
        ) * height

    left = min(
        x1,
        x2
    )

    right = max(
        x1,
        x2
    )

    top = min(
        y1,
        y2
    )

    bottom = max(
        y1,
        y2
    )

    return {

        "left":
        int(
            round(left)
        ),

        "top":
        int(
            round(top)
        ),

        "right":
        int(
            round(right)
        ),

        "bottom":
        int(
            round(bottom)
        )

    }


# ==========================================================
# Extract Bounding Box
# ==========================================================

def extract_box_from_result(
    data,
    width,
    height
):

    if not isinstance(
        data,
        dict
    ):

        return None

    # Preferred normalized box.
    for key in [

        "box_2d",
        "bbox",
        "bounding_box",
        "boundingBox",
        "box"

    ]:

        if key in data:

            box = normalize_box_2d(
                data[key],
                width,
                height
            )

            if box:

                return box

    # Nested results.
    for key in [

        "target",
        "location",
        "result",
        "object"

    ]:

        nested = data.get(
            key
        )

        if isinstance(
            nested,
            dict
        ):

            box = extract_box_from_result(
                nested,
                width,
                height
            )

            if box:

                return box

    # Legacy pixel format.
    required = [

        "left",
        "top",
        "right",
        "bottom"

    ]

    if all(
        key in data
        for key in required
    ):

        try:

            return {

                "left":
                int(
                    float(
                        data["left"]
                    )
                ),

                "top":
                int(
                    float(
                        data["top"]
                    )
                ),

                "right":
                int(
                    float(
                        data["right"]
                    )
                ),

                "bottom":
                int(
                    float(
                        data["bottom"]
                    )
                )

            }

        except Exception:

            pass

    return None


# ==========================================================
# Clean Location
# ==========================================================

def clean_location(
    data,
    width,
    height
):

    if not isinstance(
        data,
        dict
    ):

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "invalid result"

        }

    try:

        confidence = float(
            data.get(
                "confidence",
                0.0
            )
        )

    except Exception:

        confidence = 0.0

    box = extract_box_from_result(
        data,
        width,
        height
    )

    if not box:

        return {

            "found":
            False,

            "confidence":
            confidence,

            "description":
            data.get(
                "description",
                "no bounding box"
            )

        }

    left = max(
        0,
        min(
            box["left"],
            width - 1
        )
    )

    top = max(
        0,
        min(
            box["top"],
            height - 1
        )
    )

    right = max(
        0,
        min(
            box["right"],
            width - 1
        )
    )

    bottom = max(
        0,
        min(
            box["bottom"],
            height - 1
        )
    )

    found = bool(
        data.get(
            "found",
            True
        )
    )

    if (
        right <= left
        or
        bottom <= top
    ):

        found = False

    if confidence < MIN_CONFIDENCE:

        found = False

    return {

        "found":
        found,

        "confidence":
        confidence,

        "left":
        left,

        "top":
        top,

        "right":
        right,

        "bottom":
        bottom,

        "description":
        data.get(
            "description",
            "target"
        )

    }


# ==========================================================
# Locate Target On Screen
# ==========================================================

def find_screen_target(
    target
):

    # ------------------------------------------------------
    # If this is a browser/YouTube action, first wait until
    # the screen stops changing.
    # ------------------------------------------------------

    if is_youtube_target(
        target
    ):

        wait_for_page_stable()

    # ------------------------------------------------------
    # Build optimized image after the page has settled.
    # ------------------------------------------------------

    vision_info = create_vision_image(
        target
    )

    if not vision_info["success"]:

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "vision image failed"

        }

    vision_file = vision_info[
        "file"
    ]

    vision_width = vision_info[
        "sent_width"
    ]

    vision_height = vision_info[
        "sent_height"
    ]

    prompt = build_locator_prompt(
        target,
        vision_width,
        vision_height
    )

    start = time.perf_counter()

    response = vision_chat(

        VISION_MODEL,

        [

            {
                "role":
                "system",

                "content":
                prompt
            },

            {
                "role":
                "user",

                "content":
                f"Find: {target}",

                "images": [
                    vision_file
                ]
            }

        ],

        json_mode=True,

        num_predict=
        VISION_NUM_PREDICT
    )

    elapsed = (
        time.perf_counter()
        -
        start
    )

    logging.info(
        f"Vision model time: "
        f"{elapsed:.3f}s"
    )

    if not response:

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "vision returned no response"

        }

    raw = get_response_text(
        response
    )

    if not raw:

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "empty vision response"

        }

    logging.info(
        f"Vision raw response: "
        f"{raw}"
    )

    result = extract_json(
        raw
    )

    if not result:

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "invalid vision JSON"

        }

    # ------------------------------------------------------
    # Interpret coordinates relative to the reduced image.
    # ------------------------------------------------------

    crop_result = clean_location(

        result,

        vision_width,

        vision_height

    )

    if not crop_result.get(
        "found",
        False
    ):

        logging.info(
            f"Located: "
            f"{crop_result.get('description')}"
        )

        logging.info(
            f"Confidence: "
            f"{crop_result.get('confidence')}"
        )

        return crop_result

    # ------------------------------------------------------
    # Convert back to full-screen coordinates.
    # ------------------------------------------------------

    screen_box = crop_to_screen_box(

        crop_result,

        vision_info

    )

    if not screen_box:

        return {

            "found":
            False,

            "confidence":
            0.0,

            "description":
            "coordinate conversion failed"

        }

    screen_width = vision_info[
        "screen_width"
    ]

    screen_height = vision_info[
        "screen_height"
    ]

    final_result = {

        "found":
        True,

        "confidence":
        crop_result.get(
            "confidence",
            0.0
        ),

        "left":
        screen_box[
            "left"
        ],

        "top":
        screen_box[
            "top"
        ],

        "right":
        screen_box[
            "right"
        ],

        "bottom":
        screen_box[
            "bottom"
        ],

        "description":
        crop_result.get(
            "description",
            target
        )

    }

    # ------------------------------------------------------
    # Clamp.
    # ------------------------------------------------------

    final_result["left"] = max(
        0,
        min(
            final_result["left"],
            screen_width - 1
        )
    )

    final_result["top"] = max(
        0,
        min(
            final_result["top"],
            screen_height - 1
        )
    )

    final_result["right"] = max(
        0,
        min(
            final_result["right"],
            screen_width - 1
        )
    )

    final_result["bottom"] = max(
        0,
        min(
            final_result["bottom"],
            screen_height - 1
        )
    )

    if (
        final_result["right"]
        <=
        final_result["left"]
        or
        final_result["bottom"]
        <=
        final_result["top"]
    ):

        final_result["found"] = False

    logging.info(
        f"Located: "
        f"{final_result.get('description')}"
    )

    logging.info(
        f"Confidence: "
        f"{final_result.get('confidence')}"
    )

    logging.info(
        "Full-screen bounding box: "
        f"{final_result['left']},"
        f"{final_result['top']},"
        f"{final_result['right']},"
        f"{final_result['bottom']}"
    )

    return final_result


# ==========================================================
# Coordinate Conversion
# ==========================================================

def convert_coordinates(
    x,
    y,
    clicking=False,
    target=None
):

    x = int(x) + MOUSE_OFFSET_X
    y = int(y) + MOUSE_OFFSET_Y

    if clicking:

        x += CLICK_BIAS_X
        y += CLICK_BIAS_Y

        if target and is_youtube_target(
            target
        ):

            x += YOUTUBE_CLICK_BIAS_X
            y += YOUTUBE_CLICK_BIAS_Y

    screen_width, screen_height = pyautogui.size()

    x = max(
        0,
        min(
            x,
            screen_width - 1
        )
    )

    y = max(
        0,
        min(
            y,
            screen_height - 1
        )
    )

    return x, y


# ==========================================================
# Bounding Box Center
# ==========================================================

def get_center(
    result
):

    x = (
        result["left"]
        +
        result["right"]
    ) // 2

    y = (
        result["top"]
        +
        result["bottom"]
    ) // 2

    return x, y


# ==========================================================
# Move Mouse To Target
# ==========================================================

def move_mouse_to_target(
    target
):

    result = find_screen_target(
        target
    )

    if not result.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Could not find {target}"

        }

    vision_x, vision_y = get_center(
        result
    )

    mouse_x, mouse_y = convert_coordinates(
        vision_x,
        vision_y,
        clicking=False,
        target=target
    )

    logging.info(
        f"Moving mouse: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
        mouse_x,
        mouse_y,
        duration=0.3
    )

    return {

        "success":
        True,

        "confidence":
        result.get(
            "confidence",
            0
        ),

        "target":
        result.get(
            "description",
            target
        ),

        "message":
        f"Moved mouse to "
        f"{result.get('description', target)}"

    }


# ==========================================================
# Click Target
# ==========================================================

def click_screen_target(
    target
):

    result = find_screen_target(
        target
    )

    if not result.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Target not found: {target}"

        }

    vision_x, vision_y = get_center(
        result
    )

    mouse_x, mouse_y = convert_coordinates(
        vision_x,
        vision_y,
        clicking=True,
        target=target
    )

    logging.info(
        f"Clicking: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
        mouse_x,
        mouse_y,
        duration=0.2
    )

    pyautogui.click()

    time.sleep(
        0.5
    )

    return {

        "success":
        True,

        "confidence":
        result.get(
            "confidence",
            0
        ),

        "message":
        f"Clicked "
        f"{result.get('description', target)}",

        "x":
        mouse_x,

        "y":
        mouse_y

    }


# ==========================================================
# Double Click Target
# ==========================================================

def double_click_screen_target(
    target
):

    result = find_screen_target(
        target
    )

    if not result.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Target not found: {target}"

        }

    vision_x, vision_y = get_center(
        result
    )

    mouse_x, mouse_y = convert_coordinates(
        vision_x,
        vision_y,
        clicking=True,
        target=target
    )

    logging.info(
        f"Double clicking: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
        mouse_x,
        mouse_y,
        duration=0.2
    )

    pyautogui.doubleClick(
        interval=0.15
    )

    return {

        "success":
        True,

        "confidence":
        result.get(
            "confidence",
            0
        ),

        "message":
        f"Double clicked "
        f"{result.get('description', target)}"

    }


# ==========================================================
# Right Click Target
# ==========================================================

def right_click_screen_target(
    target
):

    result = find_screen_target(
        target
    )

    if not result.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Target not found: {target}"

        }

    vision_x, vision_y = get_center(
        result
    )

    mouse_x, mouse_y = convert_coordinates(
        vision_x,
        vision_y,
        clicking=True,
        target=target
    )

    logging.info(
        f"Right clicking: "
        f"{mouse_x},{mouse_y}"
    )

    pyautogui.moveTo(
        mouse_x,
        mouse_y,
        duration=0.2
    )

    pyautogui.rightClick()

    return {

        "success":
        True,

        "confidence":
        result.get(
            "confidence",
            0
        ),

        "message":
        f"Right clicked "
        f"{result.get('description', target)}"

    }


# ==========================================================
# Move Absolute
# ==========================================================

def move_absolute(
    x,
    y
):

    try:

        pyautogui.moveTo(
            int(x),
            int(y),
            duration=0.2
        )

        return {

            "success":
            True,

            "message":
            f"Moved to {x},{y}"

        }

    except Exception as e:

        return {

            "success":
            False,

            "error":
            str(e)

        }


# ==========================================================
# Scroll
# ==========================================================

def scroll_screen(
    direction="down",
    amount=None
):

    direction = str(
        direction
    ).lower()

    if amount is None:

        amount = 5

    if (
        "top" in direction
        or
        "up" in direction
    ):

        amount = abs(
            amount
        )

    else:

        amount = -abs(
            amount
        )

    pyautogui.scroll(
        amount
    )

    return {

        "success":
        True,

        "message":
        f"Scrolled {direction}"

    }


# ==========================================================
# Type Text
# ==========================================================

def type_text(
    text
):

    if not text:

        return {

            "success":
            False,

            "message":
            "Empty text"

        }

    try:

        pyautogui.write(
            str(text),
            interval=0.02
        )

        return {

            "success":
            True,

            "message":
            "Text typed"

        }

    except Exception as e:

        return {

            "success":
            False,

            "message":
            f"Typing failed: {e}"

        }


# ==========================================================
# Keyboard Input
# ==========================================================

def press_key(
    key
):

    allowed = {

        "enter",
        "escape",
        "esc",
        "tab",
        "space",
        "backspace",
        "delete",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end"

    }

    key = str(
        key
    ).lower().strip()

    if key == "esc":

        key = "escape"

    if key not in allowed:

        return {

            "success":
            False,

            "message":
            f"Key blocked: {key}"

        }

    try:

        pyautogui.press(
            key
        )

        return {

            "success":
            True,

            "message":
            f"Pressed {key}"

        }

    except Exception as e:

        return {

            "success":
            False,

            "message":
            f"Key press failed: {e}"

        }


# ==========================================================
# Hotkey Support
# ==========================================================

def press_hotkey(
    keys
):

    if not keys:

        return {

            "success":
            False,

            "message":
            "No keys supplied."

        }

    if isinstance(
        keys,
        str
    ):

        keys = keys.split("+")

    keys = [

        str(k)
        .lower()
        .strip()

        for k in keys

    ]

    allowed = {

        "ctrl",
        "alt",
        "shift",
        "win",
        "enter",
        "tab",
        "esc",
        "space",
        "a",
        "c",
        "v",
        "x",
        "z",
        "f",
        "s"

    }

    for key in keys:

        if key not in allowed:

            return {

                "success":
                False,

                "message":
                f"Blocked key: {key}"

            }

    try:

        pyautogui.hotkey(
            *keys
        )

        return {

            "success":
            True,

            "message":
            f"Pressed {'+'.join(keys)}"

        }

    except Exception as e:

        return {

            "success":
            False,

            "message":
            f"Hotkey failed: {e}"

        }


# ==========================================================
# Drag Screen Target
# ==========================================================

def drag_screen_target(
    source,
    destination
):

    start = find_screen_target(
        source
    )

    if not start.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Could not find {source}"

        }

    end = find_screen_target(
        destination
    )

    if not end.get(
        "found",
        False
    ):

        return {

            "success":
            False,

            "message":
            f"Could not find {destination}"

        }

    sx, sy = get_center(
        start
    )

    ex, ey = get_center(
        end
    )

    sx, sy = convert_coordinates(
        sx,
        sy,
        clicking=True,
        target=source
    )

    ex, ey = convert_coordinates(
        ex,
        ey,
        clicking=True,
        target=destination
    )

    logging.info(
        f"Dragging "
        f"{sx},{sy} -> {ex},{ey}"
    )

    pyautogui.moveTo(
        sx,
        sy,
        duration=0.2
    )

    pyautogui.dragTo(
        ex,
        ey,
        duration=0.8,
        button="left"
    )

    return {

        "success":
        True,

        "message":
        f"Dragged {source} "
        f"to {destination}"

    }


# ==========================================================
# Screen Change Detection
# ==========================================================

last_screen_hash = None


def screen_changed():

    global last_screen_hash

    try:

        screenshot = pyautogui.screenshot()

        current = screen_fingerprint(
            screenshot
        )

        if last_screen_hash is None:

            last_screen_hash = current

            return False

        changed = (
            current
            !=
            last_screen_hash
        )

        last_screen_hash = current

        return changed

    except Exception:

        return False


# ==========================================================
# Wait Until Element Appears
# ==========================================================

def wait_for_element(
    target,
    timeout=10
):

    start = time.time()

    while (
        time.time() - start
        <
        timeout
    ):

        result = find_screen_target(
            target
        )

        if result.get(
            "found",
            False
        ):

            return {

                "success":
                True,

                "confidence":
                result.get(
                    "confidence",
                    0
                ),

                "target":
                result.get(
                    "description",
                    target
                )

            }

        time.sleep(
            0.5
        )

    return {

        "success":
        False,

        "message":
        f"{target} did not appear"

    }


# ==========================================================
# Retry Click
# ==========================================================

def retry_click(
    target,
    attempts=3
):

    for i in range(
        attempts
    ):

        result = click_screen_target(
            target
        )

        if result.get(
            "success",
            False
        ):

            return result

        logging.warning(
            f"Click attempt "
            f"{i + 1} failed"
        )

        time.sleep(
            1
        )

    return {

        "success":
        False,

        "message":
        "All click attempts failed."

    }


# ==========================================================
# General Screen Verification
# ==========================================================

def verify_screen(
    instruction
):

    capture = capture_screen()

    if not capture["success"]:

        return False

    start_time = time.perf_counter()

    response = vision_chat(

        VERIFY_MODEL,

        [

            {
                "role":
                "system",

                "content":
"""
You are JARVIS action verification.

Look at the supplied screenshot.

Determine whether the requested computer action succeeded.

Use only visible evidence.

Do not guess.

Return ONLY JSON:

{
  "success": true,
  "confidence": 0.95,
  "reason": "brief reason"
}

Keep the reason short.
"""
            },

            {
                "role":
                "user",

                "content":
                instruction,

                "images": [
                    SCREENSHOT_FILE
                ]
            }

        ],

        json_mode=True,

        num_predict=
        VERIFY_NUM_PREDICT
    )

    elapsed = (
        time.perf_counter()
        -
        start_time
    )

    logging.info(
        f"Verification model time: "
        f"{elapsed:.3f}s"
    )

    if not response:

        return False

    raw = get_response_text(
        response
    )

    if not raw:

        return False

    logging.info(
        f"Verifier raw response: "
        f"{raw}"
    )

    data = extract_json(
        raw
    )

    if not data:

        return False

    try:

        success = bool(
            data.get(
                "success",
                False
            )
        )

        confidence = float(
            data.get(
                "confidence",
                0.0
            )
        )

    except Exception:

        return False

    reason = str(
        data.get(
            "reason",
            ""
        )
    ).strip()

    logging.info(
        f"Verification: "
        f"success={success} "
        f"confidence={confidence:.2f} "
        f"reason={reason}"
    )

    return (
        success
        and
        confidence >= MIN_CONFIDENCE
    )


# ==========================================================
# Tools Dispatcher Compatibility
# ==========================================================

def verify_screen_state(
    instruction
):

    return verify_screen(
        instruction
    )


# ==========================================================
# Safe Click
# ==========================================================

def safe_click(
    target
):

    result = click_screen_target(
        target
    )

    if not result.get(
        "success",
        False
    ):

        return result

    changed = wait_for_change()

    return {

        "success":
        changed,

        "message":
        (
            "Click completed."
            if changed
            else
            "Clicked but screen did not change."
        )

    }


# ==========================================================
# Open Application
# ==========================================================

def open_application(
    name
):

    if not name:

        return {

            "success":
            False,

            "message":
            "No application supplied."

        }

    pyautogui.press(
        "win"
    )

    time.sleep(
        0.5
    )

    type_text(
        name
    )

    time.sleep(
        0.5
    )

    press_key(
        "enter"
    )

    return {

        "success":
        True,

        "message":
        f"Opening {name}"

    }


# ==========================================================
# Command Cleanup
# ==========================================================

def clean_command(
    command
):

    command = str(
        command
    ).lower().strip()

    replacements = {

        "please ":
        "",

        "jarvis ":
        "",

        "can you ":
        "",

        "could you ":
        ""

    }

    for old, new in replacements.items():

        command = command.replace(
            old,
            new
        )

    return command


# ==========================================================
# Target Extraction
# ==========================================================

def extract_target(
    command,
    words
):

    target = command

    for word in words:

        target = target.replace(
            word,
            ""
        )

    return target.strip()


# ==========================================================
# JARVIS Command Router
# ==========================================================

def jarvis_execute(
    command
):

    original = command

    command = clean_command(
        command
    )

    result = None

    # ------------------------------------------------------
    # Analyze screen
    # ------------------------------------------------------

    if (
        "analyze screen"
        in command
        or
        "describe screen"
        in command
    ):

        result = {

            "success":
            True,

            "screen":
            analyze_screen()

        }

    # ------------------------------------------------------
    # Status
    # ------------------------------------------------------

    elif "status" in command:

        result = {

            "success":
            True,

            "status":
            jarvis_status()

        }

    # ------------------------------------------------------
    # Double click
    # ------------------------------------------------------

    elif command.startswith(
        "double click"
    ):

        target = extract_target(
            command,
            [
                "double click"
            ]
        )

        result = double_click_screen_target(
            target
        )

    # ------------------------------------------------------
    # Right click
    # ------------------------------------------------------

    elif command.startswith(
        "right click"
    ):

        target = extract_target(
            command,
            [
                "right click"
            ]
        )

        result = right_click_screen_target(
            target
        )

    # ------------------------------------------------------
    # Click
    # ------------------------------------------------------

    elif command.startswith(
        "click"
    ):

        target = extract_target(
            command,
            [
                "click"
            ]
        )

        result = click_screen_target(
            target
        )

    # ------------------------------------------------------
    # Move
    # ------------------------------------------------------

    elif command.startswith(
        "move"
    ):

        target = extract_target(
            command,
            [
                "move"
            ]
        )

        result = move_mouse_to_target(
            target
        )

    # ------------------------------------------------------
    # Type
    # ------------------------------------------------------

    elif command.startswith(
        "type"
    ):

        text = extract_target(
            command,
            [
                "type"
            ]
        )

        result = type_text(
            text
        )

    # ------------------------------------------------------
    # Press
    # ------------------------------------------------------

    elif command.startswith(
        "press"
    ):

        key = extract_target(
            command,
            [
                "press"
            ]
        )

        result = press_key(
            key
        )

    # ------------------------------------------------------
    # Scroll
    # ------------------------------------------------------

    elif command.startswith(
        "scroll"
    ):

        result = scroll_screen(
            command
        )

    # ------------------------------------------------------
    # Open
    # ------------------------------------------------------

    elif command.startswith(
        "open"
    ):

        app = extract_target(
            command,
            [
                "open"
            ]
        )

        result = open_application(
            app
        )

    else:

        result = {

            "success":
            False,

            "message":
            "Command not understood."

        }

    STATE.remember(
        original,
        result
    )

    return result


# ==========================================================
# JARVIS Memory State
# ==========================================================

class JarvisState:

    def __init__(
        self
    ):

        self.last_command = None
        self.last_target = None
        self.last_result = None
        self.history = []

    def remember(
        self,
        command,
        result
    ):

        self.last_command = command
        self.last_result = result

        self.history.append(
            {
                "command":
                command,

                "result":
                result
            }
        )

        if len(
            self.history
        ) > 50:

            self.history.pop(
                0
            )


STATE = JarvisState()


# ==========================================================
# Emergency Stop
# ==========================================================

def emergency_stop():

    try:

        pyautogui.keyDown(
            "esc"
        )

        time.sleep(
            0.1
        )

        pyautogui.keyUp(
            "esc"
        )

        return {

            "success":
            True,

            "message":
            "Emergency stop executed."

        }

    except Exception as e:

        return {

            "success":
            False,

            "message":
            f"Emergency stop failed: {e}"

        }


# ==========================================================
# Save History
# ==========================================================

def save_history():

    file = os.path.join(
        BASE_DIR,
        "jarvis_history.json"
    )

    try:

        with open(
            file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                STATE.history,
                f,
                indent=2
            )

        return True

    except Exception:

        return False


# ==========================================================
# Status
# ==========================================================

def jarvis_status():

    return {

        "active_window":
        get_active_window(),

        "screen":
        get_screen_size(),

        "vision_model":
        VISION_MODEL,

        "verify_model":
        VERIFY_MODEL,

        "vision_num_predict":
        VISION_NUM_PREDICT,

        "verify_num_predict":
        VERIFY_NUM_PREDICT,

        "page_stable_timeout":
        PAGE_STABLE_TIMEOUT,

        "page_stable_interval":
        PAGE_STABLE_INTERVAL,

        "max_vision_width":
        MAX_VISION_WIDTH,

        "min_confidence":
        MIN_CONFIDENCE,

        "mouse_offset_x":
        MOUSE_OFFSET_X,

        "mouse_offset_y":
        MOUSE_OFFSET_Y,

        "click_bias_x":
        CLICK_BIAS_X,

        "click_bias_y":
        CLICK_BIAS_Y

    }


# ==========================================================
# Final Launcher
# ==========================================================

def start_jarvis():

    print(
        """
================================

        JARVIS ONLINE

 Vision Engine Loaded
 Ollama Connected
 Mouse Control Ready

 Type commands.
 Type EXIT to close.

================================
"""
    )

    while True:

        try:

            command = input(
                "\nJARVIS >>> "
            )

            if command.lower() in [

                "exit",
                "quit",
                "shutdown"

            ]:

                save_history()

                print(
                    "JARVIS shutting down."
                )

                break

            if command.lower() == "stop":

                print(
                    emergency_stop()
                )

                continue

            result = jarvis_execute(
                command
            )

            print(
                json.dumps(
                    result,
                    indent=2
                )
            )

        except KeyboardInterrupt:

            save_history()

            print(
                "\nJARVIS interrupted."
            )

            break

        except Exception as e:

            print(
                {
                    "error":
                    str(e)
                }
            )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    start_jarvis()