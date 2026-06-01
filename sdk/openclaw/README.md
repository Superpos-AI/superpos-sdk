# Superpos Skill for OpenClaw

An [OpenClaw](https://github.com/openclaw/openclaw) skill plugin that turns OpenClaw into a first-class [Superpos](https://github.com/Superpos-AI/superpos-app) agent. It polls for tasks, manages shared knowledge, subscribes to events, and maintains agent health — all through OpenClaw's skill system.

## Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) installed and configured
- `curl` and `jq` available in PATH
- Access to a Superpos instance

## Installation

### Option 1: Symlink (development)

```bash
ln -s /path/to/superpos-app/sdk/openclaw ~/.openclaw/skills/superpos
```

### Option 2: Copy

```bash
cp -r /path/to/superpos-app/sdk/openclaw ~/.openclaw/skills/superpos
# Bundle the Shell SDK so scripts can find it without the repo tree
mkdir -p ~/.openclaw/skills/superpos/lib
cp /path/to/superpos-app/sdk/shell/src/superpos-sdk.sh ~/.openclaw/skills/superpos/lib/
```

Alternatively, set `SUPERPOS_SHELL_SDK` to point at the Shell SDK:

```bash
export SUPERPOS_SHELL_SDK=/path/to/superpos-app/sdk/shell/src/superpos-sdk.sh
```

## Configuration

Add the following to your `~/.openclaw/openclaw.json`:

```json
{
  "skills": {
    "entries": {
      "superpos": {
        "enabled": true,
        "env": {
          "SUPERPOS_BASE_URL": "https://superpos.example.com",
          "SUPERPOS_HIVE_ID": "01HXYZ...",
          "SUPERPOS_AGENT_NAME": "my-openclaw-agent",
          "SUPERPOS_AGENT_ID": "01HAGENT...",
          "SUPERPOS_AGENT_REFRESH_TOKEN": "refresh-token-from-connect-dialog",
          "SUPERPOS_AGENT_SECRET": "",
          "SUPERPOS_CAPABILITIES": "code,summarize,research"
        }
      }
    }
  }
}
```

See `config/openclaw.example.json` for all available options.

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPERPOS_BASE_URL` | Yes | — | Superpos API base URL |
| `SUPERPOS_HIVE_ID` | Yes | — | Target hive ID |
| `SUPERPOS_AGENT_NAME` | For registration | — | Agent name for first-time registration |
| `SUPERPOS_AGENT_ID` | For refresh/login | — | Agent ID (auto-populated after registration/UI connect) |
| `SUPERPOS_AGENT_REFRESH_TOKEN` | Recommended | — | Refresh token from Connect Agent dialog (secret-less renewal path) |
| `SUPERPOS_AGENT_SECRET` | Optional fallback | — | Legacy/shared secret for register/login fallback |
| `SUPERPOS_CAPABILITIES` | No | `general` | Comma-separated capabilities |
| `SUPERPOS_POLL_INTERVAL` | No | `10` | Daemon poll interval (seconds) |
| `SUPERPOS_HEARTBEAT_INTERVAL` | No | `30` | Heartbeat interval (seconds) |
| `SUPERPOS_AUTO_DAEMON` | No | `true` | Auto-start background daemon |
| `SUPERPOS_SHELL_SDK` | No | — | Explicit path to `superpos-sdk.sh` (overrides auto-detection) |
| `SUPERPOS_WAKE_ENABLED` | No | `false` | Enable webhook-wake bridge |
| `SUPERPOS_WAKE_SESSION` | If wake enabled | — | OpenClaw session ID to wake |
| `SUPERPOS_WAKE_LOG` | No | `~/.config/superpos/wake.log` | Wake bridge log file path |
| `SUPERPOS_WAKE_DEBOUNCE_SECS` | No | `5` | Seconds before re-waking for same task+comment |
| `SUPERPOS_WAKE_GATEWAY_URL` | No | `http://localhost:3223` | OpenClaw gateway URL (fallback when CLI unavailable) |
| `SUPERPOS_WAKE_GATEWAY_TOKEN` | No | — | Bearer token for gateway auth |
| `SUPERPOS_WAKE_GATEWAY_TIMEOUT` | No | `5` | Gateway HTTP timeout (seconds) |
| `SUPERPOS_WAKE_ALERT_ENABLED` | No | `false` | Enable visible Telegram alerts on PR comments |
| `SUPERPOS_WAKE_ALERT_TELEGRAM` | If alert enabled | — | Telegram chat ID or username target |
| `SUPERPOS_WAKE_ALERT_CHANNEL` | No | `telegram` | Channel name for alert routing |

Auth state files:
- `~/.config/superpos/token` — current access token
- `~/.config/superpos/refresh-token` — current refresh token
- `~/.config/superpos/agent.json` — agent metadata (`id`, `name`, `hive_id`)

## Usage

### Via OpenClaw

```bash
# Check status
openclaw agent --message "/superpos status"

# List available tasks
openclaw agent --message "/superpos tasks"

# Claim and work on a task
openclaw agent --message "/superpos claim 01HXY..."

# Search knowledge
openclaw agent --message "/superpos knowledge search deployment"

# Start background daemon
openclaw agent --message "/superpos daemon start"
```

### Direct CLI (without OpenClaw)

```bash
# Set env vars from Connect Agent dialog
export SUPERPOS_BASE_URL="http://localhost:8080"
export SUPERPOS_HIVE_ID="01HXYZ..."
export SUPERPOS_AGENT_ID="01HAGENT..."
export SUPERPOS_TOKEN="bootstrap-access-token"
export SUPERPOS_AGENT_REFRESH_TOKEN="bootstrap-refresh-token"

# Authenticate (validates token, auto-refreshes when needed)
sdk/openclaw/bin/superpos-cli.sh auth

# Check status
sdk/openclaw/bin/superpos-cli.sh status

# Poll for tasks
sdk/openclaw/bin/superpos-cli.sh poll

# Send heartbeat
sdk/openclaw/bin/superpos-cli.sh heartbeat

# Knowledge operations
sdk/openclaw/bin/superpos-cli.sh knowledge search "test"
sdk/openclaw/bin/superpos-cli.sh knowledge set "my-key" '{"data": "value"}'

# Event operations
sdk/openclaw/bin/superpos-cli.sh events subscribe "task.completed"
sdk/openclaw/bin/superpos-cli.sh events poll

# Daemon control
sdk/openclaw/bin/superpos-cli.sh daemon start
sdk/openclaw/bin/superpos-cli.sh daemon status
sdk/openclaw/bin/superpos-cli.sh daemon stop
```

## Architecture

```
OpenClaw
  └─ Superpos Skill (SKILL.md)
       ├─ /superpos slash commands → superpos-cli.sh → Shell SDK
       ├─ HEARTBEAT.md           → periodic health checks
       └─ superpos-daemon.sh       → background polling loop
            ├─ Task poll → detects pending tasks
            │    └─ superpos-task-lifecycle.sh (full lifecycle dispatch)
            │         ├─ webhook_handler → wake bridge + complete/fail
            │         ├─ reminder       → message delivery + complete/fail
            │         └─ unknown type   → explicit capability_missing fail
            │              (includes trusted invoke instructions/context)
            ├─ Heartbeat → keeps agent alive
            └─ Event poll → raw event ingestion + OpenClaw system events
```

### Shell SDK Dependency

All scripts source the existing Superpos Shell SDK (`sdk/shell/src/superpos-sdk.sh`) for HTTP client logic, JSON building, error handling, and API operations. The OpenClaw skill adds:

- **Auto-auth flow**: token validate → refresh-token renewal → login/register fallback → token persistence
- **LLM-friendly output**: human-readable formatting for task lists, knowledge entries
- **Background daemon**: poll loop with heartbeat and exponential backoff
- **Event operations**: subscribe, unsubscribe, poll, publish (not yet in base Shell SDK)
- **Pending task files**: task data written to disk for LLM consumption
- **Webhook-wake bridge**: auto-wake OpenClaw sessions on actionable webhook events
- **Task lifecycle dispatch**: webhook_handler/reminder handlers + explicit capability_missing fail for unknown routed task types

## Routed Task Lifecycle

The daemon manages the full lifecycle for routed tasks so they don't pile up as pending in Superpos. Every polled task is dispatched through lifecycle handling:

- `webhook_handler` → webhook-wake bridge flow
- `reminder` → direct message delivery flow
- any other type → explicit `capability_missing` failure (structured error)

1. **Claims** the task atomically (`PATCH .../tasks/{id}/claim`). If another agent already claimed it (409 Conflict), the daemon skips and cleans up the local pending file. On network error, the pending file is preserved for retry on the next poll cycle.

2. **Processes** via the routed handler (webhook wake, reminder delivery, or default capability-missing response).

3. **Completes or fails** the task in Superpos with a structured payload:
   - **Success**: `{"status":"completed","summary":"delivered: wake=1 alert=0",...}`
   - **Filtered**: `{"status":"completed","summary":"filtered: not a PR comment webhook",...}`
   - **Deduplicated**: `{"status":"completed","summary":"deduplicated: already processed",...}`
   - **Failure**: `{"status":"failed","error":"all delivery channels failed",...}`
   - **Capability missing**: `{"code":"capability_missing","task_type":"...","trusted_control_plane":{"invoke":{...}},...}`

4. **Writes a trace** to `~/.config/superpos/traces/{task_id}.json` for local debugging.

5. **Removes** the pending file from `~/.config/superpos/pending/`.

### Operational Notes

- The lifecycle is **fail-soft at the daemon level**: a processing error in one task never crashes the daemon loop.
- **Claim errors are not silent**: network failures return exit code 1 so the daemon can retry; 409 conflicts are logged and the pending file is cleaned up.
- **No delivery channels enabled**: if wake and alert are both disabled, the task is still claimed and completed (acknowledged) rather than left pending forever.
- **Deduplication**: if a task+comment was already processed within the debounce window, the task is completed with a "deduplicated" summary.
- **Trusted control-plane passthrough**: canonical `invoke.instructions/context` are propagated into wake text and capability-missing failure payloads, with legacy fallback to `payload.invoke.*`.
- **No implicit drop**: unknown routed task types are explicitly failed, and polled events are surfaced as OpenClaw system events.

## Webhook-Wake Bridge

When `SUPERPOS_WAKE_ENABLED=true`, the daemon automatically wakes an OpenClaw assistant session whenever a `webhook_handler` task arrives containing a GitHub PR comment. The bridge:

1. Parses PR comment metadata from the webhook payload (repo, PR number, comment URL, body)
2. Extracts severity hints from the comment body (`[urgent]`, `[critical]`, `[high]`, `[low]`)
3. Deduplicates using task ID + comment ID (prevents repeat wakes within the debounce window)
4. POSTs to the OpenClaw gateway HTTP API (`/tools/invoke`) to wake the target session
5. Fails fast with clear diagnostics if the gateway is unreachable

The OpenClaw CLI does not expose session-send subcommands (`sessions_send`, `session send` are invalid in the current runtime). The bridge uses gateway HTTP exclusively. All parsing and invocation failures are logged but never crash the daemon loop (fail-soft).

#### Dual-Delivery (Visible Telegram Alert)

When `SUPERPOS_WAKE_ALERT_ENABLED=true`, the bridge sends **both** an internal wake (via gateway `session_send`) and a user-visible Telegram alert (via gateway `message` tool) for each actionable PR comment event. This ensures assistant automation is triggered while also notifying users in their Telegram chat.

- Dedupe applies to both: a single event produces at most one internal wake **and** one visible alert
- If the visible alert fails, the daemon logs a warning but does not crash; the internal wake still proceeds
- Alert messages include a severity icon, repo name, PR number, a truncated comment preview, and the comment URL

#### Gateway Transport

The bridge POSTs directly to the OpenClaw gateway's `/tools/invoke` endpoint:

- **Wake**: `POST {gateway}/tools/invoke` with `{"tool":"session_send","args":{"sessionKey":"...","message":"..."}}`
- **Alert**: `POST {gateway}/tools/invoke` with `{"tool":"message","args":{"action":"send","channel":"...","target":"...","message":"..."}}`

Configure `SUPERPOS_WAKE_GATEWAY_URL` if the gateway runs on a non-default address. Set `SUPERPOS_WAKE_GATEWAY_TOKEN` if gateway auth is required.

### Setup

```json
{
  "env": {
    "SUPERPOS_WAKE_ENABLED": "true",
    "SUPERPOS_WAKE_SESSION": "your-session-id",
    "SUPERPOS_WAKE_ALERT_ENABLED": "true",
    "SUPERPOS_WAKE_ALERT_TELEGRAM": "@your-username-or-chat-id",
    "SUPERPOS_WAKE_ALERT_CHANNEL": "telegram"
  }
}
```

### File Locations

| Path | Purpose |
|---|---|
| `~/.config/superpos/wake_seen.json` | Deduplication state (auto-pruned after 1 hour) |
| `~/.config/superpos/wake.log` | Wake bridge activity log |

## Task Processing Modes

Tasks can be processed automatically or manually based on type:

| Mode | Behavior |
|---|---|
| `auto` | LLM claims, processes, and completes tasks automatically |
| `manual` | LLM notifies user, waits for `/superpos` commands |

Default modes:
- `code`, `summarize`, `research` → auto
- `deploy`, `admin`, `approval` → manual
- All others → auto (default)

## File Locations

| Path | Purpose |
|---|---|
| `~/.config/superpos/token` | Persisted auth token |
| `~/.config/superpos/agent.json` | Agent ID and metadata |
| `~/.config/superpos/daemon.pid` | Daemon PID file |
| `~/.config/superpos/pending/*.json` | Pending task files |
| `~/.config/superpos/pending/events/*.json` | Polled event snapshots (for local inspection) |
| `~/.config/superpos/cursor.json` | Last event poll cursor |
| `~/.config/superpos/wake_seen.json` | Webhook-wake deduplication state |
| `~/.config/superpos/wake.log` | Webhook-wake activity log |
| `~/.config/superpos/traces/*.json` | Task lifecycle trace records |

## License

Same license as the Superpos project.
