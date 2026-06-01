#!/usr/bin/env bash
# test_task_lifecycle.sh — Tests for webhook_handler task lifecycle.
#
# Validates the end-to-end claim → process → complete/fail → trace → cleanup
# flow implemented by _lifecycle_process_webhook_handler().
#
# Test areas:
#   - Claim success → process → complete
#   - Claim 409 conflict → skip gracefully
#   - Claim network error → retry (return 1)
#   - Non-PR webhook → complete with filter summary
#   - Delivery failure → fail task
#   - Dedup safety → complete (not fail)
#   - Trace file written
#   - Pending file cleaned up
#   - Race condition: two claims for same task

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides SUPERPOS_OK, SUPERPOS_ERR_CONFLICT, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

# Track API calls
_CLAIM_CALLS=0
_CLAIM_LAST_TASK=""
_CLAIM_RC=0
_COMPLETE_CALLS=0
_COMPLETE_LAST_TASK=""
_COMPLETE_LAST_RESULT=""
_FAIL_CALLS=0
_FAIL_LAST_TASK=""
_FAIL_LAST_ERROR=""

_setup() {
    export SUPERPOS_CONFIG_DIR="$_tmp_dir"
    export SUPERPOS_HIVE_ID="hive-test-001"
    export SUPERPOS_WAKE_ENABLED="true"
    export SUPERPOS_WAKE_SESSION="test-session-123"
    export SUPERPOS_WAKE_LOG="${_tmp_dir}/wake.log"
    export SUPERPOS_WAKE_DEBOUNCE_SECS="5"
    export SUPERPOS_WAKE_ALERT_ENABLED="false"
    export SUPERPOS_WAKE_ALERT_TELEGRAM=""

    export PENDING_DIR="${_tmp_dir}/pending"
    mkdir -p "$PENDING_DIR"
    rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
    rm -rf "${PENDING_DIR}/quarantine" 2>/dev/null || true

    rm -f "${_tmp_dir}/wake_seen.json"
    rm -f "${_tmp_dir}/wake.log"
    rm -rf "${_tmp_dir}/traces"

    _CLAIM_CALLS=0
    _CLAIM_LAST_TASK=""
    _CLAIM_RC=0
    _COMPLETE_CALLS=0
    _COMPLETE_LAST_TASK=""
    _COMPLETE_LAST_RESULT=""
    _FAIL_CALLS=0
    _FAIL_LAST_TASK=""
    _FAIL_LAST_ERROR=""

    # Source modules to pick up env changes
    source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
    source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

    # Mock SDK API functions
    superpos_claim_task() {
        local hive_id="$1"
        local task_id="$2"
        _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
        _CLAIM_LAST_TASK="$task_id"
        return $_CLAIM_RC
    }

    superpos_complete_task() {
        local hive_id="$1"
        local task_id="$2"
        shift 2
        _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
        _COMPLETE_LAST_TASK="$task_id"
        # Capture -r argument
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        return 0
    }

    superpos_fail_task() {
        local hive_id="$1"
        local task_id="$2"
        shift 2
        _FAIL_CALLS=$((_FAIL_CALLS + 1))
        _FAIL_LAST_TASK="$task_id"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -e) _FAIL_LAST_ERROR="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        return 0
    }

    # Mock wake transport (gateway-only in current runtime)
    _wake_send() {
        return 0
    }
}

# Build a realistic PR comment webhook task
_make_pr_comment_task() {
    local task_id="${1:-task-001}"
    local comment_id="${2:-42}"
    local repo="${3:-octocat/hello-world}"
    local pr_num="${4:-7}"
    local comment_body="${5:-Please fix the tests}"

    jq -n \
        --arg tid "$task_id" \
        --argjson cid "$comment_id" \
        --arg repo "$repo" \
        --argjson pr "$pr_num" \
        --arg cbody "$comment_body" \
        --arg curl "https://github.com/${repo}/pull/${pr_num}#issuecomment-${comment_id}" \
        --arg purl "https://github.com/${repo}/pull/${pr_num}" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                webhook_route_id: "route-001",
                service_id: "svc-001",
                event_payload: {
                    action: "created",
                    repository: { full_name: $repo },
                    sender: { login: "test-user" },
                    body: {
                        action: "created",
                        comment: {
                            id: $cid,
                            html_url: $curl,
                            body: $cbody
                        },
                        issue: {
                            number: $pr,
                            pull_request: {
                                html_url: $purl
                            }
                        },
                        repository: {
                            full_name: $repo
                        }
                    }
                }
            }
        }'
}

# Build a non-PR webhook task (push event)
_make_push_task() {
    local task_id="${1:-task-push}"
    jq -n --arg tid "$task_id" '{
        id: $tid,
        type: "webhook_handler",
        payload: {
            event_payload: {
                action: "push",
                ref: "refs/heads/main",
                repository: { full_name: "org/repo" }
            }
        }
    }'
}


# ═══════════════════════════════════════════════════════════════
# Claim + process + complete success
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — claim + process + complete success"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-t1" 100 "org/lifecycle" 10 "Review please")

# Write pending file
echo "$task_json" > "${PENDING_DIR}/lc-t1.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-t1"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on success"
assert_eq "$_CLAIM_CALLS" "1" "claim called exactly once"
assert_eq "$_CLAIM_LAST_TASK" "lc-t1" "claim called with correct task ID"
assert_eq "$_COMPLETE_CALLS" "1" "complete called exactly once"
assert_eq "$_COMPLETE_LAST_TASK" "lc-t1" "complete called with correct task ID"
assert_eq "$_FAIL_CALLS" "0" "fail not called on success"

# Verify result payload
assert_contains "$_COMPLETE_LAST_RESULT" "completed" "result contains status=completed"
assert_contains "$_COMPLETE_LAST_RESULT" "lc-t1" "result contains task ID"
assert_contains "$_COMPLETE_LAST_RESULT" "daemon" "result contains processed_by=daemon"
assert_contains "$_COMPLETE_LAST_RESULT" "delivered" "result summary mentions delivery"

# Verify pending file removed
assert_eq "$([ -f "${PENDING_DIR}/lc-t1.json" ] && echo exists || echo removed)" "removed" \
    "pending file cleaned up after success"


# ═══════════════════════════════════════════════════════════════
# Claim 409 conflict — skip gracefully
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — claim conflict (409) skips gracefully"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
task_json=$(_make_pr_comment_task "lc-conflict" 101)
echo "$task_json" > "${PENDING_DIR}/lc-conflict.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-conflict"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on conflict (graceful skip)"
assert_eq "$_CLAIM_CALLS" "1" "claim attempted"
assert_eq "$_COMPLETE_CALLS" "0" "complete not called on conflict"
assert_eq "$_FAIL_CALLS" "0" "fail not called on conflict"

# Pending file should be quarantined — ownership uncertain, preserved for recovery.
assert_eq "$([ -f "${PENDING_DIR}/lc-conflict.json" ] && echo exists || echo moved)" "moved" \
    "pending file moved from active pending"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/lc-conflict.json" ] && echo quarantined || echo missing)" "quarantined" \
    "pending file quarantined for recovery"


# ═══════════════════════════════════════════════════════════════
# Claim network error — retry (return 1)
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — claim network error returns 1 for retry"

