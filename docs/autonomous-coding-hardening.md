# Autonomous coding hardening

JARVIS's bounded software-change loop now separates fast planning from deep repair work.

## Runtime flow

```
explicit software change
    -> deterministic target resolution
    -> read_file
    -> fast CHANGE planner
    -> code_checkpoint
    -> edit_file
    -> focused code_test
    -> git diff --check
    -> completed

failed edit/test
    -> restore checkpoint
    -> focused REPAIR planner
    -> checkpoint
    -> corrective edit
    -> focused test
    -> diff check
```

Bounded CHANGE planning uses the configurable `JARVIS_CHANGE_PLANNER_MODEL`
(defaulting to the normal planner model). The coding model remains reserved for
focused corrective REPAIR work and is still available as the CHANGE fallback.

## Validation

Every successful source mutation is expected to have a focused `code_test`
and a deterministic `git_diff_check` before completion.

Failed code validation is explicitly retryable, which lets Agent Core route
the failure into checkpoint restoration and corrective repair.

## Contract benchmark

The canonical request set is stored in:

`benchmarks/autonomous_coding_cases.json`

Run the deterministic contract benchmark with:

```powershell
.\jarvis_cuda\Scripts\python.exe -m pytest -q tests/test_autonomy_hardening.py --tb=short
```

The benchmark is intentionally side-effect free except for the existing test
fixture machinery; it validates routing, source-target resolution, model-role
selection, validation modes, and bounded recovery behavior.

## Local runtime state

`self_improvement_suggestions.json` is runtime state, not source. It is no
longer tracked by Git. A static schema example is kept at
`self_improvement_suggestions.example.json`.
