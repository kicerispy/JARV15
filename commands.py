from ollama import chat
import json
import re
from pathlib import Path


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

    # Reporting language belongs to JARVIS's response mode, not the
    # search query. Strip it before handing the query to the browser so a
    # request such as "search Google for X and tell me what you find" searches
    # only for X.
    trailing_report_patterns = [
        r"\s+(?:and|then)\s+(?:tell|show)\s+me\s+(?:what|the)\b.*$",
        r"\s+(?:and|then)\s+(?:tell|show)\s+me\s+.*$",
        r"\s+(?:and|then)\s+(?:give|read)\s+me\s+(?:the\s+)?(?:results|answer|findings)\b.*$",
        r"\s+(?:and|then)\s+summari[sz]e\s+.*$",
        r"\s+(?:and|then)\s+report\s+(?:the\s+)?results\b.*$",
    ]

    for pattern in trailing_report_patterns:
        query = re.sub(
            pattern,
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()

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


def _active_context_value(active_context, key, default=None):
    """Read an ActiveContext field from either an object or dictionary."""
    if active_context is None:
        return default

    if isinstance(active_context, dict):
        return active_context.get(key, default)

    return getattr(active_context, key, default)


_ROBLOX_CONTEXT_TERMS = (
    "roblox",
    "roblox studio",
    "luau",
    "script",
    "scripts",
    "localscript",
    "localscripts",
    "modulescript",
    "modulescripts",
    "module script",
    "module scripts",
    "remoteevent",
    "remoteevents",
    "remotefunction",
    "remotefunctions",
    "gameplay",
    "datamodel",
    "server script",
    "server scripts",
    "starter player",
    "replicatedstorage",
    "server storage",
    "workspace",
    "playtest",
    "studio output",
)


def _should_preserve_roblox_context(user_request, active_context=None):
    """Prevent generic browser shortcuts from stealing Roblox follow-ups."""
    site = str(
        _active_context_value(active_context, "site", "") or ""
    ).strip().lower()

    if site != "roblox":
        return False

    text = clean_text(user_request)
    if not text:
        return False

    browser_escape_terms = (
        "browser",
        "chrome",
        "google",
        "bing",
        "youtube",
        "amazon",
        "reddit",
        "web page",
        "website",
        "web site",
        "current page",
    )

    if any(term in text for term in browser_escape_terms):
        return False

    if any(term in text for term in _ROBLOX_CONTEXT_TERMS):
        return True

    action_starts = (
        "find ",
        "locate ",
        "inspect ",
        "check ",
        "analyze ",
        "analyse ",
        "list ",
        "show ",
        "read ",
        "search ",
        "trace ",
        "map ",
        "identify ",
        "explain ",
        "tell me ",
        "look for ",
        "look at ",
        "review ",
        "diagnose ",
        "debug ",
        "investigate ",
    )

    return text.startswith(action_starts)


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


def looks_like_product_research_request(text: str) -> bool:
    """Return True for shopping/review/alternative requests that need research."""
    normalized = normalize_command(text).lower()

    if not normalized:
        return False

    research_signals = (
        "review",
        "reviews",
        "rating",
        "ratings",
        "rated",
        "alternative",
        "alternatives",
        "best value",
        "cheaper",
        "cheapest",
        "worth buying",
        "compare products",
        "compare prices",
        "comparison",
        "price",
        "buy",
        "purchase",
    )

    product_signals = (
        "product",
        "products",
        "headphone",
        "headphones",
        "earbuds",
        "laptop",
        "laptops",
        "computer",
        "computers",
        "monitor",
        "monitors",
        "phone",
        "phones",
        "tablet",
        "tablets",
        "keyboard",
        "keyboards",
        "mouse",
        "mice",
        "camera",
        "cameras",
        "television",
        "tv",
        "router",
        "routers",
        "ssd",
        "gpu",
        "cpu",
        "chair",
        "shoes",
        "vacuum",
        "appliance",
        "model",
        "models",
    )

    has_research_signal = any(
        signal in normalized
        for signal in research_signals
    )

    has_product_signal = any(
        signal in normalized
        for signal in product_signals
    )

    budget_pattern = bool(
        re.search(
            r"(?:under|below|less than|up to)\s*\$?\s*[0-9]",
            normalized,
            re.IGNORECASE,
        )
    )

    best_product_question = bool(
        re.search(
            r"\b(?:best|top|cheapest)\b.*"
            r"\b(?:product|products|model|models)\b",
            normalized,
            re.IGNORECASE,
        )
    )

    return bool(
        has_product_signal
        and (
            has_research_signal
            or budget_pattern
            or "best " in normalized
            or best_product_question
        )
    )


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

    # Search readable text on the current page.
    match = re.match(
        r"^(?:find|locate|look for) "
        r"(?:the )?(.+?) "
        r"(?:on|in) (?:the )?(?:current |this )?page$",
        normalized,
        re.IGNORECASE,
    )

    if not match:
        match = re.match(
            r"^search this page for (.+?)$",
            normalized,
            re.IGNORECASE,
        )

    if match:
        query = match.group(1).strip().rstrip("?.!").strip()
        if query:
            return {
                "steps": [{
                    "tool": "browser_find_text",
                    "argument": json.dumps({
                        "query": query,
                    }),
                }]
            }

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


def build_project_file_lookup_plan(user_request):
    """Build a deterministic project-file lookup before browser routing."""
    text = clean_text(user_request)
    if not text:
        return None

    match = re.match(
        r"^(?:find|locate|search(?:\s+for)?|look\s+for)\s+"
        r"(?:the\s+)?([A-Za-z0-9_./\\-]+)"
        r"(?:\s+(?:in|inside|within)\s+(?:my|the)\s+project)?$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    target = match.group(1).strip().rstrip("?.!,")
    filename = Path(target.replace("\\", "/")).name

    project_extensions = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
        ".json", ".yaml", ".yml", ".toml", ".md", ".lua", ".java",
        ".cpp", ".c", ".h", ".hpp", ".go", ".rs", ".rb", ".php",
        ".ps1", ".bat", ".cmd",
    }

    if (
        Path(filename).suffix.lower() not in project_extensions
        and "/" not in target
        and "\\" not in target
    ):
        return None

    if not filename or "." not in filename:
        return None

    return {
        "steps": [{
            "tool": "find_file",
            "argument": target,
        }]
    }


def build_browser_navigation_plan(user_request):
    """Build a deterministic browser navigation plan for direct URLs."""
    original = str(user_request or "").strip()

    if not original:
        return None

    normalized = clean_text(original)

    # Avoid stealing desktop application launches such as "Open Chrome".
    if normalized in {
        "open chrome",
        "open google chrome",
        "launch chrome",
        "start chrome",
    }:
        return None

    match = re.match(
        r"^(?:go to|navigate to|open|visit)\s+"
        r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?)$",
        original.strip().rstrip("?.!"),
        re.IGNORECASE,
    )

    if not match:
        return None

    target = match.group(1).strip().rstrip(".,!?")

    if not re.match(r"^https?://", target, re.IGNORECASE):
        target = "https://" + target

    return {
        "steps": [{
            "tool": "browser_goto",
            "argument": target,
        }]
    }