_setup
_CLAIM_RC=1  # generic error (not conflict)
task_json=$(_make_pr_comment_task "lc-neterr" 102)
echo "$task_json" > "${PENDING_DIR}/lc-neterr.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-neterr"
rc=$?
set -e

assert_eq "$rc" "1" "returns 1 on claim network error"
assert_eq "$_COMPLETE_CALLS" "0" "complete not called"
assert_eq "$_FAIL_CALLS" "0" "fail not called"

# Pending file should NOT be removed (will retry)
assert_eq "$([ -f "${PENDING_DIR}/lc-neterr.json" ] && echo exists || echo removed)" "exists" \
    "pending file preserved for retry"


# ═══════════════════════════════════════════════════════════════
# Non-PR webhook → complete with filter note
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — non-PR webhook completes with filter summary"

_setup
_CLAIM_RC=0
task_json=$(_make_push_task "lc-push")
echo "$task_json" > "${PENDING_DIR}/lc-push.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-push"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 for filtered task"
assert_eq "$_COMPLETE_CALLS" "1" "complete called (not left pending)"
assert_eq "$_FAIL_CALLS" "0" "fail not called for filtered task"
assert_contains "$_COMPLETE_LAST_RESULT" "filtered" "result mentions filtering"
assert_contains "$_COMPLETE_LAST_RESULT" "not a PR comment" "result explains filter reason"


# ═══════════════════════════════════════════════════════════════
# Delivery failure → fail task
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — delivery failure marks task as failed"

_setup
_CLAIM_RC=0
export SUPERPOS_WAKE_ENABLED="true"
export SUPERPOS_WAKE_SESSION="test-session"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

# Re-apply mocks after re-source
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    _FAIL_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -e) _FAIL_LAST_ERROR="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}

# Mock wake delivery to FAIL
_wake_send() { return 1; }

task_json=$(_make_pr_comment_task "lc-fail" 200 "org/fail-repo" 20 "Will fail delivery")
echo "$task_json" > "${PENDING_DIR}/lc-fail.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-fail"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 (lifecycle itself is fail-soft)"
assert_eq "$_COMPLETE_CALLS" "0" "complete not called on delivery failure"
assert_eq "$_FAIL_CALLS" "1" "fail called once"
assert_eq "$_FAIL_LAST_TASK" "lc-fail" "fail called with correct task ID"
assert_contains "$_FAIL_LAST_ERROR" "failed" "error payload indicates failure"
assert_contains "$_FAIL_LAST_ERROR" "delivery" "error mentions delivery"

# Pending file still cleaned up (task has been reported to Superpos)
assert_eq "$([ -f "${PENDING_DIR}/lc-fail.json" ] && echo exists || echo removed)" "removed" \
    "pending file cleaned up after fail"


# ═══════════════════════════════════════════════════════════════
# Dedup safety — deduplicated task still completes
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — deduplicated task completes (not left pending)"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-dedup" 300 "org/dedup" 30 "Dedup test")

# Pre-mark as seen (simulate prior processing)
_wake_mark_seen "lc-dedup:300"

echo "$task_json" > "${PENDING_DIR}/lc-dedup.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-dedup"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 for deduped task"
assert_eq "$_COMPLETE_CALLS" "1" "deduped task still gets completed in Superpos"
assert_contains "$_COMPLETE_LAST_RESULT" "deduplicated" "result mentions deduplication"

assert_eq "$([ -f "${PENDING_DIR}/lc-dedup.json" ] && echo exists || echo removed)" "removed" \
    "pending file cleaned up after dedup"


# ═══════════════════════════════════════════════════════════════
# Trace file written
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — trace file persisted"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-trace" 400 "org/trace" 40 "Trace test")
echo "$task_json" > "${PENDING_DIR}/lc-trace.json"

_lifecycle_process_webhook_handler "$task_json" "lc-trace"

assert_eq "$([ -f "${_tmp_dir}/traces/lc-trace.json" ] && echo exists || echo missing)" "exists" \
    "trace file created"

trace_content=$(cat "${_tmp_dir}/traces/lc-trace.json" 2>/dev/null || echo "")
assert_contains "$trace_content" "lc-trace" "trace contains task ID"
assert_contains "$trace_content" "completed" "trace contains status"


# ═══════════════════════════════════════════════════════════════
# No channels enabled → acknowledge (complete, not fail)
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — no channels enabled acknowledges task"

_setup
_CLAIM_RC=0
export SUPERPOS_WAKE_ENABLED="false"
export SUPERPOS_WAKE_ALERT_ENABLED="false"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

# Re-apply mocks
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "lc-nochan" 500 "org/nochan" 50 "No channels")
echo "$task_json" > "${PENDING_DIR}/lc-nochan.json"

_lifecycle_process_webhook_handler "$task_json" "lc-nochan"

assert_eq "$_COMPLETE_CALLS" "1" "no-channels: task completed (not failed)"
assert_eq "$_FAIL_CALLS" "0" "no-channels: fail not called"
assert_contains "$_COMPLETE_LAST_RESULT" "acknowledged" "no-channels: result mentions acknowledgement"


# ═══════════════════════════════════════════════════════════════
# Race condition: second claim after first succeeds
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — race: two processes claim same task"

_setup

# Simulate: first caller succeeds, second gets 409
_race_call_count=0
superpos_claim_task() {
    _race_call_count=$((_race_call_count + 1))
    _CLAIM_CALLS=$_race_call_count
    if [[ $_race_call_count -eq 1 ]]; then
        return 0  # first caller wins
    else
        return $SUPERPOS_ERR_CONFLICT  # second caller loses
    fi
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "lc-race" 600 "org/race" 60 "Race test")
echo "$task_json" > "${PENDING_DIR}/lc-race.json"

# First call — should claim and complete
_lifecycle_process_webhook_handler "$task_json" "lc-race"
assert_eq "$_COMPLETE_CALLS" "1" "race: first caller completes task"

# Write pending file again (simulating second daemon seeing same task)
echo "$task_json" > "${PENDING_DIR}/lc-race.json"
_COMPLETE_CALLS=0

# Second call — should get 409 and skip (no .claimed marker → quarantine)
_lifecycle_process_webhook_handler "$task_json" "lc-race"
assert_eq "$_COMPLETE_CALLS" "0" "race: second caller does not complete (409)"
assert_eq "$([ -f "${PENDING_DIR}/lc-race.json" ] && echo exists || echo moved)" "moved" \
    "race: second caller removes from active pending"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/lc-race.json" ] && echo quarantined || echo missing)" "quarantined" \
    "race: second caller quarantines pending file"


# ═══════════════════════════════════════════════════════════════
# Empty task_id — skipped gracefully
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — empty task_id skipped"

_setup

set +e
_lifecycle_process_webhook_handler '{"id":""}' ""
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on empty task_id"
assert_eq "$_CLAIM_CALLS" "0" "claim not called with empty task_id"


# ═══════════════════════════════════════════════════════════════
# Missing hive_id — skipped gracefully
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — missing SUPERPOS_HIVE_ID skipped"

_setup
export SUPERPOS_HIVE_ID=""
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

