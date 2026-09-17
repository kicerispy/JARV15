# Barehands Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional barehands support to JARVIS so JARVIS can drive the barehands visual ring and glass board without copying the AGPL project into the JARVIS source tree.

**Architecture:** JARVIS will use a small `barehands_controller.py` adapter that talks to a separately installed barehands instance over its documented localhost HTTP API. The controller will expose state, board commands, and board-state inspection as normal JARVIS tools. Barehands remains optional: missing/offline barehands produces a clean tool failure rather than breaking JARVIS.

**Tech Stack:** Python standard library HTTP client, existing JARVIS tool dispatcher/planner, barehands localhost HTTP API, `unittest`.

**Spec:** `docs/superpowers/plans/2026-09-16-barehands-integration.md`

## Global Constraints

- Do not copy barehands source code into JARVIS; integrate through its documented localhost protocol.
- Barehands is optional and must never become a startup dependency for JARVIS.
- Do not invoke barehands shell scripts from JARVIS; use the localhost HTTP API so Windows remains first-class.
- Validate barehands board actions against the documented allowlist before sending them.
- Keep media paths relative to barehands' configured media jail; JARVIS must not bypass that jail.
- Preserve existing JARVIS tool-result behavior and planner validation.
- Add tests for offline behavior, state writes, command validation, and board-state reads.

---

### Task 1: Add the barehands adapter and tests

**Files:**
- Create: `barehands_controller.py`
- Create: `tests/test_barehands_controller.py`

**Interfaces:**
- Produces `BarehandsController(base_url: str = "http://127.0.0.1:8794", timeout: float = 1.5)`.
- Produces `set_state(state: str) -> ToolResult` for `idle`, `listening`, `thinking`, and `speaking`.
- Produces `board_command(action: str, **payload) -> ToolResult` with the documented allowlist.
- Produces convenience methods `present(title, body)`, `add_card(title, body)`, `add_image(src, title="", body="")`, `clear()`, and `board_state()`.
- Produces `is_available() -> bool` using `/config`.

- [ ] **Step 1: Write failing unit tests**

Test the controller with mocked `urllib.request.urlopen` rather than requiring a live barehands server. Cover: state validation rejects unknown states; valid state writes POST `/cmd` only through the HTTP API; unsupported board actions are rejected before any request; `add_image` forwards only the media source and display fields; `board_state()` decodes JSON from GET `/state`; connection errors return `ToolResult(success=False)` rather than raising.

- [ ] **Step 2: Run the focused test file and confirm failure**

Run: `python -m unittest tests.test_barehands_controller -v`

Expected: FAIL because `barehands_controller.py` and its public interfaces do not yet exist.

- [ ] **Step 3: Implement the minimal HTTP adapter**

Use only Python standard-library HTTP primitives. POST JSON commands to `/cmd`; GET `/state` and `/config`; use short timeouts; normalize responses into the existing `ToolResult` contract. The adapter must not launch barehands, inspect its filesystem, or invoke its `.bat`/`.sh` files.

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: `python -m unittest tests.test_barehands_controller -v`

Expected: PASS for all controller tests.

- [ ] **Step 5: Commit**

```bash
git add barehands_controller.py tests/test_barehands_controller.py
git commit -m "feat: add optional barehands controller"
```

---

### Task 2: Register barehands as JARVIS tools

**Files:**
- Modify: `planner.py`
- Modify: `tools.py`
- Modify: `tool_executor.py`
- Test: `tests/test_barehands_controller.py`

**Interfaces:**
- Adds planner tools: `barehands_state`, `barehands_present`, `barehands_add_card`, `barehands_add_image`, `barehands_clear`, `barehands_board_state`.
- `barehands_state` argument is one of `idle|listening|thinking|speaking`.
- `barehands_present` and `barehands_add_card` use `title|||body`.
- `barehands_add_image` uses `src|||title|||body`.
- `barehands_clear` uses an empty argument.
- `barehands_board_state` uses an empty argument.

- [ ] **Step 1: Add dispatcher tests**

Add mocked tests that call `tools._run_tool_raw()` for each new tool and assert the correct controller method is selected and the returned `ToolResult` is preserved.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest tests.test_barehands_controller -v`

Expected: FAIL for the new dispatcher cases because the tool names are not registered/handled yet.

- [ ] **Step 3: Add planner registrations**

Add the six tools to `AVAILABLE_TOOLS` with concise descriptions and extend the planner prompt with argument formats and the rule that barehands is an optional visual-output capability.

- [ ] **Step 4: Add tool dispatch**

Import the controller lazily inside the relevant dispatcher branches so JARVIS startup does not require barehands-specific initialization. Return the controller's `ToolResult` unchanged.

- [ ] **Step 5: Keep executor browser behavior unchanged**

Add no special execution path beyond any tool grouping needed by existing trace handling. Barehands commands are ordinary tools and must use the existing execution/result normalization path.

- [ ] **Step 6: Run focused tests**

Run: `python -m unittest tests.test_barehands_controller -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add planner.py tools.py tool_executor.py tests/test_barehands_controller.py
git commit -m "feat: expose barehands as JARVIS tools"
```

---

### Task 3: Add automatic JARVIS visual-state synchronization

**Files:**
- Create: `barehands_state.py`
- Modify: the JARVIS runtime entry point that currently transitions between listening/thinking/speaking/idle states (identify the existing state-transition functions before editing)
- Test: `tests/test_barehands_controller.py`

**Interfaces:**
- `barehands_state.py` exposes `set_barehands_state(state: str) -> None` and never raises into the main JARVIS loop.
- It uses the singleton/default `BarehandsController` and silently logs debug information when barehands is unavailable.

- [ ] **Step 1: Write tests for state synchronization**

Test that `set_barehands_state("thinking")` calls the controller once, while an offline controller does not raise. Test all four supported states.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m unittest tests.test_barehands_controller -v`

Expected: FAIL because the state bridge does not exist.

- [ ] **Step 3: Implement the non-blocking state bridge**

Keep the bridge synchronous and short because barehands calls have a 1.5-second maximum timeout. Catch all adapter errors and log them at debug level. Do not make JARVIS wait for barehands to become available.

- [ ] **Step 4: Wire only existing lifecycle transitions**

Map existing JARVIS lifecycle states to barehands states: listening → `listening`, planner/execution work → `thinking`, TTS playback → `speaking`, and return to idle → `idle`. Do not restructure the voice loop during this feature.

- [ ] **Step 5: Run tests and a syntax/import check**

Run: `python -m unittest discover -v` and `python -m py_compile barehands_controller.py barehands_state.py planner.py tools.py tool_executor.py`

Expected: tests pass and compilation completes without errors.

- [ ] **Step 6: Commit**

```bash
git add barehands_state.py planner.py tools.py tool_executor.py tests/test_barehands_controller.py
git commit -m "feat: sync JARVIS state with barehands"
```

---

## Verification Checklist

- [ ] JARVIS imports successfully with no barehands installation present.
- [ ] All new tools fail gracefully when `127.0.0.1:8794` is unavailable.
- [ ] A live barehands instance accepts `barehands_state thinking` and a simple `barehands_present` command.
- [ ] `barehands_board_state` reads the live board state without touching barehands files directly.
- [ ] No barehands source code is copied into JARVIS.
- [ ] Existing browser tools and first-result routing remain unchanged.
