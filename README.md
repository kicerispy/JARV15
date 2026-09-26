# JARVIS

JARVIS is a local-first personal AI assistant for Windows. It combines voice interaction, deterministic command routing, browser automation, computer control, web/API research, Roblox Studio integration, n8n workflow delegation, and a bounded autonomous software-engineering loop.

## Current architecture

- **Voice:** Whisper + Piper/voice stack
- **Conversation/planning:** Ollama-backed local models
- **Browser:** Playwright and optional Browser Use integration
- **Computer control:** allowlisted Windows actions and verification
- **Roblox:** Roblox Studio MCP integration
- **Unreal Engine:** native Unreal_mcp MCP gateway integration
- **Automation:** optional n8n delegation
- **Coding/self-repair:** checkpoint → inspect → focused plan → edit → test → verification → bounded recovery
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

## Anime / anipy-cli

JARVIS includes the upstream sdaqo/anipy-cli stack at an exact matching release:

- anipy-api==3.10.1
- anipy-cli==3.10.1

The upstream packages are installed as published; JARVIS does not fork, strip, or replace their provider, player, tracker, download, remux, history, seasonal, AniList, MyAnimeList, Discord-presence, or native CLI functionality.

JARVIS adds a thin orchestration layer around that upstream stack. The native CLI remains available through the anipy_cli tool, while structured JARVIS tools expose provider discovery, search, metadata, episode lookup, stream resolution, and episode downloads.

## Adaptive runtime

JARVIS can optionally enable Hindsight as an additional long-term context backend with \`JARVIS_ADAPTIVE_MEMORY_ENABLED=1\`. The default memory order remains OpenViking -> agentmemory -> optional Hindsight -> the local fallback.

The runtime also includes bounded self-healing state, persistent failure patterns, tool circuit breaking, learned verified strategy reuse, a local FTS5 code index, and deterministic doctor/QoL diagnostics.

Optional integrations include direct n8n MCP workflow discovery/architecture/building, the Vercel agent-browser CLI fallback, and Magnitude capability detection. These are advisory or opt-in and do not replace the existing Ollama/Playwright/Anipy/Roblox/Unreal paths automatically.


Examples:

```text
"Run anipy-cli -D -s One Piece:1-3:sub"
"Search anime One Piece"
"List episodes for Cowboy Bebop"
"Get stream link for Naruto episode 12"
"Download Demon Slayer episodes 1-3"
"Watch One Piece episode 1"
```

The native anipy-cli command continues to own its normal interactive configuration and player behavior. Download/remux operations that use the structured JARVIS tool use the same upstream Downloader, download-path formatting, retry logic, and post-download hook path. FFmpeg and any external player required by the selected upstream mode must be installed separately.

## Unreal Engine / Unreal_mcp

JARVIS integrates with [ChiR24/Unreal_mcp](https://github.com/ChiR24/Unreal_mcp) through its native MCP Streamable HTTP gateway. The upstream project exposes one public `unreal` gateway with `search`, `describe`, `execute`, and `configure` operations, so JARVIS keeps the upstream capability catalog and execution semantics intact instead of copying the 23 Unreal capability families into Python.

The current upstream `dev` branch documents native MCP at `http://127.0.0.1:3000/mcp`, with capability-token authentication and session-based HTTP/SSE. JARVIS reads the capability token from `JARVIS_UNREAL_MCP_TOKEN`, `JARVIS_UNREAL_MCP_TOKEN_FILE`, or `<UnrealProject>/Saved/MCP/capability-token` when `JARVIS_UNREAL_MCP_PROJECT_PATH` is configured.

Useful commands include:

```text
"check Unreal MCP status"
"search Unreal for spawning an actor"
"describe Unreal capability manage_asset.import_asset"
"execute Unreal capability manage_asset.import_asset"
"set up Unreal MCP"
```

`unreal_mcp_setup` clones or refreshes the upstream `dev` branch under `.jarvis_external/Unreal_mcp` and reports the native plugin path. It does not silently modify an Unreal project. Install `plugins/McpAutomationBridge` into the target project, enable Native MCP on port 3000, and configure the JARVIS endpoint/token settings before executing Unreal actions.


## License

MIT. See [LICENSE](LICENSE).
