# JARVIS

JARVIS is a local-first personal AI assistant for Windows. It combines voice interaction, deterministic command routing, browser automation, computer control, web/API research, Roblox Studio integration, n8n workflow delegation, and a bounded autonomous software-engineering loop.

## Current architecture

- **Voice:** Whisper + Piper/voice stack
- **Conversation/planning:** Ollama-backed local models
- **Browser:** Playwright and optional Browser Use integration
- **Computer control:** allowlisted Windows actions and verification
- **Roblox:** Roblox Studio MCP integration
- **Automation:** optional n8n delegation
- **Coding/self-repair:** checkpoint → inspect → focused plan → edit → test → verification → bounded recovery
- **Self-healing/runtime resilience:** persistent tool-health telemetry, bounded circuit breakers, sanitized failure signatures, structured model-role fallbacks, and a persistent failure playbook that reuses prior recovery evidence
- **Learned autonomy:** bounded SQLite task traces, repeated-plan memory, conservative learned-strategy reuse, plan scoring, regression detection, temporary strategy quarantine, and automatic execution-trace verification
- **Local memory:** bounded semantic/preferences/procedure/lesson memory plus episodic failure lessons, with a SQLite FTS5 shadow index for faster deterministic recall
- **JARVIS Doctor:** read-only runtime/model/tool/Git diagnostics with optional compile and pytest probes
- **QoL diagnostics:** deterministic quick-check, resource/process/project/service diagnostics that avoid an LLM round-trip
- **Testing:** pytest regression suite plus GitHub Actions verification

JARVIS remains the orchestrator; specialist models and tools are capabilities it can delegate to.

## Requirements

JARVIS is Windows-first and currently targets Python 3.10+. The active development environment uses Python 3.12.

You also need:

- [Ollama](https://ollama.com/) running locally
- the local models configured in `config.py`
- a working microphone/audio output for voice mode
- Chromium/Chrome support for browser automation when that capability is used

Optional integrations include Roblox Studio MCP, n8n, and Browser Use.

## Quick start

Create a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For browser-agent support:

```powershell
python -m pip install -r requirements-browser-agent.txt
```

For development and tests:

```powershell
python -m pip install -r requirements-dev.txt
```

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Start JARVIS:

```powershell
python run_jarvis.py
```

The repository also includes `Run-Jarvis.bat` and `Start-Jarvis.ps1` for Windows launch workflows.

## Local models

The defaults are intentionally kept in `config.py` and can be overridden with environment variables.

The current default roles include:

- chat: `qwen3.5:9b`
- planner: `qwen3.5:9b`
- coding: `qwen2.5-coder:14b`
- coding fallback: `gemma4:26b`
- vision: `qwen2.5vl:3b`
- verification: `gemma4:e2b`

Pull only the models you actually want to run locally.

## Configuration

All machine-specific values should live in environment variables rather than source edits. See [.env.example](.env.example).

The resilience and memory layer stores local runtime state under `.jarvis_autonomy/`, which is ignored by Git. The healing journal remains JSONL for simple auditability, while repeated failure signatures are indexed in a small SQLite FTS5 playbook and the semantic-memory JSONL store can use a SQLite FTS5 shadow index for faster recall. Relevant environment controls include:
- `JARVIS_SELF_HEALING_ENABLED`
- `JARVIS_SELF_HEALING_MAX_ATTEMPTS`
- `JARVIS_TOOL_RESILIENCE_ENABLED`
- `JARVIS_TOOL_CIRCUIT_BREAKER_ENABLED`
- `JARVIS_TOOL_CIRCUIT_FAILURE_THRESHOLD`
- `JARVIS_TOOL_CIRCUIT_COOLDOWN_SECONDS`
- `JARVIS_MEMORY_ENABLED`
- `JARVIS_SELF_HEALING_FAILURE_MEMORY_ENABLED`
- `JARVIS_SELF_HEALING_RETRY_BACKOFF_BASE_SECONDS`
- `JARVIS_SELF_HEALING_RETRY_BACKOFF_MAX_SECONDS`
- `JARVIS_AUTONOMY_LEARNED_STRATEGY_ENABLED`
- `JARVIS_AUTONOMY_AUTO_VERIFICATION_ENABLED`
- `JARVIS_AUTONOMY_STRATEGY_QUARANTINE_SECONDS`
- `JARVIS_AUTONOMY_STRATEGY_MIN_SUCCESSES`
- `JARVIS_AUTONOMY_STRATEGY_MIN_SUCCESS_RATE`

Examples include:

- model selection
- Ollama endpoint
- microphone/output device IDs
- TTS tuning
- Roblox MCP endpoint
- n8n configuration
- planner/generation limits
- debug settings

Never commit a real `.env`, browser profile, cookies, tokens, API keys, or local runtime state.

## Testing

Run the complete suite locally:

```powershell
python -m pytest -q
```

JARVIS also exposes deterministic self-service tools:
- `anime_streaming_links` for official anime watch-page discovery using AniList metadata plus web search, filtered to known streaming services. It returns watch-page URLs and provider names; it does not resolve direct media manifests or protected stream URLs.
- `jarvis_doctor` for read-only system/model/tool diagnostics
- `tool_health` for reliability and circuit-breaker state
- `ollama_models` for local model inventory
- `memory_remember`, `memory_recall`, and `memory_forget` for explicit local memory control
- `healing_hints` and `healing_history` for inspecting what has failed and what recovery patterns JARVIS has learned
- `autonomy_status`, `strategy_history`, and `regression_status` for inspecting learned execution strategies, trace health, and detected regressions
- `jarvis_quickcheck`, `resource_status`, `process_snapshot`, `project_snapshot`, and `service_status` for fast deterministic diagnostics

Run the public CI-focused set:

```powershell
python -m pytest tests/test_agent_planning.py tests/test_planner_model_manager.py tests/test_browser_agent.py tests/test_task_controller.py tests/test_autonomy_kernel_v2.py -q
```

GitHub Actions runs compile checks, focused regressions, and the full pytest suite on pushes and pull requests.

## Autonomous coding safety

Explicit software changes use a bounded workflow rather than unrestricted model output:

1. resolve the target
2. gather verified source evidence
3. create a checkpoint before mutation
4. apply the smallest supported edit
5. run focused tests
6. verify the resulting diff
7. perform bounded recovery when an edit/test fails

Read-only source inspection is deliberately kept out of the mutation workflow.

## Public-project hygiene

This repository intentionally ignores:

- browser automation profiles
- cookies/session state
- local databases and history
- model weights
- audio/images generated at runtime
- checkpoints and autonomy scratch state
- local environment files
- backup/debug artifacts

See [SECURITY.md](SECURITY.md) before adding credentials or external integrations.

## License

MIT. See [LICENSE](LICENSE).
