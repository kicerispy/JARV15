from ollama import chat
import json
import re


MODEL = "gemma4:e2b"


# ==================================================
# Utility helpers
# ==================================================

def contains_any(text, phrases):

    text = text.lower()

    return any(
        phrase in text
        for phrase in phrases
    )


def clean_text(text):

    text = (
        text
        .strip()
        .lower()
    )

    # Normalize common punctuation from Whisper.
    text = re.sub(
        r"[,\.\!\?]+$",
        "",
        text
    )

    # Normalize repeated whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ==================================================
# Main compatibility helpers
# ==================================================

def normalize_command(text):
    if not text:
        return ""
    text = str(text).strip()
    text = text.rstrip(".,!?")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_cancel_command(text):
    normalized = normalize_command(text).lower()
    if not normalized:
        return False
    return normalized in {
        "stop",
        "stop talking",
        "stop speaking",
        "cancel",
        "cancel that",
        "cancel it",
        "never mind",
        "nevermind",
        "that's enough",
        "thats enough",
        "enough",
    }


def is_end_conversation_command(text):
    normalized = normalize_command(text).lower()
    if not normalized:
        return False
    return normalized in {
        "go to sleep",
        "go back to sleep",
        "sleep",
        "to sleep",
        "back to sleep",
        "go sleep",
        "end conversation",
        "end the conversation",
        "conversation off",
        "stop listening",
        "stop listening to me",
        "that's all",
        "thats all",
        "we're done",
        "were done",
        "we are done",
        "goodbye jarvis",
    }


# ==================================================
# Conversation classification
# ==================================================

def looks_like_conversation(text):

    normalized = clean_text(
        text
    )

    if not normalized:
        return False


    # --------------------------------------------------
    # Obvious conversational phrases
    # --------------------------------------------------

    conversational_phrases = {

        "alright",
        "all right",
        "okay",
        "ok",
        "got it",
        "understood",
        "thanks",
        "thank you",
        "thank you jarvis",
        "cool",
        "nice",
        "great",
        "perfect",
        "interesting",
        "that's interesting",
        "thats interesting",
        "very interesting",
        "sounds good",
        "good",
        "awesome",
        "sure",
        "yes",
        "yeah",
        "yep",
        "no",
        "nope",
        "why",
        "how",
        "really",
        "tell me more",
        "go on",
        "continue",
    }


    if normalized in conversational_phrases:

        return True


    # --------------------------------------------------
    # Obvious conversational starts
    # --------------------------------------------------

    conversational_prefixes = (

        "tell me ",
        "explain ",
        "describe ",
        "why ",
        "how does ",
        "how do ",
        "how is ",
        "what do you think ",
        "what do you know ",
        "do you think ",
        "can you explain ",
        "can you tell me ",
        "i think ",
        "i wonder ",
        "i was wondering ",
        "let's talk about ",
        "lets talk about ",
        "talk about ",
        "tell me about ",
        "what is ",
        "what are ",
        "who is ",
        "who was ",
        "where is ",
        "when was ",
        "why is ",
        "why are ",
        "how is ",
        "how was ",
    )


    if normalized.startswith(
        conversational_prefixes
    ):

        return True


    # --------------------------------------------------
    # Short conversational statements
    # --------------------------------------------------

    words = normalized.split()

    if len(words) <= 3:

        action_words = {

            "open",
            "launch",
            "start",
            "search",
            "searching",
            "find",
            "click",
            "double",
            "type",
            "move",
            "scroll",
            "press",
            "capture",
            "take",
        }

        if not any(
            word in action_words
            for word in words
        ):

            return True


    return False


# ==================================================
# Extract website search query
# ==================================================

