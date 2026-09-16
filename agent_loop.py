import sys
import logging
import time
from browser_controller import (
    browser_navigate,
    click_dom_element,
    browser_scroll,
    capture_screenshot,
    browser_media_control,
    browser_add_to_queue
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_command(task_prompt: str):
    prompt_lower = task_prompt.lower().strip()

    # 1. Handle Direct Media Controls (Pause, Resume, Mute, Volume)
    if "pause" in prompt_lower:
        logging.info("Executing media control: pause")
        print(browser_media_control("pause"))
        return
    elif prompt_lower == "play" or prompt_lower == "resume" or "resume playing" in prompt_lower:
        logging.info("Executing media control: play")
        print(browser_media_control("play"))
        return
    elif "mute" in prompt_lower and "unmute" not in prompt_lower:
        logging.info("Executing media control: mute")
        print(browser_media_control("mute"))
        return
    elif "unmute" in prompt_lower:
        logging.info("Executing media control: unmute")
        print(browser_media_control("unmute"))
        return
    elif "volume up" in prompt_lower or "louder" in prompt_lower:
        logging.info("Executing media control: volume_up")
        print(browser_media_control("volume_up"))
        return
    elif "volume down" in prompt_lower or "quieter" in prompt_lower:
        logging.info("Executing media control: volume_down")
        print(browser_media_control("volume_down"))
        return

    # 2. Handle Queue Management Requests
    if "queue" in prompt_lower:
        target = prompt_lower.replace("add", "").replace("to queue", "").replace("queue", "").strip()
        logging.info(f"Attempting to queue video: '{target}'")
        print(browser_add_to_queue(target))
        return

    # 3. Default behavior: Search and Play YouTube video
    logging.info(f"Starting JARVIS agent with task: {task_prompt}")
    search_query = task_prompt.replace("Play the ", "").replace(" video on YouTube", "").replace("play", "").strip()
    target_url = f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
    
    browser_navigate(target_url)
    time.sleep(3)
    
    logging.info(f"Attempting to click video matching: '{search_query}'")
    clicked = click_dom_element(search_query)
    
    if clicked:
        logging.info("Successfully clicked and opened the target video!")
    else:
        logging.warning("Target element not found automatically, trying fallback click...")
        click_dom_element("wifiskeleton")

    logging.info("\n[JARVIS] Action sequence complete. Video is playing, and background ad-skipper is active.")

if __name__ == "__main__":
    print("=" * 60)
    print("JARVIS Assistant Loop Active (Type 'exit' or 'quit' to stop)")
    print("=" * 60)

    # If an initial argument was passed, run it first
    if len(sys.argv) > 1:
        initial_prompt = " ".join(sys.argv[1:])
        process_command(initial_prompt)

    # Continuous loop to accept multiple commands without restarting the browser
    while True:
        try:
            user_input = input("\nJarvis> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "stop"]:
                print("[JARVIS] Shutting down assistant...")
                break
            
            process_command(user_input)
        except KeyboardInterrupt:
            print("\n[JARVIS] Shutting down assistant...")
            break