set +e
_lifecycle_process_webhook_handler '{"id":"t1"}' "t1"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on missing hive_id"
assert_eq "$_CLAIM_CALLS" "0" "claim not called without hive_id"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — _lifecycle_retry_pending_handlers
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — retries stuck pending webhook_handler tasks"

_setup
_CLAIM_RC=0
# Clean pending dir from prior tests
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
task_json=$(_make_pr_comment_task "retry-stuck" 700 "org/retry" 70 "Stuck task")

# Simulate prior claim failure: pending file exists but was never processed
echo "$task_json" > "${PENDING_DIR}/retry-stuck.json"

# Call the retry sweep (not the direct lifecycle function)
_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry sweep: claim called for stuck task"
assert_eq "$_COMPLETE_CALLS" "1" "retry sweep: task completed after retry"
assert_eq "$_COMPLETE_LAST_TASK" "retry-stuck" "retry sweep: correct task ID"
assert_eq "$([ -f "${PENDING_DIR}/retry-stuck.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep: pending file cleaned up after success"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — unknown task gets explicit capability_missing failure
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — unknown task type fails with capability_missing"

_setup
_CLAIM_RC=0

# Create a pending task of a different type
other_task=$(jq -n '{"id":"other-type-1","type":"code_review","payload":{}}')
echo "$other_task" > "${PENDING_DIR}/other-type-1.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry sweep: claim called for unknown type"
assert_eq "$_COMPLETE_CALLS" "0" "retry sweep: complete not called for unknown type"
assert_eq "$_FAIL_CALLS" "1" "retry sweep: fail called for unknown type"
trace_unknown=$(cat "${_tmp_dir}/traces/other-type-1.json" 2>/dev/null || echo "")
assert_contains "$trace_unknown" "capability_missing" "retry sweep: trace includes capability_missing code"
assert_contains "$trace_unknown" "code_review" "retry sweep: trace includes missing task type"
assert_eq "$([ -f "${PENDING_DIR}/other-type-1.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep: unknown-type pending file removed after fail"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — unknown task includes invoke passthrough fields
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — unknown task preserves trusted invoke fields"

_setup
_CLAIM_RC=0

other_task=$(jq -n '{
    "id":"other-type-2",
    "type":"triage",
    "payload":{
        "invoke":{
            "instructions":"Handle this manually",
            "context":{"ticket":"ABC-123","priority":"high"}
        }
    }
}')
echo "$other_task" > "${PENDING_DIR}/other-type-2.json"

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "1" "retry sweep invoke: fail called"
trace_invoke=$(cat "${_tmp_dir}/traces/other-type-2.json" 2>/dev/null || echo "{}")
assert_eq "$(echo "$trace_invoke" | jq -r '.trusted_control_plane.invoke.instructions // empty')" "Handle this manually" \
    "retry sweep invoke: instructions passed through"
assert_eq "$(echo "$trace_invoke" | jq -r '.trusted_control_plane.invoke.context.ticket // empty')" "ABC-123" \
    "retry sweep invoke: context passed through"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — top-level invoke takes precedence over payload.invoke
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — invoke precedence prefers top-level fields"

_setup
_CLAIM_RC=0

other_task=$(jq -n '{
    "id":"other-type-3",
    "type":"triage",
    "invoke":{
        "instructions":"Use top-level instructions",
        "context":{"ticket":"TOP-999","source":"top"}
    },
    "payload":{
        "invoke":{
            "instructions":"Legacy payload instructions",
            "context":{"ticket":"LEGACY-111","source":"payload"}
        }
    }
}')
echo "$other_task" > "${PENDING_DIR}/other-type-3.json"

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "1" "retry sweep precedence: fail called"
trace_invoke_top=$(cat "${_tmp_dir}/traces/other-type-3.json" 2>/dev/null || echo "{}")
assert_eq "$(echo "$trace_invoke_top" | jq -r '.trusted_control_plane.invoke.instructions // empty')" "Use top-level instructions" \
    "retry sweep precedence: top-level instructions win"
assert_eq "$(echo "$trace_invoke_top" | jq -r '.trusted_control_plane.invoke.context.ticket // empty')" "TOP-999" \
    "retry sweep precedence: top-level context wins"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — unknown task 409 with owned marker retries fail
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — unknown task 409 with verified .claimed retries terminal fail"

_setup
_CLAIM_RC=${SUPERPOS_ERR_CONFLICT:-6}

owned_task=$(jq -n '{"id":"other-type-conflict-owned","type":"triage","payload":{}}')
echo "$owned_task" > "${PENDING_DIR}/other-type-conflict-owned.json"
_lifecycle_write_claimed_marker "${PENDING_DIR}/other-type-conflict-owned.claimed" "other-type-conflict-owned"

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "1" "retry sweep conflict-owned: fail called for recovery"
assert_eq "$([ -f "${PENDING_DIR}/other-type-conflict-owned.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep conflict-owned: pending file removed after terminal fail"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — unknown task 409 without marker quarantines
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — unknown task 409 without .claimed quarantines for recovery"

_setup
_CLAIM_RC=${SUPERPOS_ERR_CONFLICT:-6}

conflict_task=$(jq -n '{"id":"other-type-conflict-no-marker","type":"triage","payload":{}}')
echo "$conflict_task" > "${PENDING_DIR}/other-type-conflict-no-marker.json"

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "0" "retry sweep conflict-no-marker: fail not called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/other-type-conflict-no-marker.json" ] && echo exists || echo missing)" "exists" \
    "retry sweep conflict-no-marker: pending file moved to quarantine"


describe "Retry sweep — unknown task 409 with stale-but-owned marker retries terminal fail"

_setup
_CLAIM_RC=${SUPERPOS_ERR_CONFLICT:-6}
SUPERPOS_CLAIM_TTL=1

stale_owned_task=$(jq -n '{"id":"other-type-conflict-stale-owned","type":"triage","payload":{}}')
echo "$stale_owned_task" > "${PENDING_DIR}/other-type-conflict-stale-owned.json"
_lifecycle_write_claimed_marker "${PENDING_DIR}/other-type-conflict-stale-owned.claimed" "other-type-conflict-stale-owned"
touch -d "2 minutes ago" "${PENDING_DIR}/other-type-conflict-stale-owned.claimed" 2>/dev/null || true

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "1" "retry sweep conflict-stale-owned: fail called for terminal reconciliation"
assert_eq "$([ -f "${PENDING_DIR}/other-type-conflict-stale-owned.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep conflict-stale-owned: pending file removed after terminal fail"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — unknown task fail 409 reconciles as terminal
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — unknown task fail 409 is reconciled and cleaned up"

_setup
_CLAIM_RC=0

superpos_fail_task() {
    local hive_id="$1"
    local task_id="$2"
    shift 2
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    _FAIL_LAST_TASK="$task_id"
    return ${SUPERPOS_ERR_CONFLICT:-6}
}

conflict_terminal_task=$(jq -n '{"id":"other-type-fail-409","type":"triage","payload":{}}')
echo "$conflict_terminal_task" > "${PENDING_DIR}/other-type-fail-409.json"

_lifecycle_retry_pending_handlers

