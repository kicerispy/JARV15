"""
JARVIS task planner - converts user requests into tool calls.
"""
import ast
import json
import re
from typing import Any, Dict, List, Optional

import config
from model_manager import ModelManager
from logger import logger
from project_fs import iter_project_files
from autonomous_engineering import is_test_target, requires_regression_test
from tool_registry import BROWSER_TOOLS, JSON_ARGUMENT_TOOLS

MODEL_MANAGER = ModelManager()
PLANNER_MODEL = MODEL_MANAGER.planner_model

# ==========================================================
# Available Tools
# ==========================================================

AVAILABLE_TOOLS: Dict[str, str] = {
    "n8n_status": "Check whether the configured n8n workflow orchestrator is enabled and reachable.",
    "n8n_run_workflow": "Delegate a workflow-class task to n8n. Argument is JSON with request, workflow_class, and optional context.",
    "anipy_cli": "Run the upstream anipy-cli CLI unchanged. Argument is the native CLI argument string or JSON with args.",
    "anipy_providers": "List the providers exposed by the installed anipy-api package.",
    "anipy_search": "Search anime through anipy-api providers. Argument is JSON with query and optional provider/index/all_providers.",
    "anipy_info": "Get detailed anime metadata through anipy-api. Argument is JSON selecting an anime by query/provider/identifier.",
    "anipy_episodes": "Get available anime episodes through anipy-api. Argument is JSON with query/provider/identifier and language.",
    "anipy_get_video": "Resolve an anime episode to an anipy-api video stream. Argument is JSON with anime selector, episode, language, and optional quality.",
    "anipy_download": "Download anime using the upstream anipy-api Downloader and anipy-cli configuration semantics. Argument is JSON with anime selector, episode(s), language, quality, and optional location/container/ffmpeg.",
    "context_backend_status": "Report configured OpenViking, agentmemory, and local memory backend health and selected backend.",
    "context_remember": "Persist a durable JARVIS fact, preference, lesson, or workflow. Argument is JSON.",
    "context_recall": "Recall relevant durable JARVIS memory. Argument is JSON with query and optional limit.",
    "context_search": "Build a compact context block from the configured memory backend. Argument is JSON with query and optional limit.",
    "context_read": "Read an OpenViking viking:// context document. Argument is JSON with uri and optional limit.",
    "openviking_add_resource": "Import a local or remote resource into OpenViking. Argument is JSON.",
    "openviking_add_skill": "Install a validated Agent Skill into OpenViking. Argument is JSON. Use only on explicit request.",
    "skills_status": "Report which external Agent Skill repositories are synchronized into JARVIS.",
    "skills_sync": "Explicitly clone/update the configured Agent Skill repositories. Only use when the user explicitly asks to sync, install, refresh, or update the skill sources. Never auto-run downloaded scripts.",
    "skills_search": "Search the synchronized Agent Skill catalog for relevant procedural knowledge.",
    "skills_read": "Read one synchronized SKILL.md or indexed skill document.",
    "harness_review": "Review a proposed tool plan for verification, mutation, scope, and long-horizon harness issues.",
    "unreal_mcp": "Call the upstream Unreal_mcp native MCP gateway. Argument is JSON using the upstream unreal gateway operations: search, describe, execute, or configure. Preserve upstream capability names and parameter contracts.",
    "unreal_mcp_status": "Check whether the local Unreal_mcp native MCP endpoint is reachable, authenticated, and exposing the upstream unreal gateway.",
    "unreal_mcp_setup": "Clone or refresh ChiR24/Unreal_mcp into JARVIS external-tools and report the Unreal plugin path. Do not silently modify an Unreal project.",
    "browser_connect": "Connect to the JARVIS-controlled Chrome browser.",
    "browser_search_google": "Search Google using the controlled browser.",
    "browser_search_bing": "Search Bing using the controlled browser.",
    "browser_click_first_bing_result": "Click the first Bing search result in the controlled browser.",
    "browser_goto": "Navigate the controlled browser to a URL.",
    "browser_page_info": "Read the current browser page title and URL.",
    "browser_refresh": "Refresh the current browser tab.",
    "browser_forward": "Navigate the current browser tab forward.",
    "browser_new_tab": "Open a new controlled browser tab. Argument is an optional URL.",
    "browser_switch_tab": "Switch to a browser tab by 1-based index. Argument is JSON.",
    "browser_current_tab": "Report the active browser tab and all open tabs.",
    "browser_close_tab": "Close a browser tab while keeping at least one JARVIS tab open. Argument is JSON.",
    "browser_get_links": "List visible links on the current page. Argument is JSON with optional limit.",
    "browser_open_link": "Open a visible link by text, href, or 1-based index. Argument is JSON.",
    "browser_scroll": "Scroll the controlled browser. Argument is JSON with direction and optional distance.",
    "browser_agent_run": "Run an autonomous browser task in the controlled Chrome session. Argument = task text or JSON with task and optional max_steps.",
    "browser_agent_status": "Check whether the optional autonomous browser-agent stack is installed and connected.",
    "roblox_mcp_status": "Report whether the local Roblox Studio MCP server and Studio plugin are connected.",
    "holiday_lookup": "Look up public holidays. Argument = ISO country code and optional year, e.g. US 2026.",
    "knowledge_lookup": "Look up a concise Wikipedia knowledge summary. Argument = topic.",
    "book_search": "Search Open Library for books or authors. Argument = title, author, or subject.",
    "define_word": "Define an English word using a public dictionary. Argument = word.",
    "research_arxiv": "Search arXiv research papers. Argument = research topic.",
    "research_crossref": "Search Crossref scholarly metadata. Argument = scholarly query.",
    "vehicle_lookup": "Decode a vehicle VIN using NHTSA. Argument = 17-character VIN.",
    "earthquake_search": "Get USGS earthquake information. Argument = day, week, or magnitude such as 4.5.",
    "api_discover": "Discover free no-auth public APIs. Argument = category or topic.",
"currency_convert": "Convert currencies using current exchange rates. Argument = 100 USD to EUR, or USD to EUR.",
"location_lookup": "Resolve a city or place to coordinates, timezone, country, and elevation. Argument = city or place.",
"air_quality": "Get current air-quality conditions including PM2.5, PM10, ozone, and other pollutants. Argument = city or coordinates.",
"weather_alerts": "Get active U.S. National Weather Service alerts. Argument = U.S. state, state code, or coordinates.",
"elevation_lookup": "Look up elevation for a place or coordinates. Argument = city or lat,lon.",
    "country_info": "Get World Bank country metadata such as capital, region, income level, and coordinates. Argument = country name or two-letter code.",
    "crypto_price": "Get current cryptocurrency market data without an API key. Argument = coin name or symbol.",
    "trivia_question": "Generate one free trivia question. Argument = optional category hint.",
    "joke": "Get a safe random joke from JokeAPI. Argument = optional category hint.",
    "meal_search": "Find a recipe or random meal using TheMealDB. Argument = meal or ingredient search, or empty for a random meal.",
    "tv_search": "Search TV shows with TVMaze. Argument = show name.",
    "music_search": "Search songs, artists, and albums with the iTunes Search API. Argument = song, artist, or album.",
    "musicbrainz_search": "Search MusicBrainz recording metadata. Argument = song, recording, or artist.",
    "anime_search": "Search anime using Jikan/MyAnimeList data. Argument = anime title.",
    "anime_episodes": "Find an anime and return its episodes using AniAPI, Kitsu, and Jikan fallbacks. Argument = anime title or JSON with anime/title and optional page.",
    "ghibli_search": "Search Studio Ghibli films. Argument = title, director, or empty.",
    "openalex_search": "Search scholarly works using OpenAlex. Argument = research topic.",
    "pubchem_lookup": "Look up chemical compound information from PubChem. Argument = compound name.",
    "art_search": "Search Art Institute of Chicago artworks. Argument = artist, title, or subject.",
    "nasa_eonet": "Query active NASA Earth Observatory Natural Event Tracker events. Argument = event category or empty.",
    "spacex_lookup": "Look up historical SpaceX launch records from the public community API. Argument = latest or historical.",
    "sunrise_sunset": "Get sunrise, sunset, solar noon, and twilight for a place. Argument = city or lat,lon.",
    "topo_elevation": "Get topographic elevation from OpenTopoData. Argument = place or lat,lon.",
    "public_ip": "Get the computer's current public IP address. Argument = empty.",
    "reverse_geocode": "Reverse geocode latitude,longitude with OpenStreetMap Nominatim. Argument = lat,lon.",
    "news_search": "Search recent news via the GDELT DOC 2.0 API. Argument = news topic.",
    "cat_fact": "Get a random cat fact. Argument = empty.",
    "dog_image": "Get a random dog image URL. Argument = optional breed hint.",
    "osm_search": "Search OpenStreetMap/Nominatim for a place, address, landmark, or map feature. Argument = search phrase.",
    "pokemon_lookup": "Look up Pokémon data including types, abilities, stats, and image. Argument = name or number.",
    "food_product": "Look up food product nutrition and ingredients from Open Food Facts. Argument = barcode.",
    "cocktail_search": "Find a cocktail recipe using TheCocktailDB. Argument = cocktail name, or empty for a random cocktail.",
    "openverse_search": "Search openly licensed images with Openverse. Argument = image search phrase.",
    "iss_location": "Get the International Space Station's current latitude and longitude. Argument = empty.",
    "gods_eye_status": "Report God's Eye View installation and local server status. Argument = empty.",
    "gods_eye_setup": "Install or update God's Eye View in the JARVIS external-tools directory and run its setup doctor. Argument = empty.",
    "gods_eye_start": "Start God's Eye View locally and open it in the browser. Argument = empty.",
    "gods_eye_open": "Open the local God's Eye View console in the browser. Argument = empty.",
    "gods_eye_stop": "Stop the JARVIS-managed God's Eye View process. Argument = empty.",
    "gods_eye_contacts": "Read live aircraft contacts from God's Eye View's local OpenSky bridge. Argument = empty.",
    "gods_eye_vessels": "Read live vessel contacts from God's Eye View's AIS bridge. Argument = empty.",
    "gods_eye_satellites": "Read satellite TLE records exposed by God's Eye View/CelesTrak. Argument = stations, active, or starlink.",
    "gods_eye_launches": "Read the local God's Eye View launch feed. Argument = empty.",
    "gods_eye_cameras": "Read the public camera source catalog from God's Eye View. Argument = empty.",
    "gods_eye_radio": "Read the Radio Browser station catalog from God's Eye View. Argument = empty.",
    "gods_eye_transit": "Read registered public transit feeds from God's Eye View. Argument = empty.",
    "screen_memory_status": "Check the optional local Screenpipe memory bridge. Argument = empty.",
    "screen_memory_search": "Search Screenpipe's local screen/audio/UI memory. Argument = query text or JSON filters.",
    "screen_memory_recent": "Read recent Screenpipe memory from the local machine. Argument = optional time window such as '1h ago'.",
    "browser_page_snapshot": "Read a bounded structured snapshot of the current browser page: title, URL, headings, results, buttons, inputs, links, and cleaned readable text.",
    "browser_click_result": "Click a numbered or last organic Google/YouTube result. Argument is JSON.",
    "browser_back": "Navigate the controlled browser back one page.",
    "browser_find_element": "Find a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_click_element": "Click a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_fill_element": "Fill a browser input by CSS selector, visible text, or ARIA role with optional accessible name. Argument is JSON.",
    "browser_press_key": "Press a keyboard key on a browser element by CSS selector, visible text, or ARIA role with optional accessible name. Argument is JSON.",
    "browser_wait_for_element": "Wait for a browser DOM element to become visible using selector, text, role, or accessible name. Argument is JSON.",
    "browser_extract_text": "Extract text from a browser DOM element selected by selector, text, role, or accessible name. Argument is JSON.",
    "browser_find_text": "Search the readable text of the current browser page for a phrase and return nearby context. Argument is JSON.",
    "product_research": "Research a product or product category across multiple online sources. Compare reviews, prices, value, cheaper alternatives, and better-reviewed alternatives. Argument is the full user request or JSON.",
    "browser_click_first_result": "Click the first organic Google or YouTube result through the controlled browser DOM. Argument is JSON.",
    "weather": "Get current weather. argument = location, or empty for default.",
    "current_time": "Get current time. argument = timezone/city, or empty for local.",
    "current_date": "Get today's date. argument = empty.",
    "wait": "Wait N seconds. argument = number of seconds.",
    "open_website": "Open a website in the browser. argument = site name or URL.",
    "search_website": "Search a specific site. argument = 'site|query', e.g. 'youtube|iron man trailer'.",
    "open_program": "Launch a desktop application. argument = program name, e.g. 'notepad', 'chrome'.",
    "system_status": "Report computer and JARVIS subsystem status. argument = empty.",
    "startup_status": "Report whether JARVIS starts with Windows. argument = empty.",
    "enable_startup": "Configure JARVIS to start with Windows. argument = empty.",
    "disable_startup": "Disable JARVIS Windows startup. argument = empty.",
    "task_history": "Report recent JARVIS task history. argument = empty.",
    "create_folder": "Create a folder. argument = folder name.",
    "list_files": "List files in a folder. argument = folder path, or empty for current folder.",
    "find_file": "Search for a file by name. argument = filename.",
    "open_folder": "Open a folder in File Explorer. argument = folder path.",
    "write_file": "Write content to a file. argument = 'filename|||content' format.",
    "read_file": "Read content from a file. argument = filename.",
    "edit_file": "Edit a file by replacing text. argument = 'filename|||old_text|||new_text'.",
    "code_search": "Search project source files for a symbol, string, or error message.",
    "code_test": "Validate project code. argument = JSON such as {\"mode\":\"compile\",\"path\":\"main.py\"} or {\"mode\":\"pytest\",\"path\":\"tests/test_x.py\"}.",
    "code_diagnose": "Run a broader JARVIS project diagnostic pass: Python compilation, available tests, and optional static checks. Argument is JSON.",
    "dev_command": "Run an allowlisted developer command from the JARVIS project root. Argument is JSON such as {\"command\":\"python -m pytest tests/test_x.py -q\",\"timeout\":120}.",
    "git_task_branch": "Create or activate a safe task-scoped Git branch. Argument is JSON with branch.",
    "code_checkpoint": "Create a safe checkpoint of JARVIS project source files before autonomous edits.",
    "code_restore_checkpoint": "Restore the latest JARVIS source checkpoint after an unsuccessful repair.",
    "delete_file": "Delete a file. argument = filename.",
    "web_search": "Search the web for information. argument = search query.",
    "jarvis_status": "Report JARVIS's own status/uptime. argument = empty.",
    "capture_screen": "Take a screenshot. argument = empty.",
    "screen_size": "Get screen resolution. argument = empty.",
    "get_active_window": "Get the currently focused window. argument = empty.",
    "analyze_screen": "Describe what's on screen. argument = optional question about the screen.",
    "move_mouse": "Move the mouse to an on-screen target. argument = description of the target.",
    "click_screen": "Click an on-screen target. argument = description of the target.",
    "double_click_screen": "Double-click an on-screen target. argument = description of the target.",
    "scroll_screen": "Scroll the screen. argument = direction/amount, e.g. 'down', 'up 3'.",
    "verify_screen": "Verify the screen matches an expected state. argument = description of expected state.",
    "type_text": "Type text at the current cursor/focus. argument = the text to type.",
    "press_key": "Press a keyboard key or combo. argument = key name, e.g. 'enter', 'ctrl+c'.",

    "barehands_state": "Set the Barehands ring state. argument = idle, listening, thinking, or speaking.",
    "barehands_present": "Present a titled message on the Barehands glass board. argument = 'title|||body'.",
    "barehands_add_card": "Add a card to the Barehands glass board. argument = 'title|||body'.",
    "barehands_add_image": "Add an image to the Barehands glass board. argument = 'src|||title|||body'.",
    "barehands_clear": "Clear the Barehands glass board. argument = empty.",
    "barehands_board_state": "Read the current Barehands glass board state. argument = empty.",
}


