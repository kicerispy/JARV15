from ollama import chat
import json
import re


MODEL = "qwen3:8b"


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
    # ------------------------------------------------------

    patterns = [
        rf"\bsearch\s+{re.escape(site_name)}\s+for\s+(.+)",
        rf"\bsearch\s+{re.escape(site_name)}\s+(.+)",
        rf"\bsearching\s+{re.escape(site_name)}\s+for\s+(.+)",
        rf"\bsearching\s+{re.escape(site_name)}\s+(.+)",
        rf"\bsearch\s+on\s+{re.escape(site_name)}\s+for\s+(.+)",
        rf"\bsearching\s+on\s+{re.escape(site_name)}\s+for\s+(.+)",
        rf"\bsearch\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\bsearching\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\bsearch\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\blook\s+up\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\blookup\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\bfind\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\bfind\s+(.+?)\s+in\s+{re.escape(site_name)}\b",
        rf"\blook\s+for\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\blocate\s+(.+?)\s+on\s+{re.escape(site_name)}\b",
        rf"\bgo\s+to\s+{re.escape(site_name)}\s+and\s+search\s+for\s+(.+)",
        rf"\bon\s+{re.escape(site_name)}\s+search\s+for\s+(.+)",
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

    query = re.sub(
        r"\s+(?:and|then)\s*$",
        "",
        query,
        flags=re.IGNORECASE
    ).strip()

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
        r"\bopen\s+(?:the\s+)?top\s+result\b",
        r"\bopen\s+(?:the\s+)?top\s+video\b",
        r"\bopen\s+(?:the\s+)?top\s+link\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+result\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+video\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?top\s+link\b",
        r"\bplay\s+(?:the\s+)?top\s+result\b",
        r"\bplay\s+(?:the\s+)?top\s+video\b",
        r"\bopen\s+(?:result|video|link)\s+number\s+one\b",
        r"\bclick\s+(?:on\s+)?(?:result|video|link)\s+number\s+one\b",
        r"\bplay\s+(?:result|video|link)\s+number\s+one\b",
        r"\bopen\s+(?:the\s+)?first\s+(?:item|one)\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+(?:item|one)\b",
        r"\bplay\s+(?:the\s+)?first\s+(?:item|one)\b",
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


def browser_requested(text):

    lowered = clean_text(text)

    return (
        "open chrome" in lowered
        or "open google chrome" in lowered
        or "launch chrome" in lowered
        or "start chrome" in lowered
    )


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

    site = str(
        site or ""
    ).strip().lower()

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

    # Use the canonical browser search tool for Google so the fast
    # command path is visible to the browser executor instead of routing
    # through the legacy website-search wrapper.
    if site == "google":

        steps.append(
            {
                "tool": "browser_search_google",
                "argument": query
            }
        )

    else:

        steps.append(
            {
                "tool": "search_website",
                "argument": f"{site}|{query}"
            }
        )

    return {
        "steps": steps
    }


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

    query = combined.get(
        "query",
        ""
    ).strip()

    if not query:
        return None

    site = str(
        site or ""
    ).strip().lower()

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

    # Search and click through the JARVIS browser DOM pipeline for the
    # sites that have dedicated Playwright result tools. The search tools
    # already wait for navigation/DOM readiness, so a fixed sleep is not
    # necessary.
    if site == "google":

        steps.append(
            {
                "tool": "browser_search_google",
                "argument": query
            }
        )

        steps.append(
            {
                "tool": "browser_click_first_result",
                "argument": json.dumps({
                    "site": "google"
                })
            }
        )

    elif site == "youtube":

        steps.append(
            {
                "tool": "search_website",
                "argument": f"{site}|{query}"
            }
        )

        steps.append(
            {
                "tool": "browser_click_first_result",
                "argument": json.dumps({
                    "site": "youtube"
                })
            }
        )

    else:

        steps.append(
            {
                "tool": "search_website",
                "argument": f"{site}|{query}"
            }
        )

        steps.append(
            {
                "tool": "click_screen",
                "argument": "first result"
            }
        )

    return {
        "steps": steps
    }


def extract_generic_search_query(text):
    original = str(text or "").strip()

    if not original:
        return None

    cleaned = original.strip()

    cleaned = re.sub(
        r"^(?:please|can\s+you|could\s+you|would\s+you|"
        r"hey|hey\s+jarvis|jarvis|heed)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    patterns = [
        r"^(?:search)\s+for\s+(.+?)$",
        r"^(?:search)\s+(.+?)$",
        r"^(?:find)\s+(.+?)$",
        r"^(?:look)\s+up\s+(.+?)$",
        r"^(?:lookup)\s+(.+?)$",
    ]

    query = None

    for pattern in patterns:

        match = re.search(
            pattern,
            cleaned,
            re.IGNORECASE,
        )

        if match:
            query = match.group(1).strip()
            break

    if not query:
        return None

    query = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:click|open|play|select)\s+"
        r"(?:on\s+)?"
        r"(?:the\s+)?"
        r"(?:first|top)\s+"
        r"(?:result|video|link|one)\b.*$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()

    query = re.sub(
        r"\s*,?\s*"
        r"(?:click|open|play|select)\s+"
        r"(?:on\s+)?"
        r"(?:the\s+)?"
        r"(?:first|top)\s+"
        r"(?:result|video|link|one)\b.*$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()

    query = re.sub(
        r"\s+(?:and|then)\s*$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()

    query = query.strip().rstrip("?.!,").strip()

    if not query:
        return None

    lowered = query.lower()

    explicit_sites = (
        "youtube",
        "google",
        "amazon",
        "reddit",
    )

    if any(
        site in lowered
        for site in explicit_sites
    ):
        return None

    return query


def generic_search_wants_first_result(text):
    normalized = clean_text(
        text
    )

    if not normalized:
        return False

    patterns = [
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+result\b",
        r"\bopen\s+(?:the\s+)?first\s+result\b",
        r"\bselect\s+(?:the\s+)?first\s+result\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+link\b",
        r"\bopen\s+(?:the\s+)?first\s+link\b",
        r"\bclick\s+(?:on\s+)?(?:the\s+)?first\s+one\b",
        r"\bopen\s+(?:the\s+)?first\s+one\b",
        r"\bgo\s+with\s+(?:the\s+)?first\s+result\b",
        r"\bchoose\s+(?:the\s+)?first\s+result\b",
    ]

    return any(
        re.search(
            pattern,
            normalized,
            re.IGNORECASE,
        )
        for pattern in patterns
    )


def build_browser_search_plan(
    user_request,
):
    query = extract_generic_search_query(
        user_request
    )

    if not query:
        return None

    steps = [
        {
            "tool": "browser_search_bing",
            "argument": query,
        }
    ]

    if generic_search_wants_first_result(
        user_request
    ):

        steps.append(
            {
                "tool": "browser_click_first_bing_result",
                "argument": query,
            }
        )

    return {
        "steps": steps
    }


def _browser_dom_target(target: str):
    """Convert a natural browser target into one semantic DOM target."""
    target = normalize_command(target).strip().rstrip("?.!").strip()

    if not target:
        return None

    normalized = target.lower()

    role_map = {
        "search box": "searchbox",
        "searchbox": "searchbox",
        "search field": "searchbox",
        "search input": "searchbox",
        "address bar": "textbox",
        "url bar": "textbox",
        "text box": "textbox",
        "textbox": "textbox",
        "input field": "textbox",
        "button": "button",
        "link": "link",
        "tab": "tab",
        "menu": "menu",
        "menu item": "menuitem",
        "checkbox": "checkbox",
        "radio button": "radio",
        "radio": "radio",
        "combobox": "combobox",
        "listbox": "listbox",
        "heading": "heading",
    }

    role = role_map.get(normalized)
    if role:
        return {"role": role}

    suffix_roles = (
        (" button", "button"),
        (" link", "link"),
        (" tab", "tab"),
        (" checkbox", "checkbox"),
        (" radio button", "radio"),
        (" menu item", "menuitem"),
        (" heading", "heading"),
    )

    for suffix, role_name in suffix_roles:
        if normalized.endswith(suffix) and normalized != suffix.strip():
            name = target[: -len(suffix)].strip()
            if name:
                return {
                    "role": role_name,
                    "name": name,
                }

    return {"text": target}


def build_browser_dom_plan(user_request):
    """Build deterministic Playwright DOM actions from natural language."""
    normalized = normalize_command(user_request)

    # Application launches are handled by the desktop command router below.
    # Do not interpret "Open Chrome" as clicking a DOM element named Chrome.
    if normalized.lower() in {
        "open chrome",
        "open google chrome",
        "launch chrome",
        "start chrome",
    }:
        return None

    # Find/inspect an element.
    match = re.match(
        r"^(?:find|locate|inspect|look\s+for)\s+(?:the\s+)?(.+?)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        target = _browser_dom_target(match.group(1))
        if target:
            return {
                "steps": [{
                    "tool": "browser_find_element",
                    "argument": json.dumps(target),
                }]
            }

    # Fill an element with text.
    match = re.match(
        r"^(?:fill|enter|put|type)\s+"
        r"(?:the\s+)?(.+?)\s+"
        r"(?:with|using)\s+(.+)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        target = _browser_dom_target(match.group(1))
        value = match.group(2).strip().rstrip("?.!").strip()
        if target and value:
            return {
                "steps": [{
                    "tool": "browser_fill_element",
                    "argument": json.dumps({
                        **target,
                        "value": value,
                    }),
                }]
            }

    # Press a key on a named browser element.
    match = re.match(
        r"^(?:press|hit)\s+(?:the\s+)?(.+?)\s+"
        r"(?:in|on|inside)\s+(?:the\s+)?(.+)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        key = match.group(1).strip()
        target = _browser_dom_target(match.group(2))
        if key and target:
            return {
                "steps": [{
                    "tool": "browser_press_key",
                    "argument": json.dumps({
                        **target,
                        "key": key,
                    }),
                }]
            }

    # Explicit browser click language. Contextual result phrases remain
    # handled by the context resolver and generic result routers.
    match = re.match(
        r"^(?:click|open|select|choose)\s+"
        r"(?:the\s+)?(.+?)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        target_text = match.group(1).strip()
        blocked = {
            "it",
            "that",
            "this one",
            "that one",
            "first result",
            "second result",
            "third result",
            "last result",
            "first link",
            "second link",
            "third link",
            "last link",
        }
        if target_text.lower() not in blocked:
            target = _browser_dom_target(target_text)
            if target:
                return {
                    "steps": [{
                        "tool": "browser_click_element",
                        "argument": json.dumps(target),
                    }]
                }

    # Wait for visible page content.
    match = re.match(
        r"^(?:wait\s+for|wait\s+until)\s+"
        r"(?:the\s+)?(.+?)$",
        normalized,
        re.IGNORECASE,
    )
    if match:
        target_text = match.group(1).strip()
        if target_text:
            target = _browser_dom_target(target_text)
            # Common phrase: "wait for the results".
            if target_text.lower() in {"results", "the results"}:
                target = {"text": "Results"}
            return {
                "steps": [{
                    "tool": "browser_wait_for_element",
                    "argument": json.dumps(target),
                }]
            }

    return None


def deterministic_route(user_request):

    text = clean_text(
        user_request
    )

    # ==================================================
    # Media Controls
    # ==================================================

    if contains_any(
        text,
        [
            "pause the video",
            "play the video",
            "resume playback",
            "stop media",
            "media pause",
            "media play",
        ]
    ):
        return {
            "steps": [
                {
                    "tool": "browser_media_control",
                    "argument": user_request
                }
            ]
        }

    # ==================================================
    # Direct Website Navigation
    # ==================================================

    if (
        "youtube" in text
        and (
            "open chrome" in text
            or "open google chrome" in text
            or "launch chrome" in text
            or "start chrome" in text
        )
        and not (
            "search" in text
            or "searching" in text
            or "find" in text
            or "look up" in text
            or "lookup" in text
        )
    ):
        print("JARVIS: Direct Chrome → YouTube route selected.")
        return {
            "steps": [
                {
                    "tool": "open_program",
                    "argument": "chrome"
                },
                {
                    "tool": "browser_goto",
                    "argument": "https://www.youtube.com"
                }
            ]
        }
    # ==================================================
    # YouTube
    # ==================================================

    if "youtube" in text:

        if (
            "search" in text
            or "searching" in text
            or "find" in text
            or "look up" in text
            or "lookup" in text
        ):

            combined_plan = (
                build_search_first_result_plan(
                    user_request,
                    "youtube"
                )
            )

            if combined_plan:
                print("JARVIS: YouTube multi-step search detected.")
                return combined_plan

            plan = build_website_search_plan(
                user_request,
                "youtube"
            )

            if plan:
                print("JARVIS: YouTube search detected.")
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
                print("JARVIS: Google multi-step search detected.")
                return combined_plan

            plan = build_website_search_plan(
                user_request,
                "google"
            )

            if plan:
                print("JARVIS: Google search detected.")
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
                print("JARVIS: Amazon multi-step search detected.")
                return combined_plan

            plan = build_website_search_plan(
                user_request,
                "amazon"
            )

            if plan:
                print("JARVIS: Amazon search detected.")
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
                print("JARVIS: Reddit multi-step search detected.")
                return combined_plan

            plan = build_website_search_plan(
                user_request,
                "reddit"
            )

            if plan:
                print("JARVIS: Reddit search detected.")
                return plan

    # ==================================================
    # GENERIC BROWSER DOM ACTIONS
    # ==================================================

    browser_dom_plan = build_browser_dom_plan(
        user_request
    )

    if browser_dom_plan:
        print("JARVIS: Browser DOM action detected.")
        return browser_dom_plan

    # ==================================================
    # GENERIC BROWSER SEARCH
    # ==================================================

    browser_plan = build_browser_search_plan(
        user_request
    )

    if browser_plan:

        query = extract_generic_search_query(
            user_request
        )

        print(
            f"JARVIS: Generic browser search detected: {query}"
        )

        return browser_plan

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
            _generic_first_result_targets = {
                "first result",
                "the first result",
                "on the first result",
                "first video",
                "the first video",
                "on the first video",
                "first link",
                "the first link",
                "on the first link",
                "first one",
                "the first one",
                "on the first one",
                "second result",
                "the second result",
                "second video",
                "the second video",
                "second link",
                "the second link",
                "third result",
                "the third result",
                "third video",
                "the third video",
                "third link",
                "the third link",
                "last result",
                "the last result",
                "last video",
                "the last video",
                "last link",
                "the last link",
            }

            normalized_target = target.lower().strip()

            # Contextual references must reach the context resolver before
            # the generic screen-click fallback claims the request.
            _contextual_click_targets = {
                "it",
                "that",
                "this one",
                "that one",
                "same one",
            }

            if normalized_target in _contextual_click_targets:
                return None

            if normalized_target in _generic_first_result_targets:
                return None

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
    # JARVIS / WINDOWS STATUS
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
            "jarvis health",
            "jarvis status",
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

    if contains_any(
        text,
        [
            "startup status",
            "does jarvis start with windows",
            "does jarvis start with my pc",
            "is jarvis set to start with windows",
        ]
    ):
        return {
            "steps": [
                {
                    "tool": "startup_status",
                    "argument": ""
                }
            ]
        }

    if contains_any(
        text,
        [
            "start jarvis with windows",
            "start jarvis when windows starts",
            "start jarvis on boot",
            "start jarvis when my pc starts",
            "launch jarvis with windows",
            "run jarvis on windows startup",
            "enable jarvis startup",
            "enable windows startup",
        ]
    ):
        return {
            "steps": [
                {
                    "tool": "enable_startup",
                    "argument": ""
                }
            ]
        }

    if contains_any(
        text,
        [
            "stop jarvis from starting with windows",
            "stop jarvis on boot",
            "disable jarvis startup",
            "disable windows startup",
        ]
    ):
        return {
            "steps": [
                {
                    "tool": "disable_startup",
                    "argument": ""
                }
            ]
        }

    if contains_any(
        text,
        [
            "task history",
            "what have you done",
            "what did you do recently",
            "recent tasks",
        ]
    ):
        return {
            "steps": [
                {
                    "tool": "task_history",
                    "argument": ""
                }
            ]
        }

    if text in {"go back", "go back in the browser"}:
        return {
            "steps": [
                {
                    "tool": "browser_back",
                    "argument": ""
                }
            ]
        }

    if text in {
        "what are the search results",
        "what're the search results",
        "tell me the search results",
        "show me the search results",
        "read the page",
        "read this page",
        "read the page text",
        "read page",
        "read the current browser page",
        "show this page",
        "show the page",
    }:
        return {
            "steps": [
                {
                    "tool": "browser_page_snapshot",
                    "argument": ""
                }
            ]
        }

    if text in {"read the title", "read the page title", "read title"}:
        return {
            "steps": [
                {
                    "tool": "browser_page_info",
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
browser_media_control

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

    plan = deterministic_route(
        user_request
    )

    if plan is not None:
        print(
            "JARVIS: Deterministic route selected."
        )
        return plan

    if looks_like_conversation(
        user_request
    ):
        print(
            "JARVIS: Conversation detected."
        )
        return {
            "steps": []
        }

    print(
        "JARVIS: Using LLM planner."
    )

    return llm_plan(
        user_request
    )


# ==================================================
# Compatibility constants
# ==================================================
#
# Older tests and integrations import these names directly. Keep them as
# immutable tuples derived from the same canonical phrases used by the
# parser functions below so the public compatibility surface stays stable.
# ==================================================

CANCEL_COMMANDS = (
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
)

END_CONVERSATION_COMMANDS = (
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
)

DIRECT_PREFIXES = (
    "open ",
    "close ",
    "launch ",
    "start ",
    "go to ",
    "search ",
    "find ",
    "click ",
    "open ",
    "play ",
    "pause ",
    "resume ",
    "type ",
    "press ",
    "scroll ",
)

CONTEXTUAL_PHRASES = (
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

REFERENCE_WORDS = (
    "it",
    "that",
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

    return (
        normalized == "remember"
        or normalized.startswith(remember_phrases)
    )


def is_shutdown_command(text):
    if not text:
        return False

    normalized = normalize_command(text).lower()

    shutdown_commands = {
        "quit",
        "exit",
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
        "the third one",
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

    if (
        re.match(
            r"^(?:click|open|play|select|choose|pick)\s+(?:the\s+)?"
            r"(?:first|second|third|last|top|final)\s+"
            r"(?:result|link|video|one|item)$",
            normalized,
        )
    ):
        return True

    if normalized in {
        "read the page",
        "read this page",
        "read page",
        "read the page text",
        "show the page",
        "show this page",
        "what are the search results",
        "what're the search results",
        "tell me the search results",
        "show me the search results",
        "what did the search find",
        "what did you find",
        "read the title",
        "read the page title",
        "read title",
        "go back",
        "go back in the browser",
    }:
        return True

    return (
        normalized in context_phrases
        or any(
            normalized.startswith(phrase + " ")
            for phrase in context_phrases
        )
    )
