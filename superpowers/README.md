# JARVIS Superpowers

JARVIS now includes a native adapter for the upstream **Superpowers 6.4.1**
software-development methodology.

Upstream: https://github.com/obra/superpowers

## Integrated

- Pinned upstream skill definitions under `superpowers/skills/`.
- Native workflow classification in `superpowers_engine.py`.
- Planner directives for software tasks.
- Agent-task workflow state so replanning keeps the selected methodology.
- Design/spec and multi-step plan artifact conventions under
  `docs/superpowers/`.
- Existing JARVIS checkpoints, diagnostics, tests, and verification remain
  the execution authority.

Harness-specific upstream helper scripts are not executed directly. JARVIS
maps those responsibilities onto its existing Python tools, task controller,
checkpoint system, test runner, and evidence loop.
