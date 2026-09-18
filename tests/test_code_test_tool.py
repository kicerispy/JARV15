from pathlib import Path

from tool_result import ToolResult
from tools import code_test, normalize_tool_result


def test_code_test_accepts_python_style_dict_and_py_compile_alias():
    result = code_test(
        "{'mode': 'py_compile', 'path': 'browser_controller.py'}"
    )

    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["verified"] is True
    assert result["mode"] == "compile"
    assert result["path"] == "browser_controller.py"


def test_code_test_failure_string_is_not_normalized_as_success():
    result = code_test(
        "{'mode': 'py_compile', 'path': 'missing_browser_controller.py'}"
    )

    assert isinstance(result, str)
    assert result.startswith("Code test target not found:")

    normalized = normalize_tool_result(
        result=ToolResult(
            success=True,
            tool="code_test",
            data=result,
        )
    )

    assert normalized[0] is True

    # The normalizer receives a ToolResult above, so it preserves the
    # caller-provided success bit. Verify the raw string path separately.
    normalized_raw = __import__("tool_executor").normalize_tool_result(result)
    assert normalized_raw[0] is False
    assert normalized_raw[1] is False


def test_code_test_compile_target_stays_inside_project():
    result = code_test(
        "{'mode': 'py_compile', 'path': '../browser_controller.py'}"
    )

    assert isinstance(result, str)
    assert result.startswith("Code test refused: target is outside the project.")