assert_eq "$_FAIL_CALLS" "1" "retry sweep fail-409: fail attempted"
assert_eq "$([ -f "${PENDING_DIR}/other-type-fail-409.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep fail-409: pending file removed after reconciliation"
trace_fail_409=$(cat "${_tmp_dir}/traces/other-type-fail-409.json" 2>/dev/null || echo "")
assert_contains "$trace_fail_409" "capability_missing" "retry sweep fail-409: trace persisted on reconciliation"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — handles claim failure then succeeds on next sweep
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — claim fails then succeeds on next sweep"

_setup
task_json=$(_make_pr_comment_task "retry-multi" 800 "org/multi" 80 "Multi retry")
echo "$task_json" > "${PENDING_DIR}/retry-multi.json"

# First sweep: claim fails (network error)
_CLAIM_RC=1
_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry sweep round 1: claim attempted"
assert_eq "$_COMPLETE_CALLS" "0" "retry sweep round 1: not completed (claim failed)"
assert_eq "$([ -f "${PENDING_DIR}/retry-multi.json" ] && echo exists || echo removed)" "exists" \
    "retry sweep round 1: pending file preserved for next attempt"

# Second sweep: claim succeeds
_CLAIM_CALLS=0
_CLAIM_RC=0
_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry sweep round 2: claim attempted again"
assert_eq "$_COMPLETE_CALLS" "1" "retry sweep round 2: task completed"
assert_eq "$([ -f "${PENDING_DIR}/retry-multi.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep round 2: pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — already-claimed task (409) cleaned up
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — already-claimed task quarantines pending"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
task_json=$(_make_pr_comment_task "retry-409" 900 "org/conflict" 90 "Already claimed")
echo "$task_json" > "${PENDING_DIR}/retry-409.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry sweep 409: claim attempted"
assert_eq "$_COMPLETE_CALLS" "0" "retry sweep 409: complete not called"
assert_eq "$_FAIL_CALLS" "0" "retry sweep 409: fail not called"
assert_eq "$([ -f "${PENDING_DIR}/retry-409.json" ] && echo exists || echo moved)" "moved" \
    "retry sweep 409: pending file moved from active pending"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/retry-409.json" ] && echo quarantined || echo missing)" "quarantined" \
    "retry sweep 409: pending file quarantined for recovery"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — empty pending directory is a no-op
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — empty pending dir is safe no-op"

_setup
# Ensure pending dir is empty
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true

set +e
_lifecycle_retry_pending_handlers
rc=$?
set -e

assert_eq "$rc" "0" "retry sweep: returns 0 on empty dir"
assert_eq "$_CLAIM_CALLS" "0" "retry sweep: no claims on empty dir"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — multiple stuck tasks processed in one sweep
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — processes multiple stuck tasks"

_setup
_CLAIM_RC=0

task1=$(_make_pr_comment_task "multi-1" 1001 "org/multi" 1 "First stuck")
task2=$(_make_pr_comment_task "multi-2" 1002 "org/multi" 2 "Second stuck")
echo "$task1" > "${PENDING_DIR}/multi-1.json"
echo "$task2" > "${PENDING_DIR}/multi-2.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "2" "retry sweep: both tasks claimed"
assert_eq "$_COMPLETE_CALLS" "2" "retry sweep: both tasks completed"
assert_eq "$([ -f "${PENDING_DIR}/multi-1.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep: first pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/multi-2.json" ] && echo exists || echo removed)" "removed" \
    "retry sweep: second pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# Terminal update failure — preserves pending for retry
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — complete API failure preserves pending file for retry"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-comp-fail" 1100 "org/comp-fail" 11 "Complete will fail")
echo "$task_json" > "${PENDING_DIR}/lc-comp-fail.json"

# Mock: claim succeeds, complete FAILS
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    return 1  # simulate API failure
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-comp-fail"
rc=$?
set -e

assert_eq "$rc" "1" "complete-fail: returns 1 for retry"
assert_eq "$_CLAIM_CALLS" "1" "complete-fail: claim called"
assert_eq "$_COMPLETE_CALLS" "1" "complete-fail: complete attempted"
assert_eq "$([ -f "${PENDING_DIR}/lc-comp-fail.json" ] && echo exists || echo removed)" "exists" \
    "complete-fail: pending file preserved for retry"
assert_eq "$([ -d "${_tmp_dir}/traces" ] && [ -f "${_tmp_dir}/traces/lc-comp-fail.json" ] && echo exists || echo missing)" "missing" \
    "complete-fail: no trace written on failure"


describe "Lifecycle — fail API failure preserves pending file for retry"

_setup
_CLAIM_RC=0
export SUPERPOS_WAKE_ENABLED="true"
export SUPERPOS_WAKE_SESSION="test-session"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

task_json=$(_make_pr_comment_task "lc-fail-fail" 1200 "org/fail-fail" 12 "Fail will fail")
echo "$task_json" > "${PENDING_DIR}/lc-fail-fail.json"

# Mock: claim succeeds, delivery fails, fail API also fails
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 1  # simulate API failure
}
_wake_send() { return 1; }

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-fail-fail"
rc=$?
set -e

assert_eq "$rc" "1" "fail-fail: returns 1 for retry"
assert_eq "$_FAIL_CALLS" "1" "fail-fail: fail attempted"
assert_eq "$([ -f "${PENDING_DIR}/lc-fail-fail.json" ] && echo exists || echo removed)" "exists" \
    "fail-fail: pending file preserved for retry"


describe "Lifecycle — successful complete still cleans up normally"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-ok" 1300 "org/ok" 13 "Normal success")
echo "$task_json" > "${PENDING_DIR}/lc-ok.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-ok"
rc=$?
set -e

assert_eq "$rc" "0" "success: returns 0"
assert_eq "$_COMPLETE_CALLS" "1" "success: complete called"
assert_eq "$([ -f "${PENDING_DIR}/lc-ok.json" ] && echo exists || echo removed)" "removed" \
    "success: pending file cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/lc-ok.json" ] && echo exists || echo missing)" "exists" \
    "success: trace file written"


# ═══════════════════════════════════════════════════════════════
# Claim-conflict safety: pending preserved for retry after
# partial processing by another agent
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — claim-conflict preserves pending so claimant can retry"

_setup

# Simulate: first call claims and processes but completion API fails (rc=1).
# Result artifact is saved. Second call finds the artifact and retries
# the API call directly (no re-claim needed). Task is unstuck.
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}

_comp_call=0
superpos_complete_task() {
    _comp_call=$((_comp_call + 1))
    _COMPLETE_CALLS=$_comp_call
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    if [[ $_comp_call -eq 1 ]]; then
        return 1  # first: API failure
    fi
    return 0  # subsequent: success
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "lc-strand" 2000 "org/strand" 99 "Strand scenario")
echo "$task_json" > "${PENDING_DIR}/lc-strand.json"

# Round 1: claim succeeds, completion API fails → result artifact saved
set +e
_lifecycle_process_webhook_handler "$task_json" "lc-strand"
r1=$?
set -e
assert_eq "$r1" "1" "strand-r1: returns 1 (transient failure)"
assert_eq "$([ -f "${PENDING_DIR}/lc-strand.json" ] && echo exists || echo removed)" "exists" \
    "strand-r1: pending file preserved after API failure"
assert_eq "$([ -f "${PENDING_DIR}/lc-strand.result.json" ] && echo exists || echo missing)" "exists" \
    "strand-r1: result artifact saved for retry"

