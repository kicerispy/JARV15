from pathlib import Path
import shutil
import re


path = Path("agent_core.py")
backup = Path("agent_core.py.before_verification.py")

text = path.read_text(encoding="utf-8")
shutil.copy2(path, backup)


# ==========================================================
# Add imports
# ==========================================================

if "import hashlib" not in text:
    text = text.replace(
        "import time\n",
        "import time\nimport hashlib\n",
        1,
    )

if "import pyautogui" not in text:
    text = text.replace(
        "import time\n",
        "import time\nimport pyautogui\n",
        1,
    )


# ==========================================================
# Add verification helpers
# ==========================================================

if "def _agent_screen_signature(" not in text:

    marker = "class JarvisAgent"

    insert_at = text.find(marker)

    if insert_at == -1:
        raise SystemExit(
            "ERROR: JarvisAgent class not found."
        )

    helper = '''
# ==========================================================
# Agent Action Verification
# ==========================================================

def _agent_screen_signature():
    try:
        image = pyautogui.screenshot()

        small = image.resize(
            (
                max(1, image.width // 8),
                max(1, image.height // 8),
            )
        )

        data = small.tobytes()

        return hashlib.sha256(
            data
        ).hexdigest()

    except Exception:
        return None


def _agent_verify_screen_changed(
    before_signature,
    wait_seconds=0.75,
):
    if not before_signature:
        return True

    time.sleep(
        wait_seconds
    )

    after_signature = (
        _agent_screen_signature()
    )

    if not after_signature:
        return True

    return (
        after_signature
        != before_signature
    )


def _agent_is_click_action(
    task,
):
    if not task or not task.steps:
        return False

    executable = [
        step
        for step in task.steps
        if step.tool
    ]

    if len(executable) != 1:
        return False

    return (
        executable[0].tool
        in {
            "click_screen",
            "double_click_screen",
        }
    )


'''

    text = (
        text[:insert_at]
        + helper
        + text[insert_at:]
    )


# ==========================================================
# Replace execute_task()
# ==========================================================

start_marker = "    def execute_task(\n"
end_marker = "    # ======================================================\n    # Full Run"

start = text.find(start_marker)
end = text.find(end_marker)

if start == -1:
    raise SystemExit(
        "ERROR: execute_task() not found."
    )

if end == -1 or end <= start:
    raise SystemExit(
        "ERROR: execute_task() end marker not found."
    )


new_method = '''    def execute_task(
        self,
        task: AgentTask,
        active_context,
        task_state,
        speak_callback,
    ) -> AgentTask:

        if task.status in {
            "conversation",
            "failed",
            "cancelled",
        }:
            return task

        if not task.planner_result:
            task.status = "failed"
            task.error = (
                "No valid planner result."
            )

            self.state["last_status"] = (
                task.status
            )

            self.state["last_error"] = (
                task.error
            )

            return task

        task.status = "executing"
        task.started_at = time.time()

        logger.info(
            "JARVIS AGENT: "
            "Handing task to existing executor."
        )

        # --------------------------------------------------
        # Capture screen state immediately before a click.
        # --------------------------------------------------

        verify_click = _agent_is_click_action(
            task
        )

        before_signature = None

        if verify_click:
            before_signature = (
                _agent_screen_signature()
            )

            logger.info(
                "JARVIS AGENT: "
                "Captured pre-action screen signature."
            )

        try:

            task.execution_result = self.executor(
                task.planner_result,
                active_context,
                task_state,
                speak_callback,
            )

            task.completed_at = time.time()

            result_text = str(
                task.execution_result or ""
            ).strip().lower()

            # --------------------------------------------------
            # Existing executor result handling.
            # --------------------------------------------------

            if result_text == "cancelled":

                task.status = "cancelled"

                for step in task.steps:
                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "cancelled"

            elif result_text == "done":

                # --------------------------------------------------
                # Post-action verification.
                #
                # Only used for a single click/double-click task.
                # We verify that the visible screen actually changed.
                # --------------------------------------------------

                verification_passed = True

                if verify_click:

                    verification_passed = (
                        _agent_verify_screen_changed(
                            before_signature,
                            wait_seconds=0.75,
                        )
                    )

                    logger.info(
                        "JARVIS AGENT: "
                        f"Post-click screen verification="
                        f"{verification_passed}"
                    )

                if verification_passed:

                    task.status = "completed"

                    for step in task.steps:
                        step.status = "completed"

                else:

                    # --------------------------------------------------
                    # One automatic recovery attempt.
                    #
                    # Re-run the existing executor against the same
                    # validated plan. The screen may have changed
                    # slightly and the vision locator will observe
                    # the fresh screen.
                    # --------------------------------------------------

                    logger.warning(
                        "JARVIS AGENT: "
                        "Click verification failed. "
                        "Starting automatic recovery attempt."
                    )

                    recovery_before = (
                        _agent_screen_signature()
                    )

                    try:

                        recovery_result = self.executor(
                            task.planner_result,
                            active_context,
                            task_state,
                            speak_callback,
                        )

                        recovery_text = str(
                            recovery_result or ""
                        ).strip().lower()

                        if recovery_text == "done":

                            recovery_verified = (
                                _agent_verify_screen_changed(
                                    recovery_before,
                                    wait_seconds=0.75,
                                )
                            )

                        else:

                            recovery_verified = False

                        logger.info(
                            "JARVIS AGENT: "
                            f"Recovery verification="
                            f"{recovery_verified}"
                        )

                        if recovery_verified:

                            task.status = "completed"

                            for step in task.steps:
                                step.status = "completed"

                            task.execution_result = (
                                recovery_result
                            )

                        else:

                            task.status = "failed"

                            task.error = (
                                "The action executed, "
                                "but screen verification failed "
                                "after the recovery attempt."
                            )

                            for step in task.steps:
                                if step.status in {
                                    "pending",
                                    "executing",
                                }:
                                    step.status = "failed"
                                    step.error = task.error

                    except Exception as recovery_exc:

                        task.status = "failed"

                        task.error = (
                            "Action verification failed and "
                            f"recovery raised: {recovery_exc}"
                        )

                        for step in task.steps:
                            if step.status in {
                                "pending",
                                "executing",
                            }:
                                step.status = "failed"
                                step.error = task.error

                else:

                    task.status = "completed"

                    for step in task.steps:
                        step.status = "completed"

            else:

                task.status = "failed"

                task.error = (
                    str(
                        task.execution_result
                        or "Executor reported a failure."
                    )
                )

                for step in task.steps:
                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "failed"
                        step.error = task.error

            self.state["last_result"] = (
                task.execution_result
            )

            self.state["last_status"] = (
                task.status
            )

            if task.status == "failed":
                self.state["last_error"] = (
                    task.error
                )

            logger.info(
                "JARVIS AGENT: "
                f"Execution finished with "
                f"status={task.status}"
            )

        except Exception as exc:

            task.completed_at = time.time()
            task.status = "failed"
            task.error = str(exc)

            self.state["last_error"] = str(exc)
            self.state["last_status"] = (
                task.status
            )

            for step in task.steps:
                if step.status in {
                    "pending",
                    "executing",
                }:
                    step.status = "failed"
                    step.error = str(exc)

            logger.exception(
                "JARVIS AGENT: Execution failed"
            )

        return task

'''


text = (
    text[:start]
    + new_method
    + text[end:]
)


path.write_text(
    text,
    encoding="utf-8",
)

print("PATCH_OK")