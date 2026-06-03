# TASK-080: Agent Drain Mode (Graceful Shutdown)

**Status:** ✅ done
**Branch:** `task/080-agent-drain-mode` (merged)
**PR:** [#130](https://github.com/Superpos-AI/superpos-app/pull/130)
**Depends On:** 007 (Agent model), 015 (Agent heartbeat/lifecycle API)
**Edition Scope:** `shared`

## Overview

Agent drain mode enables graceful shutdown of agents. When draining, an agent:
- Stops receiving new tasks from poll
- Cannot claim new tasks
- Continues processing in-flight tasks to completion
- Optionally auto-transitions to offline after a deadline

## Implementation

### Data Model

Migration: `2026_03_08_200000_add_drain_mode_to_agents_table.php`

| Column | Type | Description |
|--------|------|-------------|
| `is_draining` | boolean | Whether the agent is in drain mode |
| `drain_started_at` | timestamp | When drain mode was entered |
| `drain_deadline_at` | timestamp | Optional auto-offline deadline |
| `drain_reason` | string(500) | Human-readable drain reason |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/agents/drain` | Enter drain mode |
| `POST` | `/api/v1/agents/undrain` | Exit drain mode |
| `GET` | `/api/v1/agents/drain` | Get drain status |

#### Enter Drain Request Body
```json
{
  "reason": "scheduled maintenance",
  "deadline_minutes": 30
}
```

### Runtime Behavior

- **Poll**: Draining agents receive an empty task list with `meta.draining=true`
- **Claim**: Draining agents get 409 with code `draining`
- **Progress/Complete/Fail**: Work normally for in-flight tasks
- **Heartbeat**: Includes `is_draining`, `drain_deadline_at`, `drain_reason`

### Deadline Processing

Artisan command `apiary:process-drain-deadlines` runs every minute:
1. Transitions agents past `drain_deadline_at` to offline
2. Auto-completes drain for agents with no in-flight tasks

### Dashboard

- Agent list shows "Draining" status badge
- Agent detail page shows drain info card and drain/undrain buttons
- Dashboard endpoints: `POST /dashboard/agents/{id}/drain`, `POST /dashboard/agents/{id}/undrain`

### SDK Parity

- **Python SDK**: `enter_drain()`, `exit_drain()`, `drain_status()`
- **Shell SDK**: `superpos_enter_drain`, `superpos_exit_drain`, `superpos_drain_status`
- **CLI**: `drain`, `undrain`, `drain-status` commands

## Test Plan

23 tests covering:
- Enter/exit drain API (validation, state checks, auth)
- Poll returns empty for draining agents
- Claim rejected for draining agents
- In-flight task completion/failure still works
- Deadline processing transitions expired agents
- Completed drain auto-transitions
- Model helper methods
- Heartbeat includes drain info
- Artisan command
- Auth required

## Files Changed

- `database/migrations/2026_03_08_200000_add_drain_mode_to_agents_table.php`
- `app/Models/Agent.php`
- `app/Services/AgentDrainService.php`
- `app/Console/Commands/ProcessDrainDeadlines.php`
- `app/Http/Controllers/Api/AgentLifecycleController.php`
- `app/Http/Controllers/Api/TaskController.php`
- `app/Http/Controllers/Dashboard/AgentDashboardController.php`
- `app/Http/Requests/EnterDrainRequest.php`
- `database/factories/AgentFactory.php`
- `routes/api.php`
- `routes/web.php`
- `bootstrap/app.php`
- `resources/js/Components/StatusBadge.jsx`
- `resources/js/Pages/Agents.jsx`
- `resources/js/Pages/Agents/Show.jsx`
- `sdk/python/src/superpos_sdk/client.py`
- `sdk/shell/src/superpos-sdk.sh`
- `sdk/shell/bin/superpos-cli`
- `tests/Feature/AgentDrainModeTest.php`