# Round 2: result artifact found → completion retried → succeeds
set +e
_lifecycle_process_webhook_handler "$task_json" "lc-strand"
r2=$?
set -e
assert_eq "$r2" "0" "strand-r2: returns 0 (artifact retry succeeded)"
assert_eq "$_CLAIM_CALLS" "1" "strand-r2: claim only called once (round 1), not re-entered"
assert_eq "$([ -f "${PENDING_DIR}/lc-strand.json" ] && echo exists || echo removed)" "removed" \
    "strand-r2: pending file cleaned up after successful retry"
assert_eq "$([ -f "${PENDING_DIR}/lc-strand.result.json" ] && echo exists || echo missing)" "missing" \
    "strand-r2: result artifact cleaned up after successful retry"


describe "Lifecycle — conflict from different agent quarantines pending"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# No result artifact, no .claimed marker → uncertain ownership
task_json=$(_make_pr_comment_task "lc-other-agent" 2100 "org/other" 21 "Other agent owns this")
echo "$task_json" > "${PENDING_DIR}/lc-other-agent.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-other-agent"
rc=$?
set -e

assert_eq "$rc" "0" "other-agent: returns 0 (graceful skip)"
assert_eq "$_COMPLETE_CALLS" "0" "other-agent: complete not called"
assert_eq "$([ -f "${PENDING_DIR}/lc-other-agent.json" ] && echo exists || echo moved)" "moved" \
    "other-agent: pending file moved from active pending"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/lc-other-agent.json" ] && echo quarantined || echo missing)" "quarantined" \
    "other-agent: pending file quarantined for recovery"


# ═══════════════════════════════════════════════════════════════
# Result artifact retry: completion API failure saves result
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — completion API failure saves result artifact"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "lc-artifact" 3000 "org/artifact" 30 "Artifact scenario")
echo "$task_json" > "${PENDING_DIR}/lc-artifact.json"

# Mock: claim succeeds, complete FAILS
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return 1  # simulate API failure
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-artifact"
rc=$?
set -e

assert_eq "$rc" "1" "artifact: returns 1 for retry"
assert_eq "$([ -f "${PENDING_DIR}/lc-artifact.json" ] && echo exists || echo removed)" "exists" \
    "artifact: pending file preserved"
assert_eq "$([ -f "${PENDING_DIR}/lc-artifact.result.json" ] && echo exists || echo missing)" "exists" \
    "artifact: result artifact saved on completion API failure"

# Verify result artifact contains valid result
_artifact_content=$(cat "${PENDING_DIR}/lc-artifact.result.json" 2>/dev/null)
assert_contains "$_artifact_content" "lc-artifact" "artifact: result contains task ID"
assert_contains "$_artifact_content" "completed" "artifact: result contains status"


# ═══════════════════════════════════════════════════════════════
# Result artifact retry: retries API without re-claiming
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — result artifact retry skips claim, retries API"

_setup
task_json=$(_make_pr_comment_task "lc-art-retry" 3100 "org/art-retry" 31 "Retry from artifact")
echo "$task_json" > "${PENDING_DIR}/lc-art-retry.json"

# Simulate a saved result artifact from a prior partial processing
echo '{"task_id":"lc-art-retry","status":"completed","summary":"delivered: wake=1 alert=0"}' \
    > "${PENDING_DIR}/lc-art-retry.result.json"

# Mock: complete NOW succeeds
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-art-retry"
rc=$?
set -e

assert_eq "$rc" "0" "art-retry: returns 0 on success"
assert_eq "$_CLAIM_CALLS" "0" "art-retry: claim NOT called (skipped via artifact)"
assert_eq "$_COMPLETE_CALLS" "1" "art-retry: complete called from artifact"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-retry.json" ] && echo exists || echo removed)" "removed" \
    "art-retry: pending file cleaned up after success"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-retry.result.json" ] && echo exists || echo missing)" "missing" \
    "art-retry: result artifact cleaned up after success"

# Verify trace was written
assert_eq "$([ -f "${_tmp_dir}/traces/lc-art-retry.json" ] && echo exists || echo missing)" "exists" \
    "art-retry: trace file written on artifact retry success"


# ═══════════════════════════════════════════════════════════════
# Result artifact retry: API still failing preserves artifacts
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — result artifact retry still failing preserves both files"

_setup
task_json=$(_make_pr_comment_task "lc-art-still-fail" 3200 "org/still-fail" 32 "Still failing")
echo "$task_json" > "${PENDING_DIR}/lc-art-still-fail.json"
echo '{"task_id":"lc-art-still-fail","status":"completed","summary":"delivered"}' \
    > "${PENDING_DIR}/lc-art-still-fail.result.json"

# Mock: complete still fails
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return 1  # still failing
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-art-still-fail"
rc=$?
set -e

assert_eq "$rc" "1" "art-still-fail: returns 1 for retry"
assert_eq "$_CLAIM_CALLS" "0" "art-still-fail: claim NOT called (artifact path)"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-still-fail.json" ] && echo exists || echo removed)" "exists" \
    "art-still-fail: pending file preserved"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-still-fail.result.json" ] && echo exists || echo missing)" "exists" \
    "art-still-fail: result artifact preserved for next retry"


# ═══════════════════════════════════════════════════════════════
# Result artifact retry: fail status artifact retries fail API
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — fail-status artifact retries fail API, not complete"

_setup
task_json=$(_make_pr_comment_task "lc-art-fail" 3300 "org/art-fail" 33 "Fail artifact")
echo "$task_json" > "${PENDING_DIR}/lc-art-fail.json"
echo '{"task_id":"lc-art-fail","status":"failed","error":"all delivery channels failed"}' \
    > "${PENDING_DIR}/lc-art-fail.result.json"

# Mock: fail_task now succeeds
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    _FAIL_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -e) _FAIL_LAST_ERROR="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-art-fail"
rc=$?
set -e

assert_eq "$rc" "0" "art-fail: returns 0 on success"
assert_eq "$_CLAIM_CALLS" "0" "art-fail: claim NOT called (artifact path)"
assert_eq "$_COMPLETE_CALLS" "0" "art-fail: complete NOT called (status is failed)"
assert_eq "$_FAIL_CALLS" "1" "art-fail: fail called for failed-status artifact"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-fail.result.json" ] && echo exists || echo missing)" "missing" \
    "art-fail: result artifact cleaned up"


# ═══════════════════════════════════════════════════════════════
# State machine: .claimed marker written on successful claim
# ═══════════════════════════════════════════════════════════════

describe "State machine — .claimed marker written on successful claim"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "sm-claim" 4000 "org/sm" 40 "Marker test")
echo "$task_json" > "${PENDING_DIR}/sm-claim.json"

_lifecycle_process_webhook_handler "$task_json" "sm-claim"

assert_eq "$_COMPLETE_CALLS" "1" "sm-claim: task completed"
# After full success, .claimed should be cleaned up along with pending
assert_eq "$([ -f "${PENDING_DIR}/sm-claim.claimed" ] && echo exists || echo removed)" "removed" \
    "sm-claim: .claimed marker cleaned up after success"
