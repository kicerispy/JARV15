"""Canonical JARVIS tool-registry metadata.

This module deliberately contains only immutable metadata so planner, dispatcher,
executor, and regression tests can share the same browser/tool contracts without
introducing import cycles.
"""

from __future__ import annotations


ROBLOX_TOOL_PREFIX = "roblox__"


def is_roblox_tool_name(name) -> bool:
    return str(name or "").startswith(ROBLOX_TOOL_PREFIX)


N8N_TOOLS = frozenset(
    {
        "n8n_status",
        "n8n_run_workflow",
        "n8n_mcp_status",
        "n8n_mcp_list_tools",
        "n8n_workflow_architect",
        "n8n_workflow_builder",
    }
)

N8N_MCP_PREFIX = "n8n_mcp__"


JARVIS_PLATFORM_TOOLS = frozenset(
    {
        "jarvis_doctor",
        "jarvis_quickcheck",
        "resource_status",
        "process_snapshot",
        "project_snapshot",
        "service_status",
        "dependency_status",
        "code_index_rebuild",
        "code_index_status",
        "healing_hints",
        "tool_health",
        "memory_remember",
        "memory_recall",
        "memory_forget",
        "ollama_models",
        "healing_history",
        "tool_reset",
        "memory_status",
        "jarvis_capabilities",
        "autonomy_status",
        "strategy_history",
        "regression_status",
        "tool_contract_audit",
    }
)


def is_n8n_mcp_tool_name(name) -> bool:
    return str(name or "").startswith(N8N_MCP_PREFIX)


ANIPY_TOOLS = frozenset(
    {
        "anipy_cli",
        "anipy_providers",
        "anipy_search",
        "anipy_info",
        "anipy_episodes",
        "anipy_get_video",
        "anipy_download",
    }
)

ROBLOX_MCP_TOOLS = frozenset(
    {
        "roblox_mcp_status",
        "roblox_mcp_setup",
    }
)

UNREAL_MCP_TOOLS = frozenset(
    {
        "unreal_mcp",
        "unreal_mcp_status",
        "unreal_mcp_setup",
    }
)

GODS_EYE_TOOLS = frozenset(
    {
        "gods_eye_status",
        "gods_eye_setup",
        "gods_eye_start",
        "gods_eye_open",
        "gods_eye_stop",
        "gods_eye_contacts",
        "gods_eye_vessels",
        "gods_eye_satellites",
        "gods_eye_launches",
        "gods_eye_cameras",
        "gods_eye_radio",
        "gods_eye_transit",
    }
)

SCREEN_MEMORY_TOOLS = frozenset(
    {
        "screen_memory_setup",
        "screen_memory_status",
        "screen_memory_search",
        "screen_memory_recent",
    }
)

SYSTEM_HEALTH_TOOLS = frozenset(
    {
        "integration_health",
    }
)

ADAPTIVE_RUNTIME_TOOLS = frozenset(
    {
        "hindsight_status",
        "hindsight_remember",
        "hindsight_recall",
        "hindsight_reflect",
        "coding_style_review",
        "response_style",
        "magnitude_status",
        "agent_browser_status",
        "agent_browser_setup",
        "agent_browser_action",
        "browser_agent_setup",
    }
)

CONTEXT_MEMORY_TOOLS = frozenset(
    {
        "context_backend_status",
        "context_remember",
        "context_recall",
        "context_search",
        "context_read",
        "openviking_add_resource",
        "openviking_add_skill",
    }
)


AGENT_SKILL_TOOLS = frozenset(
    {
        "skills_status",
        "skills_sync",
        "skills_search",
        "skills_read",
        "harness_review",
    }
)



BROWSER_TOOLS = frozenset(
    {
        "browser_connect",
        "browser_search_google",
        "browser_search_bing",
        "browser_click_first_bing_result",
        "browser_goto",
        "browser_page_info",
        "browser_page_snapshot",
        "browser_click_first_result",
        "browser_click_result",
        "browser_back",
        "browser_find_element",
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_wait_for_element",
        "browser_extract_text",
        "browser_find_text",
        "browser_agent_run",
        "browser_agent_status",
        "browser_agent_setup",
        "browser_refresh",
        "browser_forward",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_current_tab",
        "browser_close_tab",
        "browser_get_links",
        "browser_open_link",
        "browser_scroll",
    }
)