def extract_search_query(text, site):

    cleaned = str(
        text or ""
    ).strip()

    site_name = str(
        site or ""
    ).strip()

    if not cleaned or not site_name:
        return None

    # ------------------------------------------------------
    # Remove common conversational prefixes that Whisper
    # may preserve in natural speech.
    # ------------------------------------------------------

    cleaned = re.sub(
        r"^(?:please|can\s+you|could\s+you|would\s+you|"
        r"hey|hey\s+jarvis|jarvis|heed)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # ------------------------------------------------------
    # Search phrase variations.
    #
    # Examples:
    #
    # search YouTube for Wi-Fi skeleton
    # search YouTube Wi-Fi skeleton
    # search for Wi-Fi skeleton on YouTube
    # search Wi-Fi skeleton on YouTube
    # search on YouTube for Wi-Fi skeleton
    # look up Wi-Fi skeleton on YouTube
    # find Wi-Fi skeleton on YouTube
    # find Wi-Fi skeleton in YouTube
    # ------------------------------------------------------

    patterns = [

        # search YouTube for X
        rf"\bsearch\s+{re.escape(site_name)}\s+for\s+(.+)",

        # search YouTube X
        rf"\bsearch\s+{re.escape(site_name)}\s+(.+)",

        # searching YouTube for X
        rf"\bsearching\s+{re.escape(site_name)}\s+for\s+(.+)",

        # searching YouTube X
        rf"\bsearching\s+{re.escape(site_name)}\s+(.+)",

        # search on YouTube for X
        rf"\bsearch\s+on\s+{re.escape(site_name)}\s+for\s+(.+)",

        # searching on YouTube for X
        rf"\bsearching\s+on\s+{re.escape(site_name)}\s+for\s+(.+)",

        # search for X on YouTube
        rf"\bsearch\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # searching for X on YouTube
        rf"\bsearching\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # search X on YouTube
        rf"\bsearch\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # look up X on YouTube
        rf"\blook\s+up\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # lookup X on YouTube
        rf"\blookup\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # find X on YouTube
        rf"\bfind\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # find X in YouTube
        rf"\bfind\s+(.+?)\s+in\s+{re.escape(site_name)}\b",

        # look for X on YouTube
        rf"\blook\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # locate X on YouTube
        rf"\blocate\s+(.+?)\s+on\s+{re.escape(site_name)}\b",

        # go to YouTube and search for X
        rf"\bgo\s+to\s+{re.escape(site_name)}\s+and\s+search\s+for\s+(.+)",

        # on YouTube search for X
        rf"\bon\s+{re.escape(site_name)}\s+search\s+for\s+(.+)",

        # search X using YouTube
        rf"\bsearch\s+(.+?)\s+(?:using|via)\s+{re.escape(site_name)}\b",
    ]

    query = None

    for pattern in patterns:

        match = re.search(
            pattern,
            cleaned,
            re.IGNORECASE
        )

        if match:

            query = (
                match.group(1)
                .strip()
            )

            break

    if not query:
        return None

    # ------------------------------------------------------
    # Remove trailing command language that belongs to the
    # click/open/play instruction rather than the search.
    # ------------------------------------------------------

    trailing_action_patterns = [

        r"\s+(?:and|then|,\s*)+\s+"
        r"(?:click|open|play|select)\s+"
        r"(?:on\s+)?(?:the\s+)?"
        r"(?:first|top|number\s+one|#?1)\b.*$",

        r"\s+(?:and|then)\s+"
        r"(?:click|open|play|select)\s+"
        r"(?:the\s+)?(?:first|top)\s+"
        r"(?:result|video|link|one)\b.*$",

        r"\s+(?:and|then)\s+"
        r"(?:click|open|play)\s+"
        r"(?:it|that|one)\b.*$",
    ]

    for pattern in trailing_action_patterns:

        query = re.sub(
            pattern,
            "",
            query,
            flags=re.IGNORECASE
        ).strip()

    # ------------------------------------------------------
    # Remove a dangling conjunction left by Whisper.
    #
    # Example:
    # "search YouTube for Wi-Fi skeleton and"
    # ------------------------------------------------------

    query = re.sub(
        r"\s+(?:and|then)\s*$",
        "",
        query,
        flags=re.IGNORECASE
    ).strip()

    # ------------------------------------------------------
    # Remove conversational filler from the beginning.
    # ------------------------------------------------------

    query = re.sub(
        r"^(?:please|can\s+you|could\s+you|would\s+you)\s+",
        "",
        query,
        flags=re.IGNORECASE
    ).strip()

    query = (
        query
        .strip()
        .rstrip("?.!,")
        .strip()
    )

    return query or None


def wants_first_result(text):

    normalized = clean_text(
        text
    )

    patterns = [

        # Open/click/play first result
        r"\bopen\s+(?:the\s+)?first\s+result\b",
        r"\bopen\s+(?:the\s+)?first\s+video\b",
        r"\bopen\s+(?:the\s+)?first\s+link\b",
        r"\bopen\s+(?:the\s+)?first\s+one\b",

        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+result\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+video\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+link\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+one\b",

        r"\bplay\s+(?:the\s+)?first\s+result\b",
        r"\bplay\s+(?:the\s+)?first\s+video\b",
        r"\bplay\s+(?:the\s+)?first\s+link\b",
        r"\bplay\s+(?:the\s+)?first\s+one\b",

        # Top result / top video / top link
        r"\bopen\s+(?:the\s+)?top\s+result\b",
        r"\bopen\s+(?:the\s+)?top\s+video\b",
        r"\bopen\s+(?:the\s+)?top\s+link\b",

        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+result\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+video\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+link\b",

        r"\bplay\s+(?:the\s+)?top\s+result\b",
        r"\bplay\s+(?:the\s+)?top\s+video\b",

        # Number one
        r"\bopen\s+(?:result|video|link)\s+number\s+one\b",
        r"\bclick\s+(?:on\s+)?(?:result|video|link)\s+number\s+one\b",
        r"\bplay\s+(?:result|video|link)\s+number\s+one\b",

        # First item / first one
        r"\bopen\s+(?:the\s+)?first\s+(?:item|one)\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+(?:item|one)\b",
        r"\bplay\s+(?:the\s+)?first\s+(?:item|one)\b",

        # Natural spoken variants
        r"\bgo\s+with\s+(?:the\s+)?first\s+(?:result|video|link|one)\b",
        r"\bselect\s+(?:the\s+)?first\s+(?:result|video|link|one)\b",
        r"\bchoose\s+(?:the\s+)?first\s+(?:result|video|link|one)\b",
    ]

    return any(
        re.search(
            pattern,
            normalized
        )
        for pattern in patterns
    )


def split_search_and_first_result(
    user_request,
    site
):

    if not wants_first_result(
        user_request
    ):
        return None

    search_query = extract_search_query(
        user_request,
        site
    )

    if not search_query:
        return None

    stop_patterns = [

        r"\s+(?:and|then)\s+open\s+(?:the\s+)?first\s+(?:result|video)\b.*$",

        r"\s+(?:and|then)\s+click\s+(?:the\s+)?first\s+(?:result|video)\b.*$",

        r"\s+(?:and|then)\s+play\s+(?:the\s+)?first\s+(?:result|video)\b.*$",

        r"\s+open\s+(?:the\s+)?first\s+(?:result|video)\b.*$",

        r"\s+click\s+(?:the\s+)?first\s+(?:result|video)\b.*$",

        r"\s+play\s+(?:the\s+)?first\s+(?:result|video)\b.*$",
    ]

    query = search_query

    for pattern in stop_patterns:

        query = re.sub(
            pattern,
            "",
            query,
            flags=re.IGNORECASE
        ).strip()

    query = re.sub(
        r"\s+(?:and|then)\s*$",
        "",
        query,
        flags=re.IGNORECASE
    ).strip()

    if not query:
        return None

    return {
        "query": query,
        "open_first": True,
    }


# ==================================================
# Detect browser launch
# ==================================================

def browser_requested(text):

    lowered = clean_text(text)

    return (
        "open chrome" in lowered
        or "open google chrome" in lowered
        or "launch chrome" in lowered
        or "start chrome" in lowered
    )


# ==================================================
# Build website search plan
# ==================================================

def build_website_search_plan(
    user_request,
    site
):

    query = extract_search_query(
        user_request,
        site
    )

    if not query:
        return None

    steps = []


    if browser_requested(
        user_request
    ):

        steps.append(
            {
                "tool": "open_program",
                "argument": "chrome"
            }
        )

        steps.append(
            {
                "tool": "wait",
                "argument": "2"
            }
        )


    steps.append(
        {
            "tool": "search_website",
            "argument": f"{site}|{query}"
        }
    )


    return {
        "steps": steps
    }


# ==================================================
# Build search + first-result plan
# ==================================================

def build_search_first_result_plan(
    user_request,
    site
):

    combined = split_search_and_first_result(
        user_request,
        site
    )

    if not combined:
        return None

    query = combined["query"]

    steps = []


    if browser_requested(
        user_request
    ):

        steps.append(
            {
                "tool": "open_program",
                "argument": "chrome"
            }
        )

        steps.append(
            {
                "tool": "wait",
                "argument": "2"
            }
        )


    steps.append(
        {
            "tool": "search_website",
            "argument": f"{site}|{query}"
        }
    )


    steps.append(
        {
            "tool": "wait",
            "argument": "2"
        }
    )


    steps.append(
        {
            "tool": "click_screen",
            "argument": f"first organic YouTube result for {query}"
        }
    )


    return {
        "steps": steps
    }


# ==================================================
# Deterministic routing
# ==================================================

def deterministic_route(user_request):

    text = clean_text(
        user_request
    )


    # ==================================================
    # YouTube
    # ==================================================

    if "youtube" in text:

        if (
            "search" in text
            or "searching" in text
            or "find" in text
        ):

            combined_plan = (
                build_search_first_result_plan(
                    user_request,
                    "youtube"
                )
            )

            if combined_plan:

                print(
                    "JARVIS: YouTube multi-step search detected."
                )

                return combined_plan


            plan = build_website_search_plan(
                user_request,
                "youtube"
            )

            if plan:

                print(
                    "JARVIS: YouTube search detected."
                )

                return plan


    # ==================================================
    # Google
    # ==================================================

    if "google" in text:

        if (
            "search" in text
            or "searching" in text
            or "find" in text
        ):

            combined_plan = (
                build_search_first_result_plan(
                    user_request,
                    "google"
                )
            )

            if combined_plan:

                print(
                    "JARVIS: Google multi-step search detected."
                )

                return combined_plan


            plan = build_website_search_plan(
                user_request,
                "google"
            )

            if plan:

                print(
                    "JARVIS: Google search detected."
                )

                return plan


    # ==================================================
    # Amazon
    # ==================================================

    if "amazon" in text:

        if (
            "search" in text
            or "searching" in text
            or "find" in text
        ):

            combined_plan = (
                build_search_first_result_plan(
                    user_request,
                    "amazon"
                )
            )

            if combined_plan:

                print(
                    "JARVIS: Amazon multi-step search detected."
                )

                return combined_plan


            plan = build_website_search_plan(
                user_request,
                "amazon"
            )

            if plan:

                print(
                    "JARVIS: Amazon search detected."
                )

                return plan


    # ==================================================
    # Reddit
    # ==================================================

    if "reddit" in text:

        if (
            "search" in text
            or "searching" in text
            or "find" in text
        ):

            combined_plan = (
                build_search_first_result_plan(
                    user_request,
                    "reddit"
                )
            )

            if combined_plan:

                print(
                    "JARVIS: Reddit multi-step search detected."
                )

                return combined_plan


            plan = build_website_search_plan(
                user_request,
                "reddit"
            )

            if plan:

                print(
                    "JARVIS: Reddit search detected."
                )

                return plan


    # ==================================================
    # GENERIC GOOGLE SEARCH ROUTE
    # ==================================================
    #
    # Examples:
    #
    #   search for Wi-Fi skeleton
    #   search for Python tutorials
    #   find information about quantum computing
    #   look up Tesla
    #
    # When no specific site is named, route the request to
    # Google through the deterministic search_website tool.
    #
    # Specific site handlers above this block remain higher
    # priority, so:
    #
    #   search YouTube for X
    #
    # still uses the YouTube route.
    # ==================================================

    generic_search_match = re.match(
        r"^(?:please\s+)?(?:search\s+for|search|find|look\s+up|lookup)\s+(.+?)\s*[?.!]*$",
        user_request.strip(),
        re.IGNORECASE
    )

    if generic_search_match:
        query = (
            generic_search_match.group(1)
            .strip()
            .rstrip("?.!")
        )

        # Do not steal explicitly targeted website searches.
        explicit_site_words = (
            "youtube",
            "google",
            "amazon",
            "reddit"
        )

        query_lower = query.lower()

        if (
            query
            and not any(
                site_word in query_lower
                for site_word in explicit_site_words
            )
        ):
            print(
                f"JARVIS: Generic Google search detected: {query}"
            )

            return {
                "steps": [
                    {
                        "tool": "search_website",
                        "argument": f"google|{query}"
                    }
                ]
            }


    # ==================================================
    # Weather
    # ==================================================

    if contains_any(
        text,
        [
            "weather",
            "temperature",
            "forecast",
            "is it raining",
            "is it snowing",
            "will it rain",
            "will it snow",
            "rain today",
            "snow today",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "weather",
                    "argument": user_request
                }
            ]
        }


    # ==================================================
    # Time
    # ==================================================

    if contains_any(
        text,
        [
            "what time is it",
            "what's the time",
            "whats the time",
            "current time",
            "time right now",
        ]
    ):

        location = ""

        match = re.search(
            r"\bin\s+(.+?)(?:\?|$)",
            user_request,
            re.IGNORECASE
        )

        if match:

            location = (
                match.group(1)
                .strip()
                .rstrip("?.!")
            )

        return {
            "steps": [
                {
                    "tool": "current_time",
                    "argument": location
                }
            ]
        }


    # ==================================================
    # Date
    # ==================================================

    if contains_any(
        text,
        [
            "what's today's date",
            "whats today's date",
            "what is today's date",
            "what date is it",
            "what day is it",
            "what day is today",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "current_date",
                    "argument": ""
                }
            ]
        }


    # ==================================================
    # Active window
    # ==================================================

    if contains_any(
        text,
        [
            "what application am i using",
            "what application is open",
            "what window am i on",
            "what window is open",
            "what app is open",
            "what am i currently using",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "get_active_window",
                    "argument": ""
                }
            ]
        }


    # ==================================================
    # Screen analysis
    # ==================================================

    if contains_any(
        text,
        [
            "what's on my screen",
            "whats on my screen",
            "what is on my screen",
            "look at my screen",
            "analyze my screen",
            "read the error",
            "read the error on my screen",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "analyze_screen",
                    "argument": user_request
                }
            ]
        }


    # ==================================================
    # Screenshot
    # ==================================================

    if contains_any(
        text,
        [
            "take a screenshot",
            "take screenshot",
            "capture my screen",
            "capture the screen",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "capture_screen",
                    "argument": ""
                }
            ]
        }


    # ==================================================
    # Scroll
    # ==================================================

    if "scroll to the bottom" in text:

        return {
            "steps": [
                {
                    "tool": "scroll_screen",
                    "argument": "bottom"
                }
            ]
        }


    if "scroll to the top" in text:

        return {
            "steps": [
                {
                    "tool": "scroll_screen",
                    "argument": "top"
                }
            ]
        }


    if "scroll down" in text:

        return {
            "steps": [
                {
                    "tool": "scroll_screen",
                    "argument": "down"
                }
            ]
        }


    if "scroll up" in text:

        return {
            "steps": [
                {
                    "tool": "scroll_screen",
                    "argument": "up"
                }
            ]
        }


    # ==================================================
    # Open applications
    # ==================================================

    applications = {

        "google chrome": "chrome",
        "chrome": "chrome",

        "calculator": "calculator",
        "calc": "calculator",

        "notepad": "notepad",

        "paint": "paint",

        "file explorer": "file explorer",
        "explorer": "file explorer",

        "discord": "discord",

        "spotify": "spotify",

        "steam": "steam",

        "edge": "edge",

        "firefox": "firefox",

        "word": "word",

        "excel": "excel",

        "powerpoint": "powerpoint",
    }


    open_prefixes = (
        "open ",
        "launch ",
        "start ",
    )


    if text.startswith(
        open_prefixes
    ):

        command = clean_text(
            user_request
        )


        for spoken_name, program_name in applications.items():

            if (
                command == f"open {spoken_name}"
                or command == f"launch {spoken_name}"
                or command == f"start {spoken_name}"
            ):

                print(
                    f"JARVIS: Opening {program_name} deterministically."
                )

                return {
                    "steps": [
                        {
                            "tool": "open_program",
                            "argument": program_name
                        }
                    ]
                }


    # ==================================================
    # Double click
    # ==================================================

    if (
        "double click " in text
        or "double-click " in text
    ):

        target = re.sub(
            r"^.*?double[- ]click\s+",
            "",
            user_request,
            flags=re.IGNORECASE
        ).strip()

        if target:

            return {
                "steps": [
                    {
                        "tool": "double_click_screen",
                        "argument": target
                    }
                ]
            }


    # ==================================================
    # Click
    # ==================================================

    if text.startswith(
        "click "
    ):

        target = re.sub(
            r"^click\s+",
            "",
            user_request,
            flags=re.IGNORECASE
        ).strip()

        if target:

                        return {
                "steps": [
                    {
                        "tool": "click_screen",
                        "argument": target
                    }
                ]
            }


    # ==================================================
    # Move mouse
    # ==================================================

    if (
        text.startswith("move the mouse")
        or text.startswith("move my mouse")
        or text.startswith("move cursor")
    ):

        match = re.search(
            r"(?:to|toward|towards)\s+(.+)",
            user_request,
            re.IGNORECASE
        )

        if match:

            target = (
                match.group(1)
                .strip()
                .rstrip("?.!")
            )

            return {
                "steps": [
                    {
                        "tool": "move_mouse",
                        "argument": target
                    }
                ]
            }


    # ==================================================
    # Type
    # ==================================================

    if text.startswith(
        "type "
    ):

        content = re.sub(
            r"^type\s+",
            "",
            user_request,
            flags=re.IGNORECASE
        ).strip()

        return {
            "steps": [
                {
                    "tool": "type_text",
                    "argument": content
                }
            ]
        }


    # ==================================================
    # Press key
    # ==================================================

    if text in {
        "press enter",
        "hit enter",
        "press the enter key",
    }:

        return {
            "steps": [
                {
                    "tool": "press_key",
                    "argument": "enter"
                }
            ]
        }


    # ==================================================
    # System status
    # ==================================================

    if contains_any(
        text,
        [
            "system status",
            "computer status",
            "how is my computer",
            "how is my pc",
            "cpu usage",
            "ram usage",
        ]
    ):

        return {
            "steps": [
                {
                    "tool": "system_status",
                    "argument": ""
                }
            ]
        }


    return None