assert_eq "$([ -f "${PENDING_DIR}/sm-claim.json" ] && echo exists || echo removed)" "removed" \
    "sm-claim: pending file cleaned up after success"


# ═══════════════════════════════════════════════════════════════
# State machine: .claimed marker survives terminal API failure
# ═══════════════════════════════════════════════════════════════

describe "State machine — .claimed marker survives terminal API failure"

_setup
_CLAIM_RC=0

# Make complete_task fail to simulate terminal API failure
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    return 1  # simulate API failure
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 1  # also fails
}

task_json=$(_make_pr_comment_task "sm-apifail" 4001 "org/sm" 41 "API fail test")
echo "$task_json" > "${PENDING_DIR}/sm-apifail.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-apifail"
rc=$?
set -e

assert_eq "$rc" "1" "sm-apifail: returns 1 on terminal API failure"
# .claimed marker should persist for recovery
assert_eq "$([ -f "${PENDING_DIR}/sm-apifail.claimed" ] && echo exists || echo removed)" "exists" \
    "sm-apifail: .claimed marker preserved for recovery"
# Result artifact should be saved
assert_eq "$([ -f "${PENDING_DIR}/sm-apifail.result.json" ] && echo exists || echo removed)" "exists" \
    "sm-apifail: result artifact saved for retry"


# ═══════════════════════════════════════════════════════════════
# State machine: 409 with .claimed marker → recovery via fail API
# ═══════════════════════════════════════════════════════════════

describe "State machine — 409 with .claimed marker re-processes (crash recovery)"

_setup

# Pre-create .claimed marker (simulates prior successful claim)
echo "sm-409own" > "${PENDING_DIR}/sm-409own.claimed"

_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
task_json=$(_make_pr_comment_task "sm-409own" 4002 "org/sm" 42 "Own 409")
echo "$task_json" > "${PENDING_DIR}/sm-409own.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-409own"
rc=$?
set -e

assert_eq "$rc" "0" "sm-409own: returns 0 (recovery succeeded)"
# P1 fix: re-processes instead of force-failing — task should be completed, not failed
assert_eq "$_COMPLETE_CALLS" "1" "sm-409own: complete called (re-processed successfully)"
assert_eq "$_FAIL_CALLS" "0" "sm-409own: fail NOT called (no longer force-fails)"
# Both markers should be cleaned up
assert_eq "$([ -f "${PENDING_DIR}/sm-409own.claimed" ] && echo exists || echo removed)" "removed" \
    "sm-409own: .claimed marker removed after recovery"
assert_eq "$([ -f "${PENDING_DIR}/sm-409own.json" ] && echo exists || echo removed)" "removed" \
    "sm-409own: pending file removed after recovery"


# ═══════════════════════════════════════════════════════════════
# State machine: 409 without .claimed marker → foreign claim
# ═══════════════════════════════════════════════════════════════

describe "State machine — 409 without .claimed marker quarantines pending"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
task_json=$(_make_pr_comment_task "sm-409for" 4003 "org/sm" 43 "Foreign 409")
echo "$task_json" > "${PENDING_DIR}/sm-409for.json"
# No .claimed marker — uncertain ownership

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-409for"
rc=$?
set -e

assert_eq "$rc" "0" "sm-409for: returns 0 (graceful skip)"
assert_eq "$_FAIL_CALLS" "0" "sm-409for: fail NOT called (uncertain ownership)"
assert_eq "$_COMPLETE_CALLS" "0" "sm-409for: complete NOT called"
assert_eq "$([ -f "${PENDING_DIR}/sm-409for.json" ] && echo exists || echo moved)" "moved" \
    "sm-409for: pending file moved from active pending"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/sm-409for.json" ] && echo quarantined || echo missing)" "quarantined" \
    "sm-409for: pending file quarantined for recovery"


# ═══════════════════════════════════════════════════════════════
# State machine: full round-trip claim → fail API → artifact → retry
# ═══════════════════════════════════════════════════════════════

describe "State machine — full round-trip: claim → terminal fail → artifact retry"

_setup

# Phase 1: claim succeeds, terminal API fails → artifact saved
_api_fail_count=0
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    _api_fail_count=$((_api_fail_count + 1))
    if [[ $_api_fail_count -le 1 ]]; then
        return 1  # first attempt fails
    fi
    return 0  # subsequent attempts succeed
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "sm-round" 4004 "org/sm" 44 "Round trip")
echo "$task_json" > "${PENDING_DIR}/sm-round.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-round"
rc1=$?
set -e

assert_eq "$rc1" "1" "sm-round phase1: returns 1 (terminal API failed)"
assert_eq "$([ -f "${PENDING_DIR}/sm-round.result.json" ] && echo exists || echo removed)" "exists" \
    "sm-round phase1: result artifact created"
assert_eq "$([ -f "${PENDING_DIR}/sm-round.claimed" ] && echo exists || echo removed)" "exists" \
    "sm-round phase1: .claimed marker preserved"

# Phase 2: retry picks up artifact, API succeeds this time
set +e
_lifecycle_process_webhook_handler "$task_json" "sm-round"
rc2=$?
set -e

assert_eq "$rc2" "0" "sm-round phase2: returns 0 (artifact retry succeeded)"
assert_eq "$([ -f "${PENDING_DIR}/sm-round.result.json" ] && echo exists || echo removed)" "removed" \
    "sm-round phase2: result artifact cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/sm-round.json" ] && echo exists || echo removed)" "removed" \
    "sm-round phase2: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/sm-round.claimed" ] && echo exists || echo removed)" "removed" \
    "sm-round phase2: .claimed marker cleaned up"



# ═══════════════════════════════════════════════════════════════
# .claimed recovery — API error preserves markers
# ═══════════════════════════════════════════════════════════════

describe "State machine — 409 with .claimed marker: re-processes even when fail API would error"

_setup

echo "sm-release-err" > "${PENDING_DIR}/sm-release-err.claimed"

# P1 fix: claim returns 409, but re-processing falls through to Step 2.
# fail_task is no longer called in the 409+.claimed path — complete is called.
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return $SUPERPOS_ERR_CONFLICT
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 1
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}

task_json=$(_make_pr_comment_task "sm-release-err" 5000 "org/sm" 50 "Release error")
echo "$task_json" > "${PENDING_DIR}/sm-release-err.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-release-err"
rc=$?
set -e

assert_eq "$rc" "0" "release-err: returns 0 (re-processed successfully)"
assert_eq "$_FAIL_CALLS" "0" "release-err: fail API NOT called (re-processed instead)"
assert_eq "$_COMPLETE_CALLS" "1" "release-err: complete called (task re-processed)"
assert_eq "$([ -f "${PENDING_DIR}/sm-release-err.claimed" ] && echo exists || echo removed)" "removed" \
    "release-err: .claimed marker cleaned up after re-processing"
assert_eq "$([ -f "${PENDING_DIR}/sm-release-err.json" ] && echo exists || echo removed)" "removed" \
    "release-err: pending file cleaned up after re-processing"


# ═══════════════════════════════════════════════════════════════
# .claimed recovery — re-processes instead of release attempts
# ═══════════════════════════════════════════════════════════════

describe "State machine — 409 with .claimed marker: re-processes and completes"

_setup

echo "sm-release-409" > "${PENDING_DIR}/sm-release-409.claimed"

superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return $SUPERPOS_ERR_CONFLICT
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    _COMPLETE_LAST_TASK="$2"
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}

task_json=$(_make_pr_comment_task "sm-release-409" 5001 "org/sm" 51 "Release 409")
echo "$task_json" > "${PENDING_DIR}/sm-release-409.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "sm-release-409"
rc=$?
set -e

assert_eq "$rc" "0" "release-409: returns 0 (re-processed)"
assert_eq "$_FAIL_CALLS" "0" "release-409: fail NOT called (re-processed instead)"
assert_eq "$_COMPLETE_CALLS" "1" "release-409: complete called (task re-processed)"
assert_eq "$([ -f "${PENDING_DIR}/sm-release-409.claimed" ] && echo exists || echo removed)" "removed" \
    "release-409: .claimed marker cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/sm-release-409.json" ] && echo exists || echo removed)" "removed" \
    "release-409: pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# Terminal retry 409 = reconciled success
# ═══════════════════════════════════════════════════════════════

describe "Lifecycle — result artifact retry 409 = reconciled success"

_setup
task_json=$(_make_pr_comment_task "lc-art-409" 5100 "org/art-409" 52 "Art retry 409")
echo "$task_json" > "${PENDING_DIR}/lc-art-409.json"
echo "lc-art-409" > "${PENDING_DIR}/lc-art-409.claimed"
echo '{"task_id":"lc-art-409","status":"completed","summary":"delivered"}' \
    > "${PENDING_DIR}/lc-art-409.result.json"

superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return $SUPERPOS_ERR_CONFLICT  # 409 = already completed remotely
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

set +e
_lifecycle_process_webhook_handler "$task_json" "lc-art-409"
rc=$?
set -e

assert_eq "$rc" "0" "art-409: returns 0 (reconciled)"
assert_eq "$_CLAIM_CALLS" "0" "art-409: claim NOT called (artifact path)"
assert_eq "$_COMPLETE_CALLS" "1" "art-409: complete attempted"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-409.result.json" ] && echo exists || echo missing)" "missing" \
    "art-409: result artifact cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-409.json" ] && echo exists || echo removed)" "removed" \
    "art-409: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/lc-art-409.claimed" ] && echo exists || echo removed)" "removed" \
    "art-409: .claimed marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/lc-art-409.json" ] && echo exists || echo missing)" "exists" \
    "art-409: trace written for reconciled task"


# ═══════════════════════════════════════════════════════════════
# Quarantine — quarantined files not picked up by retry sweep
# ═══════════════════════════════════════════════════════════════

describe "Quarantine — retry sweep does not process quarantined files"

_setup
_CLAIM_RC=0

