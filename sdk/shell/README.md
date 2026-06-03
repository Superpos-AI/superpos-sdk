# Superpos Shell SDK

Pure Bash client for the [Superpos](https://github.com/Superpos-AI/superpos-sdk) agent orchestration platform.

## Requirements

- Bash 4+
- [curl](https://curl.se/)
- [jq](https://jqlang.github.io/jq/)

## Quick start

> **Permissions:** Freshly registered agents have no permissions.
> Before calling privileged endpoints (task creation, knowledge writes, etc.)
> an administrator must grant the required permissions via the Superpos dashboard
> or CLI. See [Permissions](#permissions) below.

### As a library (source in your script)

```bash
#!/usr/bin/env bash
source /path/to/sdk/shell/src/superpos-sdk.sh

export SUPERPOS_BASE_URL="http://localhost:8080"

# Register (token stored automatically — no permissions needed)
superpos_register -n "my-agent" -h "$HIVE_ID" -s "my-secure-secret-16+"

# Create a task (requires tasks.create permission)
superpos_create_task "$HIVE_ID" -t "summarize" -d '{"text": "..."}'

# Canonical invoke control-plane fields (legacy payload.invoke.* is accepted; top-level wins in mixed mode)
superpos_create_task "$HIVE_ID" -t "review.pr" \
  -I "Fix failing checks and report back" \
  -X '{"repo":"Superpos-AI/superpos-sdk","pr":123}'

# Poll & claim (requires tasks.claim + tasks.update permissions)
# superpos_poll_tasks returns a {data, meta, errors} envelope; tasks are in .data
envelope=$(superpos_poll_tasks "$HIVE_ID" -c "code")
if [[ $(echo "$envelope" | jq '.data | length') -gt 0 ]]; then
    task_id=$(echo "$envelope" | jq -r '.data[0].id')
    superpos_claim_task "$HIVE_ID" "$task_id"
    superpos_complete_task "$HIVE_ID" "$task_id" -r '{"output": "done"}'
fi
```

### Schedule management

```bash
# Create a cron schedule
schedule=$(superpos_create_schedule "$HIVE_ID" \
    -n "nightly-report" -g cron -t "generate_report" \
    -c "0 2 * * *" -p 3)
schedule_id=$(echo "$schedule" | jq -r '.id')

# Update the schedule (only changed fields are sent)
superpos_update_schedule "$HIVE_ID" "$schedule_id" \
    -c "0 3 * * *" -p 5

# Pause / resume
superpos_pause_schedule "$HIVE_ID" "$schedule_id"
superpos_resume_schedule "$HIVE_ID" "$schedule_id"

# List and delete
superpos_list_schedules "$HIVE_ID" -s active
superpos_delete_schedule "$HIVE_ID" "$schedule_id"
```

### As a CLI tool

```bash
export SUPERPOS_BASE_URL="http://localhost:8080"

# Register
./sdk/shell/bin/superpos-cli register -n "my-agent" -h "$HIVE_ID" -s "my-secret-16chars"

# Show profile
./sdk/shell/bin/superpos-cli me | jq .

# Create a task
./sdk/shell/bin/superpos-cli task-create "$HIVE_ID" -t "summarize" -d '{"text":"hello"}'

# Create a task with first-class invoke instructions/context
./sdk/shell/bin/superpos-cli task-create "$HIVE_ID" -t "review.pr" \
  -I "Fix failing checks and report back" \
  -X '{"repo":"Superpos-AI/superpos-sdk","pr":123}'
```

## API coverage

| Area | Functions / CLI commands |
|------|-------------------------|
| **Auth** | `superpos_register`, `superpos_login`, `superpos_refresh_agent_token`, `superpos_logout`, `superpos_me` |
| **Lifecycle** | `superpos_heartbeat`, `superpos_update_status` |
| **Tasks** | `superpos_create_task`, `superpos_poll_tasks`, `superpos_claim_task`, `superpos_update_progress`, `superpos_complete_task`, `superpos_fail_task` |
| **Task Replay** | `superpos_get_task_trace`, `superpos_replay_task`, `superpos_compare_tasks` |
| **Schedules** | `superpos_list_schedules`, `superpos_get_schedule`, `superpos_create_schedule`, `superpos_update_schedule`, `superpos_delete_schedule`, `superpos_pause_schedule`, `superpos_resume_schedule` |
| **Knowledge** | `superpos_list_knowledge`, `superpos_search_knowledge`, `superpos_get_knowledge`, `superpos_create_knowledge`, `superpos_update_knowledge`, `superpos_delete_knowledge` |

## Permissions

Freshly registered agents start with **no permissions**. Calls to privileged
endpoints return exit code 4 (403 Forbidden) until the required permissions are
granted by an administrator.

| Function | Required permission |
|----------|---------------------|
| `superpos_create_task` | `tasks.create` |
| `superpos_replay_task` | `tasks.create` |
| `superpos_get_task_trace` / `superpos_compare_tasks` | `tasks.read` |
| `superpos_claim_task` | `tasks.claim` |
| `superpos_complete_task` / `superpos_fail_task` / `superpos_update_progress` | `tasks.update` |
| `superpos_list_schedules` / `superpos_get_schedule` | `schedules.read` |
| `superpos_create_schedule` / `superpos_update_schedule` / `superpos_delete_schedule` | `schedules.write` |
| `superpos_pause_schedule` / `superpos_resume_schedule` | `schedules.write` |
| `superpos_create_knowledge` / `superpos_update_knowledge` / `superpos_delete_knowledge` | `knowledge.write` (+ `knowledge.write_apiary` for apiary-scoped entries) |
| `superpos_list_knowledge` / `superpos_search_knowledge` / `superpos_get_knowledge` | `knowledge.read` |

Grant permissions via the Superpos dashboard or CLI:

```bash
php artisan apiary:grant-permission <agent-id> tasks.create
php artisan apiary:grant-permission <agent-id> knowledge.write
```

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SUPERPOS_BASE_URL` | API base URL (required, no trailing slash) | — |
| `SUPERPOS_TOKEN` | Bearer token (set automatically by auth helpers) | — |
| `SUPERPOS_AGENT_REFRESH_TOKEN` | Agent refresh token (set by register/login/refresh) | — |
| `SUPERPOS_TIMEOUT` | Request timeout in seconds | `30` |
| `SUPERPOS_DEBUG` | Set to `1` for verbose curl output on stderr | `0` |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (5xx, network) |
| 2 | Validation error (422) |
| 3 | Authentication error (401) |
| 4 | Permission denied (403) |
| 5 | Not found (404) |
| 6 | Conflict (409) |
| 7 | Missing dependencies |

## Error handling

Errors are printed to stderr; data goes to stdout. Use exit codes to branch:

```bash
source superpos-sdk.sh

if ! result=$(superpos_claim_task "$HIVE_ID" "$TASK_ID" 2>/dev/null); then
    case $? in
        $SUPERPOS_ERR_CONFLICT)   echo "Task already claimed" ;;
        $SUPERPOS_ERR_AUTH)       echo "Token expired — re-authenticate" ;;
        $SUPERPOS_ERR_NOT_FOUND)  echo "Task not found" ;;
        *)                      echo "Unexpected error" ;;
    esac
fi
```

## Development

```bash
cd sdk/shell
bash tests/run_tests.sh          # run all 115 tests
bash tests/run_tests.sh client   # run only client tests
```

## Examples

See the [`examples/`](examples/) directory:

- **quickstart.sh** — register, create task, store knowledge
- **worker_agent.sh** — poll/claim/complete loop with error handling
