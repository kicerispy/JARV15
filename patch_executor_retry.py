from pathlib import Path
import shutil


path = Path("tool_executor.py")
backup = Path("tool_executor.py.before_action_retry.py")

text = path.read_text(encoding="utf-8")
shutil.copy2(path, backup)


# ==========================================================
# Add retryable screen-action helper
# ==========================================================

if "def should_retry_screen_action(" not in text:

    marker = "# ============================================================\n# EXECUTE PLAN"

    insert_at = text.find(marker)

    if insert_at == -1:
        raise SystemExit(
            "ERROR: EXECUTE PLAN marker not found."
        )

    helper = '''
# ============================================================
# SCREEN ACTION RETRY POLICY
# ============================================================

def should_retry_screen_action(
    tool_name: str,
) -> bool:
    """
    Return True for screen actions that are safe to
    re-localize and retry once after verification fails.

    The retry happens at the executor layer so the screen
    vision system gets a fresh observation of the UI.
    """

    return tool_name in {
        "click_screen",
        "double_click_screen",
        "move_mouse",
        "scroll_screen",
        "type_text",
        "press_key",
    }


'''

    text = (
        text[:insert_at]
        + helper
        + text[insert_at:]
    )


# ==========================================================
# Replace the normal-tool execution section
# ==========================================================

old_block = '''            else:
                result = run_tool(
                    tool_name,
                    argument,
                )

            # =================================================
            # OPTIONAL SCREEN VERIFICATION
            # =================================================

            result = verify_action_for_task(
                tool_name,
                result,
                multi_step,
            )
'''

new_block = '''            else:
                result = run_tool(
                    tool_name,
                    argument,
                )

            # =================================================
            # ACTION VERIFICATION + AUTOMATIC RETRY
            # =================================================

            result = verify_action_for_task(
                tool_name,
                result,
                multi_step,
            )

            if (
                should_retry_screen_action(
                    tool_name
                )
                and isinstance(
                    result,
                    dict,
                )
            ):

                first_success = bool(
                    result.get(
                        "success",
                        False,
                    )
                )

                first_verified = bool(
                    result.get(
                        "verified",
                        True,
                    )
                )

                if (
                    not first_success
                    or not first_verified
                ):

                    logger.warning(
                        "JARVIS: "
                        f"{tool_name} failed verification. "
                        "Retrying once with a fresh UI observation."
                    )

                    retry_result = run_tool(
                        tool_name,
                        argument,
                    )

                    retry_result = (
                        verify_action_for_task(
                            tool_name,
                            retry_result,
                            multi_step,
                        )
                    )

                    if isinstance(
                        retry_result,
                        dict,
                    ):
                        result = retry_result

                    logger.info(
                        "JARVIS: "
                        f"{tool_name} retry finished."
                    )

            # =================================================
            # CANCELLATION AFTER TOOL
            # =================================================
'''

# The replacement includes the cancellation header because the
# original code immediately continues into that section.
# Remove the duplicated cancellation header below after replacement.

if old_block not in text:
    shutil.copy2(backup, path)
    raise SystemExit(
        "ERROR: normal-tool verification block not found."
    )

text = text.replace(
    old_block,
    new_block,
    1,
)


# ==========================================================
# Remove duplicated cancellation header if produced
# ==========================================================

duplicate = '''            # =================================================
            # CANCELLATION AFTER TOOL
            # =================================================

            # =================================================
            # CANCELLATION AFTER TOOL
            # =================================================
'''

text = text.replace(
    duplicate,
    '''            # =================================================
            # CANCELLATION AFTER TOOL
            # =================================================

''',
    1,
)


path.write_text(
    text,
    encoding="utf-8",
)

print("PATCH_OK")