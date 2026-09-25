from unittest.mock import patch

import tools


def test_execute_tool_is_backward_compatible_alias():
    expected = object()

    with patch.object(tools, "run_tool", return_value=expected) as run_tool:
        result = tools.execute_tool("n8n_workflow_builder", '{"request":"Build it"}')

    assert result is expected
    run_tool.assert_called_once_with(
        "n8n_workflow_builder",
        '{"request":"Build it"}',
    )


def test_n8n_mcp_status_bypasses_legacy_n8n_bridge():
    bridge_result = {"success": False, "message": "bridge must not be called"}
    mcp_result = {"success": True, "verified": True, "message": "native MCP"}

    with patch("n8n_bridge.run_n8n_workflow", return_value=bridge_result) as bridge, \
         patch("n8n_mcp.status", return_value=mcp_result) as status:
        result = tools._run_tool_raw("n8n_mcp_status", "")

    assert result == mcp_result
    status.assert_called_once_with()
    bridge.assert_not_called()


def test_n8n_workflow_builder_bypasses_legacy_n8n_bridge():
    bridge_result = {"success": False, "message": "bridge must not be called"}
    builder_result = {"success": True, "verified": True, "message": "builder reached"}
    argument = '{"request":"Build it","test":false,"activate":false}'

    with patch("n8n_bridge.run_n8n_workflow", return_value=bridge_result) as bridge, \
         patch("n8n_workflow_builder.run_builder", return_value=builder_result) as run_builder:
        result = tools._run_tool_raw("n8n_workflow_builder", argument)

    assert result == builder_result
    run_builder.assert_called_once_with({
        "request": "Build it",
        "test": False,
        "activate": False,
    })
    bridge.assert_not_called()
