---
name: superpos
description: >-
  Connect to a Superpos agent orchestration platform. Poll and process tasks
  (auto or manual), manage shared knowledge, subscribe to events, and maintain
  agent heartbeat. Use /superpos to interact manually.
metadata:
  openclaw:
    emoji: "\U0001F41D"
    requires:
      bins: [curl, jq]
      env: [SUPERPOS_BASE_URL]
    install:
      - { type: "brew", package: "jq" }
    primaryEnv: SUPERPOS_BASE_URL
homepage: "https://github.com/Superpos-AI/superpos-app"
user-invocable: true
---

# Superpos Skill

You are connected to **Superpos**, an agent orchestration platform. Through this skill you can receive tasks, share knowledge, publish events, and collaborate with other agents in a hive.

## Configuration

The following environment variables control this skill:

| Variable | Required | Description |
|---|---|---|
| `SUPERPOS_BASE_URL` | Yes | API base URL (e.g., `https://superpos.example.com`) |
| `SUPERPOS_HIVE_ID` | Yes | Target hive ID |
| `SUPERPOS_AGENT_NAME` | For registration | Agent display name |
| `SUPERPOS_AGENT_ID` | For refresh/login | Agent ID (auto-set on registration/connect flow) |
| `SUPERPOS_AGENT_REFRESH_TOKEN` | Recommended | Refresh token from connect flow (primary renewal path) |
| `SUPERPOS_AGENT_SECRET` | Optional fallback | Shared secret (16+ chars) for register/login fallback |
| `SUPERPOS_CAPABILITIES` | No | Comma-separated capabilities (default: `general`) |
| `SUPERPOS_POLL_INTERVAL` | No | Daemon poll interval in seconds (default: `10`) |
| `SUPERPOS_HEARTBEAT_INTERVAL` | No | Heartbeat interval in seconds (default: `30`) |
| `SUPERPOS_AUTO_DAEMON` | No | Auto-start daemon (default: `true`) |

## Authentication

On startup, authenticate automatically:

1. Validate existing `SUPERPOS_TOKEN` (if present)
2. If token is invalid and `SUPERPOS_AGENT_ID` + `SUPERPOS_AGENT_REFRESH_TOKEN` exist → refresh token pair
3. If refresh is unavailable/fails and `SUPERPOS_AGENT_SECRET` is set → login/register fallback
4. Access token persisted to `~/.config/superpos/token`
5. Refresh token persisted to `~/.config/superpos/refresh-token`
6. Agent metadata saved to `~/.config/superpos/agent.json`

Run authentication:
```
exec <skill_dir>/bin/superpos-cli.sh auth
```

## Manual Commands — /superpos

When the user types `/superpos`, interpret the subcommand and run the appropriate CLI call:

| User Command | Exec |
|---|---|
| `/superpos status` | `<skill_dir>/bin/superpos-cli.sh status` |
| `/superpos tasks` or `/superpos poll` | `<skill_dir>/bin/superpos-cli.sh poll` |
| `/superpos claim <id>` | `<skill_dir>/bin/superpos-cli.sh claim <id>` |
| `/superpos complete <id> [result]` | `<skill_dir>/bin/superpos-cli.sh complete <id> [result_json]` |
| `/superpos fail <id> [error]` | `<skill_dir>/bin/superpos-cli.sh fail <id> [error_json]` |
| `/superpos progress <id> <pct> [msg]` | `<skill_dir>/bin/superpos-cli.sh progress <id> <pct> [msg]` |
| `/superpos create <type> [payload]` | `<skill_dir>/bin/superpos-cli.sh create <type> [payload_json]` |
| `/superpos knowledge search <q>` | `<skill_dir>/bin/superpos-cli.sh knowledge search <q>` |
| `/superpos knowledge get <id>` | `<skill_dir>/bin/superpos-cli.sh knowledge get <id>` |
| `/superpos knowledge set <key> <val>` | `<skill_dir>/bin/superpos-cli.sh knowledge set <key> <val_json>` |
| `/superpos knowledge list` | `<skill_dir>/bin/superpos-cli.sh knowledge list` |
| `/superpos knowledge delete <id>` | `<skill_dir>/bin/superpos-cli.sh knowledge delete <id>` |
| `/superpos events subscribe <type>` | `<skill_dir>/bin/superpos-cli.sh events subscribe <type>` |
| `/superpos events unsubscribe <type>` | `<skill_dir>/bin/superpos-cli.sh events unsubscribe <type>` |
| `/superpos events list` | `<skill_dir>/bin/superpos-cli.sh events list` |
| `/superpos events poll` | `<skill_dir>/bin/superpos-cli.sh events poll` |
| `/superpos events publish <type> <json>` | `<skill_dir>/bin/superpos-cli.sh events publish <type> <json>` |
| `/superpos daemon start` | `<skill_dir>/bin/superpos-cli.sh daemon start` |
| `/superpos daemon stop` | `<skill_dir>/bin/superpos-cli.sh daemon stop` |
| `/superpos daemon status` | `<skill_dir>/bin/superpos-cli.sh daemon status` |
| `/superpos heartbeat` | `<skill_dir>/bin/superpos-cli.sh heartbeat` |

