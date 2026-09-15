import os
import json
import time
import ctypes
import logging
import re
import hashlib
from difflib import SequenceMatcher

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

YOUTUBE_CANDIDATE_IMAGE = os.path.join(
    BASE_DIR,
    "jarvis_youtube_candidate.png"
)

YOUTUBE_VERIFY_CONTEXT_IMAGE = os.path.join(
    BASE_DIR,
    "jarvis_youtube_verify_context.png"
)

YOUTUBE_THUMBNAIL_IMAGE = os.path.join(
    BASE_DIR,
    "jarvis_youtube_thumbnail.png"
)


# ==========================================================
# Models
# ==========================================================

VISION_MODEL = "qwen2.5vl:3b"

VERIFY_MODEL = "qwen3.5:9b"

YOUTUBE_VERIFY_MODEL = "qwen2.5vl:3b"

YOUTUBE_THUMBNAIL_MODEL = "qwen2.5vl:3b"


# ==========================================================
# Confidence
# ==========================================================

MIN_CONFIDENCE = 0.70

YOUTUBE_VERIFY_MIN_CONFIDENCE = 0.75

YOUTUBE_THUMBNAIL_MIN_CONFIDENCE = 0.80


# ==========================================================
# Ollama Limits
# ==========================================================

VISION_NUM_PREDICT = 96

VERIFY_NUM_PREDICT = 48

YOUTUBE_CANDIDATE_NUM_PREDICT = 384

YOUTUBE_VERIFY_NUM_PREDICT = 128

YOUTUBE_THUMBNAIL_NUM_PREDICT = 96


# ==========================================================
# Vision Image Size
# ==========================================================

MAX_VISION_WIDTH = 1280


# ==========================================================
# Browser / Page Stability
# ==========================================================

PAGE_STABLE_TIMEOUT = 5.0

PAGE_STABLE_INTERVAL = 0.35

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

# KEEP THESE ZERO.
#
# The click problem is handled by visual thumbnail
# localization rather than offsets.

MOUSE_OFFSET_X = 0

MOUSE_OFFSET_Y = 0

CLICK_BIAS_X = 0

CLICK_BIAS_Y = 0

YOUTUBE_CLICK_BIAS_X = 0

YOUTUBE_CLICK_BIAS_Y = 0


# ==========================================================
# YouTube Candidate Settings
# ==========================================================

YOUTUBE_CANDIDATE_LIMIT = 6

YOUTUBE_VERIFY_LIMIT = 4

YOUTUBE_CANDIDATE_PADDING = 24


# ==========================================================
# YouTube Candidate Geometry Safety
# ==========================================================

YOUTUBE_MAX_CANDIDATE_HEIGHT = 420

YOUTUBE_MAX_CANDIDATE_HEIGHT_RATIO = 0.56

YOUTUBE_MIN_CANDIDATE_WIDTH = 180


# ==========================================================
# YouTube Relevance Scoring
# ==========================================================

YOUTUBE_TITLE_WEIGHT = 0.20

YOUTUBE_CHANNEL_WEIGHT = 0.30

YOUTUBE_CONTEXT_WEIGHT = 0.50

YOUTUBE_MIN_RELEVANCE_SCORE = 0.35

YOUTUBE_MIN_FIELD_MATCH = 0.50


YOUTUBE_QUERY_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "for",
    "of",
    "in",
    "on",
    "with",
    "about",
    "please",
    "video",
    "videos",
}


# ==========================================================
# YouTube Thumbnail Safety
# ==========================================================

YOUTUBE_MIN_THUMBNAIL_WIDTH = 120

YOUTUBE_MIN_THUMBNAIL_HEIGHT = 70

YOUTUBE_MAX_THUMBNAIL_WIDTH = 700

YOUTUBE_MAX_THUMBNAIL_HEIGHT = 400

YOUTUBE_MAX_THUMBNAIL_ROW_WIDTH_RATIO = 0.80

YOUTUBE_MAX_THUMBNAIL_ROW_HEIGHT_RATIO = 0.90


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
            "error": str(e)
        }


# ==========================================================
# Fast Screen Fingerprint
# ==========================================================

