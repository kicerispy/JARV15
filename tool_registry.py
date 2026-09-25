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
\nJARVIS_PLATFORM_TOOLS = frozenset(
    {
        "jarvis_doctor",
        "tool_health",
        "memory_remember",
        "memory_recall",
        "memory_forget",
        "ollama_models",
        "healing_history",
        "tool_reset",
        "memory_status",
        "jarvis_capabilities",
    }
)



def is_n8n_mcp_tool_name(name) -> bool:
    return str(name or "").startswith(N8N_MCP_PREFIX)


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
        "jarvis_doctor",
        "memory_remember",
        "memory_recall",
        "memory_forget",
        "code_diagnose",
        "dev_command",
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
        and str(name) not in JARVIS_PLATFORM_TOOLS
        and not is_roblox_tool_name(name)
        and not is_n8n_mcp_tool_name(name)
    )
