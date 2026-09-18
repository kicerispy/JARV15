from pathlib import Path
import shutil

path = Path("screen_vision.py")
backup = Path("screen_vision.py.before_google_title_refiner_safe.py")

text = path.read_text(encoding="utf-8")
shutil.copy2(path, backup)

if "from PIL import Image" not in text:
    text = text.replace(
        "import pyautogui\n",
        "import pyautogui\nfrom PIL import Image\n",
        1,
    )

if "def refine_google_result_title(" not in text:
    marker = "def _find_screen_target_generic(\n"
    insert_at = text.find(marker)

    if insert_at == -1:
        raise SystemExit(
            "ERROR: _find_screen_target_generic() not found"
        )

    helper = '''
# ==========================================================
# Google Result Title Refinement
# ==========================================================

def refine_google_result_title(
    vision_file,
    crop_result,
    target,
):
    try:
        source = Image.open(
            vision_file
        ).convert(
            "RGB"
        )

        left = max(
            0,
            int(crop_result.get("left", 0)),
        )

        top = max(
            0,
            int(crop_result.get("top", 0)),
        )

        right = min(
            source.width,
            int(crop_result.get("right", source.width)),
        )

        bottom = min(
            source.height,
            int(crop_result.get("bottom", source.height)),
        )

        if right <= left or bottom <= top:
            return None

        region = source.crop(
            (left, top, right, bottom)
        )

        region.save(
            VISION_CROP_FILE
        )

        prompt = f"""
You are JARVIS Google search-result click localization.

This image contains ONE already-selected Google search result row.

Requested result:
{target}

Find ONLY the PRIMARY CLICKABLE SEARCH RESULT TITLE/LINK.

Do NOT return the entire result row.
Do NOT return the snippet.
Do NOT return author or artist names inside the snippet.
Do NOT return metadata.
Do NOT return secondary links.

Return a TIGHT bounding box around the visible primary clickable title/link.

For example, if the row contains:
Wifiskeleton
Jeremiah Justin Simms
Wikipedia

the correct target is the Wifiskeleton title.

Return ONLY JSON:
{{
  "found": true,
  "confidence": 0.0,
  "box_2d": [top, left, bottom, right],
  "description": "primary clickable Google result title"
}}
"""

        response = vision_chat(
            VISION_MODEL,
            [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": (
                        "Locate ONLY the primary clickable title for: "
                        f"{target}"
                    ),
                    "images": [
                        VISION_CROP_FILE
                    ],
                },
            ],
            json_mode=True,
            num_predict=64,
        )

        raw = get_response_text(
            response
        )

        if not raw:
            return None

        logging.info(
            "GOOGLE TITLE REFINEMENT RAW RESPONSE: %s",
            raw,
        )

        data = extract_json(
            raw
        )

        if not isinstance(
            data,
            dict,
        ):
            return None

        box = data.get(
            "box_2d"
        )

        if not isinstance(
            box,
            (list, tuple),
        ) or len(box) < 4:
            return None

        try:
            rel_top = float(box[0])
            rel_left = float(box[1])
            rel_bottom = float(box[2])
            rel_right = float(box[3])
        except (
            TypeError,
            ValueError,
        ):
            return None

        crop_width = max(
            1,
            right - left,
        )

        crop_height = max(
            1,
            bottom - top,
        )

        refined = {
            "found": bool(
                data.get(
                    "found",
                    True,
                )
            ),
            "confidence": float(
                data.get(
                    "confidence",
                    0.0,
                )
            ),
            "left": int(
                left +
                (rel_left / 1000.0) *
                crop_width
            ),
            "top": int(
                top +
                (rel_top / 1000.0) *
                crop_height
            ),
            "right": int(
                left +
                (rel_right / 1000.0) *
                crop_width
            ),
            "bottom": int(
                top +
                (rel_bottom / 1000.0) *
                crop_height
            ),
            "description": data.get(
                "description",
                "primary clickable Google result title",
            ),
        }

        if not refined["found"]:
            return None

        if refined["right"] <= refined["left"]:
            return None

        if refined["bottom"] <= refined["top"]:
            return None

        logging.info(
            "GOOGLE TITLE REFINEMENT BOX: "
            f"left={refined['left']} "
            f"top={refined['top']} "
            f"right={refined['right']} "
            f"bottom={refined['bottom']} "
            f"confidence={refined['confidence']}"
        )

        return refined

    except Exception as e:
        logging.warning(
            "Google title refinement failed: %s",
            e,
        )
        return None


'''

    text = (
        text[:insert_at]
        + helper
        + text[insert_at:]
    )

anchor = '''        screen_box = crop_to_screen_box(
            crop_result,
            vision_info
        )

        if not screen_box:
'''

refinement = '''        # --------------------------------------------------------
        # Refine Google result row to the actual clickable title.
        # --------------------------------------------------------

        target_lower = str(
            target or ""
        ).lower()

        if (
            "organic google result" in target_lower
            or "google result" in target_lower
        ) and crop_result.get(
            "found",
            False
        ):

            refined_result = refine_google_result_title(
                vision_file,
                crop_result,
                target
            )

            if refined_result:
                refined_screen_box = crop_to_screen_box(
                    refined_result,
                    vision_info
                )

                if refined_screen_box:
                    logging.info(
                        "JARVIS: Using refined Google clickable-title box."
                    )

                    crop_result = refined_result
                    screen_box = refined_screen_box

'''

if refinement not in text:
    if anchor not in text:
        shutil.copy2(backup, path)
        raise SystemExit(
            "ERROR: screen_box insertion point not found"
        )

    text = text.replace(
        anchor,
        anchor.replace(
            "        if not screen_box:\n",
            "",
        )
        + refinement
        + "        if not screen_box:\n",
        1,
    )

path.write_text(
    text,
    encoding="utf-8",
)

print("PATCH_OK")