def screen_fingerprint(
    screenshot
):

    try:

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

        if crop_width > MAX_VISION_WIDTH:

            scale = (
                MAX_VISION_WIDTH
                /
                float(crop_width)
            )

            new_width = MAX_VISION_WIDTH

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
            "success": True,
            "file": VISION_CROP_FILE,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "crop_left": left,
            "crop_top": top,
            "crop_width": crop_width,
            "crop_height": crop_height,
            "sent_width": final_width,
            "sent_height": final_height,
            "scale": scale
        }

    except Exception as e:

        logging.error(
            f"Vision image creation failed: {e}"
        )

        return {
            "success": False,
            "error": str(e)
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
            "width": width,
            "height": height
        }

    except Exception as e:

        return {
            "error": str(e)
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

        title = (
            buffer.value.strip()
        )

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
# Generic Locator Prompt
# ==========================================================

def build_locator_prompt(
    target,
    image_width,
    image_height
):

    return f"""
You are JARVIS visual locator.

Locate this visible target:

{target}

Image size:
width={image_width}
height={image_height}

Return ONLY JSON:

{{
  "found": true,
  "confidence": 0.90,
  "box_2d": [top, left, bottom, right],
  "description": "target"
}}

CRITICAL:

box_2d MUST be:

[top, left, bottom, right]

Coordinates are normalized from 0 to 1000.

Do NOT use:

[x1, y1, x2, y2]

Do not guess.

Return ONLY JSON.
"""


# ==========================================================
# Normalize Qwen Box
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

        top_value = float(
            box[0]
        )

        left_value = float(
            box[1]
        )

        bottom_value = float(
            box[2]
        )

        right_value = float(
            box[3]
        )

    except Exception:

        return None

    maximum = max(
        abs(top_value),
        abs(left_value),
        abs(bottom_value),
        abs(right_value)
    )

    if maximum <= 1.0:

        top_value *= height

        bottom_value *= height

        left_value *= width

        right_value *= width

    elif maximum <= 1200:

        top_value = max(
            0.0,
            min(
                top_value,
                1000.0
            )
        )

        bottom_value = max(
            0.0,
            min(
                bottom_value,
                1000.0
            )
        )

        left_value = max(
            0.0,
            min(
                left_value,
                1000.0
            )
        )

        right_value = max(
            0.0,
            min(
                right_value,
                1000.0
            )
        )

        top_value = (
            top_value
            /
            1000.0
        ) * height

        bottom_value = (
            bottom_value
            /
            1000.0
        ) * height

        left_value = (
            left_value
            /
            1000.0
        ) * width

        right_value = (
            right_value
            /
            1000.0
        ) * width

    top = min(
        top_value,
        bottom_value
    )

    bottom = max(
        top_value,
        bottom_value
    )

    left = min(
        left_value,
        right_value
    )

    right = max(
        left_value,
        right_value
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
# Generic Screen Target Locator
# ==========================================================

def _find_screen_target_generic(
    target
):

    vision_info = create_vision_image(
        None
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

    crop_result = clean_location(
        result,
        vision_width,
        vision_height
    )

    if not crop_result.get(
        "found",
        False
    ):

        return crop_result

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
            screen_box["left"],

        "top":
            screen_box["top"],

        "right":
            screen_box["right"],

        "bottom":
            screen_box["bottom"],

        "description":
            crop_result.get(
                "description",
                target
            )
    }

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
# YouTube Query Normalization
# ==========================================================

def normalize_youtube_query(
    query
):

    query = str(
        query or ""
    ).strip()

    query = query.rstrip(
        ".,!?"
    )

    query = re.sub(
        r"^(?:a|an|the)\s+",
        "",
        query,
        flags=re.IGNORECASE
    )

    query = re.sub(
        r"\s+",
        " ",
        query
    ).strip()

    return query


# ==========================================================
# YouTube Query Tokens
# ==========================================================

def youtube_query_tokens(
    text
):

    text = normalize_youtube_query(
        text
    )

    text = text.lower()

    text = re.sub(
        r"[-_/]+",
        " ",
        text
    )

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    tokens = re.findall(
        r"[a-z0-9]+",
        text
    )

    return [
        token
        for token in tokens
        if (
            token
            and
            token not in
            YOUTUBE_QUERY_STOPWORDS
        )
    ]


# ==========================================================
# Generic YouTube Text Similarity
# ==========================================================

def youtube_text_similarity(
    query,
    text
):

    query_tokens = youtube_query_tokens(
        query
    )

    text_tokens = youtube_query_tokens(
        text
    )

    if not query_tokens or not text_tokens:

        return {
            "token_overlap":
                0.0,

            "sequence_ratio":
                0.0,

            "score":
                0.0,

            "exact_phrase":
                False
        }

    query_set = set(
        query_tokens
    )

    text_set = set(
        text_tokens
    )

    overlap = len(
        query_set.intersection(
            text_set
        )
    )

    token_overlap = (
        overlap
        /
        max(
            1,
            len(query_set)
        )
    )

    query_normalized = " ".join(
        query_tokens
    )

    text_normalized = " ".join(
        text_tokens
    )

    sequence_ratio = SequenceMatcher(
        None,
        query_normalized,
        text_normalized
    ).ratio()

    exact_phrase = (
        query_normalized
        in
        text_normalized
    )

    score = max(
        token_overlap,
        sequence_ratio
    )

    if exact_phrase:

        score = max(
            score,
            1.0
        )

    return {
        "token_overlap":
            token_overlap,

        "sequence_ratio":
            sequence_ratio,

        "score":
            score,

        "exact_phrase":
            exact_phrase
    }


# ==========================================================
# YouTube Multi-Signal Relevance
# ==========================================================

def youtube_candidate_match_score(
    query,
    title,
    channel,
    context_text
):

    title_similarity = (
        youtube_text_similarity(
            query,
            title
        )
    )

    channel_similarity = (
        youtube_text_similarity(
            query,
            channel
        )
    )

    context_similarity = (
        youtube_text_similarity(
            query,
            context_text
        )
    )

    title_score = (
        title_similarity["score"]
    )

    channel_score = (
        channel_similarity["score"]
    )

    context_score = (
        context_similarity["score"]
    )

    weighted_score = (
        title_score
        *
        YOUTUBE_TITLE_WEIGHT
        +
        channel_score
        *
        YOUTUBE_CHANNEL_WEIGHT
        +
        context_score
        *
        YOUTUBE_CONTEXT_WEIGHT
    )

    strong_field_match = (
        title_score >=
        YOUTUBE_MIN_FIELD_MATCH

        or

        channel_score >=
        YOUTUBE_MIN_FIELD_MATCH

        or

        context_score >=
        YOUTUBE_MIN_FIELD_MATCH
    )

    exact_field_match = (
        title_similarity["exact_phrase"]
        or
        channel_similarity["exact_phrase"]
        or
        context_similarity["exact_phrase"]
    )

    matched = (
        exact_field_match
        or
        strong_field_match
        or
        weighted_score >=
        YOUTUBE_MIN_RELEVANCE_SCORE
    )

    return {
        "matched":
            matched,

        "score":
            weighted_score,

        "title_score":
            title_score,

        "channel_score":
            channel_score,

        "context_score":
            context_score,

        "title_exact":
            title_similarity["exact_phrase"],

        "channel_exact":
            channel_similarity["exact_phrase"],

        "context_exact":
            context_similarity["exact_phrase"]
    }


# ==========================================================
# YouTube Query Extraction
# ==========================================================

def extract_youtube_query(
    target
):

    text = str(
        target or ""
    ).strip()

    match = re.search(
        r"first\s+organic\s+youtube\s+result\s+for\s+(.+)$",
        text,
        re.IGNORECASE
    )

    if match:

        query = match.group(
            1
        ).strip()

    else:

        match = re.search(
            r"youtube\s+result\s+for\s+(.+)$",
            text,
            re.IGNORECASE
        )

        if match:

            query = match.group(
                1
            ).strip()

        else:

            query = text

    normalized = normalize_youtube_query(
        query
    )

    logging.info(
        "YouTube query normalized: "
        f"'{query}' -> '{normalized}'"
    )

    return normalized


# ==========================================================
# YouTube Candidate Detector Prompt
# ==========================================================

def youtube_candidate_prompt(
    query,
    width,
    height
):

    return f"""
You are JARVIS YouTube search-result detection.

Requested YouTube search:

{query}

Image dimensions:
width={width}
height={height}

Scan the MAIN YouTube search-results column
from TOP TO BOTTOM.

Do not stop after the first result.

Find multiple visible result rows.

Return up to {YOUTUBE_CANDIDATE_LIMIT} candidates.

Each candidate MUST represent exactly ONE
individual YouTube search-result row.

ONE BOX = ONE ROW.

A normal result row usually contains:

- one thumbnail on the LEFT
- one video title on the RIGHT
- a channel name
- metadata
- possibly a duration badge

For every candidate, extract the ACTUAL visible:

1. title
2. channel
3. context_text

"title" is the actual visible video title.

"channel" is the visible channel or creator name.

"context_text" is other visible text directly associated
with this row which helps identify the result.

Do not invent any text.

IMPORTANT RELEVANCE RULE:

The requested query does NOT have to appear in the
video title.

For example:

requested search:
Wi-Fi Skeleton

video title:
Nope your too late i already died

channel:
wifiskelton - Topic

context:
Provided by YouTube by IIP-DDS ...

That may be a relevant result.

DO NOT return:

- browser controls
- address bar
- browser tabs
- YouTube search box
- navigation
- sidebars
- channels as standalone results
- Topic pages as standalone results
- playlists
- Shorts
- shopping/product cards

A music video whose channel happens to end in
"- Topic" may still be a NORMAL VIDEO RESULT.

Advertisements MAY be returned.

If visible advertising evidence exists, such as:

Sponsored
Ad
Advertisement
Promoted

then:

"is_ad": true

and:

"ad_evidence": "exact visible text"

Never invent ad evidence.

If no visible ad label:

"is_ad": false

"ad_evidence": ""

If visibly a Short:

"is_short": true

Otherwise:

"is_short": false

"matches_query" is only your visual relevance estimate.
It is NOT the final authority.

Coordinates:

box_2d MUST be:

[top, left, bottom, right]

Coordinates are normalized from 0 to 1000.

Each box must tightly surround exactly ONE result row.

Do NOT combine multiple rows.

Return candidates in strict top-to-bottom order.

Return ONLY JSON:

{{
    "candidates": [
        {{
            "box_2d": [top, left, bottom, right],
            "title": "actual visible video title",
            "channel": "actual visible channel",
            "context_text": "other visible row-associated text",
            "confidence": 0.90,
            "is_ad": false,
            "is_short": false,
            "matches_query": true,
            "ad_evidence": ""
        }}
    ]
}}

If none are visible:

{{
    "candidates": []
}}
"""


# ==========================================================
# Build YouTube Verification Image
# ==========================================================

def _build_youtube_verification_image(
    image,
    box,
    candidate_index
):

    try:

        from PIL import ImageDraw

        verify_image = image.copy()

        draw = ImageDraw.Draw(
            verify_image
        )

        left = max(
            0,
            int(
                box["left"]
            )
        )

        top = max(
            0,
            int(
                box["top"]
            )
        )

        right = min(
            image.width - 1,
            int(
                box["right"]
            )
        )

        bottom = min(
            image.height - 1,
            int(
                box["bottom"]
            )
        )

        for offset in range(6):

            draw.rectangle(
                (
                    left - offset,
                    top - offset,
                    right + offset,
                    bottom + offset
                ),
                outline="red"
            )

        label_top = max(
            0,
            top - 30
        )

        label_right = min(
            image.width - 1,
            left + 190
        )

        draw.rectangle(
            (
                left,
                label_top,
                label_right,
                top
            ),
            fill="red"
        )

        draw.text(
            (
                left + 6,
                label_top + 6
            ),
            f"CANDIDATE {candidate_index}",
            fill="white"
        )

        verify_image.save(
            YOUTUBE_VERIFY_CONTEXT_IMAGE
        )

        return YOUTUBE_VERIFY_CONTEXT_IMAGE

    except Exception as e:

        logging.error(
            "YouTube verification image failed: "
            f"{e}"
        )

        return None


# ==========================================================
# Build Candidate-Only Thumbnail Image
# ==========================================================

def _build_youtube_candidate_thumbnail_image(
    image,
    box
):

    try:

        left = max(
            0,
            int(
                box["left"]
            )
        )

        top = max(
            0,
            int(
                box["top"]
            )
        )

        right = min(
            image.width,
            int(
                box["right"]
            )
        )

        bottom = min(
            image.height,
            int(
                box["bottom"]
            )
        )

        if (
            right <= left
            or
            bottom <= top
        ):

            return None

        candidate = image.crop(
            (
                left,
                top,
                right,
                bottom
            )
        )

        candidate.save(
            YOUTUBE_CANDIDATE_IMAGE
        )

        logging.info(
            "YouTube candidate crop saved: "
            f"{right - left}x{bottom - top}"
        )

        return {
            "file":
                YOUTUBE_CANDIDATE_IMAGE,

            "left":
                left,

            "top":
                top,

            "width":
                right - left,

            "height":
                bottom - top
        }

    except Exception as e:

        logging.error(
            "YouTube candidate crop failed: "
            f"{e}"
        )

        return None


# ==========================================================
# Locate Thumbnail Inside Verified Candidate
# ==========================================================

def locate_youtube_thumbnail(
    candidate_file,
    candidate_image_info,
    candidate_index
):

    if not candidate_file:
        return None

    candidate_width = int(
        candidate_image_info.get(
            "width",
            0
        )
    )

    candidate_height = int(
        candidate_image_info.get(
            "height",
            0
        )
    )

    if (
        candidate_width <= 0
        or
        candidate_height <= 0
    ):
        return None

    # --------------------------------------------------
    # SAFE VERIFIED-ROW CLICK REGION
    #
    # The row has already passed:
    #   1. query relevance
    #   2. ad rejection
    #   3. structural verification
    #
    # Do not rely on thumbnail aspect ratio or a second
    # vision model to locate the thumbnail. YouTube Music
    # / Topic rows can use different visual thumbnail
    # formatting.
    #
    # The thumbnail/media area is on the left side of the
    # verified result. Keep a conservative region there.
    # --------------------------------------------------

    safe_left = int(
        round(
            candidate_width
            *
            0.03
        )
    )

    safe_right = int(
        round(
            candidate_width
            *
            0.38
        )
    )

    safe_top = int(
        round(
            candidate_height
            *
            0.25
        )
    )

    safe_bottom = int(
        round(
            candidate_height
            *
            0.75
        )
    )

    safe_width = (
        safe_right
        -
        safe_left
    )

    safe_height = (
        safe_bottom
        -
        safe_top
    )

    if safe_width <= 0 or safe_height <= 0:

        logging.info(
            f"YouTube safe thumbnail region "
            f"candidate {candidate_index}: "
            "invalid geometry."
        )

        return None

    # --------------------------------------------------
    # Final candidate-relative bounds check.
    # --------------------------------------------------

    if (
        safe_left < 0
        or
        safe_top < 0
        or
        safe_right > candidate_width
        or
        safe_bottom > candidate_height
    ):

        logging.info(
            f"YouTube safe thumbnail region "
            f"candidate {candidate_index}: "
            "escaped candidate bounds."
        )

        return None

    full_image_box = {

        "left":
            candidate_image_info["left"]
            +
            safe_left,

        "top":
            candidate_image_info["top"]
            +
            safe_top,

        "right":
            candidate_image_info["left"]
            +
            safe_right,

        "bottom":
            candidate_image_info["top"]
            +
            safe_bottom
    }

    confidence = 0.90

    logging.info(
        f"YouTube safe thumbnail region "
        f"candidate {candidate_index}: "
        f"relative="
        f"{safe_left},"
        f"{safe_top},"
        f"{safe_right},"
        f"{safe_bottom} "
        f"size={safe_width}x"
        f"{safe_height}"
    )

    logging.info(
        f"YouTube thumbnail located "
        f"candidate {candidate_index}: "
        f"full_vision="
        f"{full_image_box['left']},"
        f"{full_image_box['top']},"
        f"{full_image_box['right']},"
        f"{full_image_box['bottom']} "
        f"confidence={confidence:.2f}"
    )

    return {

        "found":
            True,

        "confidence":
            confidence,

        "left":
            full_image_box["left"],

        "top":
            full_image_box["top"],

        "right":
            full_image_box["right"],

        "bottom":
            full_image_box["bottom"],

        "candidate_index":
            candidate_index
    }


# ==========================================================
# Verify Thumbnail Is Inside Candidate
# ==========================================================

def validate_youtube_thumbnail_inside_candidate(
    thumbnail_box,
    candidate_box,
    candidate_index
):

    if not thumbnail_box:

        return False

    if not candidate_box:

        return False

    if (
        thumbnail_box["left"]
        <
        candidate_box["left"]
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail extends left of candidate."
        )

        return False

    if (
        thumbnail_box["top"]
        <
        candidate_box["top"]
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail extends above candidate."
        )

        return False

    if (
        thumbnail_box["right"]
        >
        candidate_box["right"]
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail extends right of candidate."
        )

        return False

    if (
        thumbnail_box["bottom"]
        >
        candidate_box["bottom"]
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail extends below candidate."
        )

        return False

    thumbnail_width = (
        thumbnail_box["right"]
        -
        thumbnail_box["left"]
    )

    thumbnail_height = (
        thumbnail_box["bottom"]
        -
        thumbnail_box["top"]
    )

    candidate_width = (
        candidate_box["right"]
        -
        candidate_box["left"]
    )

    candidate_height = (
        candidate_box["bottom"]
        -
        candidate_box["top"]
    )

    if thumbnail_width <= 0 or thumbnail_height <= 0:

        return False

    if candidate_width <= 0 or candidate_height <= 0:

        return False

    if (
        thumbnail_width
        >=
        candidate_width
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail width equals/exceeds "
            "candidate width."
        )

        return False

    if (
        thumbnail_height
        >=
        candidate_height
    ):

        logging.info(
            f"YouTube thumbnail candidate "
            f"{candidate_index}: "
            "thumbnail height equals/exceeds "
            "candidate height."
        )

        return False

    return True


# ==========================================================
# Build Click Point From Verified Thumbnail
# ==========================================================

def get_youtube_thumbnail_click_point(
    thumbnail_box,
    candidate_box,
    candidate_index
):

    # --------------------------------------------------
    # VERIFIED YOUTUBE ROW CLICK
    #
    # The candidate has already passed:
    #   - deterministic relevance
    #   - detector-side ad rejection
    #   - structural video verification
    #
    # Thumbnail detection has proven unreliable across
    # YouTube Music / Topic layouts, so do not trust a
    # model-generated or synthetic thumbnail rectangle.
    #
    # Instead, use the verified result row and choose a
    # conservative point in its left-side media region.
    # --------------------------------------------------

    if not candidate_box:
        return None

    try:

        candidate_left = int(
            candidate_box["left"]
        )

        candidate_top = int(
            candidate_box["top"]
        )

        candidate_right = int(
            candidate_box["right"]
        )

        candidate_bottom = int(
            candidate_box["bottom"]
        )

    except (
        KeyError,
        TypeError,
        ValueError
    ):

        return None

    candidate_width = (
        candidate_right
        -
        candidate_left
    )

    candidate_height = (
        candidate_bottom
        -
        candidate_top
    )

    if (
        candidate_width <= 0
        or
        candidate_height <= 0
    ):

        logging.info(
            f"YouTube verified row "
            f"candidate {candidate_index}: "
            "invalid candidate geometry."
        )

        return None

    # --------------------------------------------------
    # Conservative left-side media point.
    #
    # Keep well away from:
    #   - title
    #   - channel
    #   - action buttons
    #   - right-side metadata
    #
    # Use the vertical center because the candidate row
    # itself has already been detected as the result.
    # --------------------------------------------------

    x = (
        candidate_left
        +
        int(
            candidate_width
            *
            0.16
        )
    )

    y = (
        candidate_top
        +
        int(
            candidate_height
            *
            0.50
        )
    )

    # --------------------------------------------------
    # Final strict bounds margin.
    # --------------------------------------------------

    safe_left = (
        candidate_left
        +
        max(
            5,
            int(
                candidate_width
                *
                0.05
            )
        )
    )

    safe_right = (
        candidate_left
        +
        int(
            candidate_width
            *
            0.40
        )
    )

    safe_top = (
        candidate_top
        +
        max(
            5,
            int(
                candidate_height
                *
                0.10
            )
        )
    )

    safe_bottom = (
        candidate_bottom
        -
        max(
            5,
            int(
                candidate_height
                *
                0.10
            )
        )
    )

    if (
        safe_right <= safe_left
        or
        safe_bottom <= safe_top
    ):

        return None

    x = max(
        safe_left,
        min(
            x,
            safe_right
        )
    )

    y = max(
        safe_top,
        min(
            y,
            safe_bottom
        )
    )

    logging.info(
        f"YouTube verified row safe click "
        f"candidate {candidate_index}: "
        f"{x},{y} "
        f"row="
        f"{candidate_left},"
        f"{candidate_top},"
        f"{candidate_right},"
        f"{candidate_bottom}"
    )

    return x, y


# ==========================================================
# YouTube Verifier Boolean Normalization
# ==========================================================

def _normalize_bool(
    value,
    default=False
):

    if isinstance(
        value,
        bool
    ):

        return value

    if isinstance(
        value,
        (int, float)
    ):

        return bool(
            value
        )

    if isinstance(
        value,
        str
    ):

        normalized = (
            value
            .strip()
            .lower()
        )

        if normalized in {
            "true",
            "yes",
            "1",
            "y",
            "on"
        }:

            return True

        if normalized in {
            "false",
            "no",
            "0",
            "n",
            "off",
            ""
        }:

            return False

    return default


# ==========================================================
# YouTube Verifier Text Normalization
# ==========================================================

def _normalize_text(
    value
):

    if value is None:

        return ""

    return str(
        value
    ).strip()


# ==========================================================
# Normalize YouTube Verifier Result
# ==========================================================

def _youtube_verifier_normalize_result(
    data,
    query,
    candidate_index
):

    """
    Accept both verifier schemas.

    OLD:

        valid
        is_ad
        is_short
        matches_query
        confidence

    NEW:

        is_video
        is_sponsored
        is_topic
        is_playlist
        is_standalone_channel_page
        is_standalone_topic_page
        is_standalone_video_page
        is_ad
        is_short
        matches_query
        confidence
        title
        channel
        context_text
        ad_evidence
        reason

    IMPORTANT:

    A normal music video can belong to a channel such as:

        artist - Topic

    That does NOT make it invalid.

    Only a standalone Topic page is rejected.
    """

    if not isinstance(
        data,
        dict
    ):

        return None

    title = _normalize_text(
        data.get(
            "title",
            ""
        )
    )

    channel = _normalize_text(
        data.get(
            "channel",
            ""
        )
    )

    context_text = _normalize_text(
        data.get(
            "context_text",
            ""
        )
    )

    reason = _normalize_text(
        data.get(
            "reason",
            ""
        )
    )

    ad_evidence = _normalize_text(
        data.get(
            "ad_evidence",
            ""
        )
    )

    try:

        confidence = float(
            data.get(
                "confidence",
                0.0
            )
        )

    except Exception:

        confidence = 0.0

    confidence = max(
        0.0,
        min(
            confidence,
            1.0
        )
    )

    # ------------------------------------------------------
    # Safety flags
    # ------------------------------------------------------

    is_ad = _normalize_bool(
        data.get(
            "is_ad",
            False
        )
    )

    is_sponsored = _normalize_bool(
        data.get(
            "is_sponsored",
            False
        )
    )

    is_short = _normalize_bool(
        data.get(
            "is_short",
            False
        )
    )

    is_playlist = _normalize_bool(
        data.get(
            "is_playlist",
            False
        )
    )

    is_standalone_channel_page = _normalize_bool(
        data.get(
            "is_standalone_channel_page",
            False
        )
    )

    is_standalone_topic_page = _normalize_bool(
        data.get(
            "is_standalone_topic_page",
            False
        )
    )

    is_standalone_video_page = _normalize_bool(
        data.get(
            "is_standalone_video_page",
            False
        )
    )

    is_topic = _normalize_bool(
        data.get(
            "is_topic",
            False
        )
    )

    # ------------------------------------------------------
    # Sponsored implies advertisement.
    # ------------------------------------------------------

    if is_sponsored:

        is_ad = True

        if not ad_evidence:

            ad_evidence = (
                "model classified candidate as sponsored"
            )

    # ------------------------------------------------------
    # Determine schema version.
    # ------------------------------------------------------

    has_is_video = (
        "is_video"
        in data
    )

    has_valid = (
        "valid"
        in data
    )

    has_matches_query = (
        "matches_query"
        in data
    )

    new_schema = (
        has_is_video
        or
        "is_sponsored"
        in data
        or
        "is_standalone_topic_page"
        in data
        or
        "is_standalone_channel_page"
        in data
        or
        "is_playlist"
        in data
    )

    is_video = _normalize_bool(
        data.get(
            "is_video",
            False
        )
    )

    old_valid = _normalize_bool(
        data.get(
            "valid",
            False
        )
    )

    explicit_matches_query = _normalize_bool(
        data.get(
            "matches_query",
            False
        )
    )

    # ------------------------------------------------------
    # Independent relevance scoring.
    # ------------------------------------------------------

    relevance = youtube_candidate_match_score(
        query,
        title,
        channel,
        context_text
    )

    if has_matches_query:

        matches_query = (
            explicit_matches_query
        )

    else:

        matches_query = (
            relevance["matched"]
        )

    # ------------------------------------------------------
    # Determine actual video result.
    # ------------------------------------------------------

    if new_schema:

        is_actual_video = (
            is_video
        )

    elif has_valid:

        is_actual_video = (
            old_valid
        )

    else:

        is_actual_video = (
            not is_playlist
            and
            not is_standalone_channel_page
            and
            not is_standalone_topic_page
            and
            bool(
                title
                or
                channel
                or
                context_text
            )
        )

    # ------------------------------------------------------
    # Structural safety.
    # ------------------------------------------------------
    #
    # NOTE:
    #
    # is_topic=True is NOT rejected.
    #
    # Topic channel music videos are allowed.
    #
    # standalone Topic pages are rejected.
    #

    structural_safety_passed = (
        is_actual_video
        and
        not is_ad
        and
        not is_short
        and
        not is_playlist
        and
        not is_standalone_channel_page
        and
        not is_standalone_topic_page
        and
        not is_standalone_video_page
    )

    # ------------------------------------------------------
    # Final validity.
    # ------------------------------------------------------

    if new_schema:

        valid = (
            structural_safety_passed
            and
            matches_query
        )

    else:

        valid = (
            old_valid
            and
            structural_safety_passed
            and
            matches_query
        )

    # ------------------------------------------------------
    # Confidence fallback.
    # ------------------------------------------------------

    if confidence <= 0.0:

        if (
            structural_safety_passed
            and
            matches_query
            and
            relevance["score"]
            >=
            YOUTUBE_MIN_RELEVANCE_SCORE
        ):

            confidence = 0.85

        else:

            confidence = 0.0

    # ------------------------------------------------------
    # Build reason when omitted.
    # ------------------------------------------------------

    if not reason:

        if is_ad:

            reason = (
                "candidate classified as sponsored/advertisement"
            )

        elif is_short:

            reason = (
                "candidate is a YouTube Short"
            )

        elif is_playlist:

            reason = (
                "candidate is a playlist"
            )

        elif is_standalone_topic_page:

            reason = (
                "candidate is a standalone Topic page"
            )

        elif is_standalone_channel_page:

            reason = (
                "candidate is a standalone channel page"
            )

        elif is_standalone_video_page:

            reason = (
                "candidate is a standalone video page"
            )

        elif not is_actual_video:

            reason = (
                "candidate is not a normal video result"
            )

        elif not matches_query:

            reason = (
                "candidate is not relevant to requested search"
            )

        elif valid:

            reason = (
                "verified normal YouTube video result"
            )

        else:

            reason = (
                "candidate failed verifier safety checks"
            )

    result = {

        "valid":
            bool(
                valid
            ),

        "is_ad":
            bool(
                is_ad
            ),

        "is_short":
            bool(
                is_short
            ),

        "matches_query":
            bool(
                matches_query
            ),

        "confidence":
            float(
                confidence
            ),

        "title":
            title,

        "channel":
            channel,

        "context_text":
            context_text,

        "ad_evidence":
            ad_evidence,

        "reason":
            reason,

        "is_video":
            bool(
                is_actual_video
            ),

        "is_sponsored":
            bool(
                is_sponsored
            ),

        "is_topic":
            bool(
                is_topic
            ),

        "is_playlist":
            bool(
                is_playlist
            ),

        "is_standalone_channel_page":
            bool(
                is_standalone_channel_page
            ),

        "is_standalone_topic_page":
            bool(
                is_standalone_topic_page
            ),

        "is_standalone_video_page":
            bool(
                is_standalone_video_page
            ),

        "relevance_score":
            float(
                relevance["score"]
            )
    }

    logging.info(
        "YOUTUBE VERIFIER NORMALIZED "
        f"candidate={candidate_index} "
        f"schema="
        f"{'new' if new_schema else 'old'} "
        f"is_video="
        f"{result['is_video']} "
        f"is_ad="
        f"{result['is_ad']} "
        f"is_sponsored="
        f"{result['is_sponsored']} "
        f"is_topic="
        f"{result['is_topic']} "
        f"is_short="
        f"{result['is_short']} "
        f"is_playlist="
        f"{result['is_playlist']} "
        f"standalone_channel="
        f"{result['is_standalone_channel_page']} "
        f"standalone_topic="
        f"{result['is_standalone_topic_page']} "
        f"standalone_video="
        f"{result['is_standalone_video_page']} "
        f"matches_query="
        f"{result['matches_query']} "
        f"relevance="
        f"{result['relevance_score']:.2f} "
        f"valid="
        f"{result['valid']} "
        f"confidence="
        f"{result['confidence']:.2f} "
        f"title="
        f"{result['title']!r} "
        f"channel="
        f"{result['channel']!r}"
    )

    return result


# ==========================================================
# YouTube Candidate Verification
# ==========================================================

def verify_youtube_candidate(
    image_path,
    query,
    candidate_index,
    candidate_box=None,
    candidate_title="",
    candidate_channel="",
    candidate_context="",
    candidate_matches_query=False,
    candidate_relevance_score=0.0,
):
    """
    Verify structural safety of one already-detected YouTube
    search-result candidate.

    Detector owns:
        title
        channel
        context
        semantic relevance
        candidate row identity

    Verifier owns:
        video-vs-non-video safety
        advertisement safety
        sponsored safety
        Shorts safety
        playlist safety

    Standalone-page flags are intentionally NOT used as
    rejection criteria here because this verifier receives a
    crop of an already-selected search-result row.
    """

    candidate_title = str(
        candidate_title or ""
    ).strip()

    candidate_channel = str(
        candidate_channel or ""
    ).strip()

    candidate_context = str(
        candidate_context or ""
    ).strip()

    prompt = f"""
You are JARVIS's FINAL YouTube SEARCH-RESULT SAFETY VERIFIER.

You are verifying ONE SPECIFIC candidate region.

The candidate was already selected by a YouTube search-result
detector.

Candidate #{candidate_index}.

The detector metadata below is authoritative:

Requested search:
{query}

Detector title:
{candidate_title}

Detector channel:
{candidate_channel}

Detector context:
{candidate_context}

Detector semantic relevance:
matched={candidate_matches_query}
score={candidate_relevance_score:.3f}

IMPORTANT:

This image is a crop of ONE ALREADY-SELECTED SEARCH RESULT ROW.

Do NOT search for another result.

Do NOT compare this candidate against neighboring results.

Do NOT replace its title.

Do NOT replace its channel.

Do NOT replace its context.

Do NOT re-evaluate semantic relevance.

Do NOT reject a candidate merely because its channel name ends
in "- Topic".

==================================================
VIDEO SAFETY
==================================================

Set:

"is_video": true

when this cropped object is a normal YouTube video search-result
row containing a thumbnail, title, channel/creator, and metadata.

Set:

"is_video": false

only when the cropped object clearly is not a normal video
search-result row.

==================================================
ADVERTISEMENT SAFETY
==================================================

Set:

"is_ad": true

ONLY when visible advertising evidence exists in THIS candidate.

Examples:

Sponsored
Ad
Advertisement
Promoted

Otherwise:

"is_ad": false

Set:

"is_sponsored": true

ONLY when explicit sponsored evidence is visible.

Otherwise:

"is_sponsored": false

Do NOT infer an advertisement because:

- the candidate is near the top
- the candidate is visually prominent
- the company is recognizable
- it appears before another result

==================================================
SHORTS SAFETY
==================================================

Set:

"is_short": true

ONLY when the candidate is visibly a YouTube Short.

Otherwise:

"is_short": false

==================================================
PLAYLIST SAFETY
==================================================

Set:

"is_playlist": true

ONLY when the candidate itself is visibly a playlist.

Otherwise:

"is_playlist": false

==================================================
TOPIC CHANNEL RULE
==================================================

A legitimate YouTube video can belong to a channel ending in:

"- Topic"

Example:

channel:
{candidate_channel}

That does NOT make the result a Topic page.

Do NOT classify this search-result row as a standalone Topic page
merely because the channel name contains "- Topic".

The detector has already selected a search-result row.

Therefore:

"is_standalone_channel_page": false
"is_standalone_topic_page": false
"is_standalone_video_page": false

for this verification task.

"is_topic" may be true or false, but it is informational only
and MUST NOT cause rejection.

==================================================
SEMANTIC RELEVANCE
==================================================

Do NOT calculate relevance.

The detector owns relevance.

Use:

matched={candidate_matches_query}

as the authoritative semantic result.

==================================================
OUTPUT
==================================================

Return ONLY JSON.

Use EXACTLY:

{{
  "is_video": true,
  "is_ad": false,
  "is_sponsored": false,
  "is_short": false,
  "is_playlist": false,
  "is_standalone_channel_page": false,
  "is_standalone_topic_page": false,
  "is_standalone_video_page": false,
  "is_topic": false,
  "confidence": 0.95,
  "ad_evidence": "",
  "reason": "brief structural reason"
}}

Do NOT return:

"title"
"channel"
"context_text"
"matches_query"
"relevance"

Those belong to the detector.
"""

    start_time = time.perf_counter()

    response = vision_chat(
        YOUTUBE_VERIFY_MODEL,
        [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": (
                    "Verify ONLY this already-selected "
                    f"YouTube search-result candidate #{candidate_index}."
                ),
                "images": [
                    image_path
                ],
            },
        ],
        json_mode=True,
        num_predict=YOUTUBE_VERIFY_NUM_PREDICT,
    )

    elapsed = (
        time.perf_counter()
        -
        start_time
    )

    logging.info(
        f"YouTube candidate {candidate_index} "
        "structural verification time: "
        f"{elapsed:.3f}s"
    )

    if not response:

        return {
            "valid": False,
            "is_video": False,
            "is_ad": False,
            "is_sponsored": False,
            "is_short": False,
            "is_playlist": False,
            "is_standalone_channel_page": False,
            "is_standalone_topic_page": False,
            "is_standalone_video_page": False,
            "is_topic": False,
            "matches_query": bool(
                candidate_matches_query
            ),
            "confidence": 0.0,
            "title": candidate_title,
            "channel": candidate_channel,
            "context_text": candidate_context,
            "ad_evidence": "",
            "relevance_score": float(
                candidate_relevance_score
            ),
            "reason": "no verifier response",
        }

    raw = get_response_text(
        response
    )

    logging.info(
        f"YouTube candidate {candidate_index} "
        "structural verifier raw: "
        f"{raw}"
    )

    data = extract_json(
        raw
    )

    if not isinstance(
        data,
        dict
    ):

        return {
            "valid": False,
            "is_video": False,
            "is_ad": False,
            "is_sponsored": False,
            "is_short": False,
            "is_playlist": False,
            "is_standalone_channel_page": False,
            "is_standalone_topic_page": False,
            "is_standalone_video_page": False,
            "is_topic": False,
            "matches_query": bool(
                candidate_matches_query
            ),
            "confidence": 0.0,
            "title": candidate_title,
            "channel": candidate_channel,
            "context_text": candidate_context,
            "ad_evidence": "",
            "relevance_score": float(
                candidate_relevance_score
            ),
            "reason": "invalid verifier JSON",
        }

    def as_bool(
        value,
        default=False,
    ):

        if isinstance(value, bool):
            return value

        if isinstance(value, str):

            value = value.strip().lower()

            if value in {
                "true",
                "yes",
                "1",
            }:
                return True

            if value in {
                "false",
                "no",
                "0",
            }:
                return False

        if isinstance(
            value,
            (int, float)
        ):
            return bool(value)

        return default

    is_video = as_bool(
        data.get(
            "is_video"
        ),
        True,
    )

    is_ad = as_bool(
        data.get(
            "is_ad"
        ),
        False,
    )

    is_sponsored = as_bool(
        data.get(
            "is_sponsored"
        ),
        False,
    )

    is_short = as_bool(
        data.get(
            "is_short"
        ),
        False,
    )

    is_playlist = as_bool(
        data.get(
            "is_playlist"
        ),
        False,
    )

    is_topic = as_bool(
        data.get(
            "is_topic"
        ),
        False,
    )

    if is_sponsored:
        is_ad = True

    try:
        confidence = float(
            data.get(
                "confidence",
                0.0
            )
        )
    except Exception:
        confidence = 0.0

    confidence = max(
        0.0,
        min(
            confidence,
            1.0
        )
    )

    ad_evidence = str(
        data.get(
            "ad_evidence",
            ""
        )
    ).strip()

    reason = str(
        data.get(
            "reason",
            ""
        )
    ).strip()

    # ------------------------------------------------------
    # Ignore unsupported advertisement claims.
    # ------------------------------------------------------

    if (
        is_ad
        and
        not is_sponsored
        and
        not ad_evidence
    ):

        logging.info(
            f"YouTube candidate {candidate_index}: "
            "verifier claimed advertisement without "
            "visible evidence; clearing claim."
        )

        is_ad = False

    # ------------------------------------------------------
    # Standalone-page flags are forced false.
    #
    # This verifier is examining a crop of an already-selected
    # search-result row, not an arbitrary full browser page.
    # ------------------------------------------------------

    is_standalone_channel_page = False
    is_standalone_topic_page = False
    is_standalone_video_page = False

    structural_ok = (
        is_video
        and
        not is_ad
        and
        not is_short
        and
        not is_playlist
    )

    matches_query = bool(
        candidate_matches_query
    )

    valid = (
        structural_ok
        and
        matches_query
    )

    if (
        structural_ok
        and
        matches_query
        and
        confidence <= 0.0
    ):
        confidence = 0.85

    result = {
        "valid": valid,

        "is_video": is_video,
        "is_ad": is_ad,
        "is_sponsored": is_sponsored,
        "is_short": is_short,
        "is_playlist": is_playlist,

        "is_standalone_channel_page":
            False,

        "is_standalone_topic_page":
            False,

        "is_standalone_video_page":
            False,

        "is_topic":
            is_topic,

        "matches_query":
            matches_query,

        "confidence":
            confidence,

        # Detector identity is authoritative.
        "title":
            candidate_title,

        "channel":
            candidate_channel,

        "context_text":
            candidate_context,

        "ad_evidence":
            ad_evidence,

        "relevance_score":
            float(candidate_relevance_score),

        "reason":
            reason,
    }

    logging.info(
        "YOUTUBE VERIFIER FINAL "
        f"candidate={candidate_index} "
        f"title={candidate_title!r} "
        f"channel={candidate_channel!r} "
        f"valid={valid} "
        f"is_video={is_video} "
        f"is_ad={is_ad} "
        f"is_sponsored={is_sponsored} "
        f"is_topic={is_topic} "
        f"is_short={is_short} "
        f"is_playlist={is_playlist} "
        f"matches_query={matches_query} "
        f"confidence={confidence:.2f} "
        f"relevance={candidate_relevance_score:.2f} "
        f"ad_evidence={ad_evidence!r} "
        f"reason={reason!r}"
    )

    return result