# ==================================================
# LLM fallback
# ==================================================

def llm_plan(user_request):

    response = chat(
        model=MODEL,
        format="json",
        messages=[
            {
                "role": "system",
                "content": """
You are JARVIS's fallback task planner.

Your job is ONLY to determine whether the user needs
a computer/tool action.

Do not turn normal conversation into a tool action.

AVAILABLE TOOLS:

weather
current_time
current_date
wait
open_website
search_website
open_program
system_status
jarvis_status
create_folder
list_files
find_file
open_folder
web_search
capture_screen
screen_size
get_active_window
analyze_screen
move_mouse
click_screen
double_click_screen
scroll_screen
verify_screen
type_text
press_key

RULES:

1. Opening applications uses open_program.
2. Opening websites uses open_website.
3. Searches may use search_website or web_search.
4. Weather uses weather.
5. Current time uses current_time.
6. Current date uses current_date.
7. Screen interaction uses screen tools.
8. Use multiple ordered steps when necessary.
9. Do not create tool actions for ordinary conversation.
10. Do not invent tools.
11. If the user is simply talking to JARVIS, asking
    a question, making a statement, acknowledging
    something, or requesting an explanation, return
    an empty steps array.
12. Return ONLY valid JSON.

FORMAT:

{
    "steps": [
        {
            "tool": "tool_name",
            "argument": "argument"
        }
    ]
}

For normal conversation:

{
    "steps": []
}
"""
            },
            {
                "role": "user",
                "content": user_request
            }
        ],
        options={
            "temperature": 0.0
        }
    )


    try:

        result = json.loads(
            response["message"]["content"]
        )


        if not isinstance(
            result,
            dict
        ):

            return {
                "steps": []
            }


        steps = result.get(
            "steps",
            []
        )


        if not isinstance(
            steps,
            list
        ):

            return {
                "steps": []
            }


        return {
            "steps": steps
        }


    except Exception as e:

        print(
            "Planner JSON error:",
            e
        )

        return {
            "steps": []
        }


