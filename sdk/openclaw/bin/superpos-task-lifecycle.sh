#!/usr/bin/env bash
# superpos-task-lifecycle.sh — End-to-end task lifecycle for auto-processed tasks.
#
# The daemon polls pending tasks but previously never claimed, processed,
# or completed them in Superpos.  This module closes the lifecycle for
# webhook_handler/reminder task types:
#
#   claim (atomic) → process → complete / fail → trace → cleanup
#
# Designed to be sourced by superpos-daemon.sh.  All functions are fail-soft
# at the daemon level (never crash the main loop), but individual failures
# are reported back to Superpos so tasks don't pile up as pending forever.
#
# Env vars:
#   SUPERPOS_CONFIG_DIR  — Config directory (resolved via _superpos_oc_config_dir)
#   SUPERPOS_HIVE_ID     — Hive ID (required, from auth)

# ── Source Shell SDK (guard against re-sourcing) ────────────────
if [[ -z "${_SUPERPOS_SDK_LOADED:-}" ]]; then
    _src="${BASH_SOURCE[0]}"
    while [[ -L "$_src" ]]; do
        _dir="$(cd "$(dirname "$_src")" && pwd)"
        _src="$(readlink "$_src")"
        [[ "$_src" != /* ]] && _src="$_dir/$_src"
    done
    SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
    unset _src _dir
    # shellcheck source=_resolve-sdk.sh
    source "${SCRIPT_DIR}/_resolve-sdk.sh"
    _superpos_find_shell_sdk || return 1
    # shellcheck source=../../shell/src/superpos-sdk.sh
    source "$_SUPERPOS_SHELL_SDK_PATH"
    _SUPERPOS_SDK_LOADED=1
fi

# ── Source auth module (for _superpos_oc_config_dir) ───────────
if ! declare -f _superpos_oc_config_dir >/dev/null 2>&1; then
    # shellcheck source=superpos-auth.sh
    source "${SCRIPT_DIR}/superpos-auth.sh"
fi

# ── Configuration ──────────────────────────────────────────────

_LIFECYCLE_CONFIG_DIR="$(_superpos_oc_config_dir)"
_LIFECYCLE_TRACE_DIR="${_LIFECYCLE_CONFIG_DIR}/traces"

# ── 409 response body inspection ──────────────────────────────

# Extract the remote task status from a 409 conflict response body.
# The Superpos API returns:
#   {"errors":[{"code":"conflict","message":"Task is not in progress. Current status: <status>"}]}
# We parse the status from the message string.
#
# Arguments:
#   $1 — response body (JSON string from stdout of superpos_complete/fail_task)
#
# Outputs: the remote status string (e.g. "completed", "failed", "expired")
#          or empty string if unparseable.
_lifecycle_parse_409_status() {
    local body="${1:-}"
    [[ -z "$body" ]] && return 0
    echo "$body" | jq -r '
        (.errors // [])[] |
        select(.code == "conflict") |
        .message // "" |
        capture("Current status: (?<s>\\S+)") |
        .s // ""
    ' 2>/dev/null | head -n1
}

# ── Retry backoff helpers ────────────────────────────────────

# Check if a task should be skipped due to retry backoff.
# Returns 0 if the task can proceed, 1 if it should wait.
_lifecycle_check_retry_backoff() {
    local pending_dir="$1"
    local task_id="$2"

    local retry_after_file="${pending_dir}/${task_id}.retry_after"
    [[ -f "$retry_after_file" ]] || return 0

    local retry_after now
    retry_after=$(cat "$retry_after_file" 2>/dev/null) || return 0
    now=$(date +%s 2>/dev/null) || return 0

    if [[ $now -lt $retry_after ]]; then
        return 1  # still in backoff window
    fi
    return 0
}

# Write a retry backoff marker with exponential delay.
# Delay: 5 * 2^(attempt-1), capped at 120s.
_lifecycle_write_retry_backoff() {
    local pending_dir="$1"
    local task_id="$2"

    local count_file="${pending_dir}/${task_id}.retry_count"
    local after_file="${pending_dir}/${task_id}.retry_after"

    local count
    count=$(cat "$count_file" 2>/dev/null) || count=0
    count=$(( count + 1 ))
    echo "$count" > "$count_file" 2>/dev/null || true

    # Exponential backoff: 5 * 2^(count-1), capped at 120s
    local delay=$(( 5 * (1 << (count - 1)) ))
    [[ $delay -gt 120 ]] && delay=120

    local now
    now=$(date +%s 2>/dev/null) || return 0
    echo $(( now + delay )) > "$after_file" 2>/dev/null || true
}

# Clean up retry backoff markers.
_lifecycle_clear_retry_backoff() {
    local pending_dir="$1"
    local task_id="$2"

    rm -f "${pending_dir}/${task_id}.retry_count"
    rm -f "${pending_dir}/${task_id}.retry_after"
}

# ── Trace persistence ─────────────────────────────────────────

# Write a trace record for audit/debugging.
# Stored at <config_dir>/traces/{task_id}.json
_lifecycle_write_trace() {
    local task_id="$1"
    local payload="$2"

    mkdir -p "$_LIFECYCLE_TRACE_DIR" 2>/dev/null || return 0
    echo "$payload" > "${_LIFECYCLE_TRACE_DIR}/${task_id}.json" 2>/dev/null || true
}

# ── Ownership evidence helpers ────────────────────────────────

# Write a JSON .claimed marker with ownership evidence.
# Stores agent identity, task ID, and claim timestamp for
# later validation during crash recovery (409 + .claimed).
#
# Arguments:
#   $1 — path to .claimed marker file
#   $2 — task ID
_lifecycle_write_claimed_marker() {
    local marker_path="$1"
    local task_id="$2"
    local agent_id="${SUPERPOS_AGENT_ID:-}"
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')

    jq -n \
        --arg tid "$task_id" \
        --arg agent "$agent_id" \
        --arg ts "$ts" \
        '{"task_id":$tid,"agent_id":$agent,"claimed_at":$ts}' \
        > "$marker_path" 2>/dev/null \
    || echo "$task_id" > "$marker_path" 2>/dev/null || true
}

# Validate ownership evidence in a .claimed marker.
# Checks: structured JSON format, task ID matches, agent identity
# matches (when available), and marker freshness (mtime within TTL).
#
# Arguments:
#   $1 — path to .claimed marker file
#   $2 — expected task ID
#
# Returns:
#   0 — ownership confirmed (safe to re-process)
#   1 — ownership not confirmed (quarantine)
_lifecycle_validate_ownership() {
    local marker_path="$1"
    local expected_task_id="$2"

    [[ -f "$marker_path" ]] || return 1

    # Parse structured marker (JSON with ownership evidence)
    local marker_tid marker_agent
    marker_tid=$(jq -r '.task_id // ""' < "$marker_path" 2>/dev/null) || marker_tid=""
    marker_agent=$(jq -r '.agent_id // ""' < "$marker_path" 2>/dev/null) || marker_agent=""

    # Legacy plain-text markers lack structured evidence — reject
    if [[ -z "$marker_tid" ]]; then
        return 1
    fi

    # Check 1: Task ID must match
    if [[ "$marker_tid" != "$expected_task_id" ]]; then
        return 1
    fi

    # Check 2: Agent identity must match (when both sides have it)
    local current_agent="${SUPERPOS_AGENT_ID:-}"
    if [[ -n "$current_agent" ]] && [[ -n "$marker_agent" ]]; then
        if [[ "$marker_agent" != "$current_agent" ]]; then
            return 1
        fi
    fi

    # Check 3: Marker freshness (mtime within TTL)
    local ttl="${SUPERPOS_CLAIM_TTL:-900}"
    local mtime now age
    mtime=$(stat -c %Y "$marker_path" 2>/dev/null) || return 1
    now=$(date +%s 2>/dev/null) || return 1
    age=$(( now - mtime ))
    if [[ $age -gt $ttl ]]; then
        return 1
    fi

    return 0
}

# Relaxed ownership check for terminal retry paths.
# Validates structured ownership (task + optional agent) but ignores marker age.
_lifecycle_validate_ownership_relaxed() {
    local marker_path="$1"
    local expected_task_id="$2"

    [[ -f "$marker_path" ]] || return 1

    local marker_tid marker_agent
    marker_tid=$(jq -r '.task_id // ""' < "$marker_path" 2>/dev/null) || marker_tid=""
    marker_agent=$(jq -r '.agent_id // ""' < "$marker_path" 2>/dev/null) || marker_agent=""

    [[ -n "$marker_tid" ]] || return 1
    [[ "$marker_tid" == "$expected_task_id" ]] || return 1

    local current_agent="${SUPERPOS_AGENT_ID:-}"
    if [[ -n "$current_agent" ]] && [[ -n "$marker_agent" ]]; then
        [[ "$marker_agent" == "$current_agent" ]] || return 1
    fi

    return 0
}

# Extract trusted control-plane invoke fields from a task payload.
# Sources (in order):
#   .invoke.instructions/context (canonical contract)
#   .payload.invoke.instructions/context (legacy fallback)
#
# Outputs compact JSON object:
#   {"instructions":"...","context":<json|null>}
_lifecycle_extract_invoke() {
    local task_json="$1"
    echo "$task_json" | jq -c '
        {
          instructions: (
            .invoke.instructions
            // .payload.invoke.instructions
            // ""
          ),
          context: (
            .invoke.context
            // .payload.invoke.context
            // null
          )
        }
    ' 2>/dev/null
}

# Process unknown routed task types with an explicit structured failure.
# This guarantees we do not silently drop routed tasks just because the local
# daemon lacks a concrete handler for the task type.
_lifecycle_process_missing_capability() {
    local task_json="${1:-}"
    local task_id="${2:-}"
    local task_type="${3:-unknown}"
    local hive_id="${SUPERPOS_HIVE_ID:-}"
    local pending_dir="${PENDING_DIR:-${_LIFECYCLE_CONFIG_DIR}/pending}"

    if [[ -z "$task_id" ]]; then
        _wake_log "WARN" "lifecycle: missing-capability empty task_id; skipping"
        return 0
    fi

    if [[ -z "$hive_id" ]]; then
        _wake_log "WARN" "lifecycle: missing-capability SUPERPOS_HIVE_ID not set; skipping task ${task_id}"
        return 0
    fi

    local claim_rc=0
    local claimed_marker="${pending_dir}/${task_id}.claimed"
    superpos_claim_task "$hive_id" "$task_id" >/dev/null 2>&1 || claim_rc=$?
    if [[ $claim_rc -ne 0 ]]; then
        if [[ $claim_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            if [[ -f "$claimed_marker" ]] && _lifecycle_validate_ownership "$claimed_marker" "$task_id"; then
                # Crash-recovery path: ownership verified and marker is fresh.
                _wake_log "INFO" "lifecycle: missing-capability task ${task_id} 409 with verified ownership; retrying terminal fail"
            elif [[ -f "$claimed_marker" ]] && _lifecycle_validate_ownership_relaxed "$claimed_marker" "$task_id"; then
                # Marker may be older than claim TTL, but ownership evidence is still valid.
                # For terminal fail retries, prefer reconciliation over quarantine.
                _wake_log "INFO" "lifecycle: missing-capability task ${task_id} 409 with stale-but-owned marker; retrying terminal fail"
            elif [[ -f "$claimed_marker" ]]; then
                _wake_log "WARN" "lifecycle: missing-capability task ${task_id} 409 with .claimed but ownership not confirmed; quarantining"
                mkdir -p "${pending_dir}/quarantine" 2>/dev/null || true
                mv -f "${pending_dir}/${task_id}.json" "${pending_dir}/quarantine/${task_id}.json" 2>/dev/null || true
                mv -f "$claimed_marker" "${pending_dir}/quarantine/${task_id}.claimed" 2>/dev/null || true
                return 0
            else
                _wake_log "WARN" "lifecycle: missing-capability task ${task_id} got 409 without .claimed marker; quarantining for recovery"
                mkdir -p "${pending_dir}/quarantine" 2>/dev/null || true
                mv -f "${pending_dir}/${task_id}.json" "${pending_dir}/quarantine/${task_id}.json" 2>/dev/null || true
                return 0
            fi
        else
            _wake_log "WARN" "lifecycle: missing-capability failed to claim task ${task_id} (rc=${claim_rc}); will retry"
            return 1
        fi
    else
        _lifecycle_write_claimed_marker "$claimed_marker" "$task_id"
    fi

    local invoke_json
    invoke_json=$(_lifecycle_extract_invoke "$task_json") || invoke_json='{"instructions":"","context":null}'

    local now_ts
    now_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')

    local err_json
    err_json=$(echo "$invoke_json" | jq -c \
        --arg id "$task_id" \
        --arg t "$task_type" \
        --arg ts "$now_ts" '
            {
              task_id: $id,
              status: "failed",
              code: "capability_missing",
              error: ("no local handler for routed task type: " + $t),
              task_type: $t,
              processed_by: "daemon",
              trusted_control_plane: {
                invoke: {
                  instructions: (.instructions // ""),
                  context: (.context // null)
                }
              },
              failed_at: $ts
            }
        ' 2>/dev/null) || \
        err_json="{\"task_id\":\"${task_id}\",\"status\":\"failed\",\"code\":\"capability_missing\"}"

    local fail_rc=0
    superpos_fail_task "$hive_id" "$task_id" -e "$err_json" >/dev/null 2>&1 || fail_rc=$?

    if [[ $fail_rc -eq 0 ]] || [[ $fail_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
        _lifecycle_write_trace "$task_id" "$err_json"
        rm -f "${pending_dir}/${task_id}.json"
        rm -f "${pending_dir}/${task_id}.result.json"
        rm -f "${pending_dir}/${task_id}.claimed"

        if [[ $fail_rc -eq 0 ]]; then
            _wake_log "INFO" "lifecycle: missing-capability failed task ${task_id} (type=${task_type})"
        else
            _wake_log "INFO" "lifecycle: missing-capability terminal retry 409 for task ${task_id}; remote already terminal — reconciled"
        fi

        return 0
    fi

    _wake_log "WARN" "lifecycle: missing-capability fail API call failed for task ${task_id}; preserving for retry"
    return 1
}

# Route every task through a lifecycle path.
_lifecycle_process_routed_task() {
    local task_json="${1:-}"
    local task_id="${2:-}"
    local task_type="${3:-}"

    # Reset per-task delivery sentinel so non-webhook task types
    # cannot inherit stale wake-delivery state.
    _lifecycle_wake_delivered=0

    case "$task_type" in
        webhook_handler)
            _lifecycle_process_webhook_handler "$task_json" "$task_id"
            ;;
        reminder)
            _lifecycle_process_reminder "$task_json" "$task_id"
            ;;
        *)
            _lifecycle_process_missing_capability "$task_json" "$task_id" "$task_type"
            ;;
    esac
}

# ── Webhook handler lifecycle ─────────────────────────────────

# Process a webhook_handler task through the full lifecycle.
#
# Steps:
#   1. Claim task atomically (409 = another agent got it → skip)
#   2. Process via webhook wake bridge (parse, dedup, deliver)
#   3. Complete or fail the task in Superpos
#   4. Write a local trace record
#   5. Remove from pending directory
#
# Arguments:
#   $1 — task JSON (full task object)
#   $2 — task ID
#
# Returns:
#   0 — processed (success, filtered, deduped, or conflict-skipped)
#   1 — transient error (claim network failure → will retry next poll)
_lifecycle_process_webhook_handler() {
    local task_json="${1:-}"
    local task_id="${2:-}"
    local hive_id="${SUPERPOS_HIVE_ID:-}"
    local pending_dir="${PENDING_DIR:-${_LIFECYCLE_CONFIG_DIR}/pending}"

    # Signal: set to 1 only when wake/alert delivery actually succeeds.
    # The daemon reads this after the call to decide whether to increment wakes_sent.
    _lifecycle_wake_delivered=0

    if [[ -z "$task_id" ]]; then
        _wake_log "WARN" "lifecycle: empty task_id; skipping"
        return 0
    fi

    if [[ -z "$hive_id" ]]; then
        _wake_log "WARN" "lifecycle: SUPERPOS_HIVE_ID not set; skipping task ${task_id}"
        return 0
    fi

    # ── Step 0: Check for saved result artifact ───────────────
    # If a prior run completed processing but the terminal API call
    # (complete/fail) failed, we saved the result to a .result.json
    # file.  Re-entering claim would get 409 and strand the task.
    # Skip directly to the terminal API call with the saved result.
    local result_artifact="${pending_dir}/${task_id}.result.json"
    if [[ -f "$result_artifact" ]]; then
        _wake_log "INFO" "lifecycle: found result artifact for task ${task_id}; retrying terminal API call"
        local saved_status saved_result
        saved_status=$(jq -r '.status // "completed"' < "$result_artifact" 2>/dev/null) || saved_status="completed"
        saved_result=$(cat "$result_artifact" 2>/dev/null) || saved_result="{}"

        local api_rc=0
        if [[ "$saved_status" == "failed" ]]; then
            superpos_fail_task "$hive_id" "$task_id" -e "$saved_result" >/dev/null 2>&1 || api_rc=$?
        else
            superpos_complete_task "$hive_id" "$task_id" -r "$saved_result" >/dev/null 2>&1 || api_rc=$?
        fi

        if [[ $api_rc -eq 0 ]]; then
            _wake_log "INFO" "lifecycle: terminal API retry succeeded for task ${task_id}"
            _lifecycle_write_trace "$task_id" "$saved_result"
            rm -f "$result_artifact"
            rm -f "${pending_dir}/${task_id}.json"
            rm -f "${pending_dir}/${task_id}.claimed"
            return 0
        elif [[ $api_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            # 409 on terminal retry = remote state already terminal.
            # Our saved result is moot — clean up local artifacts.
            _wake_log "INFO" "lifecycle: terminal retry 409 for task ${task_id}; remote already terminal — reconciled"
            _lifecycle_write_trace "$task_id" "$saved_result"
            rm -f "$result_artifact"
            rm -f "${pending_dir}/${task_id}.json"
            rm -f "${pending_dir}/${task_id}.claimed"
            return 0
        else
            _wake_log "WARN" "lifecycle: terminal API retry still failing for task ${task_id}; preserving"
            return 1
        fi
    fi

    # ── Step 1: Atomic claim ──────────────────────────────────
    local claim_rc=0
    local claimed_marker="${pending_dir}/${task_id}.claimed"
    superpos_claim_task "$hive_id" "$task_id" >/dev/null 2>&1 || claim_rc=$?

    if [[ $claim_rc -ne 0 ]]; then
        if [[ $claim_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            if [[ -f "$claimed_marker" ]]; then
                # We previously claimed this task but crashed before
                # completing processing.  Re-process from Step 2 since
                # we own it — the .claimed marker is proof of prior
                # claim success.  This avoids permanent reminder loss
                # after a crash (the old force-fail behavior dropped
                # unsent reminders).
                _wake_log "INFO" "lifecycle: task ${task_id} 409 with local .claimed marker; re-processing (crash recovery)"
                # Fall through to Step 2 processing below
            else
                # No .claimed marker → ownership uncertain.  We may have crashed
                # between a successful claim and writing the .claimed marker.
                # Quarantine instead of hard-deleting to preserve local recovery.
                _wake_log "WARN" "lifecycle: task ${task_id} got 409 without .claimed marker; quarantining for recovery"
                mkdir -p "${pending_dir}/quarantine" 2>/dev/null || true
                mv -f "${pending_dir}/${task_id}.json" "${pending_dir}/quarantine/${task_id}.json" 2>/dev/null || true
                return 0
            fi
        else
            _wake_log "WARN" "lifecycle: failed to claim task ${task_id} (rc=${claim_rc}); will retry"
            return 1
        fi
    else
        # Write .claimed marker so we can distinguish our own stale claims
        # from foreign claims on subsequent 409 encounters.
        echo "$task_id" > "$claimed_marker" 2>/dev/null || true
        _wake_log "INFO" "lifecycle: claimed task ${task_id}"
    fi

    # ── Step 2: Process via webhook wake bridge ───────────────
    local process_status="completed"
    local process_summary=""

    local parsed=""
    if parsed=$(_wake_parse_pr_comment "$task_json") && [[ -n "$parsed" ]]; then
        # PR comment — attempt delivery
        local comment_id
        comment_id=$(echo "$parsed" | jq -r '.comment_id // empty' 2>/dev/null) || comment_id=""
        local dedup_key="${task_id}:${comment_id}"

        if _wake_is_seen "$dedup_key"; then
            process_summary="deduplicated: already processed within debounce window"
        else
            # Build wake message (mirrors superpos_webhook_wake logic)
            local repo pr_number comment_url severity comment_body invoke_instructions invoke_context
            repo=$(echo "$parsed" | jq -r '.repo // "unknown"' 2>/dev/null) || repo="unknown"
            pr_number=$(echo "$parsed" | jq -r '.pr_number // ""' 2>/dev/null) || pr_number=""
            comment_url=$(echo "$parsed" | jq -r '.comment_url // ""' 2>/dev/null) || comment_url=""
            severity=$(echo "$parsed" | jq -r '.severity // "normal"' 2>/dev/null) || severity="normal"
            comment_body=$(echo "$parsed" | jq -r '.comment_body // ""' 2>/dev/null) || comment_body=""
            invoke_instructions=$(echo "$parsed" | jq -r '.invoke.instructions // ""' 2>/dev/null) || invoke_instructions=""
            invoke_context=$(echo "$parsed" | jq -c '.invoke.context // null' 2>/dev/null) || invoke_context="null"
            [[ ${#comment_body} -gt 500 ]] && comment_body="${comment_body:0:497}..."

            local message
            message=$(printf 'Webhook task %s: PR comment on %s #%s [%s]\nComment: %s\nURL: %s' \
                "$task_id" "$repo" "$pr_number" "$severity" "$comment_body" "$comment_url")
            if [[ -n "$invoke_instructions" ]]; then
                message+=$(printf '\nInvoke instructions: %s' "$invoke_instructions")
            fi
            if [[ "$invoke_context" != "null" ]]; then
                message+=$(printf '\nInvoke context: %s' "$invoke_context")
            fi

            # Deliver: wake + optional alert
            local wake_ok=0 alert_ok=0

            if [[ "${_WAKE_ENABLED:-false}" == "true" ]] && [[ -n "${_WAKE_SESSION:-}" ]]; then
                if _wake_send "$_WAKE_SESSION" "$message"; then
                    wake_ok=1
                fi
            fi

            if [[ "${_WAKE_ALERT_ENABLED:-false}" == "true" ]] && [[ -n "${_WAKE_ALERT_TELEGRAM:-}" ]]; then
                local alert_icon="🔔"
                case "$severity" in
                    urgent) alert_icon="🚨" ;;
                    high)   alert_icon="⚠️" ;;
                    low)    alert_icon="ℹ️" ;;
                esac
                local alert_body="$comment_body"
                [[ ${#alert_body} -gt 200 ]] && alert_body="${alert_body:0:197}..."
                local alert_msg
                alert_msg=$(printf '%s PR comment on %s #%s [%s]\n%s\n%s' \
                    "$alert_icon" "$repo" "$pr_number" "$severity" "$alert_body" "$comment_url")

                if _wake_send_alert "${_WAKE_ALERT_TELEGRAM}" "${_WAKE_ALERT_CHANNEL:-telegram}" "$alert_msg"; then
                    alert_ok=1
                fi
            fi

            if [[ $wake_ok -eq 1 ]] || [[ $alert_ok -eq 1 ]]; then
                _wake_mark_seen "$dedup_key"
                _lifecycle_wake_delivered=1
                process_summary="delivered: wake=${wake_ok} alert=${alert_ok}"
            elif [[ "${_WAKE_ENABLED:-false}" != "true" ]] && [[ "${_WAKE_ALERT_ENABLED:-false}" != "true" ]]; then
                # No delivery channels configured — acknowledge the task
                process_summary="no delivery channels enabled; task acknowledged"
            else
                process_status="failed"
                process_summary="all delivery channels failed"
            fi
        fi
    else
        # Not a PR comment — complete with filter note
        process_summary="filtered: not a PR comment webhook"
    fi

    # ── Step 3: Complete or fail in Superpos ────────────────────
    local now_ts
    now_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')
    local result_json

    if [[ "$process_status" == "completed" ]]; then
        result_json=$(jq -n \
            --arg id "$task_id" \
            --arg summary "$process_summary" \
            --arg ts "$now_ts" \
            '{"task_id":$id,"status":"completed","processed_by":"daemon","summary":$summary,"completed_at":$ts}' \
            2>/dev/null) || result_json="{\"task_id\":\"${task_id}\",\"status\":\"completed\"}"

        if superpos_complete_task "$hive_id" "$task_id" -r "$result_json" >/dev/null 2>&1; then
            _wake_log "INFO" "lifecycle: completed task ${task_id}: ${process_summary}"
        else
            _wake_log "WARN" "lifecycle: task ${task_id} processed but completion API call failed; saving result artifact for retry"
            echo "$result_json" > "${pending_dir}/${task_id}.result.json" 2>/dev/null || true
            return 1
        fi
    else
        result_json=$(jq -n \
            --arg id "$task_id" \
            --arg err "$process_summary" \
            --arg ts "$now_ts" \
            '{"task_id":$id,"status":"failed","error":$err,"failed_at":$ts}' \
            2>/dev/null) || result_json="{\"task_id\":\"${task_id}\",\"status\":\"failed\"}"

        if superpos_fail_task "$hive_id" "$task_id" -e "$result_json" >/dev/null 2>&1; then
            _wake_log "INFO" "lifecycle: failed task ${task_id}: ${process_summary}"
        else
            _wake_log "WARN" "lifecycle: task ${task_id} process failed and fail API call also failed; saving result artifact for retry"
            echo "$result_json" > "${pending_dir}/${task_id}.result.json" 2>/dev/null || true
            return 1
        fi
    fi

    # ── Step 4: Persist trace (only after successful API update) ──
    _lifecycle_write_trace "$task_id" "$result_json"

    # ── Step 5: Clean up pending file + all state markers ────
    rm -f "${pending_dir}/${task_id}.json"
    rm -f "${pending_dir}/${task_id}.result.json"
    rm -f "${pending_dir}/${task_id}.claimed"

    return 0
}


# ── Reminder lifecycle ────────────────────────────────────────

# Parse reminder payload from task JSON.
# Supports both direct payload fields and schedule-style task_payload nesting:
#   payload.channel / payload.target / payload.message
#   payload.task_payload.channel / payload.task_payload.target / payload.task_payload.message
#
# Outputs JSON: {"channel":"...","target":"...","message":"..."}
_lifecycle_parse_reminder_payload() {
    local task_json="$1"
    echo "$task_json" | jq -c '
        (.payload // {}) as $p
        | ($p.task_payload // {}) as $tp
        | {
            channel: (($p.channel // $tp.channel // "") | tostring | gsub("^\\s+|\\s+$"; "")),
            target:  (($p.target  // $tp.target  // "") | tostring | gsub("^\\s+|\\s+$"; "")),
            message: (($p.message // $tp.message // "") | tostring | gsub("^\\s+|\\s+$"; ""))
          }
    ' 2>/dev/null
}

# Process a reminder task through the full lifecycle.
#
# Steps:
#   1. Claim task atomically (409 = another agent got it → skip)
#   2. Parse + validate channel/target/message
#   3. Deliver via gateway HTTP bridge (_wake_send_alert)
#   4. Complete or fail the task in Superpos
#   5. Write a local trace record
#   6. Remove from pending directory
#
# Returns:
#   0 — terminal outcome recorded (completed/failed/conflict-skipped)
#   1 — transient API error (retry next poll)
_lifecycle_process_reminder() {
    local task_json="${1:-}"
    local task_id="${2:-}"
    local hive_id="${SUPERPOS_HIVE_ID:-}"
    local pending_dir="${PENDING_DIR:-${_LIFECYCLE_CONFIG_DIR}/pending}"

    if [[ -z "$task_id" ]]; then
        _wake_log "WARN" "lifecycle: reminder empty task_id; skipping"
        return 0
    fi

    if [[ -z "$hive_id" ]]; then
        _wake_log "WARN" "lifecycle: reminder SUPERPOS_HIVE_ID not set; skipping task ${task_id}"
        return 0
    fi

    # ── Step 0: Retry saved terminal result when available ────
    local result_artifact="${pending_dir}/${task_id}.result.json"
    if [[ -f "$result_artifact" ]]; then
        _wake_log "INFO" "lifecycle: reminder found result artifact for task ${task_id}; retrying terminal API call"
        local saved_status saved_result
        saved_status=$(jq -r '.status // "completed"' < "$result_artifact" 2>/dev/null) || saved_status="completed"
        saved_result=$(cat "$result_artifact" 2>/dev/null) || saved_result="{}"

        local api_rc=0 api_body=""
        if [[ "$saved_status" == "failed" ]]; then
            api_body=$(superpos_fail_task "$hive_id" "$task_id" -e "$saved_result" 2>/dev/null) || api_rc=$?
        else
            api_body=$(superpos_complete_task "$hive_id" "$task_id" -r "$saved_result" 2>/dev/null) || api_rc=$?
        fi

        if [[ $api_rc -eq 0 ]]; then
            _wake_log "INFO" "lifecycle: reminder terminal retry succeeded for task ${task_id}"
            _lifecycle_write_trace "$task_id" "$saved_result"
            rm -f "$result_artifact"
            rm -f "${pending_dir}/${task_id}.json"
            rm -f "${pending_dir}/${task_id}.claimed"
            rm -f "${pending_dir}/${task_id}.delivered"
            _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
            return 0
        elif [[ $api_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            local remote_status
            remote_status=$(_lifecycle_parse_409_status "$api_body")
            local had_delivery=0
            [[ -f "${pending_dir}/${task_id}.delivered" ]] && had_delivery=1

            if [[ "$remote_status" == "completed" ]]; then
                _wake_log "INFO" "lifecycle: reminder terminal retry 409 for task ${task_id}; remote already completed — reconciled"
            elif [[ $had_delivery -eq 1 ]]; then
                _wake_log "WARN" "lifecycle: reminder task ${task_id} delivered but remote status is '${remote_status}' (timeout race); delivery was successful — reconciling"
            else
                _wake_log "INFO" "lifecycle: reminder terminal retry 409 for task ${task_id}; remote status '${remote_status}' — reconciled"
            fi
            _lifecycle_write_trace "$task_id" "$saved_result"
            rm -f "$result_artifact"
            rm -f "${pending_dir}/${task_id}.json"
            rm -f "${pending_dir}/${task_id}.claimed"
            rm -f "${pending_dir}/${task_id}.delivered"
            _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
            return 0
        fi

        _wake_log "WARN" "lifecycle: reminder terminal API retry still failing for task ${task_id}; preserving"
        _lifecycle_write_retry_backoff "$pending_dir" "$task_id"
        return 1
    fi

    # ── Step 1: Atomic claim ──────────────────────────────────
    local claim_rc=0
    local claimed_marker="${pending_dir}/${task_id}.claimed"
    local _recovery_mode=0
    superpos_claim_task "$hive_id" "$task_id" >/dev/null 2>&1 || claim_rc=$?

    if [[ $claim_rc -ne 0 ]]; then
        if [[ $claim_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            if [[ -f "$claimed_marker" ]] && _lifecycle_validate_ownership "$claimed_marker" "$task_id"; then
                # Ownership confirmed: agent identity matches, task ID
                # matches, and marker is fresh.  Enter recovery mode with
                # duplicate-delivery prevention checks (Step 1b).
                _recovery_mode=1
                _wake_log "INFO" "lifecycle: reminder task ${task_id} 409 with verified ownership; checking for prior delivery (crash recovery)"
            elif [[ -f "$claimed_marker" ]]; then
                # .claimed exists but ownership evidence is weak, stale,
                # or mismatched.  Quarantine both files for investigation.
                _wake_log "WARN" "lifecycle: reminder task ${task_id} 409 with .claimed but ownership not confirmed; quarantining"
                mkdir -p "${pending_dir}/quarantine" 2>/dev/null || true
                mv -f "${pending_dir}/${task_id}.json" "${pending_dir}/quarantine/${task_id}.json" 2>/dev/null || true
                mv -f "$claimed_marker" "${pending_dir}/quarantine/${task_id}.claimed" 2>/dev/null || true
                return 0
            else
                # No .claimed marker → ownership uncertain.  Quarantine
                # instead of hard-deleting to preserve local recovery.
                _wake_log "WARN" "lifecycle: reminder task ${task_id} got 409 without .claimed marker; quarantining for recovery"
                mkdir -p "${pending_dir}/quarantine" 2>/dev/null || true
                mv -f "${pending_dir}/${task_id}.json" "${pending_dir}/quarantine/${task_id}.json" 2>/dev/null || true
                return 0
            fi
        else
            _wake_log "WARN" "lifecycle: reminder failed to claim task ${task_id} (rc=${claim_rc}); will retry"
            return 1
        fi
    else
        _lifecycle_write_claimed_marker "$claimed_marker" "$task_id"
        _wake_log "INFO" "lifecycle: reminder claimed task ${task_id}"
    fi

    # ── Step 1b: Duplicate delivery prevention (crash recovery) ──
    # On 409+.claimed re-entry, check for evidence that delivery already
    # happened before blindly re-sending.  This prevents duplicate user
    # notifications when crash occurs after delivery+complete but before
    # local cleanup.
    if [[ $_recovery_mode -eq 1 ]]; then
        local delivered_marker="${pending_dir}/${task_id}.delivered"

        # Check 1: Local trace → task already fully processed in a prior run
        if [[ -f "${_LIFECYCLE_TRACE_DIR}/${task_id}.json" ]]; then
            _wake_log "INFO" "lifecycle: reminder task ${task_id} has local trace; already processed — reconciling"
            rm -f "${pending_dir}/${task_id}.json"
            rm -f "${pending_dir}/${task_id}.claimed"
            rm -f "$delivered_marker"
            _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
            return 0
        fi

        # Check 2: .delivered marker → delivery happened, reconcile without re-send
        if [[ -f "$delivered_marker" ]]; then
            _wake_log "INFO" "lifecycle: reminder task ${task_id} has .delivered marker; reconciling without re-send"
            local now_ts
            now_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')
            local reconcile_json
            reconcile_json=$(jq -n \
                --arg id "$task_id" \
                --arg ts "$now_ts" \
                '{"task_id":$id,"status":"completed","processed_by":"daemon","summary":"reconciled: prior delivery confirmed","completed_at":$ts}' \
                2>/dev/null) || reconcile_json="{\"task_id\":\"${task_id}\",\"status\":\"completed\"}"

            local reconcile_rc=0 reconcile_body=""
            reconcile_body=$(superpos_complete_task "$hive_id" "$task_id" -r "$reconcile_json" 2>/dev/null) || reconcile_rc=$?

            if [[ $reconcile_rc -eq 0 ]]; then
                _wake_log "INFO" "lifecycle: reminder task ${task_id} reconciled after .delivered evidence"
                _lifecycle_write_trace "$task_id" "$reconcile_json"
                rm -f "${pending_dir}/${task_id}.json"
                rm -f "${pending_dir}/${task_id}.claimed"
                rm -f "$delivered_marker"
                _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
                return 0
            elif [[ $reconcile_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
                local remote_status
                remote_status=$(_lifecycle_parse_409_status "$reconcile_body")
                if [[ "$remote_status" == "completed" ]]; then
                    _wake_log "INFO" "lifecycle: reminder task ${task_id} already completed remotely; .delivered reconciliation OK"
                elif [[ -n "$remote_status" ]]; then
                    _wake_log "WARN" "lifecycle: reminder task ${task_id} delivered but remote status is '${remote_status}' (timeout race); delivery was successful — reconciling"
                else
                    _wake_log "INFO" "lifecycle: reminder task ${task_id} reconciled after .delivered evidence (409)"
                fi
                _lifecycle_write_trace "$task_id" "$reconcile_json"
                rm -f "${pending_dir}/${task_id}.json"
                rm -f "${pending_dir}/${task_id}.claimed"
                rm -f "$delivered_marker"
                _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
                return 0
            else
                _wake_log "WARN" "lifecycle: reminder task ${task_id} reconciliation API failed; saving artifact"
                echo "$reconcile_json" > "${pending_dir}/${task_id}.result.json" 2>/dev/null || true
                _lifecycle_write_retry_backoff "$pending_dir" "$task_id"
                return 1
            fi
        fi

        # Check 3: Remote reconciliation — query task trace from API.
        # If the server shows a terminal state, delivery already happened
        # (covers the narrow window between delivery and .delivered write).
        local remote_trace_rc=0
        local remote_trace=""
        remote_trace=$(superpos_get_task_trace "$hive_id" "$task_id" 2>/dev/null) || remote_trace_rc=$?

        if [[ $remote_trace_rc -eq 0 ]] && [[ -n "$remote_trace" ]]; then
            local remote_status
            remote_status=$(echo "$remote_trace" | jq -r '.data.status // .status // ""' 2>/dev/null) || remote_status=""
            if [[ "$remote_status" == "completed" ]] || [[ "$remote_status" == "failed" ]] \
                || [[ "$remote_status" == "cancelled" ]] || [[ "$remote_status" == "dead_letter" ]] \
                || [[ "$remote_status" == "expired" ]]; then
                _wake_log "INFO" "lifecycle: reminder task ${task_id} remote trace shows '${remote_status}'; already terminal — reconciling"
                _lifecycle_write_trace "$task_id" "$remote_trace"
                rm -f "${pending_dir}/${task_id}.json"
                rm -f "${pending_dir}/${task_id}.claimed"
                _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"
                return 0
            fi
        fi

        # No evidence of prior delivery → safe to re-process from Step 2
        _wake_log "INFO" "lifecycle: reminder task ${task_id} no prior delivery evidence; re-delivering (crash recovery)"
    fi

    # ── Step 2: Parse + validate + deliver ────────────────────
    local process_status="completed"
    local process_summary=""
    local channel=""
    local target=""
    local reminder_message=""

    local reminder_payload
    if ! reminder_payload=$(_lifecycle_parse_reminder_payload "$task_json"); then
        process_status="failed"
        process_summary="validation failed: reminder payload is not parseable"
    else
        channel=$(echo "$reminder_payload" | jq -r '.channel // ""' 2>/dev/null) || channel=""
        target=$(echo "$reminder_payload" | jq -r '.target // ""' 2>/dev/null) || target=""
        reminder_message=$(echo "$reminder_payload" | jq -r '.message // ""' 2>/dev/null) || reminder_message=""

        if [[ -z "$channel" ]] || [[ -z "$target" ]] || [[ -z "$reminder_message" ]]; then
            process_status="failed"
            process_summary="validation failed: payload requires non-empty channel, target, and message"
            _wake_log "WARN" "lifecycle: reminder validation failed for ${task_id} (channel='${channel}' target='${target}' message_len=${#reminder_message})"
        else
            if _wake_send_alert "$target" "$channel" "$reminder_message" "${_WAKE_REMINDER_SEND_TIMEOUT:-60}"; then
                process_summary="delivered reminder via ${channel} to ${target}"
                # Write delivery evidence for crash recovery idempotency.
                # Step 1b checks this marker to avoid duplicate re-sends.
                echo "$task_id" > "${pending_dir}/${task_id}.delivered" 2>/dev/null || true
                _wake_log "INFO" "lifecycle: reminder delivered for ${task_id} via channel=${channel} target=${target}"
            else
                local delivery_detail="${_WAKE_LAST_ERROR:-}"
                process_status="failed"
                if [[ -n "$delivery_detail" ]]; then
                    process_summary="delivery failed: ${delivery_detail}"
                else
                    process_summary="delivery failed: message.send channel=${channel} target=${target}"
                fi
                _wake_log "WARN" "lifecycle: reminder delivery failed for ${task_id} via channel=${channel} target=${target}: ${delivery_detail:-unknown}"
            fi
        fi
    fi

    # ── Step 3: Complete or fail in Superpos ────────────────────
    local now_ts
    now_ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')
    local result_json

    local delivered_marker="${pending_dir}/${task_id}.delivered"
    if [[ "$process_status" == "completed" ]]; then
        result_json=$(jq -n \
            --arg id "$task_id" \
            --arg summary "$process_summary" \
            --arg ch "$channel" \
            --arg tgt "$target" \
            --arg ts "$now_ts" \
            '{"task_id":$id,"status":"completed","processed_by":"daemon","summary":$summary,"delivery":{"channel":$ch,"target":$tgt},"completed_at":$ts}' \
            2>/dev/null) || result_json="{\"task_id\":\"${task_id}\",\"status\":\"completed\"}"

        local complete_rc=0 complete_body=""
        complete_body=$(superpos_complete_task "$hive_id" "$task_id" -r "$result_json" 2>/dev/null) || complete_rc=$?

        if [[ $complete_rc -eq 0 ]]; then
            _wake_log "INFO" "lifecycle: reminder completed task ${task_id}: ${process_summary}"
        elif [[ $complete_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            # 409: task already in a terminal state.  Distinguish scenarios.
            local remote_status
            remote_status=$(_lifecycle_parse_409_status "$complete_body")
            if [[ "$remote_status" == "completed" ]]; then
                _wake_log "INFO" "lifecycle: reminder task ${task_id} already completed remotely — no conflict"
            elif [[ -f "$delivered_marker" ]] && [[ -n "$remote_status" ]]; then
                _wake_log "WARN" "lifecycle: reminder task ${task_id} delivered but remote status is '${remote_status}' (timeout race); delivery was successful — reconciling"
            else
                _wake_log "INFO" "lifecycle: reminder task ${task_id} complete 409; remote status '${remote_status:-unknown}' — reconciled"
            fi
            # Either way, the task is terminal — proceed to cleanup.
        else
            _wake_log "WARN" "lifecycle: reminder task ${task_id} processed but completion API call failed; saving result artifact for retry"
            echo "$result_json" > "${pending_dir}/${task_id}.result.json" 2>/dev/null || true
            _lifecycle_write_retry_backoff "$pending_dir" "$task_id"
            return 1
        fi
    else
        local fail_detail="${_WAKE_LAST_ERROR:-}"
        result_json=$(jq -n \
            --arg id "$task_id" \
            --arg err "$process_summary" \
            --arg ch "$channel" \
            --arg tgt "$target" \
            --arg detail "$fail_detail" \
            --arg ts "$now_ts" \
            '{"task_id":$id,"status":"failed","error":$err,"delivery":{"channel":$ch,"target":$tgt},"failed_at":$ts} + (if $detail != "" then {"delivery_detail":$detail} else {} end)' \
            2>/dev/null) || result_json="{\"task_id\":\"${task_id}\",\"status\":\"failed\"}"

        local fail_rc=0 fail_body=""
        fail_body=$(superpos_fail_task "$hive_id" "$task_id" -e "$result_json" 2>/dev/null) || fail_rc=$?

        if [[ $fail_rc -eq 0 ]]; then
            _wake_log "INFO" "lifecycle: reminder failed task ${task_id}: ${process_summary}"
        elif [[ $fail_rc -eq ${SUPERPOS_ERR_CONFLICT:-6} ]]; then
            local remote_status
            remote_status=$(_lifecycle_parse_409_status "$fail_body")
            _wake_log "INFO" "lifecycle: reminder task ${task_id} fail 409; remote status '${remote_status:-unknown}' — reconciled"
        else
            _wake_log "WARN" "lifecycle: reminder task ${task_id} fail API call failed; saving result artifact for retry"
            echo "$result_json" > "${pending_dir}/${task_id}.result.json" 2>/dev/null || true
            _lifecycle_write_retry_backoff "$pending_dir" "$task_id"
            return 1
        fi
    fi

    # ── Step 4: Persist trace (only after successful API update) ──
    _lifecycle_write_trace "$task_id" "$result_json"

    # ── Step 5: Clean up pending file + all state markers ────
    rm -f "${pending_dir}/${task_id}.json"
    rm -f "${pending_dir}/${task_id}.result.json"
    rm -f "${pending_dir}/${task_id}.claimed"
    rm -f "${pending_dir}/${task_id}.delivered"
    _lifecycle_clear_retry_backoff "$pending_dir" "$task_id"

    return 0
}

# ── Retry sweep for stuck pending tasks ──────────────────────

# Retry any pending auto-lifecycle tasks that remain from prior polls.
# Called by the daemon on each poll cycle to unstick tasks whose claim
# failed with a retryable error (network timeout, etc.).
#
# Safe to call repeatedly: lifecycle's atomic claim prevents
# double-processing (409 → skip gracefully).  Result artifacts
# (.result.json) are retried directly without re-claiming.
_lifecycle_retry_pending_handlers() {
    local pending_dir="${PENDING_DIR:-${_LIFECYCLE_CONFIG_DIR}/pending}"
    [[ -d "$pending_dir" ]] || return 0

    local pending_file
    for pending_file in "${pending_dir}"/*.json; do
        [[ -f "$pending_file" ]] || continue
        [[ "$pending_file" == *.result.json ]] && continue

        local ptask_json ptask_id ptask_type
        ptask_json=$(cat "$pending_file" 2>/dev/null) || continue
        ptask_id=$(basename "$pending_file" .json)
        ptask_type=$(echo "$ptask_json" | jq -r '.type // empty' 2>/dev/null) || ptask_type=""
        [[ -z "$ptask_type" ]] && continue

        # Skip tasks still in retry backoff window
        if ! _lifecycle_check_retry_backoff "$pending_dir" "$ptask_id"; then
            continue
        fi

        _lifecycle_process_routed_task "$ptask_json" "$ptask_id" "$ptask_type" || true

        # Count successful wake/alert deliveries from retry path.
        # Only webhook_handler sets this sentinel.
        if [[ "${_lifecycle_wake_delivered:-0}" -eq 1 ]]; then
            _stats_wakes_sent=$(( ${_stats_wakes_sent:-0} + 1 ))
        fi
    done
}
