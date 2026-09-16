import base64
import json
import logging
import httpx
from PIL import Image
import io

logging.basicConfig(level=logging.INFO, format="[JARVIS] %(message)s")

def locate_target_on_screen(image_bytes: bytes, target_description: str) -> dict:
    img = Image.open(io.BytesIO(image_bytes))
    orig_w, orig_h = img.size
    
    img_resized = img.resize((1280, 720))
    buffered = io.BytesIO()
    img_resized.save(buffered, format="JPEG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    prompt = f"""Locate the video thumbnail or title matching '{target_description}' or 'wifiskeleton' on this screen.

Return ONLY a JSON object:
{{
  "found": true,
  "confidence": 0.90,
  "box_2d": [ymin, xmin, ymax, xmax],
  "description": "Selected video title/thumbnail"
}}
Coordinates are normalized 0-1000 integers.
If not found, return {{"found": false, "confidence": 0.0, "box_2d": [], "description": "not found"}}
"""

    payload = {
        "model": "qwen2.5vl:3b",
        "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
        "stream": False,
        "format": "json"
    }

    try:
        res = httpx.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=30.0)
        res.raise_for_status()
        data = res.json()["message"]["content"]
        result = json.loads(data)

        if result.get("found"):
            box = result.get("box_2d", [0, 0, 0, 0])
            ymin, xmin, ymax, xmax = box
            screen_left = int((xmin / 1000.0) * orig_w)
            screen_top = int((ymin / 1000.0) * orig_h)
            screen_right = int((xmax / 1000.0) * orig_w)
            screen_bottom = int((ymax / 1000.0) * orig_h)
            
            click_x = (screen_left + screen_right) // 2
            click_y = (screen_top + screen_bottom) // 2

            return {
                "success": True,
                "confidence": result.get("confidence", 0.0),
                "x": click_x,
                "y": click_y,
                "box": [screen_left, screen_top, screen_right, screen_bottom],
                "message": f"Located '{target_description}' via Vision"
            }
    except Exception as e:
        logging.error(f"Vision detection error: {e}")

    return {"success": False, "confidence": 0.0, "message": f"Target '{target_description}' not found on screen."}

def click_screen_target(target: str) -> dict:
    from browser_controller import click_dom_element, capture_screenshot, click_at_coords
    
    # Strategy 1: Fast Playwright DOM Selector
    if click_dom_element(target):
        return {"success": True, "message": f"Clicked '{target}' via DOM Selector"}
        
    # Strategy 2: Qwen2.5-VL Vision Fallback
    screenshot = capture_screenshot()
    if not screenshot:
        return {"success": False, "message": "Failed to capture screenshot."}
    
    detection = locate_target_on_screen(screenshot, target)
    if detection["success"]:
        click_at_coords(detection["x"], detection["y"])
        return detection
        
    return {"success": False, "message": f"Target '{target}' not found on screen."}
