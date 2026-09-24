# JARVIS Superpowers Integration Implementation Plan

**Goal:** Integrate Superpowers 6.4.1 into JARVIS's existing planner/agent
architecture without creating a second execution engine.

**Spec:** docs/superpowers/specs/2026-09-24-superpowers-integration-design.md

## Tasks

- [x] Vendor core upstream skills and MIT license.
- [x] Add native Superpowers workflow engine.
- [x] Add deterministic Superpowers tests.
- [x] Inject workflow directives into planner context.
- [x] Persist workflow selection on AgentTask.
- [ ] Run focused and full JARVIS suites.
- [ ] Verify GitHub Actions and runtime behavior.