def find_first_verified_youtube_result(
    target
):

    query = extract_youtube_query(
        target
    )

    logging.info(
        "YouTube query verification target: "
        f"{query}"
    )

    if not query:

        return {
            "found":
                False,

            "confidence":
                0.0,

            "description":
                "missing YouTube query"
        }

    wait_for_page_stable()

    vision_info = create_vision_image(
        target
    )

    if not vision_info.get(
        "success",
        False
    ):

        return {
            "found":
                False,

            "confidence":
                0.0,

            "description":
                "vision image creation failed"
        }

    vision_file = vision_info[
        "file"
    ]

    width = vision_info[
        "sent_width"
    ]

    height = vision_info[
        "sent_height"
    ]

    prompt = youtube_candidate_prompt(
        query,
        width,
        height
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
                    (
                        "Find all visible "
                        "YouTube video-result "
                        f"candidates for '{query}'."
                    ),

                "images": [
                    vision_file
                ]
            }
        ],

        json_mode=True,

        num_predict=
        YOUTUBE_CANDIDATE_NUM_PREDICT
    )

    elapsed = (
        time.perf_counter()
        -
        start
    )

    logging.info(
        "YouTube candidate detection time: "
        f"{elapsed:.3f}s"
    )

    if not response:

        return {
            "found":
                False,

            "confidence":
                0.0,

            "description":
                "candidate detector failed"
        }

    raw = get_response_text(
        response
    )

    logging.info(
        "YouTube candidate detector raw: "
        f"{raw}"
    )

    data = extract_json(
        raw
    )

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
                "invalid or incomplete candidate JSON",

            "query":
                query,

            "verified":
                False
        }

    candidates = data.get(
        "candidates",
        []
    )

    if not isinstance(
        candidates,
        list
    ):

        candidates = []

    normalized = []

    max_allowed_height = min(
        YOUTUBE_MAX_CANDIDATE_HEIGHT,
        int(
            height
            *
            YOUTUBE_MAX_CANDIDATE_HEIGHT_RATIO
        )
    )

    for candidate in candidates:

        if not isinstance(
            candidate,
            dict
        ):

            continue

        # --------------------------------------------------
        # YouTube candidate box normalization.
        #
        # The documented format is:
        #   [top, left, bottom, right]
        #   normalized 0..1000
        #
        # However, the model has occasionally returned pixel
        # coordinates such as:
        #
        #   [499, 470, 1046, 560]
        #
        # on a 1280x759 detector image.
        #
        # We only switch to pixel interpretation when at least
        # one value exceeds 1000 AND the complete rectangle still
        # fits inside the detector image. Otherwise we preserve
        # the existing normalized interpretation.
        # --------------------------------------------------

        raw_box = candidate.get(
            "box_2d"
        )

        box = None

        if (
            isinstance(
                raw_box,
                (list, tuple)
            )
            and
            len(raw_box) >= 4
        ):

            try:

                v0 = float(
                    raw_box[0]
                )

                v1 = float(
                    raw_box[1]
                )

                v2 = float(
                    raw_box[2]
                )

                v3 = float(
                    raw_box[3]
                )

                looks_like_pixel_box = (
                    max(
                        abs(v0),
                        abs(v1),
                        abs(v2),
                        abs(v3)
                    )
                    >
                    1000.0
                    and
                    0.0 <= v0 <= float(width)
                    and
                    0.0 <= v1 <= float(height)
                    and
                    0.0 <= v2 <= float(width)
                    and
                    0.0 <= v3 <= float(height)
                    and
                    v2 > v0
                    and
                    v3 > v1
                )

                if looks_like_pixel_box:

                    box = {

                        "left":
                            int(
                                round(
                                    v0
                                )
                            ),

                        "top":
                            int(
                                round(
                                    v1
                                )
                            ),

                        "right":
                            int(
                                round(
                                    v2
                                )
                            ),

                        "bottom":
                            int(
                                round(
                                    v3
                                )
                            )
                    }

                    logging.info(
                        "YouTube candidate box "
                        "interpreted as PIXEL "
                        "[left,top,right,bottom]: "
                        f"{v0},{v1},{v2},{v3}"
                    )

                else:

                    box = normalize_box_2d(
                        raw_box,
                        width,
                        height
                    )

                    if box:

                        logging.info(
                            "YouTube candidate box "
                            "interpreted using "
                            "existing normalized "
                            "[top,left,bottom,right] "
                            "convention: "
                            f"{v0},{v1},{v2},{v3}"
                        )

            except (
                TypeError,
                ValueError
            ):

                box = None

        if not box:
            continue

        title = str(
            candidate.get(
                "title",
                ""
            )
        ).strip()

        channel = str(
            candidate.get(
                "channel",
                ""
            )
        ).strip()

        context_text = str(
            candidate.get(
                "context_text",
                ""
            )
        ).strip()

        candidate_is_ad = bool(
            candidate.get(
                "is_ad",
                False
            )
        )

        candidate_ad_evidence = str(
            candidate.get(
                "ad_evidence",
                ""
            )
        ).strip()

        candidate_is_short = bool(
            candidate.get(
                "is_short",
                False
            )
        )

        candidate_matches_query = bool(
            candidate.get(
                "matches_query",
                False
            )
        )

        # --------------------------------------------------
        # Deterministic ad-language safety layer.
        #
        # The vision model is not authoritative by itself.
        # Even when it incorrectly returns is_ad=False,
        # explicitly promotional language must still cause
        # the candidate to be rejected.
        #
        # These are intentionally strong indicators rather
        # than generic commercial words such as "shop" or
        # "product", which can legitimately appear in videos.
        # --------------------------------------------------

        combined_candidate_text = " ".join(
            [
                title,
                channel,
                context_text,
                candidate_ad_evidence
            ]
        ).lower()

        explicit_ad_patterns = [
            r"\bsponsored\b",
            r"\bsponsor(?:ed)?\s+by\b",
            r"\badvertisement\b",
            r"\badvertiser\b",
            r"\bpromoted\b",
            r"\bpaid\s+promotion\b",
            r"\bpaid\s+partnership\b",
            r"\bpromotional\b",
            r"\bpromoted\s+content\b",
            r"\bvisit\s+(?:the\s+)?advertiser\b",
            r"\blearn\s+more\b",
            r"\bshop\s+now\b",
            r"\bbuy\s+now\b",
            r"\binstall\s+now\b",
            r"\bdownload\s+now\b",
            r"\bsign\s+up\s+now\b",
            r"\bget\s+started\b",
            r"\border\s+now\b",
            r"\btry\s+it\s+now\b",
        ]

        explicit_ad_matches = []

        for pattern in explicit_ad_patterns:

            if re.search(
                pattern,
                combined_candidate_text,
                re.IGNORECASE
            ):

                explicit_ad_matches.append(
                    pattern
                )

        detector_text_ad = bool(
            explicit_ad_matches
        )

        if detector_text_ad:

            logging.info(
                f"YouTube candidate: "
                f"REJECTED BY DETERMINISTIC AD "
                f"LANGUAGE FILTER "
                f"title={title!r} "
                f"channel={channel!r} "
                f"matches={explicit_ad_matches}"
            )

            continue

        box_width = (
            box["right"]
            -
            box["left"]
        )

        box_height = (
            box["bottom"]
            -
            box["top"]
        )

        if box_height > max_allowed_height:

            logging.info(
                "YouTube candidate rejected "
                "as oversized box: "
                f"title={title!r} "
                f"box="
                f"{box['left']},"
                f"{box['top']},"
                f"{box['right']},"
                f"{box['bottom']} "
                f"height={box_height} "
                f"max={max_allowed_height}"
            )

            continue

        if (
            box_width
            <
            YOUTUBE_MIN_CANDIDATE_WIDTH
        ):

            logging.info(
                "YouTube candidate rejected "
                "as too narrow: "
                f"title={title!r} "
                f"width={box_width}"
            )

            continue

        # --------------------------------------------------
        # Only reject Topic-style TITLE entries.
        #
        # A channel named "- Topic" is allowed.
        # --------------------------------------------------

        title_lower = title.lower()

        if (
            title_lower.endswith(
                "- topic"
            )
            or
            title_lower.endswith(
                " topic"
            )
        ):

            logging.info(
                "YouTube candidate rejected "
                "as Topic-style title: "
                f"title={title!r}"
            )

            continue

        candidate_copy = dict(
            candidate
        )

        candidate_copy[
            "box"
        ] = box

        candidate_copy[
            "_box_width"
        ] = box_width

        candidate_copy[
            "_box_height"
        ] = box_height

        candidate_copy[
            "_detector_is_ad"
        ] = candidate_is_ad

        candidate_copy[
            "_detector_ad_evidence"
        ] = candidate_ad_evidence

        candidate_copy[
            "_detector_is_short"
        ] = candidate_is_short

        candidate_copy[
            "_detector_matches_query"
        ] = candidate_matches_query

        candidate_copy[
            "_detector_title"
        ] = title

        candidate_copy[
            "_detector_channel"
        ] = channel

        candidate_copy[
            "_detector_context"
        ] = context_text

        normalized.append(
            candidate_copy
        )

    normalized.sort(
        key=lambda item:
        item["box"]["top"]
    )

    logging.info(
        "YouTube candidates detected after "
        "geometry/title filtering: "
        f"{len(normalized)}"
    )

    for debug_index, candidate in enumerate(
        normalized,
        start=1
    ):

        box = candidate[
            "box"
        ]

        logging.info(
            "YouTube candidate normalized "
            f"#{debug_index}: "
            f"title="
            f"{candidate.get('title', '')!r} "
            f"channel="
            f"{candidate.get('channel', '')!r} "
            f"context="
            f"{candidate.get('context_text', '')!r} "
            f"box="
            f"{box['left']},"
            f"{box['top']},"
            f"{box['right']},"
            f"{box['bottom']}"
        )

        logging.info(
            "YouTube candidate detector evidence "
            f"#{debug_index}: "
            f"is_ad="
            f"{bool(candidate.get('is_ad', False))} "
            f"is_short="
            f"{bool(candidate.get('is_short', False))} "
            f"matches_query="
            f"{bool(candidate.get('matches_query', False))} "
            f"ad_evidence="
            f"{str(candidate.get('ad_evidence', '')).strip()!r}"
        )

    if not normalized:

        return {
            "found":
                False,

            "confidence":
                0.0,

            "description":
                "no valid YouTube candidates detected",

            "query":
                query,

            "verified":
                False
        }

    try:

        from PIL import Image

        image = Image.open(
            vision_file
        ).convert(
            "RGB"
        )

    except Exception as e:

        logging.error(
            "YouTube verification image "
            f"open failed: {e}"
        )

        return {
            "found":
                False,

            "confidence":
                0.0,

            "description":
                "could not open vision image",

            "query":
                query,

            "verified":
                False
        }

    candidates_to_verify = normalized[
        :YOUTUBE_VERIFY_LIMIT
    ]

    for index, candidate in enumerate(
        candidates_to_verify,
        start=1
    ):

        box = candidate[
            "box"
        ]

        detector_is_ad = bool(
            candidate.get(
                "_detector_is_ad",
                False
            )
        )

        detector_ad_evidence = str(
            candidate.get(
                "_detector_ad_evidence",
                ""
            )
        ).strip()

        detector_is_short = bool(
            candidate.get(
                "_detector_is_short",
                False
            )
        )

        detector_title = str(
            candidate.get(
                "_detector_title",
                candidate.get(
                    "title",
                    ""
                )
            )
        ).strip()

        detector_channel = str(
            candidate.get(
                "_detector_channel",
                candidate.get(
                    "channel",
                    ""
                )
            )
        ).strip()

        detector_context = str(
            candidate.get(
                "_detector_context",
                candidate.get(
                    "context_text",
                    ""
                )
            )
        ).strip()

        # --------------------------------------------------
        # Initial deterministic relevance.
        # --------------------------------------------------

        detector_match = (
            youtube_candidate_match_score(
                query,
                detector_title,
                detector_channel,
                detector_context
            )
        )

        logging.info(
            f"YouTube candidate {index} "
            "deterministic relevance: "
            f"query={query!r} "
            f"title={detector_title!r} "
            f"channel={detector_channel!r} "
            f"context={detector_context!r} "
            f"title_score="
            f"{detector_match['title_score']:.2f} "
            f"channel_score="
            f"{detector_match['channel_score']:.2f} "
            f"context_score="
            f"{detector_match['context_score']:.2f} "
            f"weighted_score="
            f"{detector_match['score']:.2f} "
            f"matched="
            f"{detector_match['matched']}"
        )

        # --------------------------------------------------
        # Authoritative detector-side ad rejection.
        # --------------------------------------------------

        if (
            detector_is_ad
            or
            detector_ad_evidence
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED BEFORE VERIFIER "
                f"(is_ad={detector_is_ad}, "
                f"ad_evidence="
                f"{detector_ad_evidence!r}, "
                f"title={detector_title!r})"
            )

            continue

        # --------------------------------------------------
        # Detector-side Shorts rejection.
        # --------------------------------------------------

        if detector_is_short:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED BEFORE VERIFIER AS SHORT "
                f"title={detector_title!r}"
            )

            continue

        # --------------------------------------------------
        # Full-context verification.
        # --------------------------------------------------

        context_image = (
            _build_youtube_verification_image(
                image,
                box,
                index
            )
        )

        if not context_image:

            continue

        verification = (
            verify_youtube_candidate(
                context_image,
                query,
                index,
                candidate_box=box,
                candidate_title=detector_title,
                candidate_channel=detector_channel,
                candidate_context=detector_context,
                candidate_matches_query=detector_match["matched"],
                candidate_relevance_score=detector_match["score"],
            )
        )

        logging.info(
            f"YouTube candidate {index} "
            "verification: "
            f"valid={verification['valid']} "
            f"is_ad={verification['is_ad']} "
            f"is_short={verification['is_short']} "
            f"matches={verification['matches_query']} "
            f"confidence="
            f"{verification['confidence']:.2f} "
            f"title="
            f"{verification.get('title', '')!r} "
            f"channel="
            f"{verification.get('channel', '')!r}"
        )

        # --------------------------------------------------
        # Never allow verifier to override detector ad
        # evidence.
        # --------------------------------------------------

        # --------------------------------------------------
        # Final ad safety.
        #
        # The verifier can reject an ad, but it cannot
        # override the deterministic ad filter above.
        # --------------------------------------------------

        verifier_is_ad = bool(
            verification.get(
                "is_ad",
                False
            )
        )

        verifier_ad_evidence = str(
            verification.get(
                "ad_evidence",
                ""
            )
        ).strip()

        if verifier_is_ad:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS AD BY VERIFIER."
            )

            continue

        if verifier_ad_evidence:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED: verifier supplied "
                f"ad evidence={verifier_ad_evidence!r}"
            )

            continue

        # --------------------------------------------------
        # Never allow Shorts.
        # --------------------------------------------------

        if verification[
            "is_short"
        ]:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS SHORT BY VERIFIER."
            )

            continue

        # --------------------------------------------------
        # Structural safety fields.
        # --------------------------------------------------

        if verification.get(
            "is_playlist",
            False
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS PLAYLIST."
            )

            continue

        if verification.get(
            "is_standalone_channel_page",
            False
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS STANDALONE CHANNEL PAGE."
            )

            continue

        if verification.get(
            "is_standalone_topic_page",
            False
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS STANDALONE TOPIC PAGE."
            )

            continue

        if verification.get(
            "is_standalone_video_page",
            False
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED AS STANDALONE VIDEO PAGE."
            )

            continue

        if not verification.get(
            "is_video",
            False
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED: verifier says candidate "
                "is not a normal video result."
            )

            continue

        # --------------------------------------------------
        # Final relevance.
        #
        # The detector owns semantic identity and relevance.
        # The verifier owns structural safety only.
        # --------------------------------------------------

        logging.info(
            f"YouTube candidate {index} "
            "FINAL relevance: "
            f"detector="
            f"{detector_match['score']:.2f} "
            f"matched="
            f"{detector_match['matched']}"
        )

        relevance_passed = (
            detector_match["matched"]
        )

        # --------------------------------------------------
        # Final verifier validity.
        # --------------------------------------------------

        if not verification[
            "valid"
        ]:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED VERIFIER INVALID: "
                f"{verification['reason']}"
            )

            continue

        if (
            verification["confidence"]
            <
            YOUTUBE_VERIFY_MIN_CONFIDENCE
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED LOW CONFIDENCE "
                f"{verification['confidence']:.2f}"
            )

            continue

        # --------------------------------------------------
        # Candidate is now verified.
        #
        # The result has already passed:
        #   - detector-side ad rejection
        #   - deterministic relevance
        #   - structural verification
        #   - is_video validation
        #
        # Do not require a second thumbnail detector here.
        # YouTube Music / Topic rows can use thumbnail layouts
        # that the small vision model fails to localize.
        #
        # The click-point helper now derives a conservative point
        # directly from the VERIFIED candidate row.
        # --------------------------------------------------

        screen_box = crop_to_screen_box(
            box,
            vision_info
        )

        if not screen_box:

            logging.info(
                f"YouTube candidate {index}: "
                "candidate screen coordinate "
                "conversion failed."
            )

            continue

        click_point = (
            get_youtube_thumbnail_click_point(
                None,
                screen_box,
                index
            )
        )

        if not click_point:

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED: no safe verified-row "
                "click point."
            )

            continue

        click_x, click_y = click_point

        # --------------------------------------------------
        # Final strict bounds validation.
        # --------------------------------------------------

        if not (
            screen_box["left"]
            <=
            click_x
            <=
            screen_box["right"]
            and
            screen_box["top"]
            <=
            click_y
            <=
            screen_box["bottom"]
        ):

            logging.info(
                f"YouTube candidate {index}: "
                "REJECTED: click point escaped "
                "verified row bounds."
            )

            continue

        logging.info(
            f"YouTube verified row click candidate "
            f"{index}: "
            f"{click_x},{click_y}"
        )

        # --------------------------------------------------
        # Mouse calibration remains zero.
        # --------------------------------------------------

        click_x, click_y = (
            convert_coordinates(
                click_x,
                click_y,
                clicking=True,
                target=target
            )
        )

        #
        # Search-result rows can vertically overlap slightly
        # when the vision model's boxes are imperfect.
        #
        # A thumbnail center can therefore be mathematically
        # inside the accepted row while still being too close
        # to the row above it.
        #
        # Keep the final click point safely inside the lower
        # interior of the VERIFIED candidate.
        # --------------------------------------------------

        candidate_top = int(
            screen_box["top"]
        )

        candidate_bottom = int(
            screen_box["bottom"]
        )

        candidate_height = (
            candidate_bottom
            -
            candidate_top
        )

        if candidate_height > 0:

            safe_click_y = (
                candidate_top
                +
                int(
                    candidate_height
                    *
                    0.45
                )
            )

            original_click_y = click_y

            click_y = max(
                click_y,
                safe_click_y
            )

            click_y = min(
                click_y,
                candidate_bottom - 10
            )

            logging.info(
                f"YouTube final click safety "
                f"candidate {index}: "
                f"y={original_click_y} -> {click_y} "
                f"candidate_vertical="
                f"{candidate_top}-{candidate_bottom} "
                f"safe_y={safe_click_y}"
            )

        # --------------------------------------------------
        # Mouse calibration remains zero.
        # --------------------------------------------------

        click_x, click_y = (
            convert_coordinates(
                click_x,
                click_y,
                clicking=True,
                target=target
            )
        )

        result = {

            "found":
                True,

            "confidence":
                verification[
                    "confidence"
                ],

            "left":
                screen_box["left"],

            "top":
                screen_box["top"],

            "right":
                screen_box["right"],

            "bottom":
                screen_box["bottom"],

            "description":
                (
                    "verified organic YouTube "
                    f"result #{index} for {query}"
                ),

            "query":
                query,

            "verified":
                True,

            "is_ad":
                False,

            "is_short":
                False,

            "matches_query":
                True,

            "title":
                detector_title,

            "channel":
                detector_channel,

            "context_text":
                detector_context,

            "deterministic_match_score":
                detector_match["score"],

            "thumbnail":
                {
                    "left":
                        screen_box["left"],

                    "top":
                        screen_box["top"],

                    "right":
                        screen_box["right"],

                    "bottom":
                        screen_box["bottom"]
                },

            "click_x":
                click_x,

            "click_y":
                click_y
        }

        logging.info(
            "VERIFIED YOUTUBE RESULT: "
            f"{result['description']}"
        )

        logging.info(
            "Verified full-screen bounding box: "
            f"{result['left']},"
            f"{result['top']},"
            f"{result['right']},"
            f"{result['bottom']}"
        )

        logging.info(
            "Verified YouTube title: "
            f"{result['title']!r}"
        )

        logging.info(
            "Verified YouTube channel: "
            f"{result['channel']!r}"
        )

        logging.info(
            "Verified YouTube context: "
            f"{result['context_text']!r}"
        )

        logging.info(
            "Verified YouTube thumbnail box: "
            f"{result['thumbnail']['left']},"
            f"{result['thumbnail']['top']},"
            f"{result['thumbnail']['right']},"
            f"{result['thumbnail']['bottom']}"
        )

        logging.info(
            "Verified YouTube thumbnail click: "
            f"{click_x},{click_y}"
        )

        return result

    return {

        "found":
            False,

        "confidence":
            0.0,

        "description":
            (
                "No YouTube candidate passed "
                "context verification and thumbnail "
                "safety checks"
            ),

        "query":
            query,

        "verified":
            False
    }