# Browser tools whose arguments are JSON objects encoded as strings.


# ==========================================================
# Planner Scope
# ==========================================================

_RESEARCH_PLANNER_TOOLS = {
    "product_research",
}


_BROWSER_PLANNER_TOOLS = {
    name
    for name in AVAILABLE_TOOLS
    if name.startswith("browser_")
} | {
    "open_program",
    "open_website",
    "search_website",
    "capture_screen",
    "analyze_screen",
    "verify_screen",
}

_CODE_PLANNER_TOOLS = {
    "write_file",
    "read_file",
    "edit_file",
    "delete_file",
    "code_search",
    "code_test",
    "code_diagnose",
    "dev_command",
    "code_checkpoint",
    "code_restore_checkpoint",
    "list_files",
    "find_file",
}


ROBLOX_TOOL_PREFIX = "roblox__"

ROBLOX_FALLBACK_TOOL_DESCRIPTIONS = {
    "roblox__get_place_info": "Get the active Roblox place and Studio instance information.",
    "roblox__get_project_structure": "Get the Roblox Studio game hierarchy.",
    "roblox__search_files": "Search Roblox instances or script content.",
    "roblox__grep_scripts": "Search all Roblox script sources with line context.",
    "roblox__get_script_source": "Read a Roblox script source.",
    "roblox__edit_script_lines": "Make a targeted exact-text edit in a Roblox script.",
    "roblox__insert_script_lines": "Insert Luau into a Roblox script after a line.",
    "roblox__delete_script_lines": "Delete a range of lines from a Roblox script.",
    "roblox__execute_luau": "Execute Luau in Roblox Studio edit/plugin context.",
    "roblox__start_playtest": "Start a Roblox Studio playtest.",
    "roblox__get_playtest_output": "Read captured Roblox playtest output.",
    "roblox__stop_playtest": "Stop the active Roblox playtest.",
    "roblox__get_output_log": "Read Roblox Studio output log history.",
    "roblox__capture_screenshot": "Capture the Roblox Studio viewport.",
    "roblox__get_selection": "Read the currently selected Roblox Studio instances.",
    "roblox__set_property": "Set an instance property in Roblox Studio.",
    "roblox__create_object": "Create an instance in Roblox Studio.",
    "roblox__delete_object": "Delete an instance in Roblox Studio.",
}

ROBLOX_INSPECTION_TOOLS = frozenset({
    "roblox__get_file_tree",
    "roblox__search_files",
    "roblox__get_place_info",
    "roblox__get_services",
    "roblox__search_objects",
    "roblox__get_instance_properties",
    "roblox__get_instance_children",
    "roblox__search_by_property",
    "roblox__get_class_info",
    "roblox__get_project_structure",
    "roblox__mass_get_property",
    "roblox__get_script_source",
    "roblox__get_attributes",
    "roblox__get_tags",
    "roblox__get_tagged",
    "roblox__get_selection",
    "roblox__get_playtest_output",
    "roblox__get_connected_instances",
    "roblox__list_library",
    "roblox__search_materials",
    "roblox__get_build",
    "roblox__get_asset_details",
    "roblox__get_asset_thumbnail",
    "roblox__preview_asset",
    "roblox__get_descendants",
    "roblox__compare_instances",
    "roblox__get_output_log",
    "roblox__capture_screenshot",
    "roblox__grep_scripts",
})

ROBLOX_MUTATION_TOOLS = frozenset({
    "roblox__set_property",
    "roblox__mass_set_property",
    "roblox__set_properties",
    "roblox__create_object",
    "roblox__mass_create_objects",
    "roblox__delete_object",
    "roblox__smart_duplicate",
    "roblox__mass_duplicate",
    "roblox__clone_object",
    "roblox__set_script_source",
    "roblox__edit_script_lines",
    "roblox__insert_script_lines",
    "roblox__delete_script_lines",
    "roblox__set_attribute",
    "roblox__delete_attribute",
    "roblox__add_tag",
    "roblox__remove_tag",
    "roblox__execute_luau",
    "roblox__start_playtest",
    "roblox__stop_playtest",
    "roblox__create_build",
    "roblox__generate_build",
    "roblox__import_build",
    "roblox__import_scene",
    "roblox__insert_asset",
    "roblox__upload_asset",
    "roblox__simulate_mouse_input",
    "roblox__simulate_keyboard_input",
    "roblox__character_navigation",
    "roblox__undo",
    "roblox__redo",
    "roblox__bulk_set_attributes",
    "roblox__find_and_replace_in_scripts",
})

ROBLOX_TEST_TOOLS = frozenset({
    "roblox__start_playtest",
    "roblox__get_playtest_output",
    "roblox__stop_playtest",
    "roblox__get_output_log",
})

def is_roblox_tool_name(tool_name: str) -> bool:
    return str(tool_name or "").strip().startswith(ROBLOX_TOOL_PREFIX)


def is_roblox_request(text: str) -> bool:
    normalized = _normalized_words(text)

    if not normalized:
        return False

    signals = (
        "roblox",
        "roblox studio",
        "luau",
        "localscript",
        "modulescript",
        "playtest",
        "datamodel",
        "studio output",
    )

    return any(signal in normalized for signal in signals)


def is_roblox_mutation_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in ROBLOX_MUTATION_TOOLS


def get_roblox_planner_tools() -> Dict[str, str]:
    try:
        from roblox_mcp import get_roblox_planner_tool_descriptions

        live = get_roblox_planner_tool_descriptions()

        if live:
            return live
    except Exception as exc:
        logger.debug(
            f"JARVIS planner: Roblox MCP tool discovery unavailable: {exc}"
        )

    return dict(ROBLOX_FALLBACK_TOOL_DESCRIPTIONS)


