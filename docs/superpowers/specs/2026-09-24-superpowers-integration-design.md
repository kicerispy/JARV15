# JARVIS Superpowers Integration — Design Specification

**Date:** 2026-09-24
**Upstream reference:** obra/superpowers 6.4.1

## Goal

Integrate Superpowers methodology into JARVIS without replacing its existing
planner, task controller, checkpoints, diagnostics, browser tools, or
verification system.

## Architecture

Vendor the upstream skill definitions and use a deterministic native adapter
to select an engineering workflow before the LLM planner generates executable
tool calls. Store the chosen workflow on AgentTask so replanning cannot silently
drop the methodology.

## Workflow

- Bounded repair: systematic debugging + TDD-oriented repair + verification.
- Bounded change: design + TDD-oriented implementation + verification.
- Architectural/multi-step work: design + writing-plans + inline execution +
  review/verification guidance.
- Ordinary conversation and non-software work remain unchanged.

## Acceptance

- Deterministic workflow selection is unit-tested.
- Planner context receives the selected workflow rules.
- Agent replanning retains the workflow context.
- Skill files and version are locally inspectable.