JSON_ARGUMENT_TOOLS = frozenset(
    {
        "healing_hints",
        "jarvis_doctor",
        "memory_remember",
        "memory_recall",
        "memory_forget",
        "strategy_history",
        "regression_status",
        "n8n_run_workflow",
        "n8n_mcp_status",
        "n8n_mcp_list_tools",
        "n8n_workflow_architect",
        "n8n_workflow_builder",
        "integration_health",
        "browser_click_result",
        "browser_click_first_result",
        "browser_find_element",
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_wait_for_element",
        "browser_extract_text",
        "browser_find_text",
        "browser_switch_tab",
        "browser_close_tab",
        "browser_get_links",
        "browser_open_link",
        "browser_scroll",
        "product_research",
        "code_diagnose",
        "dev_command",
        "anipy_providers",
        "anipy_search",
        "anipy_info",
        "anipy_episodes",
        "anipy_get_video",
        "anipy_download",
        "unreal_mcp",
        "context_remember",
        "context_recall",
        "context_search",
        "context_read",
        "openviking_add_resource",
        "openviking_add_skill",
        "skills_search",
        "skills_read",
        "harness_review",
        "hindsight_remember",
        "hindsight_recall",
        "hindsight_reflect",
        "coding_style_review",
        "response_style",
        "agent_browser_setup",
        "agent_browser_action",
    }
)


# Core JARVIS tools that are part of the planner contract but are not
# integration-specific. Keeping these in the canonical registry lets the
# doctor detect planner/dispatcher drift instead of silently accepting unknown
# tools.
CORE_RUNTIME_TOOLS = frozenset(
    {
        "weather",
        "current_time",
        "current_date",
        "wait",
        "open_website",
        "search_website",
        "open_program",
        "system_status",
        "startup_status",
        "enable_startup",
        "disable_startup",
        "task_history",
        "create_folder",
        "list_files",
        "find_file",
        "open_folder",
        "write_file",
        "read_file",
        "edit_file",
        "code_search",
        "code_test",
        "git_task_branch",
        "code_checkpoint",
        "code_restore_checkpoint",
        "delete_file",
        "dev_command",
        "web_search",
        "jarvis_status",
        "capture_screen",
        "screen_size",
        "get_active_window",
        "analyze_screen",
        "move_mouse",
        "click_screen",
        "double_click_screen",
        "scroll_screen",
        "verify_screen",
        "type_text",
        "press_key",
        "barehands_state",
        "barehands_present",
        "barehands_add_card",
        "barehands_add_image",
        "barehands_clear",
        "barehands_board_state",
    }
)


PUBLIC_API_TOOLS = frozenset(
    {
        "holiday_lookup",
        "knowledge_lookup",
        "book_search",
        "define_word",
        "research_arxiv",
        "research_crossref",
        "vehicle_lookup",
        "earthquake_search",
        "api_discover",
        "currency_convert",
        "location_lookup",
        "air_quality",
        "weather_alerts",
        "elevation_lookup",
        "country_info",
        "crypto_price",
        "trivia_question",
        "joke",
        "meal_search",
        "tv_search",
        "music_search",
        "musicbrainz_search",
        "anime_search",
        "anime_episodes",
        "ghibli_search",
        "openalex_search",
        "pubchem_lookup",
        "art_search",
        "nasa_eonet",
        "spacex_lookup",
        "sunrise_sunset",
        "topo_elevation",
        "public_ip",
        "reverse_geocode",
        "news_search",
        "cat_fact",
        "dog_image",
        "osm_search",
        "pokemon_lookup",
        "food_product",
        "cocktail_search",
        "openverse_search",
        "iss_location",
    }
)


SYSTEM_ROUTE_TOOLS = frozenset(
    {
        "integration_health",
        "roblox_mcp_setup",
        "screen_memory_setup",
        "tool_contract_audit",
    }
)