def _deterministic_n8n_plan(
    user_command: str,
    active_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Route workflow-class requests directly to n8n without an LLM plan."""
    normalized = _normalized_words(user_command)

    if not normalized:
        return None

    # Explicit n8n status requests are observational and never delegated as a
    # workflow execution.
    if (
        "n8n" in normalized
        and any(
            phrase in normalized
            for phrase in (
                "status",
                "running",
                "reachable",
                "online",
                "connected",
                "connection",
                "available",
                "installed",
            )
        )
    ):
        return {
            "goal": "check n8n workflow orchestrator status",
            "steps": [
                {
                    "tool": "n8n_status",
                    "argument": "",
                },
            ],
            "resolved_command": user_command,
        }

    try:
        from n8n_bridge import classify_n8n_request
        workflow_class = classify_n8n_request(normalized)
    except Exception:
        workflow_class = None

    if workflow_class is None:
        return None

    return {
        "goal": f"delegate {workflow_class} workflow to n8n",
        "steps": [
            {
                "tool": "n8n_run_workflow",
                "argument": json.dumps(
                    {
                        "request": str(user_command).strip(),
                        "workflow_class": workflow_class,
                        "context": (
                            dict(active_context)
                            if isinstance(active_context, dict)
                            else {}
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "resolved_command": user_command,
        "execution_owner": "n8n",
        "workflow_class": workflow_class,
    }


def _deterministic_roblox_plan(
    user_command: str,
) -> Optional[Dict[str, Any]]:
    """Handle obvious Roblox Studio requests without relying on the LLM."""
    normalized = _normalized_words(user_command)

    if not normalized or not is_roblox_request(normalized):
        return None

    connection_signals = (
        "connection",
        "connected",
        "connectivity",
        "status",
        "available",
        "online",
    )

    if any(signal in normalized for signal in connection_signals):
        return {
            "goal": "check Roblox Studio MCP connection",
            "steps": [
                {
                    "tool": "roblox_mcp_status",
                    "argument": "",
                }
            ],
            "resolved_command": user_command,
        }

    identifier_signals = (
        "place id",
        "game id",
        "place identifier",
        "game identifier",
        "place and game id",
        "place and game identifiers",
    )

    if any(signal in normalized for signal in identifier_signals):
        return {
            "goal": "get Roblox place and game IDs",
            "steps": [
                {
                    "tool": "roblox__get_place_info",
                    "argument": "{}",
                },
            ],
            "resolved_command": user_command,
        }

    diagnostic_signals = (
        "error",
        "errors",
        "broken",
        "bug",
        "bugs",
        "diagnose",
        "diagnostic",
        "debug",
        "investigate",
        "not working",
        "wrong",
    )

    if any(signal in normalized for signal in diagnostic_signals):
        return {
            "goal": "inspect Roblox Studio project for problems",
            "steps": [
                {
                    "tool": "roblox__get_place_info",
                    "argument": "{}",
                },
                {
                    "tool": "roblox__get_project_structure",
                    "argument": "{}",
                },
                {
                    "tool": "roblox__search_files",
                    "argument": '{"query":"Script","searchType":"type"}',
                },
                {
                    "tool": "roblox__get_output_log",
                    "argument": "{}",
                },
            ],
            "resolved_command": user_command,
        }

    inspection_signals = (
        "inspect",
        "inspection",
        "explore",
        "look at",
        "view",
        "show",
        "check",
    )

    if any(signal in normalized for signal in inspection_signals):
        return {
            "goal": "inspect Roblox Studio project",
            "steps": [
                {
                    "tool": "roblox__get_place_info",
                    "argument": "{}",
                },
                {
                    "tool": "roblox__get_project_structure",
                    "argument": "{}",
                },
            ],
            "resolved_command": user_command,
        }

    return None


def _deterministic_roblox_context_plan(
    user_command: str,
    active_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Handle common Roblox follow-ups without losing the Studio domain."""
    if not isinstance(active_context, dict):
        return None

    site = str(
        active_context.get("site", "") or ""
    ).strip().lower()

    last_tool = str(
        active_context.get("last_tool", "") or ""
    ).strip().lower()

    normalized = _normalized_words(user_command)

    if not normalized:
        return None

    # Strong Roblox/gameplay language is sufficient to preserve the local
    # Studio domain even when the previous Roblox MCP call failed before it
    # could establish ActiveContext.
    implicit_roblox = any(
        phrase in normalized
        for phrase in (
            "core gameplay",
            "gameplay system",
            "gameplay systems",
            "gameplay scripts",
            "scripts that control the gameplay",
            "scripts that control gameplay",
            "script that controls the gameplay",
            "script that controls gameplay",
            "remote events",
            "remote functions",
            "server scripts",
            "local scripts",
            "module scripts",
            "modulescripts",
        )
    )

    if (
        site != "roblox"
        and not last_tool.startswith(ROBLOX_TOOL_PREFIX)
        and not implicit_roblox
    ):
        return None

    if (
        "find the scripts" in normalized
        or "find scripts" in normalized
        or "find the script" in normalized
        or "find scripts that" in normalized
        or "find the scripts that" in normalized
    ):
        return {
            "goal": "find Roblox gameplay scripts",
            "steps": [
                {
                    "tool": "roblox__search_files",
                    "argument": '{"query":"Script","searchType":"type"}',
                },
            ],
            "resolved_command": user_command,
        }

    return None


def _roblox_safe_fallback_plan(
    user_command: str,
) -> Dict[str, Any]:
    """Return a read-only Roblox plan when the model cannot produce one."""
    deterministic = _deterministic_roblox_plan(user_command)

    if deterministic is not None:
        return deterministic

    return {
        "goal": "inspect Roblox Studio project",
        "steps": [
            {
                "tool": "roblox__get_project_structure",
                "argument": "{}",
            },
        ],
        "resolved_command": user_command,
    }



_ANIPY_PLANNER_TOOLS = {
    "anipy_cli",
    "anipy_providers",
    "anipy_search",
    "anipy_info",
    "anipy_episodes",
    "anipy_get_video",
    "anipy_download",
}

_UNREAL_MCP_PLANNER_TOOLS = {
    "unreal_mcp",
    "unreal_mcp_status",
    "unreal_mcp_setup",
}

_CONTEXT_MEMORY_PLANNER_TOOLS = {
    "context_backend_status",
    "context_recall",
    "context_search",
    "context_read",
}

_AGENT_SKILL_PLANNER_TOOLS = {
    "skills_status",
    "skills_search",
    "skills_read",
    "harness_review",
}

def _planner_tool_scope(
    user_command: str,
    active_context: Optional[Dict[str, Any]] = None,
) -> Optional[set[str]]:
    """Return a narrow planner tool scope for clearly typed task domains."""
    text = str(user_command or "").strip().lower()

    if not text:
        return None

    try:
        from n8n_bridge import classify_n8n_request
        if classify_n8n_request(text) is not None or (
            "n8n" in text
            and any(
                phrase in text
                for phrase in (
                    "status",
                    "running",
                    "reachable",
                    "online",
                    "connected",
                    "connection",
                )
            )
        ):
            return {
                "n8n_status",
                "n8n_run_workflow",
            }
    except Exception:
        pass

    if is_roblox_request(text):
        roblox_tools = set(get_roblox_planner_tools().keys())
        roblox_tools.add("roblox_mcp_status")
        return roblox_tools

    # Preserve Roblox domain context across natural follow-up commands.
    # After JARVIS has inspected a Studio place, requests such as
    # "find the scripts that control the core gameplay systems" do not need
    # to repeat the word "Roblox" to remain in the Roblox tool scope.
    context_site = ""
    context_tool = ""
    if isinstance(active_context, dict):
        context_site = str(
            active_context.get("site", "") or ""
        ).strip().lower()
        context_tool = str(
            active_context.get("last_tool", "") or ""
        ).strip().lower()

    if (
        context_site == "unreal"
        or context_tool in {"unreal_mcp", "unreal_mcp_status"}
    ):
        unreal_followup_signals = (
            "actor",
            "asset",
            "blueprint",
            "level",
            "world",
            "material",
            "mesh",
            "component",
            "physics",
            "animation",
            "sequencer",
            "niagara",
            "ai",
            "audio",
            "camera",
            "viewport",
            "inspect",
            "create",
            "delete",
            "edit",
            "build",
            "test",
        )
        if any(signal in text for signal in unreal_followup_signals):
            return _UNREAL_MCP_PLANNER_TOOLS

    if (
        context_site == "roblox"
        or context_tool.startswith(ROBLOX_TOOL_PREFIX)
    ):
        roblox_followup_signals = (
            "game",
            "script",
            "scripts",
            "module",
            "modules",
            "gameplay",
            "system",
            "systems",
            "studio",
            "place",
            "instance",
            "output",
            "error",
            "bug",
            "broken",
            "inspect",
            "find",
            "search",
            "structure",
        )

        if any(signal in text for signal in roblox_followup_signals):
            roblox_tools = set(get_roblox_planner_tools().keys())
            roblox_tools.add("roblox_mcp_status")
            return roblox_tools

    anime_domain_signals = (
        "anime",
        "anipy",
        "anilist",
        "myanimelist",
        "anime episode",
        "anime episodes",
    )

    anime_action_signals = (
        "watch",
        "play",
        "stream",
        "download",
        "search",
        "find",
        "episode",
        "episodes",
        "provider",
        "seasonal",
        "dub",
        "sub",
    )

    if (
        any(signal in text for signal in anime_domain_signals)
        and any(signal in text for signal in anime_action_signals)
    ):
        return _ANIPY_PLANNER_TOOLS

    unreal_domain_signals = (
        "unreal",
        "unreal engine",
        "unreal editor",
        "ue5",
        "ue 5",
        "ue editor",
        "ue project",
    )

    unreal_action_signals = (
        "build",
        "spawn",
        "actor",
        "blueprint",
        "asset",
        "material",
        "level",
        "world",
        "niagara",
        "particle",
        "animation",
        "physics",
        "sequencer",
        "cinematic",
        "audio",
        "ai",
        "behavior tree",
        "pcg",
        "geometry",
        "networking",
        "render",
        "camera",
        "viewport",
        "play",
        "playtest",
        "test",
        "inspect",
        "import",
        "delete",
        "create",
        "edit",
    )

    if any(signal in text for signal in unreal_domain_signals) and (
        any(signal in text for signal in unreal_action_signals)
        or "mcp" in text
    ):
        return _UNREAL_MCP_PLANNER_TOOLS

    skill_domain_signals = (
        "skill",
        "agent skill",
        "cybersecurity",
        "cyber security",
        "threat hunting",
        "incident response",
        "security analysis",
        "diagram",
        "architecture diagram",
        "flowchart",
        "scientific",
        "science",
        "research workflow",
        "bioinformatics",
        "chemistry",
        "biology",
        "harness engineering",
        "agent harness",
    )

    if any(signal in text for signal in skill_domain_signals):
        return (
            set(_AGENT_SKILL_PLANNER_TOOLS)
            | set(_CONTEXT_MEMORY_PLANNER_TOOLS)
            | set(_CODE_PLANNER_TOOLS)
        )

    code_signals = (
        "code",
        "coding",
        "python",
        "javascript",
        "typescript",
        "source file",
        "stack trace",
        "exception",
        "traceback",
        "compile",
        "pytest",
        "refactor",
        "repository",
        "git",
        "bug",
        "debug",
        "repair",
    )

    research_signals = (
        "product research",
        "product",
        "products",
        "reviews",
        "review",
        "alternative",
        "alternatives",
        "cheaper",
        "best",
        "cheapest",
        "best value",
        "best price",
        "worth buying",
        "which should i buy",
        "compare prices",
        "compare products",
    )

    browser_signals = (
        "browser",
        "chrome",
        "website",
        "web page",
        "webpage",
        "google",
        "youtube",
        "bing",
        "url",
        "link",
        "button",
        "search box",
        "search field",
        "textbox",
        "email field",
        "sign in",
        "pricing",
        "page",
        "navigate",
        "click",
        "fill",
        "press enter",
        "scroll",
        "download",
    )

    if any(signal in text for signal in code_signals):
        return set(_CODE_PLANNER_TOOLS) | set(_AGENT_SKILL_PLANNER_TOOLS) | {"context_recall", "context_search"}

    # Product/review/price research has its own orchestration tool. Keep the
    # planner from expanding one research request into dozens of fragile DOM steps.
    if any(signal in text for signal in research_signals) and (
        any(
            word in text
            for word in (
                "find",
                "research",
                "review",
                "compare",
                "recommend",
                "buy",
                "price",
                "alternative",
            )
        )
        or "under" in text
        or "below" in text
        or "$" in text
    ):
        return _RESEARCH_PLANNER_TOOLS

    if any(signal in text for signal in browser_signals):
        return _BROWSER_PLANNER_TOOLS

    return None


# ==========================================================
# Planner Prompt
# ==========================================================

def _planner_prompt(
    tool_names: Optional[set[str]] = None,
) -> str:
    """Build the planner prompt with available tools."""
    if not tool_names:
        selected_tools = dict(AVAILABLE_TOOLS)
    else:
        selected_tools = {
            name: AVAILABLE_TOOLS[name]
            for name in AVAILABLE_TOOLS
            if name in tool_names
        }

        if any(
            str(name).startswith(ROBLOX_TOOL_PREFIX)
            for name in tool_names
        ):
            selected_tools.update(
                {
                    name: description
                    for name, description in get_roblox_planner_tools().items()
                    if name in tool_names
                }
            )

    tool_list = "\n".join(
        f"{name}: {desc}"
        for name, desc in selected_tools.items()
    )
    return f"""
You are JARVIS's task planner â€” an expert software engineer and systems architect.

Your job: convert a user request into a list of tool calls.

If the request needs no tool (a question, chit-chat, opinion,
or something you'd just answer in conversation), return an
empty steps list.

Available tools for this request:

{tool_list}

Tool-scope rule:
- Use only tools in the scoped list above.
- Prefer a deterministic browser tool over screen automation when available.
- Do not invent tools or switch domains without evidence from the request.

Rules:

ANIPY-CLI RULES:

- Preserve the upstream anipy-cli tool rather than recreating or disabling its native modes.
- Use anipy_cli for the full native CLI, including watch, download, binge, seasonal, AniList, MyAnimeList, history, local-file/native-provider workflows, players, Discord presence, configuration, and command-line options.
- Use anipy_search, anipy_info, anipy_episodes, and anipy_get_video for structured read-only anime operations.
- Use anipy_download only when the request specifies an episode or explicit episode range; it uses the upstream Downloader/configuration path.
- Do not route anime requests to generic browser tools when an anipy tool can satisfy the request.

UNREAL ENGINE / UNREAL_MCP RULES:

- Use unreal_mcp for Unreal Engine actions through the upstream `unreal` gateway; do not recreate the upstream capability families in JARVIS.
- Follow the upstream workflow: `search` capability -> `describe` the exact capability/parameters when needed -> `execute` the validated action.
- Preserve exact upstream canonical capability names, legacy tool/action aliases, selectors, and parameter names returned by the gateway.
- Do not invent Unreal asset paths, actor names, capability ids, or parameter names. Reuse values returned by Unreal MCP observations.
- Use unreal_mcp_status for connection/authentication checks and unreal_mcp_setup only for explicit setup requests.
- Unreal MCP execution is an external side effect inside the Unreal Editor. Do not retry destructive execute/configure operations automatically.

WINDOWS STARTUP AND RUNTIME STATUS:

- Use system_status when the user asks about computer or JARVIS subsystem health.
- Use startup_status when the user asks whether JARVIS starts with Windows.
- Use enable_startup when the user asks JARVIS to start automatically with Windows.
- Use disable_startup when the user asks JARVIS to stop starting with Windows.
- Use task_history when the user asks what JARVIS has recently done.

BAREHANDS TOOL SELECTION:

- jarvis_status is for reporting JARVIS's own internal status or uptime.
- barehands_present is for presenting information on the Barehands glass board.
- If the user asks to show, display, present, put, or place information
  on the Barehands display or glass board, use barehands_present.
- A request to display JARVIS status on Barehands is a display request,
  not a jarvis_status query; use barehands_present rather than jarvis_status.

N8N WORKFLOW ORCHESTRATION RULES:

When a request is about scheduling, recurring work, persistent monitoring,
conditional notifications, external-service integrations, or explicit workflow
orchestration, prefer n8n as the execution owner. External-service actions are
n8n-first even when they are a single action (for example, sending an email,
creating a GitHub issue, updating a calendar, or controlling a supported media
service). JARVIS should not recreate an integration locally when n8n can own it.
- Use n8n_run_workflow with JSON containing request, workflow_class, and context.
- Do not replace an n8n workflow with local wait loops or ad-hoc JARVIS code.
- n8n owns workflow retries, waiting, branching, and external-service state.
- JARVIS owns the real-time voice, browser, Roblox, computer-control, and code-repair loops.
- If n8n is unavailable, report the n8n failure instead of silently executing a different workflow.

ROBLOX STUDIO MCP RULES:

When the request targets Roblox Studio, use the roblox__ tools instead of JARVIS filesystem tools.
- Use the live Roblox MCP tool names and their JSON schemas exactly.
- Discover the game structure or search scripts before making a Roblox code change.
- Read the exact Luau source with roblox__get_script_source before editing it.
- Prefer roblox__edit_script_lines for small targeted changes; use insert/delete line tools when appropriate.
- Do not replace an entire script with roblox__set_script_source unless the change genuinely requires it.
- After a code or gameplay change, start a playtest and inspect roblox__get_playtest_output and/or roblox__get_output_log.
- When a playtest reports an error, use that output as evidence for the next repair.
- Do not invent Roblox instance paths. Reuse exact paths returned by previous Roblox MCP observations.
- Keep Roblox MCP arguments as JSON objects.

CODE REPAIR RULES:

When the user asks JARVIS to fix, debug, repair, diagnose, inspect,
refactor, modify, patch, or test software:

1. Treat the request as an actionable task, not ordinary conversation.
2. Inspect the relevant project files before editing.
3. Use code_search to locate symbols, error messages, and likely call sites.
4. Use read_file to inspect the surrounding implementation.
5. Make the smallest targeted change needed.
6. Before modifying project code, create a code_checkpoint.
7. Use code_test after changes. Prefer py_compile for individual Python files,
   and pytest for relevant automated tests.
8. For browser automation in this project, browser_controller.py is the
   primary browser implementation file. Do not invent a filename such as
   browser_automation.py when browser_controller.py is the relevant module.
9. Do not invent file paths. When the target file is uncertain, discover it
   with code_search, list_files, or find_file before reading or modifying it.
10. Do not claim a fix is complete until validation succeeds.
11. If validation fails, inspect the failure, revise the change, and test again.
12. If repeated repair attempts are unsuccessful, use code_restore_checkpoint
    before reporting that the task could not be completed.
13. For multi-step repairs, keep working through the task instead of returning
    code or instructions for the user to apply manually.
14. Treat software work as an iterative engineering loop: inspect, diagnose,
    plan the smallest safe change, checkpoint, modify, validate, inspect failures,
    and repeat until the requested behavior is verified.
15. When the user asks JARVIS to diagnose or repair itself, prefer
    code_diagnose first when the failure or target is not already known.
16. Use validation output as evidence. Never replace a failing implementation
    with a guessed fix without reading the relevant source and understanding the
    failure.
17. For code creation, do not stop after writing files. Run an appropriate
    validation step and repair the generated implementation when validation fails.
18. Use dev_command only for controlled development operations when the
existing file/search/test tools cannot perform the required step. Never use
shell operators, pipes, or command chaining; pass one developer command.

INTERNAL PHASE OVERRIDES:

JARVIS may prepend an internal phase marker to a planning request. When one is
present, it is authoritative and overrides generic planning preferences:

- [JARVIS_INTERNAL_PHASE:SOURCE_READ]
  Return a minimal inspection plan containing read_file for the verified target.
  Do not edit files and do not add unrelated discovery steps.

- [JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]
  Return a minimal diagnostic plan containing code_diagnose for the verified
  target. Do not use code_test instead. Do not edit files. Prefer a narrow
  targeted diagnostic argument such as:
  {{"path":"target.py","run_tests":false,"run_lint":false,"run_types":false}}

- [JARVIS_INTERNAL_PHASE:REPAIR]
  Use the verified evidence supplied in the request. Return the smallest safe
  repair plan with code_checkpoint before mutation and code_test after mutation.
  Do not repeat generic discovery unless the evidence explicitly shows that
  another focused source read is required.
  For edit_file, the argument MUST be exactly:
  filename|||old_text|||new_text
  Use three literal pipe characters between all three fields. Never use ||
  between old_text and new_text.

DEVELOPER COMMAND RULES:

- Use dev_command for dependency installation, targeted test execution,
  static-analysis commands, or other necessary developer tooling.
- Prefer the active JARVIS Python interpreter for Python and pip commands.
- Keep commands project-scoped and do not use shell chaining.
- Treat command output as evidence for subsequent repair decisions.

AUTONOMOUS SOFTWARE ENGINEERING LOOP:

For coding, debugging, repair, and self-diagnosis tasks, JARVIS should
behave like a careful senior engineer working directly in the project:

1. Discover the real project files and relevant symbols.
2. Run the narrowest useful diagnostic first.
3. Read the exact source involved in the failure.
4. Form a concrete hypothesis from the evidence.
5. Create a checkpoint before modifying source.
6. Apply the smallest targeted change.
7. Re-run focused tests, then broader validation when appropriate.
8. If validation fails, treat the failure output as new evidence and iterate.
9. Stop only when the requested behavior is verified, or when the evidence
   shows that the problem cannot be safely completed.

PRODUCT RESEARCH RULES:

When the user asks to find products, compare prices, inspect reviews, or locate
cheaper/better alternatives, prefer the product_research tool as the primary
orchestration tool. It searches multiple result sets and source types, gathers
bounded evidence, and returns separate best-match, value, cheaper-option, and
better-reviewed outcomes. The argument may be the full user request or JSON
such as {{"item":"wireless headphones","budget":150,"request":"find the best
one and compare reviews"}}. Do not replace it with a long sequence of generic
browser clicks unless the request specifically asks for a particular website
workflow.

PUBLIC API RULES:

Use structured public APIs when they are a better source than
browser automation.

Prefer these tools when the request matches their purpose:

- holiday_lookup for public holiday questions.
- knowledge_lookup for concise factual topic lookups.
- book_search for books, authors, editions, and basic book metadata.
- define_word for dictionary definitions.
- research_arxiv for scientific and research paper discovery.
- research_crossref for scholarly publication metadata.
- vehicle_lookup for VIN decoding.
- earthquake_search for earthquake information.
- api_discover when JARVIS needs to find another free/no-auth API.
- country_info for country metadata.
- crypto_price for live cryptocurrency quotes.
- trivia_question and joke for lightweight entertainment requests.
- meal_search for recipes and meal ideas.
- tv_search, music_search, musicbrainz_search, anime_search, and ghibli_search for media discovery.
- openalex_search and pubchem_lookup for research and scientific lookups.
- art_search for Art Institute of Chicago collections.
- nasa_eonet for current NASA natural-event information.
- sunrise_sunset, topo_elevation, reverse_geocode, and osm_search for geographic utilities.
- news_search for recent news discovery.
- public_ip for the current external IP address.
- cat_fact and dog_image for lightweight fun/media requests.

God's Eye View and Screenpipe are optional local capabilities:
- Use gods_eye_status/setup/start/open/stop for the local God's Eye View console.
- Use gods_eye_contacts, gods_eye_launches, gods_eye_cameras, gods_eye_radio, and gods_eye_transit for data exposed by a running GEV instance.
- Use screen_memory_status/search/recent only when the local Screenpipe service is configured and reachable.

Do not use these APIs as a replacement for web research when the
user needs current prices, shopping comparisons, reviews, news,
or information that requires live web pages.

For product research, continue using the existing product_research
and browser/web tools.

API arguments should normally be plain strings unless the tool
description explicitly specifies another format.

GENERIC BROWSER DOM RULES:

When controlling a browser, prefer browser_* DOM tools over
screen-coordinate tools whenever the target can be located in
the page DOM.

Browser workflow:

1. Navigate to the intended page.
2. Inspect the page with browser_page_info or browser_find_element.
3. For semantic controls, prefer ARIA role plus accessible name, for example
   {{"role":"button","name":"Sign in"}} or {{"role":"textbox","name":"Email"}}.
4. Use browser_fill_element for text inputs.
5. Use browser_press_key for Enter or other keyboard actions.
6. Use browser_click_element for links, buttons, tabs, menus, and controls.
7. Use browser_wait_for_element when content may load asynchronously.
8. Use browser_extract_text or browser_page_info to verify the result.
9. Use browser_find_text when the user asks to find a phrase or information
   somewhere in the current page's readable content.
10. Use browser_click_result for second, third, or last search results.
11. Use browser_refresh for refresh/reload requests.
12. Use browser_forward for forward-navigation requests.
13. Use browser_current_tab when the user asks which tab/page is active.
14. Use browser_new_tab to open a new tab, especially when the user explicitly says "new tab".
15. Use browser_switch_tab/browser_close_tab for explicit tab management.
16. Use browser_get_links when the user asks what links are on the page.
17. Use browser_open_link when a specific visible link needs to be opened.
18. Use browser_scroll for page scrolling when DOM scrolling is sufficient.
19. Use browser_back for requests to go back to the previous page.
11. When an action fails, use the browser state and observations to
   choose a different strategy during replanning.

DOM TOOL ARGUMENT FORMAT:

DOM browser tools use a JSON object encoded as the step's argument string.
Supported target fields are selector, text, role, and optional name.
"name" is an accessible-name filter used with "role".

Examples:

browser_find_element
argument = {{"role":"searchbox"}}

browser_find_element
argument = {{"role":"button","name":"Sign in"}}

browser_find_element
argument = {{"text":"Sign in"}}

browser_find_element
argument = {{"selector":"button[type=submit]"}}

browser_fill_element
argument = {{"role":"searchbox","value":"Iron Man trailer"}}

browser_press_key
argument = {{"role":"searchbox","key":"Enter"}}

browser_click_element
argument = {{"role":"button","name":"Submit"}}

browser_wait_for_element
argument = {{"role":"heading","name":"Results","timeout":10000}}

browser_extract_text
argument = {{"selector":"main"}}

browser_find_text
argument = {{"query":"pricing"}}

Browser rules:

- Every DOM tool argument MUST be valid JSON.
- Prefer ARIA roles and visible text over fragile CSS selectors.
- Do not invent CSS selectors when a stable semantic target exists.
- Do not use screen coordinates for browser interaction when a DOM
  action can perform the same operation.
- Keep browser actions atomic: one action per step.
- Do not assume a click succeeded; verify the resulting state.
- Use browser_page_info after important navigation or interactions.
- Use browser_extract_text when a specific DOM element's text must be inspected.
- Use browser_find_text when the requested information may appear anywhere
  in the current page text.
- Use browser_find_element before acting when element existence is uncertain.
- Use browser_wait_for_element when the page may still be loading.
- Use the specialized Bing/YouTube browser tools when their deterministic
  behavior is clearly more reliable.
- Do not combine multiple DOM operations into one step.

1. Return ONLY JSON. No explanation.
2. Every step must use exactly one tool name from the list above.
3. "argument" must always be a string (use "" if the tool needs none).
4. For complex requests, break them into multiple steps.
   Example: "Create a todo app" -> write index.html, write styles.css, write app.js
5. Never invent a tool name that isn't in the list.
6. If unsure whether a tool applies, return an empty steps list
   instead of guessing.
7. When generating code, include ALL necessary files.
8. Prefer single HTML files for web apps (embed CSS/JS).
9. For multi-file projects, order steps logically (styles before scripts).

Multi-Step Examples:

User:
Create a todo app with HTML, CSS, and JavaScript

Output:
{{
"goal": "create todo app",
"steps": [
  {{"tool": "write_file", "argument": "todo.html|||<!DOCTYPE html>\\n<html>\\n<head>\\n<title>Todo App</title>\\n<link rel=\"stylesheet\" href=\"styles.css\">\\n</head>\\n<body>\\n<div id=\"app\">\\n<input id=\"new-todo\" type=\"text\">\\n<button id=\"add-btn\">Add</button>\\n<ul id=\"todo-list\"></ul>\\n</body>\\n</html>"}},
  {{"tool": "write_file", "argument": "styles.css|||#app {{ max-width: 400px; margin: 50px auto; padding: 20px; }}\\n.todo-item {{ padding: 10px; border: 1px solid #ccc; margin: 5px 0; }}"}}
]
}}

User:
Set up a Python project with a main script and requirements file

Output:
{{
"goal": "create python project",
"steps": [
  {{"tool": "write_file", "argument": "requirements.txt|||requests>=2.31.0\\npytest>=7.4.0"}},
  {{"tool": "write_file", "argument": "main.py|||# Main application\\nimport requests\\n\\ndef main():\\n    print('Hello World')\\n\\nif __name__ == '__main__':\\n    main()"}}
]
}}

User:
What's the weather in Belvidere, IL?

Output:
{{
"goal": "check weather",
"steps": [
  {{"tool": "weather", "argument": "Belvidere, IL"}}
]
}}

User:
Search YouTube for the Iron Man trailer

Output:
{{
"goal": "search youtube",
"steps": [
  {{"tool": "search_website", "argument": "youtube|Iron Man trailer"}}
]
}}

User:
Tell me a joke

Output:
{{
"goal": "conversation",
"steps": []
}}

User:
Tell me a story about Iron Man

Output:
{{
"goal": "conversation",
"steps": []
}}

IMPORTANT: When the user asks you to CREATE, WRITE, or BUILD something (code, scripts, games, documents), you MUST generate the complete, working content yourself and use the write_file tool. Do NOT say you can't do it - just generate the code and write it.

CRITICAL: Requests to tell a story, joke, or share creative content are CONVERSATIONAL â€” return an empty steps list. JARVIS generates creative content directly, it does not search the web for stories. Examples that should return empty steps:
- "Tell me a story about X"
- "Write a joke"
- "Create a poem"
- "Tell me a fun fact"
- "Say something creative"
"""


# ==========================================================
# JSON Extraction
# ==========================================================

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from a string, handling markdown code blocks."""
    if not text:
        return None

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ==========================================================
# Planner Quality Gates
# ==========================================================

CODE_REPAIR_TERMS = (
    "fix",
    "repair",
    "refactor",
    "modify",
    "patch",
    "resolve",
    "broken",
    "not working",
    "doesn't work",
    "doesnt work",
    "self-heal",
    "self heal",
)

CODE_DIAGNOSTIC_TERMS = (
    "debug",
    "diagnose",
    "inspect",
    "investigate",
    "test",
    "broken",
    "not working",
    "doesn't work",
    "doesnt work",
    "crash",
    "crashed",
    "failure",
)

SOFTWARE_DOMAIN_TERMS = (
    "code",
    "script",
    "software",
    "jarvis",
    "runtime",
    "project",
    "automation",
    "browser",
    "python",
    "javascript",
    "program",
    "bug",
    "error",
    "exception",
    "traceback",
    "module",
    "repository",
    "codebase",
    "app",
    "application",
    "website",
    "game",
    "roblox",
    "luau",
    "roblox studio",
    "playtest",
    ".py",
    ".js",
)

SOFTWARE_CHANGE_DOMAIN_TERMS = SOFTWARE_DOMAIN_TERMS + (
    "function",
    "capability",
)

CODE_INSPECTION_TOOLS = {
    "code_search",
    "code_diagnose",
    "read_file",
    "list_files",
    "find_file",
}

CODE_MUTATION_TOOLS = {
    "write_file",
    "edit_file",
    "delete_file",
}


def _normalized_words(text: str) -> str:
    return " ".join(
        str(text or "").strip().lower().split()
    )


def is_explicit_self_repair_request(text: str) -> bool:
    """Return True only when the request targets JARVIS's own code and asks for a repair."""
    normalized = _normalized_words(text)

    self_directed = any(
        phrase in normalized
        for phrase in (
            "fix yourself",
            "repair yourself",
            "diagnose yourself",
            "self diagnose",
            "self-diagnose",
            "improve yourself",
            "upgrade yourself",
            "make yourself better",
            "make yourself smarter",
            "improve your own code",
            "upgrade your own code",
            "run a full diagnostic on yourself",
            "run a full diagnostic on your own code",
            "audit yourself",
            "audit your own code",
            "find bugs in your own code",
            "check yourself for bugs",
            "check your own code",
            "inspect your own code",
        )
    )

    repair_requested = (
        any(
            term in normalized
            for term in CODE_REPAIR_TERMS
        )
        or any(
            phrase in normalized
            for phrase in (
                "improve yourself",
                "upgrade yourself",
                "make yourself better",
                "make yourself smarter",
                "improve your own code",
                "upgrade your own code",
            )
        )
    )

    return self_directed and repair_requested


def is_observation_only_request(text: str) -> bool:
    """Return True when a request explicitly forbids modifications."""
    normalized = _normalized_words(text)

    if not normalized:
        return False

    return any(
        phrase in normalized
        for phrase in (
            "before changing anything",
            "before making any changes",
            "before changing the game",
            "before modifying anything",
            "before making modifications",
            "without changing anything",
            "without making changes",
            "without modifying anything",
            "without modifying the game",
            "without editing anything",
            "do not change anything",
            "don't change anything",
            "do not modify anything",
            "don't modify anything",
            "do not edit anything",
            "don't edit anything",
            "no changes yet",
            "no modifications yet",
            "read only",
            "read-only",
        )
    )


def is_software_repair_request(text: str) -> bool:
    normalized = _normalized_words(text)

    explicit_self_repair = any(
        phrase in normalized
        for phrase in (
            "fix yourself",
            "repair yourself",
            "improve yourself",
            "upgrade yourself",
            "make yourself better",
            "make yourself smarter",
            "improve your own code",
            "upgrade your own code",
            "self diagnose and fix",
            "self-diagnose and fix",
            "diagnose yourself and fix",
            "diagnose yourself and repair",
            "run a full diagnostic on yourself and fix",
            "run a full diagnostic on yourself and repair",
            "audit yourself and fix",
            "audit your own code and fix",
            "find bugs in your own code and fix",
            "check your own code and fix",
            "fix your own code",
            "repair your own code",
        )
    )

    explicit_self_diagnostic_repair = (
        any(
            phrase in normalized
            for phrase in (
                "diagnose yourself",
                "self diagnose",
                "self-diagnose",
                "run a full diagnostic on yourself",
                "run a full diagnostic on your own code",
                "audit yourself",
                "audit your own code",
                "check yourself for bugs",
                "check your own code",
                "inspect your own code",
                "find bugs in your own code",
            )
        )
        and any(
            term in normalized
            for term in CODE_REPAIR_TERMS
        )
    )

    return explicit_self_repair or explicit_self_diagnostic_repair or (
        any(term in normalized for term in CODE_REPAIR_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def is_software_diagnostic_request(text: str) -> bool:
    normalized = _normalized_words(text)

    explicit_self_diagnostic = any(
        phrase in normalized
        for phrase in (
            "diagnose yourself",
            "self diagnose",
            "self-diagnose",
            "run a full diagnostic on yourself",
            "run a full diagnostic on your own code",
            "audit yourself",
            "audit your own code",
            "check yourself for bugs",
            "check your own code",
            "inspect your own code",
            "find bugs in your own code",
        )
    )

    return explicit_self_diagnostic or (
        any(term in normalized for term in CODE_DIAGNOSTIC_TERMS)
        and any(term in normalized for term in SOFTWARE_DOMAIN_TERMS)
    )


def is_software_change_request(text: str) -> bool:
    """Return True for software feature/change work that should be validated."""
    normalized = _normalized_words(text)

    change_terms = (
        "add",
        "implement",
        "integrate",
        "enhance",
        "improve",
        "upgrade",
        "introduce",
        "enable",
        "support",
        "build",
        "create",
        "make",
        "write",
        "generate",
        "change",
    )

    explicit_self_change = any(
        phrase in normalized
        for phrase in (
            "change your own code",
            "modify your own code",
            "improve yourself",
            "add a feature to yourself",
            "add a feature to jarvis",
            "add a function to jarvis",
        )
    )

    return explicit_self_change or (
        any(term in normalized for term in change_terms)
        and any(term in normalized for term in SOFTWARE_CHANGE_DOMAIN_TERMS)
    )


def _plan_has_test_mutation(tool_names: list[str], steps: list[dict]) -> bool:
    """Return True when a plan mutates a conventional test target."""
    for step, tool in zip(steps, tool_names):
        if tool not in {"edit_file", "write_file", "delete_file"}:
            continue

        argument = str(step.get("argument", "") or "")
        target = argument.split("|||", 1)[0].strip()
        if is_test_target(target):
            return True

    return False


def assess_plan(
    user_command: str,
    plan: Dict[str, Any],
    require_modification: Optional[bool] = None,
    require_code_read: bool = False,
    require_code_test: bool = False,
    require_code_diagnose: bool = False,
    allow_prior_evidence: bool = False,
) -> List[str]:
    """
    Return planner-quality issues for code/automation repair tasks.

    These are pre-execution guardrails: an incomplete candidate plan is
    rejected and given one chance to be repaired by the planner.
    """
    steps = (
        plan.get("steps", [])
        if isinstance(plan, dict)
        else []
    )

    if not (
        is_software_diagnostic_request(user_command)
        or is_software_change_request(user_command)
        or is_software_repair_request(user_command)
    ):
        return []

    if require_modification is None:
        require_modification = (
            is_software_repair_request(user_command)
            and not is_observation_only_request(user_command)
        )

    tool_names = [
        str(
            step.get("tool", "")
            or ""
        ).strip()
        for step in steps
        if isinstance(step, dict)
    ]

    issues: List[str] = []

    roblox_request = is_roblox_request(user_command)
    roblox_inspection_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in ROBLOX_INSPECTION_TOOLS
    ]
    roblox_mutation_indices = [
        index
        for index, tool in enumerate(tool_names)
        if is_roblox_mutation_tool(tool)
    ]
    roblox_test_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in ROBLOX_TEST_TOOLS
    ]

    inspection_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool in CODE_INSPECTION_TOOLS
        ),
        None,
    )

    mutation_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in CODE_MUTATION_TOOLS
    ]

    # Validate edit_file's three-part wire format before execution.
    # The executor expects: filename|||old_text|||new_text.
    for step in steps:
        if not isinstance(step, dict):
            continue

        if str(step.get("tool", "") or "").strip() != "edit_file":
            continue

        argument = str(step.get("argument", "") or "")
        parts = argument.split("|||", 2)

        if len(parts) != 3 or any(not part for part in parts):
            issues.append(
                "edit_file arguments must use exactly "
                "filename|||old_text|||new_text with three non-empty parts. "
                "Do not use || between old_text and new_text."
            )

    checkpoint_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool == "code_checkpoint"
        ),
        None,
    )

    test_indices = [
        index
        for index, tool in enumerate(tool_names)
        if tool in {"code_test", "code_diagnose"}
    ]

    if requires_regression_test(user_command):
        has_test_mutation = _plan_has_test_mutation(tool_names, steps)

        if require_modification and not has_test_mutation:
            issues.append(
                "This change requires regression coverage. The plan must "
                "add or update a test file before validation."
            )

    # --------------------------------------------------------
    # File-target sanity checks for diagnostic/repair plans.
    # --------------------------------------------------------
    # A planner hallucinating a source filename is worse than returning
    # an incomplete plan: it causes an avoidable execution failure and can
    # contaminate the repair evidence. Reject nonexistent read/edit targets
    # before execution and give the planner a concrete correction.
    # --------------------------------------------------------
    import ast
    from pathlib import Path

    base = Path.cwd().resolve()
    protected_parts = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "jarvis_cuda",
        "venv",
        ".venv",
        "node_modules",
        "build",
        "dist",
        ".jarvis_checkpoints",
    }

    for step in steps:
        if not isinstance(step, dict):
            continue

        tool = str(step.get("tool", "") or "").strip()
        argument = str(step.get("argument", "") or "").strip()

        target = ""
        if tool == "read_file":
            target = argument
        elif tool in {"edit_file", "delete_file", "write_file"}:
            target = argument.split("|||", 1)[0].strip()
        elif tool == "code_test":
            try:
                payload = json.loads(argument)
                if not isinstance(payload, dict):
                    payload = ast.literal_eval(argument)
                if isinstance(payload, dict):
                    target = str(payload.get("path", "") or "").strip()
            except (json.JSONDecodeError, ValueError, SyntaxError):
                target = ""

        if not target or tool == "write_file":
            continue

        candidate = (base / target).resolve()

        try:
            relative_candidate = candidate.relative_to(base)
        except ValueError:
            issues.append(
                f"The {tool} target must stay inside the project: {target}"
            )
            continue

        if any(
            part.lower() in protected_parts
            for part in relative_candidate.parts
        ):
            issues.append(
                f"The {tool} target points to an internal/generated path: "
                f"{target}. Use the actual project source file instead."
            )
            continue

        if not candidate.exists():
            issues.append(
                f"The planner referenced a nonexistent {tool} target: {target}. "
                "Do not invent filenames; use the actual discovered project file."
            )

    request_lower = str(user_command or "").lower()

    if (
        "browser" in request_lower
        and "automation" in request_lower
    ):
        for step in steps:
            if not isinstance(step, dict):
                continue

            tool = str(step.get("tool", "") or "").strip()
            argument = str(step.get("argument", "") or "").strip()

            if tool not in {
                "read_file",
                "edit_file",
                "delete_file",
                "code_test",
            }:
                continue

            if "browser_automation.py" in argument.lower():
                issues.append(
                    "For browser automation in this project, use the existing "
                    "browser_controller.py target. browser_automation.py does not exist."
                )

    # A standalone diagnostic-test phase is intentionally allowed to
    # operate on already-verified source evidence. The runtime controller
    # uses this phase only after source inspection has completed, so requiring
    # another inspection tool here would reject the diagnostic plan itself.
    if (
        inspection_index is None
        and not roblox_request
        and not allow_prior_evidence
        and not require_code_test
    ):
        issues.append(
            "The repair plan must inspect the relevant project code "
            "before attempting to fix it."
        )

    read_index = next(
        (
            index
            for index, tool in enumerate(tool_names)
            if tool == "read_file"
        ),
        None,
    )

    if require_code_read and read_index is None and not allow_prior_evidence:
        issues.append(
            "The next investigation phase must read the actual relevant "
            "source file with read_file before choosing a code change."
        )

    if require_code_test and not test_indices and not roblox_request:
        issues.append(
            "The next diagnostic phase must run code_test so the "
            "implementation can be validated before deciding whether to edit."
        )

    if require_code_diagnose and not roblox_request:
        diagnose_indices = [
            index
            for index, tool in enumerate(tool_names)
            if tool == "code_diagnose"
        ]

        if not diagnose_indices:
            issues.append(
                "The required diagnostic phase must run code_diagnose "
                "against the verified target before any repair decision."
            )

    # Browser automation needs a behavioral smoke test, not only a syntax
    # check. Once browser automation is the active repair domain, require the
    # dedicated browser_smoke mode so the planner cannot satisfy the gate
    # with a meaningless compile-only validation.
    request_lower = str(user_command or "").lower()
    if (
        require_code_test
        and "browser" in request_lower
        and "automation" in request_lower
        and test_indices
    ):
        browser_smoke_present = False

        for step in steps:
            if not isinstance(step, dict):
                continue

            if str(step.get("tool", "") or "").strip() != "code_test":
                continue

            argument = str(step.get("argument", "") or "").strip()

            try:
                payload = json.loads(argument)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            if (
                isinstance(payload, dict)
                and str(payload.get("mode", "") or "").strip().lower()
                in {"browser_smoke", "browser_self_test"}
            ):
                browser_smoke_present = True
                break

        if not browser_smoke_present:
            issues.append(
                "Browser automation diagnostics must use code_test with "
                'mode "browser_smoke" before any repair decision.'
            )

    requires_modification = bool(require_modification)

    if roblox_request:
        if (
            is_software_diagnostic_request(user_command)
            and not roblox_inspection_indices
        ):
            issues.append(
                "A Roblox diagnostic plan must inspect Studio structure, script source, or output before reporting a diagnosis."
            )

        if requires_modification and not roblox_mutation_indices:
            issues.append(
                "This Roblox change request must include an appropriate roblox__ mutation tool."
            )

        if roblox_mutation_indices:
            first_roblox_mutation = min(roblox_mutation_indices)

            if (
                not roblox_inspection_indices
                or min(roblox_inspection_indices) > first_roblox_mutation
            ):
                issues.append(
                    "Roblox inspection must occur before the first Studio mutation."
                )

            if (
                not roblox_test_indices
                or max(roblox_test_indices) < max(roblox_mutation_indices)
            ):
                issues.append(
                    "Roblox changes must be followed by playtest/output validation."
                )

    elif requires_modification and not mutation_indices:
        issues.append(
            "This request explicitly asks for a fix or code change. "
            "The plan must include an appropriate file modification step."
        )

    if not roblox_request:
        if mutation_indices:
            first_mutation = min(mutation_indices)

            if (
                not allow_prior_evidence
                and (
                    inspection_index is None
                    or inspection_index > first_mutation
                )
            ):
                issues.append(
                    "Inspection must occur before the first file modification."
                )

            if checkpoint_index is None or checkpoint_index > first_mutation:
                issues.append(
                    "A code_checkpoint must occur before autonomous "
                    "file modification work."
                )

            if not test_indices or max(test_indices) < max(mutation_indices):
                issues.append(
                    "The repair plan must run code_test after the final file "
                    "modification."
                )
        elif requires_modification and not test_indices:
            issues.append(
                "A software repair plan must include code_test so the result "
                "can be validated."
            )

    return issues


