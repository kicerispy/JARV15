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
        "agent_browser_action",
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
        "agent_browser_action",
    }
)


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
        and not is_roblox_tool_name(name)
    )