# ==========================================================
# Find Screen Target
# ==========================================================

def find_screen_target(
    target
):

    if is_youtube_target(
        target
    ):

        return find_first_verified_youtube_result(
            target
        )

    return _find_screen_target_generic(
        target
    )


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

        if (
            target
            and
            is_youtube_target(
                target
            )
        ):

            x += YOUTUBE_CLICK_BIAS_X

            y += YOUTUBE_CLICK_BIAS_Y

    screen_width, screen_height = (
        pyautogui.size()
    )

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
# Bounding Box -> Click Point
# ==========================================================

def get_center(
    result,
    target=None
):

    left = int(
        result["left"]
    )

    top = int(
        result["top"]
    )

    right = int(
        result["right"]
    )

    bottom = int(
        result["bottom"]
    )

    width = max(
        1,
        right - left
    )

    height = max(
        1,
        bottom - top
    )

    x = (
        left
        +
        right
    ) // 2

    y = (
        top
        +
        bottom
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

    # ------------------------------------------------------
    # YouTube verified result:
    # move to verified thumbnail center.
    # ------------------------------------------------------

    if (
        is_youtube_target(target)
        and
        result.get(
            "thumbnail"
        )
    ):

        thumbnail = result[
            "thumbnail"
        ]

        mouse_x = (
            thumbnail["left"]
            +
            thumbnail["right"]
        ) // 2

        mouse_y = (
            thumbnail["top"]
            +
            thumbnail["bottom"]
        ) // 2

    else:

        vision_x, vision_y = get_center(
            result,
            target=target
        )

        mouse_x, mouse_y = (
            convert_coordinates(
                vision_x,
                vision_y,
                clicking=False,
                target=target
            )
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


# ==========================================================
# JARVIS FAST LOCAL YOUTUBE SAFETY HELPERS
# ==========================================================

def youtube_region_signature(
    screen_box,
    size=24
):
    """
    Cheap local screenshot fingerprint.

    No Ollama.
    No vision model.
    """

    try:

        screenshot = pyautogui.screenshot()

        left = max(
            0,
            int(screen_box.get("left", 0))
        )

        top = max(
            0,
            int(screen_box.get("top", 0))
        )

        right = min(
            screenshot.width,
            int(screen_box.get("right", 0))
        )

        bottom = min(
            screenshot.height,
            int(screen_box.get("bottom", 0))
        )

        if (
            right <= left
            or
            bottom <= top
        ):

            return None

        crop = screenshot.crop(
            (
                left,
                top,
                right,
                bottom
            )
        )

        crop = crop.convert(
            "L"
        )

        crop = crop.resize(
            (
                size,
                size
            )
        )

        return tuple(
            int(pixel // 8)
            for pixel in crop.getdata()
        )

    except Exception as exc:

        logging.warning(
            "YouTube region signature failed: %s",
            exc
        )

        return None


def youtube_region_difference(
    first,
    second
):
    if not first or not second:

        return 1.0

    if len(first) != len(second):

        return 1.0

    changed = 0

    total = len(first)

    for a, b in zip(
        first,
        second
    ):

        if abs(
            a - b
        ) > 1:

            changed += 1

    return (
        changed
        /
        max(
            1,
            total
        )
    )


def youtube_fast_pre_click_check(
    screen_box,
    delay=0.05,
    max_difference=0.035
):
    """
    Fast local pre-click safety gate.

    Takes two tiny screenshots of the verified YouTube
    result region.

    If the region is stable, the click is allowed.

    If it is moving, the caller falls back to the existing
    expensive full YouTube verification pipeline.
    """

    if not screen_box:

        logging.warning(
            "YouTube fast pre-click verification rejected: "
            "missing screen region."
        )

        return False

    first = youtube_region_signature(
        screen_box
    )

    if not first:

        logging.warning(
            "YouTube fast pre-click verification rejected: "
            "first capture failed."
        )

        return False

    if delay > 0:

        time.sleep(
            delay
        )

    second = youtube_region_signature(
        screen_box
    )

    if not second:

        logging.warning(
            "YouTube fast pre-click verification rejected: "
            "second capture failed."
        )

        return False

    difference = (
        youtube_region_difference(
            first,
            second
        )
    )

    logging.info(
        "YouTube fast pre-click visual difference: %.3f",
        difference
    )

    if difference > max_difference:

        logging.warning(
            "YouTube fast pre-click verification FAILED: "
            "verified region changed."
        )

        return False

    logging.info(
        "YouTube fast pre-click verification PASSED."
    )

    return True


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

    # ------------------------------------------------------
    # YouTube:
    #
    # Use ONLY independently verified thumbnail
    # click point.
    # ------------------------------------------------------

    if (
        is_youtube_target(target)
        and
        result.get(
            "thumbnail"
        )
    ):

        mouse_x = int(
            result.get(
                "click_x"
            )
        )

        mouse_y = int(
            result.get(
                "click_y"
            )
        )

        thumbnail = result[
            "thumbnail"
        ]

        logging.info(
            "Using independently verified "
            "YouTube thumbnail."
        )

        logging.info(
            "Thumbnail screen box: "
            f"{thumbnail['left']},"
            f"{thumbnail['top']},"
            f"{thumbnail['right']},"
            f"{thumbnail['bottom']}"
        )

    else:

        vision_x, vision_y = get_center(
            result,
            target=target
        )

        mouse_x, mouse_y = (
            convert_coordinates(
                vision_x,
                vision_y,
                clicking=True,
                target=target
            )
        )


    # --------------------------------------------------
    # FAST PRE-CLICK YOUTUBE VERIFICATION
    #
    # The expensive YouTube detector/verifier has already
    # confirmed this result.
    #
    # Instead of running Ollama a second time, perform a
    # tiny local visual-stability check immediately before
    # the physical click.
    #
    # If the region changed, fall back to the existing
    # full YouTube verification pipeline.
    # --------------------------------------------------

    if is_youtube_target(
        target
    ):

        logging.info(
            "YouTube fast pre-click verification starting."
        )

        verified_region = result.get(
            "thumbnail"
        )

        if not verified_region:

            logging.warning(
                "YouTube fast pre-click verification rejected: "
                "missing verified result region."
            )

            return {
                "success":
                    False,

                "confidence":
                    0.0,

                "message":
                    "YouTube click rejected: "
                    "missing verified result region."
            }


        # --------------------------------------------------
        # FAST LOCAL CHECK
        # --------------------------------------------------

        stable = (
            youtube_fast_pre_click_check(
                verified_region
            )
        )


        # --------------------------------------------------
        # FAST PATH
        # --------------------------------------------------

        if stable:

            fresh_click_x = result.get(
                "click_x"
            )

            fresh_click_y = result.get(
                "click_y"
            )

            if (
                fresh_click_x is None
                or
                fresh_click_y is None
            ):

                logging.warning(
                    "YouTube fast pre-click verification "
                    "rejected: missing verified click point."
                )

                return {
                    "success":
                        False,

                    "confidence":
                        0.0,

                    "message":
                        "No verified YouTube click point available."
                }


            mouse_x, mouse_y = (
                convert_coordinates(
                    fresh_click_x,
                    fresh_click_y,
                    clicking=True,
                    target=target
                )
            )

            logging.info(
                "YouTube fast pre-click verification "
                "PASSED. Using verified click="
                f"{mouse_x},{mouse_y}"
            )


        # --------------------------------------------------
        # SLOW FALLBACK ONLY IF REGION CHANGED
        # --------------------------------------------------

        else:

            logging.warning(
                "YouTube result changed immediately "
                "before click."
            )

            logging.warning(
                "Running full YouTube re-verification."
            )

            fresh_result = (
                find_first_verified_youtube_result(
                    target
                )
            )

            if not fresh_result.get(
                "found",
                False
            ):

                logging.warning(
                    "YouTube full re-verification failed."
                )

                logging.warning(
                    "CLICK ABORTED."
                )

                return {
                    "success":
                        False,

                    "confidence":
                        0.0,

                    "message":
                        "YouTube click aborted because "
                        "the result could not be re-verified."
                }


            if not fresh_result.get(
                "verified",
                False
            ):

                logging.warning(
                    "YouTube full re-verification "
                    "rejected the result."
                )

                logging.warning(
                    "CLICK ABORTED."
                )

                return {
                    "success":
                        False,

                    "confidence":
                        0.0,

                    "message":
                        "YouTube result failed final "
                        "safety verification."
                }


            fresh_click_x = fresh_result.get(
                "click_x"
            )

            fresh_click_y = fresh_result.get(
                "click_y"
            )

            if (
                fresh_click_x is None
                or
                fresh_click_y is None
            ):

                logging.warning(
                    "YouTube full re-verification "
                    "returned no safe click point."
                )

                logging.warning(
                    "CLICK ABORTED."
                )

                return {
                    "success":
                        False,

                    "confidence":
                        0.0,

                    "message":
                        "No safe YouTube click point "
                        "was available."
                }


            mouse_x, mouse_y = (
                convert_coordinates(
                    fresh_click_x,
                    fresh_click_y,
                    clicking=True,
                    target=target
                )
            )

            logging.info(
                "YouTube full re-verification PASSED. "
                "Fresh click="
                f"{mouse_x},{mouse_y}"
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

    time.sleep(
        0.10
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

    if (
        is_youtube_target(target)
        and
        result.get(
            "thumbnail"
        )
    ):

        mouse_x = int(
            result["click_x"]
        )

        mouse_y = int(
            result["click_y"]
        )

    else:

        vision_x, vision_y = get_center(
            result,
            target=target
        )

        mouse_x, mouse_y = (
            convert_coordinates(
                vision_x,
                vision_y,
                clicking=True,
                target=target
            )
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

    if (
        is_youtube_target(target)
        and
        result.get(
            "thumbnail"
        )
    ):

        mouse_x = int(
            result["click_x"]
        )

        mouse_y = int(
            result["click_y"]
        )

    else:

        vision_x, vision_y = get_center(
            result,
            target=target
        )

        mouse_x, mouse_y = (
            convert_coordinates(
                vision_x,
                vision_y,
                clicking=True,
                target=target
            )
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

        keys = keys.split(
            "+"
        )

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
        start,
        target=source
    )

    ex, ey = get_center(
        end,
        target=destination
    )

    sx, sy = (
        convert_coordinates(
            sx,
            sy,
            clicking=True,
            target=source
        )
    )

    ex, ey = (
        convert_coordinates(
            ex,
            ey,
            clicking=True,
            target=destination
        )
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
# Wait For Change
# ==========================================================

def wait_for_change(
    timeout=5.0,
    interval=0.25
):

    start = time.time()

    try:

        baseline = screen_fingerprint(
            pyautogui.screenshot()
        )

    except Exception:

        return False

    if not baseline:

        return False

    while (
        time.time()
        -
        start
        <
        timeout
    ):

        time.sleep(
            interval
        )

        try:

            current = screen_fingerprint(
                pyautogui.screenshot()
            )

        except Exception:

            continue

        if (
            current
            and
            current != baseline
        ):

            return True

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
        time.time()
        -
        start
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

    elif "status" in command:

        result = {

            "success":
                True,

            "status":
                jarvis_status()
        }

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

    elif command.startswith(
        "scroll"
    ):

        result = scroll_screen(
            command
        )

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

        pyautogui.press(
            "escape"
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

        "youtube_verify_model":
            YOUTUBE_VERIFY_MODEL,

        "youtube_thumbnail_model":
            YOUTUBE_THUMBNAIL_MODEL,

        "vision_num_predict":
            VISION_NUM_PREDICT,

        "verify_num_predict":
            VERIFY_NUM_PREDICT,

        "youtube_candidate_num_predict":
            YOUTUBE_CANDIDATE_NUM_PREDICT,

        "youtube_verify_num_predict":
            YOUTUBE_VERIFY_NUM_PREDICT,

        "youtube_thumbnail_num_predict":
            YOUTUBE_THUMBNAIL_NUM_PREDICT,

        "page_stable_timeout":
            PAGE_STABLE_TIMEOUT,

        "page_stable_interval":
            PAGE_STABLE_INTERVAL,

        "max_vision_width":
            MAX_VISION_WIDTH,

        "min_confidence":
            MIN_CONFIDENCE,

        "youtube_candidate_limit":
            YOUTUBE_CANDIDATE_LIMIT,

        "youtube_verify_limit":
            YOUTUBE_VERIFY_LIMIT,

        "youtube_verify_min_confidence":
            YOUTUBE_VERIFY_MIN_CONFIDENCE,

        "youtube_thumbnail_min_confidence":
            YOUTUBE_THUMBNAIL_MIN_CONFIDENCE,

        "youtube_max_candidate_height":
            YOUTUBE_MAX_CANDIDATE_HEIGHT,

        "youtube_max_candidate_height_ratio":
            YOUTUBE_MAX_CANDIDATE_HEIGHT_RATIO,

        "youtube_min_candidate_width":
            YOUTUBE_MIN_CANDIDATE_WIDTH,

        "youtube_title_weight":
            YOUTUBE_TITLE_WEIGHT,

        "youtube_channel_weight":
            YOUTUBE_CHANNEL_WEIGHT,

        "youtube_context_weight":
            YOUTUBE_CONTEXT_WEIGHT,

        "youtube_min_relevance_score":
            YOUTUBE_MIN_RELEVANCE_SCORE,

        "youtube_min_field_match":
            YOUTUBE_MIN_FIELD_MATCH,

        "mouse_offset_x":
            MOUSE_OFFSET_X,

        "mouse_offset_y":
            MOUSE_OFFSET_Y,

        "click_bias_x":
            CLICK_BIAS_X,

        "click_bias_y":
            CLICK_BIAS_Y,

        "youtube_click_bias_x":
            YOUTUBE_CLICK_BIAS_X,

        "youtube_click_bias_y":
            YOUTUBE_CLICK_BIAS_Y
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