# ==========================================================
# Project File Target Resolution
# ==========================================================

def _normalized_filename_key(value: str) -> str:
    """Normalize a filename so voice-transcribed punctuation is ignored."""
    import re

    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _resolve_project_file_target(target: str, base) -> Optional[str]:
    """Resolve an existing project file when punctuation/underscores were lost.

    Resolution is conservative: a correction is returned only when exactly one
    project file has the same normalized filename (or normalized relative path).
    """
    from pathlib import Path

    raw = str(target or "").strip().strip('"').strip("'")
    if not raw:
        return None

    base = Path(base).resolve()
    direct = (base / raw).resolve()
    try:
        direct.relative_to(base)
    except ValueError:
        return None

    if direct.exists() and direct.is_file():
        return direct.relative_to(base).as_posix()

    target_key = _normalized_filename_key(raw)
    target_parts = [
        _normalized_filename_key(part)
        for part in Path(raw).parts
        if part not in {".", ""}
    ]

    matches = []
    try:
        for path in iter_project_files(base):
            if not path.is_file():
                continue

            relative = path.relative_to(base)
            name_key = _normalized_filename_key(path.name)
            relative_parts = [
                _normalized_filename_key(part)
                for part in relative.parts
            ]

            if name_key == target_key or relative_parts == target_parts:
                matches.append(relative.as_posix())
                if len(matches) > 1:
                    break
    except OSError:
        return None

    return matches[0] if len(matches) == 1 else None