# Clear all pending files from prior tests
rm -f "${PENDING_DIR}"/*.json "${PENDING_DIR}"/*.claimed "${PENDING_DIR}"/*.result.json 2>/dev/null || true

# Place a task in quarantine (simulating a prior uncertain 409)
mkdir -p "${PENDING_DIR}/quarantine"
quarantine_task=$(_make_pr_comment_task "q-old" 9000 "org/quarantined" 90 "Quarantined task")
echo "$quarantine_task" > "${PENDING_DIR}/quarantine/q-old.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "0" "quarantine: claim NOT called for quarantined file"
assert_eq "$_COMPLETE_CALLS" "0" "quarantine: complete NOT called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/q-old.json" ] && echo exists || echo missing)" "exists" \
    "quarantine: file remains in quarantine untouched"


# ═══════════════════════════════════════════════════════════════
# Wake metric signal: _lifecycle_wake_delivered
# ═══════════════════════════════════════════════════════════════

describe "Wake metric — successful delivery sets _lifecycle_wake_delivered=1"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "wm-ok" 10001 "org/wm" 101 "Wake metric success")
echo "$task_json" > "${PENDING_DIR}/wm-ok.json"

_lifecycle_process_webhook_handler "$task_json" "wm-ok"

assert_eq "${_lifecycle_wake_delivered}" "1" "wake metric: set to 1 on successful delivery"


describe "Wake metric — deduplicated wake does not set _lifecycle_wake_delivered"

_setup
_CLAIM_RC=0
task_json=$(_make_pr_comment_task "wm-dedup" 10002 "org/wm" 102 "Wake metric dedup")

# Pre-mark as seen
_wake_mark_seen "wm-dedup:10002"

echo "$task_json" > "${PENDING_DIR}/wm-dedup.json"

_lifecycle_process_webhook_handler "$task_json" "wm-dedup"

assert_eq "${_lifecycle_wake_delivered}" "0" "wake metric: stays 0 on dedup"


describe "Wake metric — filtered (non-PR) task does not set _lifecycle_wake_delivered"

_setup
_CLAIM_RC=0
task_json=$(_make_push_task "wm-filter")
echo "$task_json" > "${PENDING_DIR}/wm-filter.json"

_lifecycle_process_webhook_handler "$task_json" "wm-filter"

assert_eq "${_lifecycle_wake_delivered}" "0" "wake metric: stays 0 on filtered task"


describe "Wake metric — delivery failure does not set _lifecycle_wake_delivered"

_setup
_CLAIM_RC=0
export SUPERPOS_WAKE_ENABLED="true"
export SUPERPOS_WAKE_SESSION="test-session"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

# Re-apply mocks
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -e) _FAIL_LAST_ERROR="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
# Mock wake delivery to FAIL
_wake_send() { return 1; }

task_json=$(_make_pr_comment_task "wm-fail" 10004 "org/wm" 104 "Wake metric fail")
echo "$task_json" > "${PENDING_DIR}/wm-fail.json"

_lifecycle_process_webhook_handler "$task_json" "wm-fail"

assert_eq "${_lifecycle_wake_delivered}" "0" "wake metric: stays 0 on delivery failure"
assert_eq "$_FAIL_CALLS" "1" "wake metric fail: task marked as failed"


describe "Wake metric — no channels enabled does not set _lifecycle_wake_delivered"

_setup
_CLAIM_RC=0
export SUPERPOS_WAKE_ENABLED="false"
export SUPERPOS_WAKE_ALERT_ENABLED="false"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

# Re-apply mocks
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    _CLAIM_LAST_TASK="$2"
    return 0
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "wm-nochan" 10005 "org/wm" 105 "Wake metric no channels")
echo "$task_json" > "${PENDING_DIR}/wm-nochan.json"

_lifecycle_process_webhook_handler "$task_json" "wm-nochan"

assert_eq "${_lifecycle_wake_delivered}" "0" "wake metric: stays 0 with no channels enabled"
assert_eq "$_COMPLETE_CALLS" "1" "wake metric no-chan: task still completed"


# ═══════════════════════════════════════════════════════════════
# Retry sweep — wakes_sent incremented on successful delivery
# ═══════════════════════════════════════════════════════════════

describe "Retry sweep — increments _stats_wakes_sent on successful delivery"

_setup
_CLAIM_RC=0
_stats_wakes_sent=0
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
task_json=$(_make_pr_comment_task "retry-wake" 11001 "org/retry-wake" 111 "Retry wake count")

echo "$task_json" > "${PENDING_DIR}/retry-wake.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "1" "retry-wake: claim called"
assert_eq "$_COMPLETE_CALLS" "1" "retry-wake: task completed"
assert_eq "${_stats_wakes_sent}" "1" "retry-wake: _stats_wakes_sent incremented to 1"
assert_eq "$([ -f "${PENDING_DIR}/retry-wake.json" ] && echo exists || echo removed)" "removed" \
    "retry-wake: pending file cleaned up"


describe "Retry sweep — does not increment _stats_wakes_sent on filtered task"

_setup
_CLAIM_RC=0
_stats_wakes_sent=0
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
task_json=$(_make_push_task "retry-nocount")

echo "$task_json" > "${PENDING_DIR}/retry-nocount.json"

_lifecycle_retry_pending_handlers

assert_eq "$_COMPLETE_CALLS" "1" "retry-nocount: task completed"
assert_eq "${_stats_wakes_sent}" "0" "retry-nocount: _stats_wakes_sent stays 0 for filtered task"


describe "Retry sweep — increments _stats_wakes_sent for each delivered task in batch"

_setup
_CLAIM_RC=0
_stats_wakes_sent=0
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true

task1=$(_make_pr_comment_task "retry-batch-1" 11003 "org/batch" 1 "Batch wake 1")
task2=$(_make_pr_comment_task "retry-batch-2" 11004 "org/batch" 2 "Batch wake 2")
echo "$task1" > "${PENDING_DIR}/retry-batch-1.json"
echo "$task2" > "${PENDING_DIR}/retry-batch-2.json"

_lifecycle_retry_pending_handlers

assert_eq "$_CLAIM_CALLS" "2" "retry-batch: both tasks claimed"
assert_eq "$_COMPLETE_CALLS" "2" "retry-batch: both tasks completed"
assert_eq "${_stats_wakes_sent}" "2" "retry-batch: _stats_wakes_sent incremented for each delivery"


describe "Retry sweep — does not increment _stats_wakes_sent on claim failure"

_setup
_CLAIM_RC=1
_stats_wakes_sent=0
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
task_json=$(_make_pr_comment_task "retry-claimfail" 11005 "org/claimfail" 5 "Claim fails")

echo "$task_json" > "${PENDING_DIR}/retry-claimfail.json"

_lifecycle_retry_pending_handlers

assert_eq "${_stats_wakes_sent}" "0" "retry-claimfail: _stats_wakes_sent stays 0 on claim failure"


describe "Retry sweep — non-webhook task does not inherit stale wake-delivered flag"

_setup
_CLAIM_RC=0
_stats_wakes_sent=0
rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true

task1=$(_make_pr_comment_task "retry-mixed-webhook" 11006 "org/mixed" 6 "Webhook first")
task2=$(jq -n '{"id":"retry-mixed-unknown","type":"triage","payload":{}}')
echo "$task1" > "${PENDING_DIR}/retry-mixed-webhook.json"
echo "$task2" > "${PENDING_DIR}/retry-mixed-unknown.json"

_lifecycle_retry_pending_handlers

assert_eq "${_stats_wakes_sent}" "1" "retry-mixed: wakes_sent increments only for webhook delivery"


# ═══════════════════════════════════════════════════════════════
# P1: 409+.claimed crash recovery — re-processes, delivers wake
# ═══════════════════════════════════════════════════════════════

describe "P1 — 409+.claimed re-processes and delivers wake (no reminder loss)"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Pre-create .claimed marker (simulates crash after claim, before processing)
echo "p1-recover" > "${PENDING_DIR}/p1-recover.claimed"

task_json=$(_make_pr_comment_task "p1-recover" 20001 "org/p1" 201 "Crash recovery wake")
echo "$task_json" > "${PENDING_DIR}/p1-recover.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "p1-recover"
rc=$?
set -e

assert_eq "$rc" "0" "p1-recover: returns 0"
assert_eq "$_COMPLETE_CALLS" "1" "p1-recover: task completed (wake delivered)"
assert_eq "$_FAIL_CALLS" "0" "p1-recover: fail NOT called (no force-fail)"
assert_eq "${_lifecycle_wake_delivered}" "1" "p1-recover: wake was delivered"
assert_contains "$_COMPLETE_LAST_RESULT" "delivered" "p1-recover: result confirms delivery"
assert_eq "$([ -f "${PENDING_DIR}/p1-recover.claimed" ] && echo exists || echo removed)" "removed" \
    "p1-recover: .claimed marker cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/p1-recover.json" ] && echo exists || echo removed)" "removed" \
    "p1-recover: pending file cleaned up"


describe "P1 — 409+.claimed re-processes; delivery failure still marks task failed"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
export SUPERPOS_WAKE_ENABLED="true"
export SUPERPOS_WAKE_SESSION="test-session"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

# Pre-create .claimed marker
echo "p1-delfail" > "${PENDING_DIR}/p1-delfail.claimed"

# Mock: claim 409, wake delivery fails, fail API succeeds
superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return $SUPERPOS_ERR_CONFLICT
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -r) _COMPLETE_LAST_RESULT="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in -e) _FAIL_LAST_ERROR="$2"; shift 2 ;; *) shift ;; esac
    done
    return 0
}
_wake_send() { return 1; }

task_json=$(_make_pr_comment_task "p1-delfail" 20002 "org/p1" 202 "Delivery will fail")
echo "$task_json" > "${PENDING_DIR}/p1-delfail.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "p1-delfail"
rc=$?
set -e

assert_eq "$rc" "0" "p1-delfail: returns 0 (fail-soft)"
assert_eq "$_FAIL_CALLS" "1" "p1-delfail: fail called (delivery failed)"
assert_eq "$_COMPLETE_CALLS" "0" "p1-delfail: complete NOT called (delivery failed)"
assert_eq "${_lifecycle_wake_delivered}" "0" "p1-delfail: wake not delivered"
assert_eq "$([ -f "${PENDING_DIR}/p1-delfail.claimed" ] && echo exists || echo removed)" "removed" \
    "p1-delfail: .claimed marker cleaned up"


describe "P1 — 409+.claimed with terminal API failure saves artifact for retry"

_setup

echo "p1-apifail" > "${PENDING_DIR}/p1-apifail.claimed"

superpos_claim_task() {
    _CLAIM_CALLS=$((_CLAIM_CALLS + 1))
    return $SUPERPOS_ERR_CONFLICT
}
superpos_complete_task() {
    _COMPLETE_CALLS=$((_COMPLETE_CALLS + 1))
    return 1  # terminal API fails
}
superpos_fail_task() {
    _FAIL_CALLS=$((_FAIL_CALLS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "p1-apifail" 20003 "org/p1" 203 "API will fail")
echo "$task_json" > "${PENDING_DIR}/p1-apifail.json"

set +e
_lifecycle_process_webhook_handler "$task_json" "p1-apifail"
rc=$?
set -e

assert_eq "$rc" "1" "p1-apifail: returns 1 (retryable)"
assert_eq "$([ -f "${PENDING_DIR}/p1-apifail.result.json" ] && echo exists || echo missing)" "exists" \
    "p1-apifail: result artifact saved for retry"
assert_eq "$([ -f "${PENDING_DIR}/p1-apifail.claimed" ] && echo exists || echo missing)" "exists" \
    "p1-apifail: .claimed marker preserved for next retry"


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════

test_summary