# ==================================================
# Fast command compatibility API
# ==================================================

def get_fast_command(user_request):
    """
    Return a deterministic fast-command plan when one exists.

    main.py uses this function as the lightweight command lookup
    before falling back to the full planner.
    """
    try:
        return deterministic_route(user_request)
    except Exception as e:
        print(f"JARVIS: Fast command lookup error: {e}")
        return None

# ==================================================
# Public planner
# ==================================================

def create_plan(user_request):

    user_request = (
        user_request
        .strip()
    )


    if not user_request:

        return {
            "steps": []
        }


    # --------------------------------------------------
    # Deterministic routing FIRST
    # --------------------------------------------------

    plan = deterministic_route(
        user_request
    )


    if plan is not None:

        print(
            "JARVIS: Deterministic route selected."
        )

        return plan


    # --------------------------------------------------
    # Lightweight conversation gate
    # --------------------------------------------------

    if looks_like_conversation(
        user_request
    ):

        print(
            "JARVIS: Conversation detected."
        )

        return {
            "steps": []
        }


    # --------------------------------------------------
    # LLM fallback for ambiguous requests
    # --------------------------------------------------

    print(
        "JARVIS: Using LLM planner."
    )


    return llm_plan(
        user_request
    )
def is_creative_request(text):
    """
    Return True when the request is primarily a creative/writing request
    rather than a desktop-control command.
    """
    if not text:
        return False

    text = str(text).strip().lower()

    creative_phrases = (
        "write ",
        "rewrite ",
        "draft ",
        "compose ",
        "create a story",
        "write a story",
        "write me a story",
        "make up a story",
        "write a poem",
        "write poetry",
        "compose a poem",
        "write lyrics",
        "compose lyrics",
        "make a poem",
        "make up a story",
        "brainstorm ",
        "come up with ",
        "generate an idea",
        "generate ideas",
        "create an idea",
        "give me ideas",
        "write a script",
        "write dialogue",
        "create dialogue",
    )

    return text.startswith(creative_phrases) or any(
        phrase in text
        for phrase in creative_phrases
    )