# ==========================================================
# Plan Validation
# ==========================================================

def validate_plan(plan: Any) -> Dict[str, Any]:
    """Validate and clean a planner response."""
    if not isinstance(plan, dict) or "steps" not in plan:
        return {"goal": "", "steps": []}

    steps = plan.get("steps")
    if not isinstance(steps, list):
        return {"goal": plan.get("goal", ""), "steps": []}

    clean: List[Dict[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue

        tool = step.get("tool")
        argument = step.get("argument", "")

        is_dynamic_roblox_tool = is_roblox_tool_name(tool)

        if tool not in AVAILABLE_TOOLS and not is_dynamic_roblox_tool:
            logger.warning(f"Rejected unknown tool: {tool}")
            continue

        if is_dynamic_roblox_tool:
            try:
                from roblox_mcp import is_known_roblox_tool

                remote_tool = tool[len(ROBLOX_TOOL_PREFIX):]

                if (
                    not is_known_roblox_tool(remote_tool)
                    and tool not in ROBLOX_FALLBACK_TOOL_DESCRIPTIONS
                ):
                    logger.warning(
                        f"Rejected unknown Roblox MCP tool: {remote_tool}"
                    )
                    continue
            except Exception as exc:
                logger.warning(
                    f"Roblox MCP tool validation unavailable: {exc}"
                )
                continue

        normalized_argument = (
            str(argument) if argument is not None else ""
        )

        # LLMs occasionally emit Python-literal dictionaries such as
        # {'role': 'button'} instead of strict JSON. Canonicalize browser
        # object arguments at the planner boundary so every downstream
        # browser dispatcher receives one stable JSON representation.
        if (
            (tool in JSON_ARGUMENT_TOOLS or is_roblox_tool_name(tool))
            and normalized_argument.strip()
        ):
            raw_argument = normalized_argument.strip()
            try:
                payload = json.loads(raw_argument)
            except json.JSONDecodeError as json_exc:
                try:
                    payload = ast.literal_eval(raw_argument)
                except (ValueError, SyntaxError):
                    logger.warning(
                        f"Rejected invalid browser argument for {tool}: {json_exc}"
                    )
                    continue

            if not isinstance(payload, dict):
                logger.warning(
                    f"Rejected non-object browser argument for {tool}"
                )
                continue

            try:
                normalized_argument = json.dumps(
                    payload,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    f"Rejected non-JSON browser argument for {tool}: {exc}"
                )
                continue

        # Discard hallucinated source-read steps before execution when the
        # planner also supplied other usable steps. A bad read target should
        # never be allowed to turn a valid investigation into a tool failure.
        if tool == "read_file" and normalized_argument.strip():
            from pathlib import Path

            candidate = (Path.cwd().resolve() / normalized_argument.strip()).resolve()

            try:
                candidate.relative_to(Path.cwd().resolve())
            except ValueError:
                logger.warning(
                    f"Rejected read_file target outside project: {normalized_argument}"
                )
                continue

            if not candidate.exists():
                resolved = _resolve_project_file_target(
                    normalized_argument,
                    Path.cwd().resolve(),
                )
                if resolved:
                    logger.info(
                        "Resolved probable voice-transcribed file path "
                        f"{normalized_argument!r} -> {resolved!r}"
                    )
                    normalized_argument = resolved
                else:
                    logger.warning(
                        f"Rejected nonexistent read_file target: {normalized_argument}"
                    )
                    continue

        clean.append({
            "tool": str(tool),
            "argument": normalized_argument,
        })

    validated_plan = {
        "goal": plan.get("goal", ""),
        "steps": clean,
    }

    # Preserve orchestration metadata that is not an executable step. Agent
    # Core uses this marker to keep deterministic internal phases silent.
    if plan.get("jarvis_internal_phase"):
        validated_plan["jarvis_internal_phase"] = True

    if "resolved_command" in plan:
        validated_plan["resolved_command"] = str(
            plan.get("resolved_command") or ""
        )

    return validated_plan


# ==========================================================
# Create Plan
# ==========================================================


# ============================================================
# SPECIALIZED API PLAN REPAIR
# ============================================================
#
# Qwen can occasionally choose search_website for specialized
# sources even though dedicated API tools are available.
#
# Repair those plans after validation so specialized tools
# remain deterministic while normal web searches are untouched.

_validate_plan_original = validate_plan


def _repair_specialized_api_steps(plan):
    if not isinstance(plan, dict):
        return plan

    steps = plan.get("steps")

    if not isinstance(steps, list):
        return plan

    for step in steps:
        if not isinstance(step, dict):
            continue

        tool = str(step.get("tool", "")).strip().lower()
        argument = str(step.get("argument", "")).strip()

        if tool != "search_website":
            continue

        argument_lower = argument.lower()

        # ----------------------------------------------------
        # Google Books -> dedicated book search API
        # ----------------------------------------------------
        if argument_lower.startswith("google_books|"):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "book_search"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(google_books|...) -> "
                    f"book_search({query})"
                )

        # ----------------------------------------------------
        # arXiv -> dedicated research API
        # ----------------------------------------------------
        elif argument_lower.startswith("arxiv|"):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "research_arxiv"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(arxiv|...) -> "
                    f"research_arxiv({query})"
                )

        # ----------------------------------------------------
        # Frankfurter / currency -> currency_convert
        # ----------------------------------------------------
        elif (
            argument_lower.startswith("currency|")
            or argument_lower.startswith("exchange|")
            or argument_lower.startswith("frankfurter|")
        ):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "currency_convert"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(currency|...) -> "
                    f"currency_convert({query})"
                )

        # ----------------------------------------------------
        # Geocoding -> location_lookup
        # ----------------------------------------------------
        elif (
            argument_lower.startswith("geocode|")
            or argument_lower.startswith("location|")
            or argument_lower.startswith("open_meteo_geocode|")
        ):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "location_lookup"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(geocode|...) -> "
                    f"location_lookup({query})"
                )

        # ----------------------------------------------------
        # Air quality -> air_quality
        # ----------------------------------------------------
        elif (
            argument_lower.startswith("air_quality|")
            or argument_lower.startswith("aqi|")
        ):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "air_quality"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(air_quality|...) -> "
                    f"air_quality({query})"
                )

        # ----------------------------------------------------
        # NWS alerts -> weather_alerts
        # ----------------------------------------------------
        elif (
            argument_lower.startswith("nws_alerts|")
            or argument_lower.startswith("weather_alerts|")
        ):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "weather_alerts"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(weather_alerts|...) -> "
                    f"weather_alerts({query})"
                )

        # ----------------------------------------------------
        # Elevation -> elevation_lookup
        # ----------------------------------------------------
        elif argument_lower.startswith("elevation|"):
            query = argument.split("|", 1)[1].strip()

            if query:
                step["tool"] = "elevation_lookup"
                step["argument"] = query

                print(
                    "JARVIS DEBUG: repaired planner route "
                    "search_website(elevation|...) -> "
                    f"elevation_lookup({query})"
                )

    return plan


