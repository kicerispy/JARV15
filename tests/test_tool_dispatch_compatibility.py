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
