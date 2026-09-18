from pathlib import Path
import re

path = Path("screen_vision.py")
text = path.read_text(encoding="utf-8")

# ------------------------------------------------------------
# Insert generic vision candidate validator
# ------------------------------------------------------------

helper = r'''
# ==========================================================
# Generic Vision Candidate Validation
# ==========================================================

def validate_generic_vision_candidate(
    target,
    result,
    width,
    height
):
    """
    Reject vision results that are geometrically implausible
    for the requested UI target.

    This is intentionally deterministic. A high confidence
    score from the vision model does NOT override bad geometry.
    """

    if not isinstance(result, dict):
        return {
            "valid": False,
            "reason": "result is not a dictionary"
        }

    if not result.get("found", False):
        return {
            "valid": False,
            "reason": "vision reported target not found"
        }

    try:
        left = int(result.get("left", 0))
        top = int(result.get("top", 0))
        right = int(result.get("right", 0))
        bottom = int(result.get("bottom", 0))
    except Exception:
        return {
            "valid": False,
            "reason": "invalid bounding box values"
        }

    box_width = right - left
    box_height = bottom - top

    if box_width <= 0 or box_height <= 0:
        return {
            "valid": False,
            "reason": "invalid bounding box dimensions"
        }

    if width <= 0 or height <= 0:
        return {
            "valid": False,
            "reason": "invalid screen dimensions"
        }

    target_text = str(target).lower().strip()

    width_ratio = box_width / float(width)
    height_ratio = box_height / float(height)
    left_ratio = left / float(width)
    top_ratio = top / float(height)
    right_ratio = right / float(width)
    bottom_ratio = bottom / float(height)

    center_x_ratio = (
        (left + right) / 2.0
    ) / float(width)

    center_y_ratio = (
        (top + bottom) / 2.0
    ) / float(height)

    # ------------------------------------------------------
    # Universal sanity checks
    # ------------------------------------------------------

    # A normal UI control should not cover almost the
    # entire screen unless the target explicitly describes
    # a large region.
    large_region_terms = [
        "screen",
        "window",
        "page",
        "desktop",
        "browser window",
        "content area",
    ]

    is_large_region_request = any(
        term in target_text
        for term in large_region_terms
    )

    if not is_large_region_request:
        if width_ratio > 0.85 and height_ratio > 0.45:
            return {
                "valid": False,
                "reason":
                    f"candidate is implausibly large "
                    f"({width_ratio:.2f}w x {height_ratio:.2f}h)"
            }

    # Reject almost-screen-height thin false positives.
    if (
        height_ratio > 0.65
        and
        width_ratio < 0.20
    ):
        return {
            "valid": False,
            "reason":
                "candidate is an implausibly tall narrow region"
        }

    # Reject microscopic boxes that are unlikely to be a
    # usable clickable UI element.
    if box_width < 5 or box_height < 5:
        return {
            "valid": False,
            "reason":
                "candidate is too small"
        }

    # ------------------------------------------------------
    # Address bar
    # ------------------------------------------------------

    if (
        "address bar" in target_text
        or
        "url bar" in target_text
        or
        "omnibox" in target_text
        or
        "browser address" in target_text
    ):
        # Chrome/browser address bars are near the upper
        # portion of the screen and normally very wide.
        if top_ratio > 0.20:
            return {
                "valid": False,
                "reason":
                    f"address bar candidate is too low "
                    f"(top={top_ratio:.2f})"
            }

        if width_ratio < 0.25:
            return {
                "valid": False,
                "reason":
                    f"address bar candidate is too narrow "
                    f"(width={width_ratio:.2f})"
            }

        if height_ratio > 0.15:
            return {
                "valid": False,
                "reason":
                    f"address bar candidate is too tall "
                    f"(height={height_ratio:.2f})"
            }

    # ------------------------------------------------------
    # Chrome menu / browser menu
    # ------------------------------------------------------

    if (
        "chrome menu" in target_text
        or
        "browser menu" in target_text
        or
        "three dot menu" in target_text
        or
        "three-dot menu" in target_text
        or
        "menu button" in target_text
    ):
        # Browser menu controls should be small and near the
        # upper-right portion of the screen.
        if top_ratio > 0.20:
            return {
                "valid": False,
                "reason":
                    f"browser menu candidate is too low "
                    f"(top={top_ratio:.2f})"
            }

        if center_x_ratio < 0.75:
            return {
                "valid": False,
                "reason":
                    f"browser menu candidate is not far enough right "
                    f"(center_x={center_x_ratio:.2f})"
            }

        if width_ratio > 0.15 or height_ratio > 0.15:
            return {
                "valid": False,
                "reason":
                    "browser menu candidate is too large"
            }

    # ------------------------------------------------------
    # Search box
    # ------------------------------------------------------

    if (
        "search box" in target_text
        or
        "search bar" in target_text
        or
        "search field" in target_text
    ):
        if width_ratio < 0.15:
            return {
                "valid": False,
                "reason":
                    "search box candidate is too narrow"
            }

    # ------------------------------------------------------
    # Generic top-bar controls
    # ------------------------------------------------------

    top_bar_terms = [
        "toolbar",
        "tab bar",
        "title bar",
        "navigation bar",
        "nav bar",
        "browser toolbar",
    ]

    if any(
        term in target_text
        for term in top_bar_terms
    ):
        if top_ratio > 0.25:
            return {
                "valid": False,
                "reason":
                    "top-bar target candidate is too low"
            }

    # ------------------------------------------------------
    # Generic bottom-bar controls
    # ------------------------------------------------------

    bottom_bar_terms = [
        "taskbar",
        "dock",
        "status bar",
    ]

    if any(
        term in target_text
        for term in bottom_bar_terms
    ):
        if bottom_ratio < 0.75:
            return {
                "valid": False,
                "reason":
                    "bottom-bar target candidate is too high"
            }

    return {
        "valid": True,
        "reason": "geometry passed"
    }


'''

