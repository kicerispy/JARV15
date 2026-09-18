from pathlib import Path
import shutil

path = Path("agent_core.py")
backup = Path("agent_core.py.before_status_fix.py")

text = path.read_text(encoding="utf-8")
shutil.copy2(path, backup)

start_marker = "    def execute_task(\n"
end_marker = "    # ======================================================\n    # Full Run"

start = text.find(start_marker)
end = text.find(end_marker)

if start == -1:
    raise SystemExit("ERROR: execute_task() not found")

if end == -1 or end <= start:
    raise SystemExit("ERROR: execute_task() end marker not found")

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
            task.error = "No valid planner result."

            self.state["last_status"] = task.status
            self.state["last_error"] = task.error

            return task

        task.status = "executing"
        task.started_at = time.time()

        logger.info(
            "JARVIS AGENT: "
            "Handing task to existing executor."
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

            if result_text == "cancelled":

                task.status = "cancelled"

                for step in task.steps:
                    if step.status in {
                        "pending",
                        "executing",
                    }:
                        step.status = "cancelled"

            elif result_text == "done":

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
            self.state["last_status"] = task.status

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