def validate_plan(*args, **kwargs):
    plan = _validate_plan_original(*args, **kwargs)
    return _repair_specialized_api_steps(plan)


def create_plan(
    user_command: str,
    active_context: Optional[Dict[str, Any]] = None,
    history_text: str = ""
) -> Dict[str, Any]:
    """
    Convert a user command into a plan of tool calls.

    Args:
        user_command: The user's request.
        active_context: Current active task context.
        history_text: Recent conversation history.

    Returns:
        A dict with 'goal' and 'steps' keys.
    """
    if not user_command or not user_command.strip():
        return {"goal": "", "steps": []}

    # Workflow-class requests belong to n8n because it is better at
    # persistent state, schedules, retries, branching, and external-service
    # orchestration than JARVIS's real-time task loop.
    deterministic_n8n = _deterministic_n8n_plan(
        user_command,
        active_context=active_context,
    )

    if deterministic_n8n is not None:
        logger.info(
            "JARVIS planner: n8n workflow route selected."
        )
        return validate_plan(deterministic_n8n)

    # Preserve Roblox domain context for follow-up requests that omit the
    # word "Roblox", such as "find the scripts that control gameplay".
    deterministic_roblox_context = _deterministic_roblox_context_plan(
        user_command,
        active_context=active_context,
    )

    if deterministic_roblox_context is not None:
        logger.info(
            "JARVIS planner: deterministic Roblox context route selected."
        )
        return validate_plan(deterministic_roblox_context)

    # Obvious Roblox Studio requests should not depend on Qwen's ability
    # to understand local-machine access. The MCP adapter is the actual
    # authority for these operations, so keep these routes model-free.
    deterministic_roblox = _deterministic_roblox_plan(user_command)

    if deterministic_roblox is not None:
        logger.info(
            "JARVIS planner: deterministic Roblox route selected."
        )
        return validate_plan(deterministic_roblox)

    # Internal agent phases are already semantically resolved. Their
    # prompts may contain ordinary words such as "run", "search", or "add"
    # that happen to match user-facing deterministic commands. Never let the
    # general command router hijack an internal phase; the phase marker is
    # authoritative and must reach the focused planner below.
    internal_phase = bool(
        re.match(
            r"^\s*\[JARVIS_INTERNAL_PHASE:[A-Z_]+\]",
            str(user_command or ""),
            re.IGNORECASE,
        )
    )

    # Use the canonical command router as the first safety boundary.
    # Agent Core may call this planner directly, bypassing main.py's
    # fast-command lookup, so simple actions must still stay model-free.
    normalized_pre_route = " ".join(
        user_command.strip().lower().rstrip(".,!?").split()
    )

    # Some commands have a more specific planner-level route that must
    # run before commands.deterministic_route(). The generic command router
    # intentionally handles many broad browser/status phrases, so let the
    # specialized context-aware routes below own these cases.
    defer_contextual_route = False

    if active_context:
        active_site_pre_route = str(
            active_context.get("site", "") or ""
        ).strip().lower()

        active_query_pre_route = str(
            active_context.get("last_query", "") or ""
        ).strip()

        if (
            active_site_pre_route in {"google", "youtube"}
            and active_query_pre_route
            and re.match(
                r"^(?:click|open|play|select|choose|pick)\s+"
                r"(?:the\s+)?"
                r"(?:first|top|second|third|last|final)\s+"
                r"(?:browser\s+)?"
                r"(?:result|link|video|one|item)"
                r"(?:\s+on\s+[a-z0-9.-]+)?$",
                normalized_pre_route,
                re.IGNORECASE,
            )
        ):
            defer_contextual_route = True

    if re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"the\s+browser\s+element\s+with\s+visible\s+text\s+"
        r"['\"].+['\"]$",
        user_command.strip(),
        re.IGNORECASE,
    ):
        defer_contextual_route = True

    if normalized_pre_route in {
        "read the current browser page",
        "read current browser page",
        "read this page",
        "read the page",
        "read page",
        "read the page text",
        "show this page",
        "open the previously selected browser result",
        "open the previously selected result",
    }:
        defer_contextual_route = True

    if (
        "barehands" in normalized_pre_route
        and (
            "display" in normalized_pre_route
            or "glass board" in normalized_pre_route
            or "show" in normalized_pre_route
            or "present" in normalized_pre_route
            or "put" in normalized_pre_route
            or "place" in normalized_pre_route
        )
        and "status" in normalized_pre_route
        and (
            "card" in normalized_pre_route
            or "status" in normalized_pre_route
        )
    ):
        defer_contextual_route = True

    try:
        if internal_phase or defer_contextual_route:
            deterministic_plan = None
        else:
            from commands import deterministic_route

            deterministic_plan = deterministic_route(
                user_command,
                active_context=active_context,
            )

        if deterministic_plan:
            deterministic_result = validate_plan(
                {
                    "goal": user_command,
                    "steps": deterministic_plan.get("steps", []),
                    "resolved_command": user_command,
                }
            )

            if deterministic_result.get("steps"):
                logger.info(
                    "JARVIS planner: deterministic command route selected."
                )
                return deterministic_result
    except Exception as exc:
        logger.debug(
            f"JARVIS planner: deterministic route unavailable: {exc}"
        )

    # ========================================================
    # DETERMINISTIC FIRST-RESULT ROUTER
    # ========================================================
    #
    # When a previous search established a website and query,
    # commands such as:
    #
    #   Click the first result
    #
    # should NOT be left to the language model.
    #
    # Google:
    #   click the first organic Google result for QUERY
    #
    # YouTube:
    #   click the first organic YouTube result for QUERY
    #
    # This creates a normal planner result so the rest of the
    # existing execution pipeline remains unchanged.
    # ========================================================

    normalized_command = (
        user_command
        .strip()
        .lower()
        .rstrip(".,!?")
    )

    normalized_command = " ".join(
        normalized_command.split()
    )

    first_result_phrases = {
        "click the first result",
        "click first result",
        "click on the first result",
        "click on first result",

        "click the first browser result",
        "click first browser result",
        "click the first browser result on google",
        "click first browser result on google",
        "click the first browser result on youtube",
        "click first browser result on youtube",

        "open the first result",
        "open first result",
        "open the first browser result",
        "open first browser result",
        "open the first browser result on google",
        "open first browser result on google",
        "open the first browser result on youtube",
        "open first browser result on youtube",

        "play the first result",
        "play first result",

        "click the first video",
        "click first video",
        "click on the first video",
        "click on first video",

        "open the first video",
        "open first video",

        "play the first video",
        "play first video",

        "click the first link",
        "click first link",
        "click on the first link",
        "click on first link",

        "open the first link",
        "open first link",

        "click the first one",
        "click first one",
        "click on the first one",
        "click on first one",

        "open the first one",
        "open first one",
    }

    if (
        normalized_command in first_result_phrases
        and active_context
    ):
        active_site = str(
            active_context.get("site", "") or ""
        ).strip().lower()

        active_query = str(
            active_context.get("last_query", "") or ""
        ).strip()

        if (
            active_site in {
                "google",
                "youtube",
            }
            and active_query
        ):
            if active_site == "google":
                resolved_command = (
                    "click the first organic Google result for "
                    + active_query
                )

                print(
                    "JARVIS planner:"
                )

                print(
                    f"  Original: {user_command}"
                )

                print(
                    f"  Context site: Google"
                )

                print(
                    f"  Context query: {active_query}"
                )

                print(
                    f"  Resolved: {resolved_command}"
                )

                return {
                    "goal": "click first Google result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": "google",
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

            if active_site == "youtube":
                resolved_command = (
                    "click the first organic YouTube result for "
                    + active_query
                )

                print(
                    "JARVIS planner:"
                )

                print(
                    f"  Original: {user_command}"
                )

                print(
                    f"  Context site: YouTube"
                )

                print(
                    f"  Context query: {active_query}"
                )

                print(
                    f"  Resolved: {resolved_command}"
                )

                return {
                    "goal": "click first YouTube result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": "youtube",
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

    # ========================================================
    # DETERMINISTIC AUTONOMOUS BROWSER ROUTER
    # ========================================================
    #
    # Explicit autonomous-browser requests should stay model-free at the
    # outer planner layer. The Browser Use worker still performs its own
    # multi-step reasoning inside the isolated environment.
    # ========================================================

    autonomous_browser_task = None

    for prefix in (
        "use autonomous browser to ",
        "use the autonomous browser to ",
        "use browser agent to ",
        "use the browser agent to ",
        "have the autonomous browser ",
        "let the autonomous browser ",
        "have the browser agent ",
        "let the browser agent ",
    ):
        if normalized_command.startswith(prefix):
            autonomous_browser_task = user_command.strip()[len(prefix):].strip()
            break

    if autonomous_browser_task:
        return {
            "goal": "run autonomous browser task",
            "steps": [
                {
                    "tool": "browser_agent_run",
                    "argument": json.dumps({
                        "task": autonomous_browser_task,
                        "max_steps": 12,
                    }),
                }
            ],
            "resolved_command": user_command.strip(),
        }

    # ========================================================
    # DETERMINISTIC BROWSER READ ROUTER
    # ========================================================
    if normalized_command in {
        "read the current browser page",
        "read current browser page",
        "read this page",
        "read the page",
        "read page",
        "read the page text",
        "show this page",
    }:
        return {
            "goal": "read current browser page",
            "steps": [
                {
                    "tool": "browser_extract_text",
                    "argument": json.dumps({
                        "selector": "body",
                    }),
                }
            ],
            "resolved_command": "read the current browser page",
        }

    if normalized_command in {
        "inspect the current browser page",
        "read the current browser title",
        "read the page title",
        "inspect the page title",
    }:
        return {
            "goal": "inspect current browser page",
            "steps": [
                {
                    "tool": "browser_page_info",
                    "argument": "",
                }
            ],
            "resolved_command": "inspect the current browser page",
        }

    # ========================================================
    # ========================================================
    # DETERMINISTIC ORDINAL BROWSER RESULT ROUTER
    # ========================================================
    #
    # Context resolution can produce canonical browser phrases such as:
    #   click the second browser result on google
    #   click the last browser result on youtube
    #
    # These are execution-safe browser actions and should never be handed
    # back to the LLM planner. Use the active browser context for the site
    # and search query so the action stays on the current search.
    # ========================================================

    browser_result_match = re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"(?:the\s+)?"
        r"(first|top|second|third|last|final)\s+"
        r"(?:browser\s+)?"
        r"(?:result|link|video|one|item)"
        r"(?:\s+on\s+([a-z0-9.-]+))?$",
        normalized_command,
        re.IGNORECASE,
    )

    if browser_result_match and active_context:
        ordinal = browser_result_match.group(1).lower()
        explicit_site = (
            browser_result_match.group(2) or ""
        ).strip().lower()

        active_site = str(
            active_context.get("site", "") or ""
        ).strip().lower()

        active_query = str(
            active_context.get("last_query", "") or ""
        ).strip()

        site = explicit_site or active_site

        if site in {"google", "youtube"} and active_query:
            if ordinal in {"first", "top"}:
                resolved_command = (
                    f"click the first browser result on {site}"
                )
                return {
                    "goal": f"click first {site} result",
                    "steps": [
                        {
                            "tool": "browser_click_first_result",
                            "argument": json.dumps({
                                "site": site,
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

            index = {
                "second": 2,
                "third": 3,
                "last": "last",
                "final": "last",
            }.get(ordinal)

            if index is not None:
                resolved_command = (
                    f"click the {ordinal} browser result on {site}"
                )
                return {
                    "goal": f"click {ordinal} {site} result",
                    "steps": [
                        {
                            "tool": "browser_click_result",
                            "argument": json.dumps({
                                "index": index,
                                "site": site,
                                "query": active_query,
                            }),
                        }
                    ],
                    "resolved_command": resolved_command,
                }

    # ========================================================
    # DETERMINISTIC SELECTED-RESULT REOPEN ROUTER
    # ========================================================
    if normalized_command in {
        "open the previously selected browser result",
        "open the previously selected result",
    } and active_context:
        selected_url = str(
            active_context.get("last_result_url", "") or ""
        ).strip()

        if selected_url:
            return {
                "goal": "reopen previously selected browser result",
                "steps": [
                    {
                        "tool": "browser_goto",
                        "argument": selected_url,
                    }
                ],
                "resolved_command": normalized_command,
            }

    # ========================================================
    # DETERMINISTIC BROWSER ELEMENT REFERENCE ROUTER
    # ========================================================
    #
    # The context resolver can resolve phrases such as "click it" to:
    #   click the browser element with visible text '...'
    #
    # Keep that path model-free so a selected browser result does not
    # fall back to the LLM planner or screen vision.
    # ========================================================

    visible_text_match = re.match(
        r"^(?:click|open|play|select|choose|pick)\s+"
        r"the\s+browser\s+element\s+with\s+visible\s+text\s+"
        r"(?P<quoted>['\"].+['\"])$",
        user_command.strip(),
        re.IGNORECASE,
    )

    if visible_text_match:
        try:
            visible_text = ast.literal_eval(
                visible_text_match.group("quoted")
            )
        except (SyntaxError, ValueError):
            visible_text = ""

        if isinstance(visible_text, str) and visible_text.strip():
            return {
                "goal": "click referenced browser element",
                "steps": [
                    {
                        "tool": "browser_click_element",
                        "argument": json.dumps({
                            "text": visible_text.strip(),
                        }),
                    }
                ],
                "resolved_command": user_command.strip(),
            }

    # ========================================================
    # DETERMINISTIC BAREHANDS DISPLAY ROUTER
    # ========================================================
    #
    # Display requests should never depend on the planner model choosing
    # between jarvis_status and a Barehands presentation tool. The user
    # explicitly asked for a display action, so route it directly.
    # ========================================================

    if (
        "barehands" in normalized_command
        and (
            "display" in normalized_command
            or "glass board" in normalized_command
            or "show" in normalized_command
            or "present" in normalized_command
            or "put" in normalized_command
            or "place" in normalized_command
        )
        and "status" in normalized_command
        and (
            "card" in normalized_command
            or "status" in normalized_command
        )
    ):
        return {
            "goal": "show JARVIS status on Barehands",
            "steps": [
                {
                    "tool": "barehands_present",
                    "argument": (
                        "JARVIS Status|||"
                        "JARVIS status requested on the Barehands display."
                    ),
                }
            ],
        }

    # ========================================================
    # DETERMINISTIC ANIME EPISODE ROUTER
    # ========================================================
    # Episode-list questions are specialized structured lookups. Keep them
    # out of the generic knowledge planner so Qwen cannot substitute a
    # knowledge_lookup when the user explicitly wants episode data.
    anime_episode_match = None
    for pattern in (
        r"^(?:what are|what're|list|show|give me|tell me)\s+(?:the\s+)?episodes?\s+(?:of|for)\s+(.+)$",
        r"^(?:episodes?|episode list)\s+(?:of|for)\s+(.+)$",
    ):
        anime_episode_match = re.match(pattern, normalized_command, re.IGNORECASE)
        if anime_episode_match:
            break

    if anime_episode_match:
        anime_title = anime_episode_match.group(1).strip().rstrip(".,!? ")
        if anime_title:
            return {
                "goal": "get anime episode list",
                "steps": [
                    {
                        "tool": "anime_episodes",
                        "argument": anime_title,
                    }
                ],
                "resolved_command": user_command.strip(),
            }

    # Normalize optional context once deterministic routing is complete.
    # Internal planner phases may call create_plan() without active context, while
    # Agent Core can provide its ActiveContext wrapper instead of a plain dict.
    if hasattr(active_context, "to_dict"):
        try:
            active_context = active_context.to_dict()
        except Exception:
            active_context = {}
    elif not isinstance(active_context, dict):
        active_context = {}

    context_str = ""
    if active_context:
        context_str = f"""

Active task context:
Website: {active_context.get('site', 'none')}
Search query: {active_context.get('last_query', 'none')}
Last tool: {active_context.get('last_tool', 'none')}
"""

        try:
            from result_context import compact_context_description

            compact_result_context = compact_context_description(
                active_context
            )

            if compact_result_context:
                context_str += (
                    "\nStructured result context:\n"
                    + compact_result_context
                    + "\n"
                )
        except Exception:
            pass

    # Cheap intent/entity resolution gives the LLM planner a stable semantic
    # interpretation without requiring another model call.
    try:
        from intent_resolver import resolve_intent

        intent_hints = resolve_intent(
            user_command,
            active_context=active_context,
        )
        context_str += (
            "\nDeterministic intent hints:\n"
            + str(intent_hints)
            + "\n"
        )
    except Exception as exc:
        logger.debug(
            f"JARVIS planner: intent resolution skipped: {exc}"
        )

    try:
        from superpowers_engine import planner_directives
        superpowers_context = planner_directives(user_command)
        if superpowers_context:
            context_str += "\n" + superpowers_context + "\n"
    except Exception as exc:
        logger.debug(
            f"JARVIS planner: Superpowers directives skipped: {exc}"
        )

    learned_hints = active_context.get("learned_hints")
    if isinstance(learned_hints, list) and learned_hints:
        cleaned_hints = [
            str(item).strip()
            for item in learned_hints[:3]
            if str(item).strip()
        ]
        if cleaned_hints:
            context_str += (
                "\nLessons from previous JARVIS task attempts:\n"
                + "\n".join(
                    f"- {item}"
                    for item in cleaned_hints
                )
                + "\n"
            )

    history_str = f"\nRecent conversation:\n{history_text}" if history_text else ""

    # --------------------------------------------------------
    # Focused autonomous phase prompts
    # --------------------------------------------------------
    # Agent Core prefixes internal phase markers so intermediate
    # investigation/test planning cannot accidentally enter repair mode.
    # Repair uses the coding model; bounded CHANGE planning uses the faster
    # dedicated change-planner model. Discovery remains model-free where possible.
    # --------------------------------------------------------
    is_repair_phase = "[JARVIS_INTERNAL_PHASE:REPAIR]" in user_command
    is_change_phase = "[JARVIS_INTERNAL_PHASE:CHANGE]" in user_command
    is_source_read_phase = "[JARVIS_INTERNAL_PHASE:SOURCE_READ]" in user_command
    is_diagnostic_test_phase = "[JARVIS_INTERNAL_PHASE:DIAGNOSTIC_TEST]" in user_command

    if is_repair_phase:
        repair_tools = {
            name: AVAILABLE_TOOLS[name]
            for name in (
                "code_checkpoint",
                "edit_file",
                "write_file",
                "delete_file",
                "code_test",
                "read_file",
            )
        }

        repair_tool_list = "\n".join(
            f"{name}: {desc}"
            for name, desc in repair_tools.items()
        )

        system_content = f"""You are JARVIS's focused software repair planner.

The investigation is complete. The user message contains verified source and
diagnostic evidence from the real project.

Available tools:
{repair_tool_list}

REPAIR HANDOFF MODE — HIGH PRIORITY:

Rules:
- Make ONE evidence-supported repair; do not rediscover the project.
- Use the existing verified target file.
- Prefer edit_file for existing source:
  filename|||old_text|||new_text
- Copy old_text exactly from the verified source evidence.
- Create code_checkpoint before any mutation.
- Run code_test after the final mutation.
- Use read_file only when the supplied evidence does not contain enough source
  to make the repair safely.
- Do not invent filenames, code, errors, or behavior.
- Return executable JSON only. Never return prose or an empty plan.

Required shape:
{{
  "goal": "brief repair goal",
  "steps": [
    {{"tool": "code_checkpoint", "argument": ""}},
    {{"tool": "edit_file", "argument": "existing_file.py|||exact old source|||exact new source"}},
    {{"tool": "code_test", "argument": "{{\"mode\":\"compile\",\"path\":\"existing_file.py\"}}"}}
  ]
}}

The final step must validate the changed target. Return ONLY JSON.
"""
    elif is_change_phase:
        system_content = f"""You are JARVIS's bounded software-change planner.

Verified source evidence is already supplied. Implement the original request
with the smallest safe edit. Do not rediscover files.

Rules:
- Existing files: use edit_file as filename|||exact_old_text|||exact_new_text.
- Create code_checkpoint before any mutation.
- Run code_test after the mutation.
- For regression-test requests, edit the named test file and run its focused tests.
- Do not return a read-only plan for an explicit change request.
- Do not invent paths or source not present in the evidence.
- Return executable JSON only.

Required JSON:
{{
  "goal": "brief goal",
  "steps": [
    {{"tool": "code_checkpoint", "argument": ""}},
    {{"tool": "edit_file", "argument": "file.py|||exact old source|||exact new source"}},
    {{"tool": "code_test", "argument": "{{\"mode\":\"pytest\",\"path\":\"tests/test_target.py\"}}"}}
  ]
}}

Return ONLY JSON.
"""
    elif is_source_read_phase:
        system_content = f"""You are JARVIS's focused source-inspection planner.

The project discovery phase is complete. Verified evidence is included in
the user message. You must inspect the actual existing source before any
repair is planned.

Do NOT modify files.
Do NOT use list_files.
Do NOT perform broad project-wide discovery when the evidence already names
the target.
Prefer exactly one read_file step for the verified target source file.
Do not invent filenames.

Return ONLY valid JSON with goal and steps. Every argument must be a string.
"""

    elif is_diagnostic_test_phase:
        system_content = f"""You are JARVIS's focused diagnostic test planner.

The relevant source file has already been inspected. Verified evidence is
included in the user message. Run a targeted diagnostic against the existing
implementation before any repair is planned.

Do NOT modify files.
Do NOT use list_files.
Do NOT perform broad rediscovery.
Prefer exactly one code_diagnose step for the verified target.
Use a narrow JSON argument such as:
{{"path":"target.py","run_tests":false,"run_lint":false,"run_types":false}}
Do not invent filenames.

Return ONLY valid JSON with goal and steps. Every argument must be a string.
"""

    else:
        planner_scope = _planner_tool_scope(
            user_command,
            active_context=active_context,
        )

        system_content = (
            _planner_prompt(planner_scope)
            + context_str
            + history_str
        )

    messages = [
        {
            "role": "system",
            "content": system_content
        },
        {
            "role": "user",
            "content": user_command
        }
    ]

    import time

    try:
        print("JARVIS DEBUG: planner -> calling Ollama", flush=True)
        planner_start = time.perf_counter()

        focused_implementation_phase = (
            is_repair_phase or is_change_phase
        )

        planner_model = (
            MODEL_MANAGER.coding_model
            if is_repair_phase
            else (
                MODEL_MANAGER.change_planner_model
                if is_change_phase
                else PLANNER_MODEL
            )
        )

        if focused_implementation_phase:
            phase_label = (
                "repair" if is_repair_phase else "change"
            )
            logger.info(
                f"JARVIS DEBUG: {phase_label} planner -> using {planner_model}"
            )

        if is_repair_phase:
            response = MODEL_MANAGER.coding(
                messages,
                format="json",
                options={
                    "temperature": 0,
                    "num_predict": 240,
                    "num_ctx": config.CODING_NUM_CTX,
                },
                model=planner_model,
            )
        elif is_change_phase:
            response = MODEL_MANAGER.change_planner(
                messages,
                format="json",
            )
        else:
            response = MODEL_MANAGER.planner(
                messages,
                format="json",
            )

        elapsed = time.perf_counter() - planner_start

        print(
            f"JARVIS DEBUG: Ollama returned after "
            f"{elapsed:.3f}s",
            flush=True
        )

        # Ollama reports the major latency components on ChatResponse. Keep
        # these metrics in the debug log so cold-load time is distinguishable
        # from prompt evaluation and token generation time.
        if focused_implementation_phase:
            def _seconds_from_ns(name: str):
                try:
                    value = getattr(response, name, None)
                    if value is None:
                        return None
                    return float(value) / 1_000_000_000.0
                except (TypeError, ValueError):
                    return None

            metric_parts = []
            for name, label in (
                ("load_duration", "load"),
                ("prompt_eval_duration", "prompt_eval"),
                ("eval_duration", "generation"),
            ):
                seconds = _seconds_from_ns(name)
                if seconds is not None:
                    metric_parts.append(f"{label}={seconds:.3f}s")

            if metric_parts:
                print(
                    "JARVIS DEBUG: focused planner latency breakdown: "
                    + " | ".join(metric_parts),
                    flush=True,
                )

            for name, label in (
                ("prompt_eval_count", "prompt_tokens"),
                ("eval_count", "generated_tokens"),
            ):
                try:
                    value = getattr(response, name, None)
                    if value is not None:
                        print(
                            f"JARVIS DEBUG: focused planner {label}={value}",
                            flush=True,
                        )
                except Exception:
                    pass

        print(
            f"JARVIS DEBUG: response type={type(response).__name__}",
            flush=True
        )

    except Exception as e:
        logger.error(f"Planner LLM call failed: {e}")

        if focused_implementation_phase:
            try:
                if is_change_phase:
                    fallback_model = MODEL_MANAGER.coding_model
                    logger.warning(
                        "JARVIS DEBUG: change planner failed; "
                        f"falling back to coding model {fallback_model}"
                    )
                    fallback_response = MODEL_MANAGER.coding(
                        messages,
                        format="json",
                        options={
                            "temperature": 0,
                            "num_predict": 512,
                            "num_ctx": config.CODING_NUM_CTX,
                        },
                        model=fallback_model,
                    )
                else:
                    fallback_model = MODEL_MANAGER.coding_fallback_model

                    if (
                        not fallback_model
                        or fallback_model == planner_model
                    ):
                        return {"goal": "", "steps": []}

                    logger.warning(
                        "JARVIS DEBUG: primary coding planner failed; "
                        f"falling back to {fallback_model}"
                    )
                    fallback_response = MODEL_MANAGER.coding(
                        messages,
                        format="json",
                        options={
                            "temperature": 0,
                            "num_predict": 240,
                            "num_ctx": config.CODING_NUM_CTX,
                        },
                        model=fallback_model,
                    )

                fallback_content = (
                    fallback_response
                    .get("message", {})
                    .get("content", "")
                )
                fallback_data = extract_json(fallback_content)

                if fallback_data:
                    validated_fallback = validate_plan(fallback_data)
                    if validated_fallback.get("steps"):
                        logger.info(
                            "JARVIS DEBUG: focused coding fallback planner "
                            "recovered a valid plan."
                        )
                        return validated_fallback

            except Exception as fallback_exc:
                logger.error(
                    f"Coding fallback planner failed: {fallback_exc}"
                )

        return {"goal": "", "steps": []}

    print("JARVIS DEBUG: extracting message content", flush=True)

    content = response.get("message", {}).get("content", "")

    print(
        f"JARVIS DEBUG: content length={len(content)}",
        flush=True
    )

    print("JARVIS DEBUG: calling extract_json()", flush=True)

    data = extract_json(content)

    print(
        f"JARVIS DEBUG: extract_json returned "
        f"type={type(data).__name__}",
        flush=True
    )

    if not data:
        logger.warning(f"Planner returned invalid JSON: {content[:200]}")

        if (
            is_roblox_request(user_command)
            and not is_repair_phase
            and not is_change_phase
        ):
            fallback = _roblox_safe_fallback_plan(user_command)
            validated_fallback = validate_plan(fallback)
            if validated_fallback.get("steps"):
                logger.info(
                    "JARVIS planner: recovered with deterministic Roblox fallback."
                )
                return validated_fallback

        if is_change_phase:
            fallback_model = MODEL_MANAGER.coding_model
            logger.warning(
                "JARVIS DEBUG: change planner returned invalid output; "
                f"falling back to {fallback_model}"
            )
            try:
                fallback_response = MODEL_MANAGER.coding(
                    messages,
                    format="json",
                    options={
                        "temperature": 0,
                        "num_predict": 512,
                        "num_ctx": config.CODING_NUM_CTX,
                    },
                    model=fallback_model,
                )
                fallback_content = (
                    fallback_response
                    .get("message", {})
                    .get("content", "")
                )
                fallback_data = extract_json(fallback_content)

                if fallback_data:
                    validated_fallback = validate_plan(fallback_data)
                    if validated_fallback.get("steps"):
                        logger.info(
                            "JARVIS DEBUG: change coding fallback planner "
                            "returned a valid plan."
                        )
                        return validated_fallback
            except Exception as fallback_exc:
                logger.error(
                    f"Change fallback planner failed: {fallback_exc}"
                )

        if is_repair_phase:
            fallback_model = MODEL_MANAGER.coding_fallback_model
            if fallback_model and fallback_model != planner_model:
                logger.warning(
                    "JARVIS DEBUG: focused planner returned invalid "
                    f"output; falling back to {fallback_model}"
                )
                try:
                    fallback_response = chat(
                        model=fallback_model,
                        messages=messages,
                        format="json",
                        options={
                            "temperature": 0,
                            "num_predict": 240,
                            "num_ctx": config.CODING_NUM_CTX,
                        },
                        keep_alive=config.CODING_MODEL_KEEP_ALIVE,
                    )
                    fallback_content = (
                        fallback_response
                        .get("message", {})
                        .get("content", "")
                    )
                    fallback_data = extract_json(fallback_content)

                    if fallback_data:
                        logger.info(
                            "JARVIS DEBUG: coding fallback planner "
                            "returned a valid plan."
                        )
                        validated_fallback = validate_plan(fallback_data)
                        if validated_fallback.get("steps"):
                            return validated_fallback

                except Exception as fallback_exc:
                    logger.error(
                        f"Coding fallback planner failed: {fallback_exc}"
                    )

        return {"goal": "", "steps": []}

    print("JARVIS DEBUG: calling validate_plan()", flush=True)

    validated = validate_plan(data)

    if (
        is_roblox_request(user_command)
        and not is_repair_phase
        and not is_change_phase
        and not validated.get("steps")
    ):
        fallback = _roblox_safe_fallback_plan(user_command)
        validated_fallback = validate_plan(fallback)
        if validated_fallback.get("steps"):
            logger.info(
                "JARVIS planner: model produced no usable Roblox steps; "
                "using deterministic fallback."
            )
            validated = validated_fallback

    print(
        f"JARVIS DEBUG: validate_plan returned "
        f"{validated!r}",
        flush=True
    )

    return validated


# ============================================================
# KNOWLEDGE PLAN REPAIR
# ============================================================
#
# Qwen can occasionally understand a factual question but return
# an empty step list. When the smart router already classified the
# request as a knowledge query, an empty plan is not useful.
#
# Preserve normal model planning, but repair empty knowledge plans
# into the dedicated knowledge_lookup tool.

_create_plan_original_knowledge_repair = create_plan


_KNOWLEDGE_IDENTITY_EXCLUSIONS = (
    "what is your name",
    "who are you",
    "what can you do",
    "what is my name",
    "who am i",
)


_KNOWLEDGE_PREFIXES = (
    "what is ",
    "what are ",
    "who is ",
    "who was ",
    "tell me about ",
    "explain ",
)


def _knowledge_argument_from_query(query):
    text = str(query or "").strip()

    text = re.sub(
        r"[?!.]+$",
        "",
        text,
    ).strip()

    lowered = text.lower()

    for prefix in _KNOWLEDGE_PREFIXES:
        if lowered.startswith(prefix):
            argument = text[len(prefix):].strip()

            if argument:
                return argument

    return None


def create_plan(command, *args, **kwargs):
    plan = _create_plan_original_knowledge_repair(
        command,
        *args,
        **kwargs,
    )

    query = str(command or "").strip().lower()

    if any(
        query.startswith(prefix)
        for prefix in _KNOWLEDGE_IDENTITY_EXCLUSIONS
    ):
        return plan

    knowledge_argument = _knowledge_argument_from_query(
        command
    )

    if not knowledge_argument:
        return plan

    if not isinstance(plan, dict):
        return plan

    steps = plan.get("steps")

    if isinstance(steps, list) and steps:
        return plan

    repaired = dict(plan)

    repaired["steps"] = [
        {
            "tool": "knowledge_lookup",
            "argument": knowledge_argument,
        }
    ]

    print(
        "JARVIS DEBUG: repaired empty knowledge plan -> "
        f"knowledge_lookup({knowledge_argument})"
    )

    return repaired


# ============================================================
# SPECIALIZED API PLANNER PREFLIGHT
# ============================================================
#
# Obvious structured API requests should not depend on the LLM
# selecting the correct specialized tool. Preserve normal model
# planning for everything else.

_create_plan_original_specialized_api = create_plan


def _clean_specialized_api_location(command):
    text = str(command or "").strip()

    for marker in (
        " in ",
        " near ",
        " at ",
    ):
        position = text.lower().find(marker)

        if position != -1:
            location = text[position + len(marker):].strip()
            location = location.rstrip("?.!,")
            if location:
                return location

    return None


def _specialized_api_plan(command):
    text = str(command or "").strip()
    lowered = text.lower()

    if not lowered:
        return None

    # --------------------------------------------------------
    # Currency
    # --------------------------------------------------------

    if (
        lowered.startswith("convert ")
        and " to " in lowered
    ):
        return {
            "goal": "convert currency",
            "steps": [
                {
                    "tool": "currency_convert",
                    "argument": text.rstrip("?.!,"),
                }
            ],
        }

    # --------------------------------------------------------
    # Air quality
    # --------------------------------------------------------

    if any(
        phrase in lowered
        for phrase in (
            "air quality",
            "air pollution",
            "air pollutants",
            "aqi",
            "pm2.5",
            "pm10",
        )
    ):
        location = _clean_specialized_api_location(command)

        if location:
            return {
                "goal": "check air quality",
                "steps": [
                    {
                        "tool": "air_quality",
                        "argument": location,
                    }
                ],
            }

    # --------------------------------------------------------
    # Weather alerts / warnings
    # --------------------------------------------------------

    if any(
        phrase in lowered
        for phrase in (
            "weather alert",
            "weather alerts",
            "weather warning",
            "weather warnings",
            "severe weather alert",
            "severe weather alerts",
        )
    ):
        location = _clean_specialized_api_location(command)

        if location:
            return {
                "goal": "check weather alerts",
                "steps": [
                    {
                        "tool": "weather_alerts",
                        "argument": location,
                    }
                ],
            }

    # --------------------------------------------------------
    # Elevation / altitude
    # --------------------------------------------------------

    if (
        "elevation of " in lowered
        or "altitude of " in lowered
        or "elevation in " in lowered
        or "altitude in " in lowered
    ):
        location = None

        for marker in (
            " elevation of ",
            " altitude of ",
            " elevation in ",
            " altitude in ",
        ):
            position = lowered.find(marker)

            if position != -1:
                location = text[
                    position + len(marker):
                ].strip().rstrip("?.!,")
                break

        if location:
            return {
                "goal": "find elevation",
                "steps": [
                    {
                        "tool": "elevation_lookup",
                        "argument": location,
                    }
                ],
            }

    return None


def create_plan(command, *args, **kwargs):
    specialized = _specialized_api_plan(command)

    if specialized is not None:
        print(
            "JARVIS DEBUG: deterministic specialized API plan -> "
            f"{specialized['steps'][0]['tool']}("
            f"{specialized['steps'][0]['argument']})"
        )

        return specialized

    return _create_plan_original_specialized_api(
        command,
        *args,
        **kwargs,
    )