# JARVIS + n8n

JARVIS delegates workflow-class tasks to n8n when n8n is enabled.

## JARVIS owns

- wake word, VAD, Whisper, and Piper
- real-time Windows/computer control
- browser DOM automation
- Roblox Studio MCP operations
- coding, diagnosis, checkpoints, edits, and validation
- evidence capture and final answer composition

## n8n owns

- schedules and recurring tasks
- persistent monitoring
- delayed and long-running workflows
- conditional branching
- notification fan-out
- external-service integrations
- workflow-level retries and state

n8n is called through one HTTP Webhook gateway. The webhook receives structured JSON and can route on workflow_class:

- schedule
- monitor
- integration
- orchestration

JARVIS sets allow_local_fallback=false for delegated workflows. A failed n8n dispatch therefore remains an n8n failure instead of being silently reinterpreted as a different local task.

## Enable the bridge

Set these environment variables before starting JARVIS:

    $env:JARVIS_N8N_ENABLED="1"
    $env:JARVIS_N8N_BASE_URL="http://127.0.0.1:5678"
    $env:JARVIS_N8N_WEBHOOK_PATH="webhook/jarvis-gateway"

An optional token can be set with:

    $env:JARVIS_N8N_WEBHOOK_TOKEN="replace-with-a-long-random-token"

For a remote n8n instance, the bridge refuses to dispatch without a webhook token.

## Start local n8n

n8n supports self-hosting with npm or Docker. For a simple local development setup:

    npx n8n

JARVIS expects the n8n base URL at http://127.0.0.1:5678 by default.

When JARVIS_N8N_ENABLED=1, JARVIS also starts the repository-local n8n launcher automatically in the background. It first checks port 5678 and will not create a duplicate n8n process. JARVIS startup does not wait for n8n to finish loading; a background monitor reports whether n8n becomes reachable.

Disable automatic launch without disabling the n8n bridge with:

    $env:JARVIS_N8N_AUTOSTART="0"

## Create the gateway workflow

Create a workflow in n8n with a Webhook trigger:

- Method: POST
- Path: jarvis-gateway
- Respond: Immediately for long-running or scheduled jobs
- Respond: When Last Node Finishes for short synchronous workflows

Branch on the incoming workflow_class field and put your actual workflow logic behind the gateway or call sub-workflows from it.

Return JSON containing at least:

    {
      "accepted": true,
      "message": "Workflow accepted."
    }

Additional useful fields include execution_id and workflow_class. The bridge preserves returned JSON fields.

## Test

From JARVIS:

    Is n8n running?

Then test a delegated workflow request:

    Remind me tomorrow to test the Roblox game

## Security

Keep a local development instance bound to localhost unless remote access is required. n8n provides a security audit for unprotected webhooks, risky nodes, credentials, filesystem access, and instance security settings.

For remote deployments, use HTTPS and configure JARVIS_N8N_WEBHOOK_TOKEN.

## Source control

Keep n8n workflow exports and backups separate from JARVIS runtime artifacts unless you intentionally want them versioned. n8n also provides Git-based environment source control on supported plans.

## n8n -> JARVIS local computer actions

When n8n needs to perform an action on the Windows desktop, call the loopback JARVIS action gateway instead of using unrestricted shell/PowerShell execution.

Endpoint:

    http://127.0.0.1:8765/v1/jarvis/action

Health:

    http://127.0.0.1:8765/healthz

Supported actions:

    open_program: {"program":"spotify"}
    browser_goto: {"url":"https://..."}
    browser_search_google: {"query":"..."}
    type_text: {"text":"..."}
    press_key: {"key":"enter"}
    click_screen_target: {"target":"Spotify Play button"}
    analyze_screen: {"question":"What is visible?"}
    verify_screen_state: {"expected":"Spotify is playing music"}
    get_active_window: {}
    get_screen_size: {}

The program launcher reuses JARVIS's existing application allowlist. The gateway does not accept arbitrary shell commands, PowerShell, executable paths, or Python.

The service binds only to 127.0.0.1. When JARVIS_N8N_WEBHOOK_TOKEN is configured, the same value is required in the X-JARVIS-N8N-TOKEN header. Keep n8n local-only during development.

A useful workflow pattern is:

    n8n trigger/schedule
        ↓
    workflow logic / service integrations
        ↓
    HTTP Request -> JARVIS local action
        ↓
    JARVIS computer action
        ↓
    JARVIS browser/screen verification
        ↓
    workflow continues or reports failure

This is the intended ownership split: n8n handles persistence, schedules, branching, retries, and external services; JARVIS handles real-time Windows control and visual verification.
## First computer workflow: Spotify Liked Songs

An importable workflow is included at:

    n8n/workflows/jarvis-gateway-spotify.json

Import that workflow into n8n, publish/activate it, and keep its webhook path as
jarvis-gateway. It routes requests containing Spotify + Liked Songs to the
dedicated JARVIS action.

The action:

1. Opens Spotify using JARVIS's existing Windows application allowlist.
2. Uses Spotify's documented Windows shortcut Alt+Shift+S to go to Liked Songs.
3. Uses JARVIS screen vision to verify the Liked Songs view.
4. Checks whether playback is already active; if not, uses Spotify's documented
   Space Play/Pause shortcut to start playback.
5. Verifies the final Spotify playback state with JARVIS screen vision.

This keeps the side-effecting desktop interaction in JARVIS while n8n owns the
workflow invocation and orchestration.