marker = "# ==========================================================\n# Locate Target On Screen"

if helper.strip() not in text:
    if marker not in text:
        raise SystemExit(
            "PATCH FAILED: could not find insertion marker."
        )

    text = text.replace(
        marker,
        helper.rstrip() + "\n\n\n" + marker,
        1
    )

# ------------------------------------------------------------
# Locate generic target function
# ------------------------------------------------------------

match = re.search(
    r'(?ms)^def _find_screen_target_generic\(.*?(?=^def find_screen_target\()',
    text
)

if not match:
    raise SystemExit(
        "PATCH FAILED: could not find _find_screen_target_generic()."
    )

func = match.group(0)

# ------------------------------------------------------------
# Find the cleaned result assignment used by the current
# retry implementation.
# ------------------------------------------------------------

clean_pattern = r'(?P<indent>\s*)crop_result\s*=\s*clean_location\(\s*result,\s*screen_width,\s*screen_height\s*\)'

clean_match = re.search(
    clean_pattern,
    func
)

if not clean_match:
    # Try common alternate variable names.
    clean_pattern_alt = (
        r'(?P<indent>\s*)'
        r'(?P<var>result|crop_result)\s*=\s*'
        r'clean_location\(\s*'
        r'(?P<input>result|crop_result),\s*'
        r'(?P<width>[^,\n]+),\s*'
        r'(?P<height>[^\)\n]+)\s*\)'
    )

    clean_match = re.search(
        clean_pattern_alt,
        func
    )

    if not clean_match:
        raise SystemExit(
            "PATCH FAILED: could not find clean_location() inside "
            "_find_screen_target_generic()."
        )

    var = clean_match.group("var")
    indent = clean_match.group("indent")
    width_expr = clean_match.group("width").strip()
    height_expr = clean_match.group("height").strip()

    validation_block = f'''
{indent}validation = validate_generic_vision_candidate(
{indent}    target,
{indent}    {var},
{indent}    {width_expr},
{indent}    {height_expr}
{indent})
{indent}
{indent}if not validation["valid"]:
{indent}    logging.warning(
{indent}        "Vision candidate rejected: "
{indent}        f"{{validation['reason']}}"
{indent}    )
{indent}    {var}["found"] = False
{indent}    {var}["validation_reason"] = validation["reason"]
'''

    insert_at = clean_match.end()

    func = (
        func[:insert_at]
        +
        validation_block
        +
        func[insert_at:]
    )

else:
    indent = clean_match.group("indent")

    validation_block = f'''
{indent}validation = validate_generic_vision_candidate(
{indent}    target,
{indent}    crop_result,
{indent}    screen_width,
{indent}    screen_height
{indent})
{indent}
{indent}if not validation["valid"]:
{indent}    logging.warning(
{indent}        "Vision candidate rejected: "
{indent}        f"{{validation['reason']}}"
{indent}    )
{indent}    crop_result["found"] = False
{indent}    crop_result["validation_reason"] = validation["reason"]
'''

    insert_at = clean_match.end()

    func = (
        func[:insert_at]
        +
        validation_block
        +
        func[insert_at:]
    )

# ------------------------------------------------------------
# Replace generic function in source
# ------------------------------------------------------------

text = (
    text[:match.start()]
    +
    func
    +
    text[match.end():]
)

path.write_text(
    text,
    encoding="utf-8"
)

print("Generic vision candidate validation installed.")