KNOWN_DYNAMIC_TOOL_PREFIXES = (
    ROBLOX_TOOL_PREFIX,
    N8N_MCP_PREFIX,
)


def all_static_tools() -> frozenset[str]:
    """Return every exact tool name owned by the static JARVIS registry."""
    groups = (
        N8N_TOOLS,
        JARVIS_PLATFORM_TOOLS,
        ANIPY_TOOLS,
        ROBLOX_MCP_TOOLS,
        UNREAL_MCP_TOOLS,
        GODS_EYE_TOOLS,
        SCREEN_MEMORY_TOOLS,
        SYSTEM_HEALTH_TOOLS,
        ADAPTIVE_RUNTIME_TOOLS,
        CONTEXT_MEMORY_TOOLS,
        AGENT_SKILL_TOOLS,
        BROWSER_TOOLS,
        JSON_ARGUMENT_TOOLS,
        CORE_RUNTIME_TOOLS,
        PUBLIC_API_TOOLS,
        SYSTEM_ROUTE_TOOLS,
    )
    combined: set[str] = set()
    for group in groups:
        combined.update(group)
    return frozenset(combined)


def registry_contract_report(
    planner_tools=None,
) -> dict:
    """Audit planner-visible tools against the canonical static registry."""
    registry = all_static_tools()
    planner_names = (
        {str(name) for name in (planner_tools or []) if str(name).strip()}
        if planner_tools is not None
        else None
    )

    report = {
        "registry_tool_count": len(registry),
        "planner_tool_count": len(planner_names) if planner_names is not None else None,
        "dynamic_prefixes": list(KNOWN_DYNAMIC_TOOL_PREFIXES),
        "planner_missing_from_registry": [],
        "registry_only_tools": [],
        "healthy": True,
    }

    if planner_names is None:
        return report

    planner_missing = sorted(
        name
        for name in planner_names
        if name not in registry
        and not any(name.startswith(prefix) for prefix in KNOWN_DYNAMIC_TOOL_PREFIXES)
    )
    registry_only = sorted(
        name
        for name in registry
        if name not in planner_names
        and not any(name.startswith(prefix) for prefix in KNOWN_DYNAMIC_TOOL_PREFIXES)
    )

    report["planner_missing_from_registry"] = planner_missing
    report["registry_only_tools"] = registry_only
    report["healthy"] = not planner_missing
    return report


def tool_contract_audit() -> dict:
    """Run a live planner/registry contract audit."""
    try:
        from planner import AVAILABLE_TOOLS

        report = registry_contract_report(AVAILABLE_TOOLS.keys())
        return {
            "success": True,
            "verified": True,
            "tool": "tool_contract_audit",
            **report,
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": True,
            "tool": "tool_contract_audit",
            "healthy": False,
            "error": str(exc),
        }



def validate_known_tools(tool_names) -> list[str]:
    """Return invalid names from a registry consumer."""
    if tool_names is None:
        return []
    return sorted(
        str(name)
        for name in tool_names
        if str(name) not in BROWSER_TOOLS
        and str(name) not in JSON_ARGUMENT_TOOLS
        and str(name) not in N8N_TOOLS
        and str(name) not in ANIPY_TOOLS
        and str(name) not in ROBLOX_MCP_TOOLS
        and str(name) not in UNREAL_MCP_TOOLS
        and str(name) not in CONTEXT_MEMORY_TOOLS
        and str(name) not in AGENT_SKILL_TOOLS
        and str(name) not in GODS_EYE_TOOLS
        and str(name) not in SCREEN_MEMORY_TOOLS
        and str(name) not in SYSTEM_HEALTH_TOOLS
        and str(name) not in ADAPTIVE_RUNTIME_TOOLS
        and str(name) not in JARVIS_PLATFORM_TOOLS
        and str(name) not in CORE_RUNTIME_TOOLS
        and str(name) not in PUBLIC_API_TOOLS
        and str(name) not in SYSTEM_ROUTE_TOOLS
        and not is_roblox_tool_name(name)
        and not is_n8n_mcp_tool_name(name)
    )
