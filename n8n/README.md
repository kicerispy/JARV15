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