# ==================================================
# Compatibility helpers expected by main.py
# ==================================================

def is_creative_request(text):
    if not text:
        return False

    normalized = normalize_command(text).lower()

    creative_prefixes = (
        "write ",
        "rewrite ",
        "draft ",
        "compose ",
        "create a story",
        "write a story",
        "write me a story",
        "make up a story",
        "write a poem",
        "write poetry",
        "compose a poem",
        "make a poem",
        "write lyrics",
        "compose lyrics",
        "write a script",
        "write dialogue",
        "create dialogue",
        "brainstorm ",
        "come up with ",
        "generate ideas",
        "give me ideas",
    )

    return normalized.startswith(creative_prefixes)


def is_remember_command(text):
    if not text:
        return False

    normalized = normalize_command(text).lower()

    remember_phrases = (
        "remember that ",
        "remember this ",
        "please remember ",
        "save this ",
        "save that ",
        "remember ",
        "don't forget ",
        "dont forget ",
        "do not forget ",
    )

    return normalized.startswith(remember_phrases)


def is_shutdown_command(text):
    if not text:
        return False

    normalized = normalize_command(text).lower()

    shutdown_commands = {
        "shutdown",
        "shut down",
        "shutdown jarvis",
        "shut down jarvis",
        "turn yourself off",
        "turn off jarvis",
        "power off",
        "power down",
        "exit jarvis",
        "quit jarvis",
    }

    return normalized in shutdown_commands