def _is_specialized_api_request(user_request):
    text = clean_text(user_request)

    if not text:
        return False

    # Explicit site searches should remain on the browser/search path.
    explicit_browser_search = (
        (
            "search " in text
            or "find " in text
            or "look up " in text
        )
        and any(
            site in text
            for site in (
                " google ",
                " google",
                "youtube",
                "bing",
                "amazon",
                "reddit",
            )
        )
    )

    if explicit_browser_search:
        return False

    if (
        text.startswith("convert ")
        and " to " in text
    ):
        return True

    specialized_phrases = (
        "air quality",
        "air pollution",
        "air pollutants",
        "aqi",
        "pm2.5",
        "pm10",
        "weather alert",
        "weather alerts",
        "weather warning",
        "weather warnings",
        "severe weather alert",
        "severe weather alerts",
        "elevation of ",
        "altitude of ",
        "elevation in ",
        "altitude in ",
    )

    return any(
        phrase in text
        for phrase in specialized_phrases
    )


def _extract_browser_url(text):
    match = re.search(
        r"https?://[^\s<>\"']+|www\.[^\s<>\"']+|"
        r"\b[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s<>\"']*)?",
        str(text or ""),
        re.IGNORECASE,
    )
    if not match:
        return ""
    value = match.group(0).rstrip(".,;:!?)]}\"'")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    return value


