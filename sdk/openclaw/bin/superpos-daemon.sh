#!/usr/bin/env bash
# superpos-daemon.sh — Background polling daemon for the Superpos OpenClaw skill.
#
# Runs as a background process, polling for tasks, sending heartbeats,
# and checking events on configurable intervals.
#
# Usage:
#   superpos-daemon.sh              # Run in foreground
#   superpos-daemon.sh &            # Run in background
#   superpos-cli.sh daemon start    # Preferred: via CLI
#
# Env vars:
#   SUPERPOS_POLL_INTERVAL         — Seconds between task polls (default: 10)
#   SUPERPOS_HEARTBEAT_INTERVAL    — Seconds between heartbeats (default: 30)
#   SUPERPOS_POLL_MAX_TASKS        — Max tasks per poll cycle (default: 20, cap: 20)
#   SUPERPOS_CONFIG_DIR            — Config directory (default: ~/.config/superpos)

set -euo pipefail

# Resolve through symlinks (OpenClaw may symlink the install)
_src="${BASH_SOURCE[0]}"
while [[ -L "$_src" ]]; do
    _dir="$(cd "$(dirname "$_src")" && pwd)"
    _src="$(readlink "$_src")"
    [[ "$_src" != /* ]] && _src="$_dir/$_src"
done
SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
unset _src _dir

# Locate and source Shell SDK (supports repo layout, bundled copy, env override)
# shellcheck source=_resolve-sdk.sh
source "${SCRIPT_DIR}/_resolve-sdk.sh"
_superpos_find_shell_sdk || exit 1
# shellcheck source=../../shell/src/superpos-sdk.sh
source "$_SUPERPOS_SHELL_SDK_PATH"
_SUPERPOS_SDK_LOADED=1

# shellcheck source=superpos-auth.sh
source "${SCRIPT_DIR}/superpos-auth.sh"
# shellcheck source=superpos-tasks.sh
source "${SCRIPT_DIR}/superpos-tasks.sh"
# shellcheck source=superpos-events.sh
source "${SCRIPT_DIR}/superpos-events.sh"
# shellcheck source=superpos-webhook-wake.sh
source "${SCRIPT_DIR}/superpos-webhook-wake.sh"
# shellcheck source=superpos-task-lifecycle.sh
source "${SCRIPT_DIR}/superpos-task-lifecycle.sh"

# ── Configuration ───────────────────────────────────────────────

POLL_INTERVAL="${SUPERPOS_POLL_INTERVAL:-10}"
HEARTBEAT_INTERVAL="${SUPERPOS_HEARTBEAT_INTERVAL:-30}"
# Maximum tasks per poll cycle (floor: 1, cap: 20 regardless of env value)
_poll_max_env="${SUPERPOS_POLL_MAX_TASKS:-20}"
# Sanitize: non-numeric values (e.g. "foo", "", whitespace) fall back to default
if ! [[ "$_poll_max_env" =~ ^-?[0-9]+$ ]]; then
    echo "[superpos-daemon] WARNING: SUPERPOS_POLL_MAX_TASKS='${_poll_max_env}' is not numeric, defaulting to 20" >&2
    _poll_max_env=20
fi
POLL_MAX_TASKS=$(( _poll_max_env > 20 ? 20 : (_poll_max_env < 1 ? 1 : _poll_max_env) ))
unset _poll_max_env
CONFIG_DIR="$(_superpos_oc_config_dir)"
PID_FILE="${CONFIG_DIR}/daemon.pid"
PENDING_DIR="${CONFIG_DIR}/pending"
STATS_FILE="${CONFIG_DIR}/daemon-stats.json"

# Backoff state
_backoff_delay=1
_backoff_max=300

# Health diagnostics counters
_stats_poll_cycles=0
_stats_tasks_received=0
_stats_tasks_processed=0
_stats_wakes_sent=0
_stats_errors=0
_stats_last_poll_time=""
_stats_last_task_time=""
_stats_started_at=""

# ── PID management ──────────────────────────────────────────────

_daemon_check_duplicate() {
    if [[ -f "$PID_FILE" ]]; then
        local existing_pid
        existing_pid=$(cat "$PID_FILE")
        if kill -0 "$existing_pid" 2>/dev/null; then
            echo "Daemon already running (PID $existing_pid). Stop it first." >&2
            exit 1
        fi
        # Stale PID file — clean up
        rm -f "$PID_FILE"
    fi
}

_daemon_write_pid() {
    mkdir -p "$CONFIG_DIR"
    echo $$ > "$PID_FILE"
}

_daemon_remove_pid() {
    rm -f "$PID_FILE"
}

# ── Cleanup on exit ─────────────────────────────────────────────

_daemon_cleanup() {
    echo "[superpos-daemon] Shutting down..." >&2
    superpos_update_status "offline" >/dev/null 2>&1 || true
    _daemon_write_stats 2>/dev/null || true
    _daemon_remove_pid
    echo "[superpos-daemon] Offline." >&2
}

# ── Backoff helpers ─────────────────────────────────────────────

_backoff_reset() {
    _backoff_delay=1
}

_backoff_sleep() {
    echo "[superpos-daemon] Retrying in ${_backoff_delay}s..." >&2
    sleep "$_backoff_delay"
    _backoff_delay=$(( _backoff_delay * 2 ))
    if [[ $_backoff_delay -gt $_backoff_max ]]; then
        _backoff_delay=$_backoff_max
    fi
}

# _rate_limit_sleep — sleep for retry-after duration on 429 responses.
#   Uses _SUPERPOS_RETRY_AFTER (set by SDK) when available, otherwise
#   falls back to exponential backoff.
_rate_limit_sleep() {
    local retry_after="${_SUPERPOS_RETRY_AFTER:-}"
    if [[ -n "$retry_after" ]] && [[ "$retry_after" =~ ^[0-9]+$ ]]; then
        echo "[superpos-daemon] Rate-limited, retry-after ${retry_after}s" >&2
        sleep "$retry_after"
    else
        echo "[superpos-daemon] Rate-limited, retrying in ${_backoff_delay}s..." >&2
        sleep "$_backoff_delay"
        _backoff_delay=$(( _backoff_delay * 2 ))
        if [[ $_backoff_delay -gt $_backoff_max ]]; then
            _backoff_delay=$_backoff_max
        fi
    fi
}

# ── Health diagnostics ─────────────────────────────────────────

_daemon_write_stats() {
    local pending_count=0
    if [[ -d "$PENDING_DIR" ]]; then
        pending_count=$(find "$PENDING_DIR" -maxdepth 1 -name '*.json' ! -name '*.result.json' 2>/dev/null | wc -l)
    fi
    local now_iso
    now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%s)

    cat > "$STATS_FILE" <<STATS_EOF
{
  "pid": $$,
  "started_at": "${_stats_started_at}",
  "updated_at": "${now_iso}",
  "poll_max_tasks": ${POLL_MAX_TASKS},
  "poll_interval": ${POLL_INTERVAL},
  "poll_cycles": ${_stats_poll_cycles},
  "tasks_received": ${_stats_tasks_received},
  "tasks_processed": ${_stats_tasks_processed},
  "wakes_sent": ${_stats_wakes_sent},
  "errors": ${_stats_errors},
  "pending_queue": ${pending_count},
  "last_poll_time": "${_stats_last_poll_time}",
  "last_task_time": "${_stats_last_task_time}"
}
STATS_EOF
}

# ── Task file management ───────────────────────────────────────

_daemon_save_pending_task() {
    local task_json="$1"
    local task_id
    task_id=$(echo "$task_json" | jq -r '.id')
    mkdir -p "$PENDING_DIR"
    echo "$task_json" > "${PENDING_DIR}/${task_id}.json"
}

_daemon_save_pending_event() {
    local event_json="$1"
    local event_id
    event_id=$(echo "$event_json" | jq -r '.id // empty' 2>/dev/null) || event_id=""
    [[ -n "$event_id" ]] || return 0

    local events_dir="${PENDING_DIR}/events"
    mkdir -p "$events_dir"
    echo "$event_json" > "${events_dir}/${event_id}.json"
}

_daemon_process_routed_task() {
    local task_json="$1"
    local task_id="$2"
    local task_type="$3"

    _lifecycle_process_routed_task "$task_json" "$task_id" "$task_type" || true

    # Only webhook_handler path sets this sentinel when a wake/alert was delivered.
    if [[ "${_lifecycle_wake_delivered:-0}" -eq 1 ]]; then
        _stats_wakes_sent=$(( _stats_wakes_sent + 1 ))
    fi
}

# _daemon_event_is_exec_ready EVENT_JSON — Check if event has execution-ready invoke fields.
# Returns 0 (true) when the event carries top-level invoke.instructions,
# meaning the daemon can dispatch without a follow-up detail fetch.
_daemon_event_is_exec_ready() {
    local event_json="$1"
    local instructions
    instructions=$(echo "$event_json" | jq -r '.invoke.instructions // empty' 2>/dev/null) || instructions=""
    [[ -n "$instructions" ]]
}

# _daemon_build_event_dispatch_text — Build dispatch text for OpenClaw system event.
# For execution-ready events, includes invoke instructions/context inline.
# For legacy events, returns the reference-only text.
_daemon_build_event_dispatch_text() {
    local event_json="$1"
    local event_type="$2"
    local event_id="$3"

    local text="superpos:event:${event_type}:${event_id}"

    local instructions
    instructions=$(echo "$event_json" | jq -r '.invoke.instructions // empty' 2>/dev/null) || instructions=""
    if [[ -n "$instructions" ]]; then
        text+=$'\n'"invoke.instructions: ${instructions}"

        local context
        context=$(echo "$event_json" | jq -c '.invoke.context // null' 2>/dev/null) || context="null"
        if [[ "$context" != "null" ]]; then
            text+=$'\n'"invoke.context: ${context}"
        fi
    fi

    echo "$text"
}

_daemon_process_polled_events() {
    local hive_id="${SUPERPOS_HIVE_ID:-}"
    [[ -n "$hive_id" ]] || return 0

    local events
    events=$(superpos_oc_events_poll_raw 2>/dev/null) || return 0

    local count
    count=$(echo "$events" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)
    [[ "$count" -gt 0 ]] || return 0

    local i
    for i in $(seq 0 $(( count - 1 ))); do
        local event_json event_id event_type
        event_json=$(echo "$events" | jq -c ".[${i}]" 2>/dev/null) || continue
        event_id=$(echo "$event_json" | jq -r '.id // empty' 2>/dev/null) || event_id=""
        event_type=$(echo "$event_json" | jq -r '.type // "unknown"' 2>/dev/null) || event_type="unknown"

        [[ -n "$event_id" ]] || continue

        # Execution-ready events carry invoke.instructions at top level;
        # skip saving a pending snapshot when the dispatch text already
        # contains all the data the consumer needs.
        local exec_ready=0
        if _daemon_event_is_exec_ready "$event_json"; then
            exec_ready=1
            echo "[superpos-daemon] New event (exec-ready): ${event_id} (type: ${event_type})" >&2
        else
            _daemon_save_pending_event "$event_json"
            echo "[superpos-daemon] New event: ${event_id} (type: ${event_type})" >&2
        fi

        local dispatch_ok=1
        local dispatch_text
        dispatch_text=$(_daemon_build_event_dispatch_text "$event_json" "$event_type" "$event_id")

        # Notify OpenClaw via system event.
        # If dispatch fails (including missing CLI), do NOT advance cursor
        # and do NOT prune snapshot.
        if command -v openclaw >/dev/null 2>&1; then
            if ! openclaw system event \
                --text "$dispatch_text" \
                --mode now 2>/dev/null; then
                dispatch_ok=0
                # On dispatch failure, ensure pending is saved for retry
                # even if we skipped it earlier (exec-ready path).
                if [[ $exec_ready -eq 1 ]]; then
                    _daemon_save_pending_event "$event_json"
                fi
                echo "[superpos-daemon] Event dispatch failed for ${event_id}; preserving snapshot for retry" >&2
            fi
        else
            dispatch_ok=0
            if [[ $exec_ready -eq 1 ]]; then
                _daemon_save_pending_event "$event_json"
            fi
            echo "[superpos-daemon] openclaw command not found; preserving event ${event_id} for retry" >&2
        fi

        if [[ $dispatch_ok -ne 1 ]]; then
            # Critical: stop processing this polled batch on first dispatch failure.
            # Otherwise a later successful cursor commit could skip the failed event.
            break
        fi

        # Advance cursor only after this event is successfully handled.
        if superpos_oc_events_commit_cursor "$event_id"; then
            # Event is durably acknowledged via cursor commit; prune local snapshot
            # to avoid unbounded disk growth in long-running daemons.
            rm -f "${PENDING_DIR}/events/${event_id}.json" 2>/dev/null || true
        else
            echo "[superpos-daemon] Cursor commit failed for ${event_id}; preserving snapshot for retry" >&2
            break
        fi
    done
}

# ── Main loop ───────────────────────────────────────────────────

main() {
    _daemon_check_duplicate

    echo "[superpos-daemon] Starting (poll=${POLL_INTERVAL}s, heartbeat=${HEARTBEAT_INTERVAL}s, max_tasks=${POLL_MAX_TASKS})..." >&2
    _stats_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%s)

    # Authenticate
    if ! superpos_oc_ensure_auth >/dev/null 2>&1; then
        echo "[superpos-daemon] Authentication failed. Exiting." >&2
        exit 1
    fi

    # Set online status
    superpos_update_status "online" >/dev/null 2>&1 || true

    # Write PID file and set up trap
    _daemon_write_pid
    trap _daemon_cleanup EXIT INT TERM

    local last_heartbeat=0

    echo "[superpos-daemon] Online and polling." >&2

    while true; do
        local now _skip_poll_sleep=0
        now=$(date +%s)

        # Heartbeat — classify failure explicitly to avoid auth-reset loops
        if (( now - last_heartbeat >= HEARTBEAT_INTERVAL )); then
            local hb_rc=0
            superpos_heartbeat >/dev/null 2>&1 || hb_rc=$?

            if [[ "$hb_rc" -eq 0 ]]; then
                _backoff_reset
                last_heartbeat=$now
            elif [[ "$hb_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
                echo "[superpos-daemon] Heartbeat rate-limited (429)" >&2
                _stats_errors=$(( _stats_errors + 1 ))
                _rate_limit_sleep
                continue
            elif [[ "$hb_rc" -eq "$SUPERPOS_ERR_AUTH" ]]; then
                echo "[superpos-daemon] Heartbeat auth failed (401), re-authenticating..." >&2
                if ! superpos_oc_ensure_auth >/dev/null 2>&1; then
                    echo "[superpos-daemon] Re-authentication failed" >&2
                    _backoff_sleep
                    continue
                fi
                # Do NOT advance last_heartbeat here — re-auth succeeded but
                # the heartbeat itself was never delivered.  Leave the timer
                # so the next iteration immediately retries the heartbeat.
            else
                echo "[superpos-daemon] Heartbeat failed (rc=${hb_rc}), transient error" >&2
                _stats_errors=$(( _stats_errors + 1 ))
                _backoff_sleep
                continue
            fi
        fi

        # Poll for tasks
        local hive_id="${SUPERPOS_HIVE_ID:-}"
        if [[ -n "$hive_id" ]]; then
            local tasks poll_rc=0
            tasks=$(superpos_poll_tasks "$hive_id" -l "$POLL_MAX_TASKS" 2>/dev/null) || poll_rc=$?

            if [[ "$poll_rc" -eq 0 ]]; then
                _backoff_reset
                _stats_poll_cycles=$(( _stats_poll_cycles + 1 ))
                _stats_last_poll_time=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%s)

                local count
                count=$(echo "$tasks" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

                if [[ "$count" -gt 0 ]]; then
                    _stats_tasks_received=$(( _stats_tasks_received + count ))

                    # Save each task to pending directory
                    for i in $(seq 0 $(( count - 1 ))); do
                        local task_json
                        task_json=$(echo "$tasks" | jq ".[$i]")
                        local task_id task_type
                        task_id=$(echo "$task_json" | jq -r '.id')
                        task_type=$(echo "$task_json" | jq -r '.type')

                        # Only save if not already pending
                        if [[ ! -f "${PENDING_DIR}/${task_id}.json" ]]; then
                            _daemon_save_pending_task "$task_json"
                            _stats_tasks_processed=$(( _stats_tasks_processed + 1 ))
                            _stats_last_task_time=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%s)
                            echo "[superpos-daemon] New task: ${task_id} (type: ${task_type})" >&2

                            # Notify OpenClaw via system event (best-effort)
                            if command -v openclaw >/dev/null 2>&1; then
                                openclaw system event \
                                    --text "superpos:task:${task_type}:${task_id}" \
                                    --mode now 2>/dev/null || true
                            fi

                            # Always route every polled task through lifecycle dispatch.
                            # Unknown task types are explicitly failed with capability_missing.
                            _daemon_process_routed_task "$task_json" "$task_id" "$task_type"
                        fi
                    done
                fi
            elif [[ "$poll_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
                echo "[superpos-daemon] Task poll rate-limited (429)" >&2
                _stats_errors=$(( _stats_errors + 1 ))
                _rate_limit_sleep
                _skip_poll_sleep=1
            elif [[ "$poll_rc" -eq "$SUPERPOS_ERR_AUTH" ]]; then
                echo "[superpos-daemon] Task poll auth failed (401), re-authenticating..." >&2
                _stats_errors=$(( _stats_errors + 1 ))
                superpos_oc_ensure_auth >/dev/null 2>&1 || true
            else
                echo "[superpos-daemon] Task poll failed (rc=${poll_rc})" >&2
                _stats_errors=$(( _stats_errors + 1 ))
            fi

            # Poll and surface events (best-effort, no silent drop)
            _daemon_process_polled_events || true

            # Retry any stuck pending auto-lifecycle tasks from prior polls.
            # If a prior claim failed transiently (network error), the pending
            # file was preserved — this sweep re-attempts lifecycle processing.
            _lifecycle_retry_pending_handlers

            # Write health stats periodically (every poll cycle)
            _daemon_write_stats 2>/dev/null || true
        fi

        # Skip loop-tail sleep if _rate_limit_sleep already waited
        if [[ "$_skip_poll_sleep" -eq 0 ]]; then
            sleep "$POLL_INTERVAL"
        fi
    done
}

main "$@"