def should_resolve_context(text):
    if not text:
        return False

    normalized = normalize_command(text).lower()

    context_phrases = (
        "click it",
        "open it",
        "play it",
        "select it",
        "use it",
        "that one",
        "this one",
        "the first one",
        "the second one",
        "the last one",
        "same one",
        "do that",
        "do it",
        "try that",
        "try it",
        "go there",
        "open that",
        "click that",
        "play that",
        "select that",
    )

    return (
        normalized in context_phrases
        or any(
            normalized.startswith(phrase + " ")
            for phrase in context_phrases
        )
    )

import re

# ==================================================
# Fast command override
# ==================================================

def get_fast_command(user_request):
    """
    Fast deterministic routing for common desktop commands.

    This override specifically handles "look up X on YouTube"
    requests so they never fall through to the slow LLM planner.
    """

    text = str(user_request or "").strip()

    lowered = text.lower()

    # --------------------------------------------------
    # YouTube: "look up X" + first result
    # --------------------------------------------------

    if "youtube" in lowered and (
        "look up" in lowered
        or "lookup" in lowered
    ):

        query = None

        patterns = [
            r"\block\s+up\s+(.+?)(?:\s+and\s+(?:click|open|play)\s+(?:the\s+)?first\s+(?:result|video)\b.*)?$",
            r"\blookup\s+(.+?)(?:\s+and\s+(?:click|open|play)\s+(?:the\s+)?first\s+(?:result|video)\b.*)?$",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:
                query = match.group(1).strip()
                break

        if query:
            query = query.rstrip(".,!?")

            steps = []

            # Open Chrome when explicitly requested.
            if (
                "open chrome" in lowered
                or "open google chrome" in lowered
                or "launch chrome" in lowered
                or "start chrome" in lowered
            ):
                steps.append({
                    "tool": "open_program",
                    "argument": "chrome"
                })

                steps.append({
                    "tool": "wait",
                    "argument": "2"
                })

            steps.append({
                "tool": "search_website",
                "argument": f"youtube|{query}"
            })

            steps.append({
                "tool": "wait",
                "argument": "2"
            })

            # Only add the click when the request asks for it.
            if (
                "first result" in lowered
                or "first video" in lowered
            ):
                steps.append({
                    "tool": "click_screen",
                    "argument": f"first organic YouTube result for {query}"
                })

            print("JARVIS: Fast YouTube look-up route selected.")

            return {
                "steps": steps
            }

    # --------------------------------------------------
    # Everything else uses the existing deterministic router
    # --------------------------------------------------

    try:
        return deterministic_route(user_request)
    except Exception as e:
        print(f"JARVIS: Fast command lookup error: {e}")
        return None

import re

def get_fast_command(user_request):
    text = str(user_request or "").strip()

    lowered = text.lower()

    # Handle:
    # Open Chrome, go onto YouTube, look up Wi-Fi Skeleton and click the first result.

    if "youtube" in lowered and "look up" in lowered:

        match = re.search(
            r"look\s+up\s+(.+?)(?:\s+and\s+(?:click|open|play)\s+the\s+first\s+(?:result|video).*)?$",
            text,
            re.IGNORECASE
        )

        if match:
            query = match.group(1).strip().rstrip(".,!?")

            steps = []

            if (
                "open chrome" in lowered
                or "open google chrome" in lowered
                or "launch chrome" in lowered
                or "start chrome" in lowered
            ):
                steps.append({
                    "tool": "open_program",
                    "argument": "chrome"
                })
                steps.append({
                    "tool": "wait",
                    "argument": "2"
                })

            steps.append({
                "tool": "search_website",
                "argument": f"youtube|{query}"
            })

            steps.append({
                "tool": "wait",
                "argument": "2"
            })

            if "first result" in lowered or "first video" in lowered:
                steps.append({
                    "tool": "click_screen",
                    "argument": f"first organic YouTube result for {query}"
                })

            print("JARVIS: Fast YouTube route selected.")

            return {
                "steps": steps
            }

    # Fall back to the existing deterministic router.
    try:
        return deterministic_route(user_request)
    except Exception as e:
        print(f"JARVIS: Fast command lookup error: {e}")
        return None