def build_browser_qol_plan(user_request):
    """Build zero-LLM plans for common browser navigation and maintenance."""
    text = clean_text(user_request)
    if not text:
        return None

    autonomous_browser = (
        "autonomous browser" in text
        or "browser agent" in text
        or "browser use" in text
    )
    if autonomous_browser:
        return None

    if any(term in text for term in (
        "page title",
        "title of the page",
        "title of that page",
        "read the title",
        "read the page title",
    )):
        url = _extract_browser_url(user_request)
        steps = []
        if url:
            steps.append({"tool": "browser_goto", "argument": url})
        steps.append({"tool": "browser_page_info", "argument": ""})
        return {"steps": steps}

    if any(term in text for term in (
        "current url",
        "current page url",
        "what url am i on",
    )):
        return {"steps": [{"tool": "browser_page_info", "argument": ""}]}

    if text in {
        "refresh", "refresh page", "refresh the page",
        "refresh the browser", "reload", "reload page", "reload the page",
    }:
        return {"steps": [{"tool": "browser_refresh", "argument": ""}]}

    if text in {"go forward", "go forward in the browser", "forward"}:
        return {"steps": [{"tool": "browser_forward", "argument": ""}]}

    if re.match(r"^(?:open|create|start)\s+(?:a\s+)?new\s+tab$", text, re.IGNORECASE):
        return {"steps": [{"tool": "browser_new_tab", "argument": ""}]}

    new_tab_match = re.match(
        r"^(?:open|create|start)\s+(?:a\s+)?new\s+tab\s+(?:to|with)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if new_tab_match:
        target = _extract_browser_url(new_tab_match.group(1))
        if target:
            return {"steps": [{"tool": "browser_new_tab", "argument": target}]}

    tab_match = re.match(
        r"^(?:switch|go)\s+(?:to\s+)?tab\s+(\d+)$",
        text,
        re.IGNORECASE,
    )
    if tab_match:
        return {
            "steps": [{
                "tool": "browser_switch_tab",
                "argument": json.dumps({"index": int(tab_match.group(1))}),
            }]
        }

    if text in {"close this tab", "close the current tab", "close current tab"}:
        return {
            "steps": [{
                "tool": "browser_close_tab",
                "argument": json.dumps({"index": "current"}),
            }]
        }

    if text in {
        "what links are on this page",
        "what links are on the page",
        "show me the links on this page",
        "list the links on this page",
        "get the links on this page",
    }:
        return {
            "steps": [{
                "tool": "browser_get_links",
                "argument": json.dumps({"limit": 30}),
            }]
        }

    open_link_match = re.match(
        r"^(?:open|click)\s+(?:the\s+)?"
        r"(first|second|third|fourth|fifth|last)\s+link$",
        text,
        re.IGNORECASE,
    )
    if open_link_match:
        ordinal = open_link_match.group(1).lower()
        ordinal_map = {
            "first": 1, "second": 2, "third": 3,
            "fourth": 4, "fifth": 5, "last": "last",
        }
        return {
            "steps": [{
                "tool": "browser_open_link",
                "argument": json.dumps({"index": ordinal_map[ordinal]}),
            }]
        }

    if text in {"scroll down the page", "scroll down", "scroll the page down"}:
        return {
            "steps": [{
                "tool": "browser_scroll",
                "argument": json.dumps({"direction": "down", "distance": 600}),
            }]
        }

    if text in {"scroll up the page", "scroll up", "scroll the page up"}:
        return {
            "steps": [{
                "tool": "browser_scroll",
                "argument": json.dumps({"direction": "up", "distance": 600}),
            }]
        }

    return None



def build_anipy_plan(user_request):
    """Build deterministic first-class routes for the upstream anipy-cli integration."""
    original = str(user_request or "").strip()
    text = clean_text(original)
    if not text:
        return None

    explicit = re.match(
        r"^(?:(?:run|use|launch|start)\s+(?:the\s+)?|)anipy(?:-|\s+)cli(?:\s+(.*))?$",
        original,
        re.IGNORECASE,
    )
    if explicit:
        return {
            "steps": [{
                "tool": "anipy_cli",
                "argument": (explicit.group(1) or "").strip(),
            }]
        }

    if (
        ("anipy" in text or "anime" in text)
        and any(phrase in text for phrase in (
            "providers",
            "provider list",
            "available providers",
        ))
    ):
        return {"steps": [{"tool": "anipy_providers", "argument": ""}]}

    anime_domain = any(
        phrase in text
        for phrase in ("anime", "anipy", "anilist", "myanimelist")
    )

    # Natural anime requests often omit the word "anime". Episode-specific
    # watch/download/stream requests are sufficiently specific to enter the
    # Anipy parser without hijacking unrelated generic browser/file tasks.
    episode_action = bool(
        re.search(
            r"\b(?:watch|play|stream|download|save|list|show|get|find|resolve)\b.*\bepisodes?\b",
            original,
            re.IGNORECASE,
        )
    )
    if not anime_domain and not episode_action:
        return None

    language_match = re.search(r"\b(sub|dub)\b", text, re.IGNORECASE)
    default_language = language_match.group(1).lower() if language_match else None

    patterns = (
        r"^(?:search|find|look up)\s+(?:for\s+)?(?:the\s+)?anime\s+(.+)$",
        r"^(?:search|find|look up)\s+(?:for\s+)?(.+?)\s+(?:on\s+)?anipy(?:-|\s+)cli$",
        r"^(?:anime)\s+(?:search|find)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, original, re.IGNORECASE)
        if match:
            query = match.group(1).strip().rstrip("?.!,").strip()
            if query:
                return {
                    "steps": [{
                        "tool": "anipy_search",
                        "argument": json.dumps({"query": query, **({"language": default_language} if default_language else {})}),
                    }]
                }

    match = re.match(
        r"^(?:get|show|find|tell me)\s+(?:the\s+)?(?:anime\s+)?"
        r"(?:info|information|details|metadata)\s+(?:for|on|about)\s+(.+)$",
        original,
        re.IGNORECASE,
    )
    if match:
        query = match.group(1).strip().rstrip("?.!,").strip()
        if query:
            return {"steps": [{"tool": "anipy_info", "argument": json.dumps({"query": query})}]}

    match = re.match(
        r"^(?:list|show|get|find)\s+(?:the\s+)?(?:available\s+)?"
        r"(?:anime\s+)?episodes?\s+(?:for|of)\s+(.+)$",
        original,
        re.IGNORECASE,
    )
    if match:
        query = match.group(1).strip().rstrip("?.!,").strip()
        return {
            "steps": [{
                "tool": "anipy_episodes",
                "argument": json.dumps({"query": query, **({"language": default_language} if default_language else {})}),
            }]
        }

    match = re.match(
        r"^(?:get|find|resolve)\s+(?:the\s+)?(?:video|stream|stream\s+link|video\s+link)"
        r"\s+(?:for|of)\s+(.+?)\s+episode\s+(\d+(?:\.\d+)?)(?:\s+(sub|dub))?$",
        original,
        re.IGNORECASE,
    )
    if match:
        ep_text = match.group(2)
        episode = float(ep_text) if "." in ep_text else int(ep_text)
        return {
            "steps": [{
                "tool": "anipy_get_video",
                "argument": json.dumps({
                    "query": match.group(1).strip(),
                    "episode": episode,
                    **({"language": (match.group(3) or default_language).lower()} if (match.group(3) or default_language) else {}),
                }),
            }]
        }

    match = re.match(
        r"^(?:download|save)\s+(?:the\s+)?(?:anime\s+)?(.+?)\s+"
        r"episodes?\s+([0-9]+(?:\.[0-9]+)?(?:\s*-\s*[0-9]+(?:\.[0-9]+)?)?)"
        r"(?:\s+(sub|dub))?$",
        original,
        re.IGNORECASE,
    )
    if match:
        episode_range = re.sub(r"\s+", "", match.group(2))
        episode_value = episode_range
        if "-" not in episode_range:
            episode_value = float(episode_range) if "." in episode_range else int(episode_range)
        return {
            "steps": [{
                "tool": "anipy_download",
                "argument": json.dumps({
                    "query": match.group(1).strip(),
                    "episodes": episode_value,
                    **({"language": (match.group(3) or default_language).lower()} if (match.group(3) or default_language) else {}),
                }),
            }]
        }

    match = re.match(
        r"^(?:download|save)\s+(?:the\s+)?(?:anime\s+)?(.+)$",
        original,
        re.IGNORECASE,
    )
    if match and not re.search(r"\b(?:episode|episodes)\b", match.group(1), re.IGNORECASE):
        return {"steps": [{"tool": "anipy_cli", "argument": "-D"}]}

    match = re.match(
        r"^(?:watch|play|stream)\s+(?:the\s+)?(?:anime\s+)?(.+?)\s+"
        r"episodes?\s+([0-9]+(?:\.[0-9]+)?(?:\s*-\s*[0-9]+(?:\.[0-9]+)?)?)"
        r"(?:\s+(sub|dub))?$",
        original,
        re.IGNORECASE,
    )
    if match:
        episode_range = re.sub(r"\s+", "", match.group(2))
        lang = (match.group(3) or default_language)
        query = match.group(1).strip()
        search_arg = f"{query}:{episode_range}"
        if lang:
            search_arg += f":{lang.lower()}"
        args = ["-s", search_arg]
        if "-" in episode_range:
            args = ["-B", "-s", search_arg]
        return {"steps": [{"tool": "anipy_cli", "argument": json.dumps({"args": args})}]}

    match = re.match(
        r"^(?:watch|play)\s+(?:the\s+)?(?:anime\s+)?(.+)$",
        original,
        re.IGNORECASE,
    )
    if match:
        return {"steps": [{"tool": "anipy_cli", "argument": ""}]}

    return None


def deterministic_route(user_request, active_context=None):


    if _is_specialized_api_request(user_request):
        return None

    text = clean_text(
        user_request
    )

    # ==================================================
    # Roblox Studio requests must never be intercepted by the generic
    # browser DOM/search shortcuts. The Roblox MCP planner owns these tasks.
    if (
        "roblox" in text
        or "luau" in text
        or "localscript" in text
        or "modulescript" in text
        or "playtest" in text
    ):
        return None

    # Preserve an established Roblox Studio domain for natural follow-ups.
    # Also protect the browser fast path from obvious software/gameplay
    # requests that omit the word Roblox.
    if _should_preserve_roblox_context(
        user_request,
        active_context,
    ):
        print("JARVIS: Preserving active Roblox context for follow-up request.")
        return None

    software_like_find = (
        text.startswith("find ")
        and any(
            phrase in text
            for phrase in (
                "the scripts",
                "scripts that",
                "script that",
                "gameplay systems",
                "gameplay system",
                "module scripts",
                "modulescripts",
                "remote events",
                "remote functions",
                "server scripts",
                "local scripts",
            )
        )
    )

    if software_like_find:
        print("JARVIS: Software/gameplay follow-up detected.")
        return None


    # ==================================================
    # ANIPY-CLI / ANIME
    # ==================================================

    anipy_plan = build_anipy_plan(user_request)
    if anipy_plan:
        print("JARVIS: anipy-cli route selected.")
        return anipy_plan

    # Project filename lookups must run before generic browser "find/search" routes.
    project_file_plan = build_project_file_lookup_plan(user_request)

    if project_file_plan:

        print("JARVIS: Project file lookup detected.")

        return project_file_plan


    # Direct Browser Navigation
    # ==================================================

    navigation_plan = build_browser_navigation_plan(
        user_request
    )

    if navigation_plan:
        print("JARVIS: Direct browser navigation detected.")
        return navigation_plan

    # ==================================================
    # BROWSER QUALITY-OF-LIFE FAST PATHS
    # ==================================================

    browser_qol_plan = build_browser_qol_plan(
        user_request
    )

    if browser_qol_plan:
        print("JARVIS: Browser QoL fast path selected.")
        return browser_qol_plan

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
    # PRODUCT RESEARCH
    # ==================================================

    if looks_like_product_research_request(user_request):
        print("JARVIS: Product research request detected.")
        return {
            "steps": [{
                "tool": "product_research",
                "argument": json.dumps({
                    "request": user_request,
                }),
            }],
        }

    # ==================================================
    # GENERIC BROWSER DOM ACTIONS
    # ==================================================
    #
    # Do not let generic "find/locate/look for" matching
    # hijack requests that clearly belong to the structured
    # public API/research layer.
    # ==================================================

    api_intent = contains_any(
        text,
        [
            "public holiday",
            "public holidays",
            "holiday",
            "holidays",
            "define ",
            "definition of ",
            "dictionary",
            "book ",
            "books ",
            "author ",
            "authors ",
            "research paper",
            "research papers",
            "research article",
            "research articles",
            "arxiv",
            "scholarly",
            "scholarly paper",
            "scholarly papers",
            "vin ",
            "vehicle identification number",
            "vehicle vin",
            "earthquake",
            "earthquakes",
            "public api",
            "public apis",
            "free api",
            "free apis",
        ],
    )

    if not api_intent:
        browser_dom_plan = build_browser_dom_plan(
            user_request
        )

        if browser_dom_plan:
            print("JARVIS: Browser DOM action detected.")
            return browser_dom_plan

    # ==================================================
    # GENERIC BROWSER SEARCH
    # ==================================================
    #
    # Structured API/research requests must reach the planner.
    # Do not intercept them with the generic browser-search shortcut.
    # ==================================================

    if not api_intent:
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
                ordinal_map = {
                    "first": 1,
                    "the first": 1,
                    "first result": 1,
                    "the first result": 1,
                    "first video": 1,
                    "the first video": 1,
                    "first link": 1,
                    "the first link": 1,
                    "first one": 1,
                    "the first one": 1,
                    "second result": 2,
                    "the second result": 2,
                    "second video": 2,
                    "the second video": 2,
                    "second link": 2,
                    "the second link": 2,
                    "third result": 3,
                    "the third result": 3,
                    "third video": 3,
                    "the third video": 3,
                    "third link": 3,
                    "the third link": 3,
                    "last result": -1,
                    "the last result": -1,
                    "last video": -1,
                    "the last video": -1,
                    "last link": -1,
                    "the last link": -1,
                }

                index = ordinal_map.get(normalized_target)
                if index is not None:
                    return {
                        "steps": [
                            {
                                "tool": "browser_click_result",
                                "argument": json.dumps({
                                    "index": index,
                                })
                            }
                        ]
                    }

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

    # Barehands display requests must win over the generic
    # "jarvis status" route below.
    if (
        "barehands" in text
        and (
            "display" in text
            or "glass board" in text
            or "show" in text
            or "present" in text
            or "put" in text
            or "place" in text
        )
        and "status" in text
        and (
            "card" in text
            or "status" in text
        )
    ):
        print("JARVIS: Barehands status display detected.")
        return {
            "steps": [{
                "tool": "barehands_present",
                "argument": (
                    "JARVIS Status|||"
                    "JARVIS status requested on the Barehands display."
                ),
            }]
        }

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

def get_fast_command(user_request, active_context=None):
    try:
        return deterministic_route(
            user_request,
            active_context=active_context,
        )
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

        "tell me more",

        "tell me more about that",

        "tell me more about this",

        "tell me more about it",

        "what else can you tell me",

        "give me more details",

        "expand on that",

        "what was the first one",

        "what was the second one",

        "what was the third one",

        "what was the last one",

        "tell me about the first one",

        "tell me about the second one",

        "tell me about the third one",

        "tell me about the last one",

        "what is the source",

        "where did you get that",

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
        "tell me more",
        "tell me more about that",
        "tell me more about this",
        "tell me more about it",
        "what else can you tell me",
        "give me more details",
        "expand on that",
        "what was the first one",
        "what was the second one",
        "what was the third one",
        "what was the last one",
        "tell me about the first one",
        "tell me about the second one",
        "tell me about the third one",
        "tell me about the last one",
        "what is the source",
        "where did you get that",
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