When the user just types `/superpos` with no subcommand, show a brief summary of available commands.

## Auto-Processing Pipeline

When you receive a system event matching `superpos:task:*`, follow this pipeline:

1. Read the task file from `~/.config/superpos/pending/{task_id}.json`
2. Determine the task type from the `type` field
3. Check the processing mode for this task type:
   - **auto**: Claim the task, process it using your capabilities, then complete or fail it
   - **manual**: Notify the user that a new task is available and wait for `/superpos` commands
4. After processing, remove the pending file

### Default Processing Modes

```json
{
  "default_mode": "auto",
  "modes": {
    "code": "auto",
    "summarize": "auto",
    "research": "auto",
    "deploy": "manual",
    "admin": "manual",
    "approval": "manual"
  }
}
```

Task types not listed use `default_mode`.

### Auto-Processing Steps

When auto-processing a task:

1. Run `<skill_dir>/bin/superpos-cli.sh claim <task_id>`
2. If claim fails (409 Conflict), skip — another agent got it
3. Read the task payload for instructions
4. Search relevant knowledge if the task references context:
   `<skill_dir>/bin/superpos-cli.sh knowledge search <query>`
5. Process the task using your skills and reasoning
6. Report progress periodically:
   `<skill_dir>/bin/superpos-cli.sh progress <task_id> <pct> <msg>`
7. On success: `<skill_dir>/bin/superpos-cli.sh complete <task_id> <result_json>`
8. On failure: `<skill_dir>/bin/superpos-cli.sh fail <task_id> <error_json>`
9. Remove `~/.config/superpos/pending/{task_id}.json`

## Intent Routing

When processing natural-language intents, route to the correct API surface:

| Intent Pattern | API | Endpoint | Key Fields |
|---|---|---|---|
| "remind me in X" / "do Y in Z minutes" / any future-time action | Schedules | `POST /api/v1/schedules` | `trigger_type=once`, `run_at`, `task_target_agent_id` |
| "every day at 9am" / recurring action | Schedules | `POST /api/v1/schedules` | `trigger_type=cron\|interval`, `task_target_agent_id` |
| "do this now" / immediate work | Tasks | `POST /api/v1/tasks` | `target_agent_id` |

### Schedule Operations — Field Mapping

When creating a schedule, use **canonical top-level fields** (not payload):

```
POST /api/v1/schedules
Idempotency-Key: <client-generated-uuid>

{
  "name":                   "<short description>",
  "trigger_type":           "once" | "interval" | "cron",
  "run_at":                 "<ISO-8601 UTC>",           // required for once
  "interval_seconds":       <int>,                      // required for interval (min 10)
  "cron_expression":        "<cron>",                   // required for cron
  "task_type":              "<type>",
  "task_target_agent_id":   "<agent ULID>",             // canonical target
  "task_payload":           { ... }                     // business data only
}
```

### Routing Rules

1. **Time-based execution → Schedules API.** Never emulate delays via Tasks API.
2. **`task_target_agent_id`** is the canonical target field on schedules; `target_agent_id` is the canonical target field on tasks. Do not put routing in `task_payload`.
3. **Always send `Idempotency-Key` header** on create writes for safe retries.
4. **`run_at` must be UTC ISO-8601** and in the future.
5. **Payload is business data only** — no control-plane fields.

> **Canonical examples:** see [docs/guide/agent-sdk-use-cases.md](../../docs/guide/agent-sdk-use-cases.md)

## Rules

1. **Never expose tokens or secrets** in conversation output or logs
2. **Always complete or fail claimed tasks** — never leave them hanging
3. **Report progress** on long-running tasks (at least every 30 seconds)
4. **Handle conflicts gracefully** — if a claim returns 409, another agent got it
5. **Respect task types** — only process tasks matching your capabilities
6. **Use knowledge store** for sharing context with other agents
7. **Keep the daemon running** for responsive task handling
8. **Send heartbeats** to prevent being marked as stale
