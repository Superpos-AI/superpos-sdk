#!/usr/bin/env bash
# test_reminder_lifecycle.sh — Tests for reminder task lifecycle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

# Mock state directory — used for subshell-safe counters.
# When production code captures stdout via $(), the function runs in a
# subshell, so variable updates are lost.  File-based state survives.
_MOCK_DIR=""

_CLAIM_RC=0
_COMPLETE_RC=0
_COMPLETE_BODY=""
_FAIL_RC=0
_FAIL_BODY=""
_SEND_RC=0

# Read a mock counter from file (subshell-safe).
_mock_read() { cat "${_MOCK_DIR}/${1}" 2>/dev/null || echo ""; }
_mock_read_n() { local v; v=$(cat "${_MOCK_DIR}/${1}" 2>/dev/null) || v=0; echo "$v"; }

_setup() {
    export SUPERPOS_CONFIG_DIR="$_tmp_dir"
    export SUPERPOS_HIVE_ID="hive-test-reminder"
    export SUPERPOS_AGENT_ID="test-agent-reminder"
    export SUPERPOS_CLAIM_TTL=900
    export PENDING_DIR="${_tmp_dir}/pending"

    mkdir -p "$PENDING_DIR"
    rm -f "${PENDING_DIR}"/*.json 2>/dev/null || true
    rm -f "${PENDING_DIR}"/*.claimed 2>/dev/null || true
    rm -f "${PENDING_DIR}"/*.delivered 2>/dev/null || true
    rm -f "${PENDING_DIR}"/*.retry_count 2>/dev/null || true
    rm -f "${PENDING_DIR}"/*.retry_after 2>/dev/null || true
    rm -rf "${PENDING_DIR}/quarantine" 2>/dev/null || true
    rm -rf "${_tmp_dir}/traces"

    # Reset mock state via files (subshell-safe)
    _MOCK_DIR="${_tmp_dir}/mock"
    rm -rf "$_MOCK_DIR"
    mkdir -p "$_MOCK_DIR"
    echo 0 > "${_MOCK_DIR}/claim_calls"
    echo 0 > "${_MOCK_DIR}/complete_calls"
    echo 0 > "${_MOCK_DIR}/fail_calls"
    echo 0 > "${_MOCK_DIR}/send_calls"

    _CLAIM_RC=0
    _COMPLETE_RC=0
    _COMPLETE_BODY=""
    _FAIL_RC=0
    _FAIL_BODY=""
    _SEND_RC=0
    _TRACE_RC=1
    _TRACE_OUTPUT=""

    source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
    source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

    superpos_claim_task() {
        local n; n=$(cat "${_MOCK_DIR}/claim_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/claim_calls"
        return $_CLAIM_RC
    }

    superpos_complete_task() {
        local task_id="$2"
        shift 2
        local n; n=$(cat "${_MOCK_DIR}/complete_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/complete_calls"
        echo "$task_id" > "${_MOCK_DIR}/complete_last_task"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -r) echo "$2" > "${_MOCK_DIR}/complete_last_result"; shift 2 ;;
                *) shift ;;
            esac
        done
        [[ -n "$_COMPLETE_BODY" ]] && echo "$_COMPLETE_BODY"
        return $_COMPLETE_RC
    }

    superpos_fail_task() {
        local task_id="$2"
        shift 2
        local n; n=$(cat "${_MOCK_DIR}/fail_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/fail_calls"
        echo "$task_id" > "${_MOCK_DIR}/fail_last_task"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -e) echo "$2" > "${_MOCK_DIR}/fail_last_error"; shift 2 ;;
                *) shift ;;
            esac
        done
        [[ -n "$_FAIL_BODY" ]] && echo "$_FAIL_BODY"
        return $_FAIL_RC
    }

    _wake_send_alert() {
        local n; n=$(cat "${_MOCK_DIR}/send_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/send_calls"
        echo "${1:-}" > "${_MOCK_DIR}/send_last_target"
        echo "${2:-}" > "${_MOCK_DIR}/send_last_channel"
        echo "${3:-}" > "${_MOCK_DIR}/send_last_message"
        echo "${4:-}" > "${_MOCK_DIR}/send_last_timeout"
        return $_SEND_RC
    }

    superpos_get_task_trace() {
        if [[ -n "$_TRACE_OUTPUT" ]]; then
            echo "$_TRACE_OUTPUT"
        fi
        return $_TRACE_RC
    }
}

_make_reminder_task() {
    local task_id="${1:-r-1}"
    local channel="${2:-telegram}"
    local target="${3:-12345}"
    local message="${4:-Test reminder}"

    jq -n \
        --arg tid "$task_id" \
        --arg ch "$channel" \
        --arg tgt "$target" \
        --arg msg "$message" \
        '{id:$tid,type:"reminder",payload:{channel:$ch,target:$tgt,message:$msg}}'
}

_make_reminder_task_nested() {
    local task_id="${1:-r-nested-1}"
    local channel="${2:-telegram}"
    local target="${3:-12345}"
    local message="${4:-Nested reminder}"

    jq -n \
        --arg tid "$task_id" \
        --arg ch "$channel" \
        --arg tgt "$target" \
        --arg msg "$message" \
        '{id:$tid,type:"reminder",payload:{task_payload:{channel:$ch,target:$tgt,message:$msg}}}'
}

# Write a JSON .claimed marker matching the production format.
# Arguments: task_id [agent_id]
_write_test_claimed_marker() {
    local task_id="${1:-}"
    local agent_id="${2:-${SUPERPOS_AGENT_ID:-test-agent-reminder}}"
    local ts
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%s')
    jq -n --arg tid "$task_id" --arg agent "$agent_id" --arg ts "$ts" \
        '{"task_id":$tid,"agent_id":$agent,"claimed_at":$ts}' \
        > "${PENDING_DIR}/${task_id}.claimed"
}

describe "Reminder lifecycle — claim + deliver + complete success"

_setup
task_json=$(_make_reminder_task_nested "rem-ok" "telegram" "94650650" "Ship build")
echo "$task_json" > "${PENDING_DIR}/rem-ok.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-ok"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on successful reminder delivery"
assert_eq "$(_mock_read_n claim_calls)" "1" "claim called once"
assert_eq "$(_mock_read_n send_calls)" "1" "message delivery called once"
assert_eq "$(_mock_read send_last_channel)" "telegram" "delivery uses parsed channel"
assert_eq "$(_mock_read send_last_target)" "94650650" "delivery uses parsed target"
assert_eq "$(_mock_read send_last_message)" "Ship build" "delivery uses parsed message"
assert_eq "$(_mock_read_n complete_calls)" "1" "complete called once"
assert_eq "$(_mock_read_n fail_calls)" "0" "fail not called on success"
assert_contains "$(_mock_read complete_last_result)" "completed" "complete result includes status"
assert_eq "$([ -f "${PENDING_DIR}/rem-ok.json" ] && echo exists || echo removed)" "removed" "pending file removed after success"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-ok.json" ] && echo exists || echo missing)" "exists" "trace file written"


describe "Reminder lifecycle — validation failure fails task"

_setup
task_json=$(jq -n '{id:"rem-bad",type:"reminder",payload:{channel:"telegram",message:"No target"}}')
echo "$task_json" > "${PENDING_DIR}/rem-bad.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-bad"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after failing invalid reminder"
assert_eq "$(_mock_read_n claim_calls)" "1" "claim still called before validation"
assert_eq "$(_mock_read_n send_calls)" "0" "delivery not attempted for invalid payload"
assert_eq "$(_mock_read_n complete_calls)" "0" "complete not called on validation failure"
assert_eq "$(_mock_read_n fail_calls)" "1" "fail called on validation failure"
assert_contains "$(_mock_read fail_last_error)" "validation failed" "fail payload includes validation error"
assert_eq "$([ -f "${PENDING_DIR}/rem-bad.json" ] && echo exists || echo removed)" "removed" "pending file removed after validation failure"


describe "Reminder lifecycle — delivery failure fails task"

_setup
_SEND_RC=1
task_json=$(_make_reminder_task "rem-send-fail" "telegram" "777" "Delivery should fail")
echo "$task_json" > "${PENDING_DIR}/rem-send-fail.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-send-fail"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after failing delivery"
assert_eq "$(_mock_read_n send_calls)" "1" "delivery attempted once"
assert_eq "$(_mock_read_n complete_calls)" "0" "complete not called when delivery fails"
assert_eq "$(_mock_read_n fail_calls)" "1" "fail called when delivery fails"
assert_contains "$(_mock_read fail_last_error)" "delivery failed" "fail payload includes delivery error"


describe "Retry sweep — processes reminder and explicitly fails unsupported types"

_setup
reminder_task=$(_make_reminder_task "rem-retry" "telegram" "999" "Retry reminder")
other_task=$(jq -n '{id:"other-1",type:"code_review",payload:{}}')

echo "$reminder_task" > "${PENDING_DIR}/rem-retry.json"
echo "$other_task" > "${PENDING_DIR}/other-1.json"

_lifecycle_retry_pending_handlers

assert_eq "$(_mock_read_n claim_calls)" "2" "retry sweep claims reminder and unsupported task"
assert_eq "$(_mock_read_n complete_calls)" "1" "retry sweep completes reminder task"
assert_eq "$(_mock_read_n fail_calls)" "1" "retry sweep fails unsupported task with explicit response"
assert_eq "$([ -f "${PENDING_DIR}/rem-retry.json" ] && echo exists || echo removed)" "removed" "retry sweep removes reminder pending file"
assert_eq "$([ -f "${PENDING_DIR}/other-1.json" ] && echo exists || echo removed)" "removed" "retry sweep removes unsupported pending file after fail"


# ═══════════════════════════════════════════════════════════════
# Crash recovery: 409 + .claimed → re-process and deliver
# ═══════════════════════════════════════════════════════════════

describe "Crash recovery — 409 + verified .claimed re-processes reminder (no drop)"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Pre-create JSON .claimed marker with matching ownership evidence
_write_test_claimed_marker "rem-crash"

task_json=$(_make_reminder_task "rem-crash" "telegram" "94650650" "Crash recovery reminder")
echo "$task_json" > "${PENDING_DIR}/rem-crash.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-crash"
rc=$?
set -e

assert_eq "$rc" "0" "crash-recovery: returns 0"
assert_eq "$(_mock_read_n send_calls)" "1" "crash-recovery: delivery attempted (re-processed)"
assert_eq "$(_mock_read send_last_target)" "94650650" "crash-recovery: correct target"
assert_eq "$(_mock_read send_last_channel)" "telegram" "crash-recovery: correct channel"
assert_eq "$(_mock_read send_last_message)" "Crash recovery reminder" "crash-recovery: correct message"
assert_eq "$(_mock_read_n complete_calls)" "1" "crash-recovery: task completed (not dropped)"
assert_eq "$(_mock_read_n fail_calls)" "0" "crash-recovery: fail NOT called (no force-fail)"
assert_contains "$(_mock_read complete_last_result)" "completed" "crash-recovery: result confirms completion"
assert_contains "$(_mock_read complete_last_result)" "delivered" "crash-recovery: result confirms delivery"
assert_eq "$([ -f "${PENDING_DIR}/rem-crash.claimed" ] && echo exists || echo removed)" "removed" \
    "crash-recovery: .claimed marker cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-crash.json" ] && echo exists || echo removed)" "removed" \
    "crash-recovery: pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# Crash recovery: 409 + .claimed with delivery failure → fails task
# ═══════════════════════════════════════════════════════════════

describe "Crash recovery — 409 + verified .claimed with delivery failure still fails task properly"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
_SEND_RC=1

_write_test_claimed_marker "rem-crash-delfail"

task_json=$(_make_reminder_task "rem-crash-delfail" "telegram" "777" "Will fail delivery")
echo "$task_json" > "${PENDING_DIR}/rem-crash-delfail.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-crash-delfail"
rc=$?
set -e

assert_eq "$rc" "0" "crash-delfail: returns 0 (fail-soft)"
assert_eq "$(_mock_read_n send_calls)" "1" "crash-delfail: delivery attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "crash-delfail: complete NOT called (delivery failed)"
assert_eq "$(_mock_read_n fail_calls)" "1" "crash-delfail: fail called (delivery failure)"
assert_contains "$(_mock_read fail_last_error)" "delivery failed" "crash-delfail: error mentions delivery failure"
assert_eq "$([ -f "${PENDING_DIR}/rem-crash-delfail.claimed" ] && echo exists || echo removed)" "removed" \
    "crash-delfail: .claimed marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# Crash recovery: 409 + .claimed with terminal API failure → artifact saved
# ═══════════════════════════════════════════════════════════════

describe "Crash recovery — 409 + verified .claimed with terminal API failure saves artifact"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

_write_test_claimed_marker "rem-crash-apifail"

# Override complete_task to fail
_COMPLETE_RC=1

task_json=$(_make_reminder_task "rem-crash-apifail" "telegram" "555" "API will fail")
echo "$task_json" > "${PENDING_DIR}/rem-crash-apifail.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-crash-apifail"
rc=$?
set -e

assert_eq "$rc" "1" "crash-apifail: returns 1 (retryable)"
assert_eq "$(_mock_read_n send_calls)" "1" "crash-apifail: delivery was attempted"
assert_eq "$([ -f "${PENDING_DIR}/rem-crash-apifail.result.json" ] && echo exists || echo missing)" "exists" \
    "crash-apifail: result artifact saved for retry"
assert_eq "$([ -f "${PENDING_DIR}/rem-crash-apifail.claimed" ] && echo exists || echo missing)" "exists" \
    "crash-apifail: .claimed marker preserved for next retry"


# ═══════════════════════════════════════════════════════════════
# 409 without .claimed → quarantine (not force-fail)
# ═══════════════════════════════════════════════════════════════

describe "Crash recovery — 409 without .claimed quarantines reminder"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# No .claimed marker — uncertain ownership
task_json=$(_make_reminder_task "rem-foreign" "telegram" "111" "Foreign claim")
echo "$task_json" > "${PENDING_DIR}/rem-foreign.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-foreign"
rc=$?
set -e

assert_eq "$rc" "0" "foreign: returns 0 (graceful skip)"
assert_eq "$(_mock_read_n send_calls)" "0" "foreign: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "foreign: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "0" "foreign: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/rem-foreign.json" ] && echo exists || echo moved)" "moved" \
    "foreign: pending file moved from active"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-foreign.json" ] && echo quarantined || echo missing)" "quarantined" \
    "foreign: pending file quarantined for recovery"


# ═══════════════════════════════════════════════════════════════
# 409 + .claimed but WRONG agent → quarantine (no blind re-delivery)
# ═══════════════════════════════════════════════════════════════

describe "Ownership gate — 409 + .claimed with wrong agent_id quarantines"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Write marker with a different agent_id
_write_test_claimed_marker "rem-wrong-agent" "other-agent-999"

task_json=$(_make_reminder_task "rem-wrong-agent" "telegram" "111" "Wrong agent")
echo "$task_json" > "${PENDING_DIR}/rem-wrong-agent.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-wrong-agent"
rc=$?
set -e

assert_eq "$rc" "0" "wrong-agent: returns 0 (graceful quarantine)"
assert_eq "$(_mock_read_n send_calls)" "0" "wrong-agent: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "wrong-agent: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "0" "wrong-agent: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-wrong-agent.json" ] && echo quarantined || echo missing)" "quarantined" \
    "wrong-agent: pending file quarantined"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-wrong-agent.claimed" ] && echo quarantined || echo missing)" "quarantined" \
    "wrong-agent: .claimed marker quarantined for investigation"


# ═══════════════════════════════════════════════════════════════
# 409 + .claimed but STALE marker → quarantine (no blind re-delivery)
# ═══════════════════════════════════════════════════════════════

describe "Ownership gate — 409 + .claimed with stale marker quarantines"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Write a valid marker (correct agent, correct task_id) then backdate it
_write_test_claimed_marker "rem-stale"
touch -d "2 hours ago" "${PENDING_DIR}/rem-stale.claimed"

task_json=$(_make_reminder_task "rem-stale" "telegram" "222" "Stale marker")
echo "$task_json" > "${PENDING_DIR}/rem-stale.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-stale"
rc=$?
set -e

assert_eq "$rc" "0" "stale: returns 0 (graceful quarantine)"
assert_eq "$(_mock_read_n send_calls)" "0" "stale: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "stale: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "0" "stale: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-stale.json" ] && echo quarantined || echo missing)" "quarantined" \
    "stale: pending file quarantined"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-stale.claimed" ] && echo quarantined || echo missing)" "quarantined" \
    "stale: .claimed marker quarantined"


# ═══════════════════════════════════════════════════════════════
# 409 + legacy plain-text .claimed → quarantine (no structured evidence)
# ═══════════════════════════════════════════════════════════════

describe "Ownership gate — 409 + legacy plain-text .claimed quarantines"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Write old-format plain-text marker (pre-P2)
echo "rem-legacy" > "${PENDING_DIR}/rem-legacy.claimed"

task_json=$(_make_reminder_task "rem-legacy" "telegram" "333" "Legacy marker")
echo "$task_json" > "${PENDING_DIR}/rem-legacy.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-legacy"
rc=$?
set -e

assert_eq "$rc" "0" "legacy: returns 0 (graceful quarantine)"
assert_eq "$(_mock_read_n send_calls)" "0" "legacy: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "legacy: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "0" "legacy: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-legacy.json" ] && echo quarantined || echo missing)" "quarantined" \
    "legacy: pending file quarantined"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-legacy.claimed" ] && echo quarantined || echo missing)" "quarantined" \
    "legacy: .claimed marker quarantined"


# ═══════════════════════════════════════════════════════════════
# 409 + .claimed with mismatched task_id → quarantine
# ═══════════════════════════════════════════════════════════════

describe "Ownership gate — 409 + .claimed with mismatched task_id quarantines"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Write marker for a different task_id
_write_test_claimed_marker "rem-other-task"
mv "${PENDING_DIR}/rem-other-task.claimed" "${PENDING_DIR}/rem-mismatch.claimed"

task_json=$(_make_reminder_task "rem-mismatch" "telegram" "444" "Mismatched task")
echo "$task_json" > "${PENDING_DIR}/rem-mismatch.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-mismatch"
rc=$?
set -e

assert_eq "$rc" "0" "mismatch: returns 0 (graceful quarantine)"
assert_eq "$(_mock_read_n send_calls)" "0" "mismatch: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "mismatch: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "0" "mismatch: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/quarantine/rem-mismatch.json" ] && echo quarantined || echo missing)" "quarantined" \
    "mismatch: pending file quarantined"


# ═══════════════════════════════════════════════════════════════
# Claim network error → retry (return 1), consistent behavior
# ═══════════════════════════════════════════════════════════════

describe "Reminder lifecycle — claim network error returns 1 for retry"

_setup
_CLAIM_RC=1  # generic error (not conflict)
task_json=$(_make_reminder_task "rem-neterr" "telegram" "888" "Network error")
echo "$task_json" > "${PENDING_DIR}/rem-neterr.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-neterr"
rc=$?
set -e

assert_eq "$rc" "1" "neterr: returns 1 on claim network error"
assert_eq "$(_mock_read_n send_calls)" "0" "neterr: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "0" "neterr: complete not called"
assert_eq "$(_mock_read_n fail_calls)" "0" "neterr: fail not called"
assert_eq "$([ -f "${PENDING_DIR}/rem-neterr.json" ] && echo exists || echo removed)" "exists" \
    "neterr: pending file preserved for retry"


# ═══════════════════════════════════════════════════════════════
# Full round-trip: claim → crash → 409+.claimed → re-deliver
# ═══════════════════════════════════════════════════════════════

describe "Crash recovery — full round-trip: claim OK, crash, 409+.claimed re-delivers"

_setup

# Phase 1: claim succeeds, delivery succeeds, complete API fails → artifact saved
# Override complete_task to fail on first call, succeed on subsequent
superpos_complete_task() {
    local task_id="$2"
    shift 2
    local n; n=$(cat "${_MOCK_DIR}/complete_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/complete_calls"
    echo "$task_id" > "${_MOCK_DIR}/complete_last_task"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -r) echo "$2" > "${_MOCK_DIR}/complete_last_result"; shift 2 ;;
            *) shift ;;
        esac
    done
    if [[ $(( n + 1 )) -eq 1 ]]; then
        return 1  # first: API failure
    fi
    return 0  # subsequent: success
}

task_json=$(_make_reminder_task "rem-roundtrip" "telegram" "42" "Round-trip reminder")
echo "$task_json" > "${PENDING_DIR}/rem-roundtrip.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-roundtrip"
r1=$?
set -e

assert_eq "$r1" "1" "roundtrip-r1: returns 1 (terminal API failed)"
assert_eq "$(_mock_read_n send_calls)" "1" "roundtrip-r1: delivery was attempted"
assert_eq "$([ -f "${PENDING_DIR}/rem-roundtrip.result.json" ] && echo exists || echo missing)" "exists" \
    "roundtrip-r1: result artifact saved"
assert_eq "$([ -f "${PENDING_DIR}/rem-roundtrip.claimed" ] && echo exists || echo missing)" "exists" \
    "roundtrip-r1: .claimed marker preserved"

# Phase 2: result artifact found → completion retried → succeeds
set +e
_lifecycle_process_reminder "$task_json" "rem-roundtrip"
r2=$?
set -e

assert_eq "$r2" "0" "roundtrip-r2: returns 0 (artifact retry succeeded)"
assert_eq "$([ -f "${PENDING_DIR}/rem-roundtrip.result.json" ] && echo exists || echo removed)" "removed" \
    "roundtrip-r2: result artifact cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-roundtrip.json" ] && echo exists || echo removed)" "removed" \
    "roundtrip-r2: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-roundtrip.claimed" ] && echo exists || echo removed)" "removed" \
    "roundtrip-r2: .claimed marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# .claimed marker written on successful claim, cleaned on success
# ═══════════════════════════════════════════════════════════════

describe "Reminder — .claimed marker written as JSON on claim, cleaned on success"

_setup
_CLAIM_RC=0
task_json=$(_make_reminder_task "rem-marker" "telegram" "333" "Marker test")
echo "$task_json" > "${PENDING_DIR}/rem-marker.json"

# Override complete_task to capture marker before cleanup
superpos_complete_task() {
    local task_id="$2"
    shift 2
    local n; n=$(cat "${_MOCK_DIR}/complete_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/complete_calls"
    echo "$task_id" > "${_MOCK_DIR}/complete_last_task"
    # Capture marker content while it still exists (before cleanup in Step 5)
    cp "${PENDING_DIR}/rem-marker.claimed" "${_MOCK_DIR}/captured_marker" 2>/dev/null || true
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -r) echo "$2" > "${_MOCK_DIR}/complete_last_result"; shift 2 ;;
            *) shift ;;
        esac
    done
    return 0
}

_lifecycle_process_reminder "$task_json" "rem-marker"

assert_eq "$(_mock_read_n complete_calls)" "1" "marker: task completed"
assert_eq "$([ -f "${PENDING_DIR}/rem-marker.claimed" ] && echo exists || echo removed)" "removed" \
    "marker: .claimed cleaned up after success"
assert_eq "$([ -f "${PENDING_DIR}/rem-marker.json" ] && echo exists || echo removed)" "removed" \
    "marker: pending file cleaned up after success"

# Verify JSON marker format with ownership evidence
_marker_content=$(cat "${_MOCK_DIR}/captured_marker" 2>/dev/null) || _marker_content=""
marker_tid=$(echo "$_marker_content" | jq -r '.task_id // ""' 2>/dev/null) || marker_tid=""
marker_agent=$(echo "$_marker_content" | jq -r '.agent_id // ""' 2>/dev/null) || marker_agent=""
assert_eq "$marker_tid" "rem-marker" "marker: JSON marker contains correct task_id"
assert_eq "$marker_agent" "$SUPERPOS_AGENT_ID" "marker: JSON marker contains correct agent_id"


# ═══════════════════════════════════════════════════════════════
# P2: Duplicate delivery prevention — local trace exists
# Crash after delivery+complete+trace but before cleanup
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — local trace blocks re-delivery on 409+.claimed"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Simulate: prior run completed fully but crashed before cleanup.
# .claimed marker exists (verified), local trace exists.
_write_test_claimed_marker "rem-dup-trace"
mkdir -p "${_tmp_dir}/traces" 2>/dev/null
echo '{"task_id":"rem-dup-trace","status":"completed"}' > "${_tmp_dir}/traces/rem-dup-trace.json"

task_json=$(_make_reminder_task "rem-dup-trace" "telegram" "94650650" "Should NOT re-deliver")
echo "$task_json" > "${PENDING_DIR}/rem-dup-trace.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-trace"
rc=$?
set -e

assert_eq "$rc" "0" "dup-trace: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-trace: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "0" "dup-trace: complete NOT called (already done)"
assert_eq "$(_mock_read_n fail_calls)" "0" "dup-trace: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-trace.json" ] && echo exists || echo removed)" "removed" \
    "dup-trace: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-trace.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-trace: .claimed marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# P2: Duplicate delivery prevention — .delivered marker exists
# Crash after delivery but before local cleanup
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — .delivered marker reconciles without re-send"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Simulate: prior run delivered but crashed before cleanup.
# .claimed and .delivered markers exist, no trace, no .result.json.
_write_test_claimed_marker "rem-dup-delivered"
echo "rem-dup-delivered" > "${PENDING_DIR}/rem-dup-delivered.delivered"

task_json=$(_make_reminder_task "rem-dup-delivered" "telegram" "94650650" "Should NOT re-deliver")
echo "$task_json" > "${PENDING_DIR}/rem-dup-delivered.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-delivered"
rc=$?
set -e

assert_eq "$rc" "0" "dup-delivered: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-delivered: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "1" "dup-delivered: complete called (reconciliation)"
assert_eq "$(_mock_read_n fail_calls)" "0" "dup-delivered: fail NOT called"
assert_contains "$(_mock_read complete_last_result)" "reconciled" "dup-delivered: result mentions reconciliation"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-delivered.json" ] && echo exists || echo removed)" "removed" \
    "dup-delivered: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-delivered.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-delivered: .claimed marker cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-delivered.delivered" ] && echo exists || echo removed)" "removed" \
    "dup-delivered: .delivered marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-dup-delivered.json" ] && echo exists || echo missing)" "exists" \
    "dup-delivered: trace written on reconciliation"


# ═══════════════════════════════════════════════════════════════
# P2: Duplicate prevention — .delivered marker with API failure
# Reconciliation API fails → saves artifact (fail-soft)
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — .delivered reconciliation API failure saves artifact"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

_write_test_claimed_marker "rem-dup-apifail"
echo "rem-dup-apifail" > "${PENDING_DIR}/rem-dup-apifail.delivered"

# Override complete_task to fail
_COMPLETE_RC=1

task_json=$(_make_reminder_task "rem-dup-apifail" "telegram" "555" "API will fail")
echo "$task_json" > "${PENDING_DIR}/rem-dup-apifail.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-apifail"
rc=$?
set -e

assert_eq "$rc" "1" "dup-apifail: returns 1 (retryable)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-apifail: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "1" "dup-apifail: complete attempted (reconciliation)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-apifail.result.json" ] && echo exists || echo missing)" "exists" \
    "dup-apifail: result artifact saved for retry"


# ═══════════════════════════════════════════════════════════════
# P2: Remote reconciliation prevents duplicate when local evidence missing
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — remote trace terminal blocks re-delivery"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Simulate: prior run delivered+completed remotely, but no local evidence
# (.delivered not written or lost). Remote trace shows completed.
_write_test_claimed_marker "rem-dup-remote"

# Mock remote trace to return completed status
_TRACE_RC=0
_TRACE_OUTPUT='{"data":{"task_id":"rem-dup-remote","status":"completed"}}'
superpos_get_task_trace() {
    if [[ -n "$_TRACE_OUTPUT" ]]; then
        echo "$_TRACE_OUTPUT"
    fi
    return $_TRACE_RC
}

task_json=$(_make_reminder_task "rem-dup-remote" "telegram" "94650650" "Should NOT re-deliver")
echo "$task_json" > "${PENDING_DIR}/rem-dup-remote.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-remote"
rc=$?
set -e

assert_eq "$rc" "0" "dup-remote: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-remote: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "0" "dup-remote: complete NOT called (remote already terminal)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-remote.json" ] && echo exists || echo removed)" "removed" \
    "dup-remote: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-remote.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-remote: .claimed marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-dup-remote.json" ] && echo exists || echo missing)" "exists" \
    "dup-remote: trace written from remote reconciliation"


# ═══════════════════════════════════════════════════════════════
# P2: Remote reconciliation treats cancelled as terminal
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — remote trace cancelled blocks re-delivery"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

_write_test_claimed_marker "rem-dup-cancelled"

_TRACE_RC=0
_TRACE_OUTPUT='{"data":{"task_id":"rem-dup-cancelled","status":"cancelled"}}'
superpos_get_task_trace() {
    if [[ -n "$_TRACE_OUTPUT" ]]; then
        echo "$_TRACE_OUTPUT"
    fi
    return $_TRACE_RC
}

task_json=$(_make_reminder_task "rem-dup-cancelled" "telegram" "94650650" "Should NOT re-deliver (cancelled)")
echo "$task_json" > "${PENDING_DIR}/rem-dup-cancelled.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-cancelled"
rc=$?
set -e

assert_eq "$rc" "0" "dup-cancelled: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-cancelled: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "0" "dup-cancelled: complete NOT called (remote already terminal)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-cancelled.json" ] && echo exists || echo removed)" "removed" \
    "dup-cancelled: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-cancelled.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-cancelled: .claimed marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-dup-cancelled.json" ] && echo exists || echo missing)" "exists" \
    "dup-cancelled: trace written from remote reconciliation"


# ═══════════════════════════════════════════════════════════════
# P2: Remote reconciliation treats dead_letter as terminal
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — remote trace dead_letter blocks re-delivery"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

_write_test_claimed_marker "rem-dup-deadletter"

_TRACE_RC=0
_TRACE_OUTPUT='{"data":{"task_id":"rem-dup-deadletter","status":"dead_letter"}}'
superpos_get_task_trace() {
    if [[ -n "$_TRACE_OUTPUT" ]]; then
        echo "$_TRACE_OUTPUT"
    fi
    return $_TRACE_RC
}

task_json=$(_make_reminder_task "rem-dup-deadletter" "telegram" "94650650" "Should NOT re-deliver (dead_letter)")
echo "$task_json" > "${PENDING_DIR}/rem-dup-deadletter.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-deadletter"
rc=$?
set -e

assert_eq "$rc" "0" "dup-deadletter: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-deadletter: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "0" "dup-deadletter: complete NOT called (remote already terminal)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-deadletter.json" ] && echo exists || echo removed)" "removed" \
    "dup-deadletter: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-deadletter.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-deadletter: .claimed marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-dup-deadletter.json" ] && echo exists || echo missing)" "exists" \
    "dup-deadletter: trace written from remote reconciliation"


# ═══════════════════════════════════════════════════════════════
# P2: Remote reconciliation treats expired as terminal
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — remote trace expired blocks re-delivery"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

_write_test_claimed_marker "rem-dup-expired"

_TRACE_RC=0
_TRACE_OUTPUT='{"data":{"task_id":"rem-dup-expired","status":"expired"}}'
superpos_get_task_trace() {
    if [[ -n "$_TRACE_OUTPUT" ]]; then
        echo "$_TRACE_OUTPUT"
    fi
    return $_TRACE_RC
}

task_json=$(_make_reminder_task "rem-dup-expired" "telegram" "94650650" "Should NOT re-deliver (expired)")
echo "$task_json" > "${PENDING_DIR}/rem-dup-expired.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-dup-expired"
rc=$?
set -e

assert_eq "$rc" "0" "dup-expired: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "dup-expired: delivery NOT attempted (duplicate prevented)"
assert_eq "$(_mock_read_n complete_calls)" "0" "dup-expired: complete NOT called (remote already terminal)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-expired.json" ] && echo exists || echo removed)" "removed" \
    "dup-expired: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-dup-expired.claimed" ] && echo exists || echo removed)" "removed" \
    "dup-expired: .claimed marker cleaned up"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-dup-expired.json" ] && echo exists || echo missing)" "exists" \
    "dup-expired: trace written from remote reconciliation"


# ═══════════════════════════════════════════════════════════════
# P2: Pre-delivery crash still re-delivers (fix doesn't break recovery)
# ═══════════════════════════════════════════════════════════════

describe "Duplicate prevention — pre-delivery crash still re-delivers correctly"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT

# Simulate: genuine pre-delivery crash. Only .claimed exists,
# no .delivered, no trace, remote trace fails (non-terminal).
_write_test_claimed_marker "rem-precrash"

# Remote trace returns failure (no trace available)
_TRACE_RC=1
_TRACE_OUTPUT=""
superpos_get_task_trace() {
    if [[ -n "$_TRACE_OUTPUT" ]]; then
        echo "$_TRACE_OUTPUT"
    fi
    return $_TRACE_RC
}

task_json=$(_make_reminder_task "rem-precrash" "telegram" "42" "Pre-delivery crash reminder")
echo "$task_json" > "${PENDING_DIR}/rem-precrash.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-precrash"
rc=$?
set -e

assert_eq "$rc" "0" "precrash: returns 0 (delivered successfully)"
assert_eq "$(_mock_read_n send_calls)" "1" "precrash: delivery attempted (correct for pre-delivery crash)"
assert_eq "$(_mock_read send_last_target)" "42" "precrash: correct target"
assert_eq "$(_mock_read send_last_channel)" "telegram" "precrash: correct channel"
assert_eq "$(_mock_read send_last_message)" "Pre-delivery crash reminder" "precrash: correct message"
assert_eq "$(_mock_read_n complete_calls)" "1" "precrash: task completed"
assert_eq "$(_mock_read_n fail_calls)" "0" "precrash: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/rem-precrash.json" ] && echo exists || echo removed)" "removed" \
    "precrash: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-precrash.claimed" ] && echo exists || echo removed)" "removed" \
    "precrash: .claimed marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# P2: .delivered marker written on delivery, cleaned on success
# ═══════════════════════════════════════════════════════════════

describe "Reminder — .delivered marker written on delivery, cleaned on success"

_setup
_CLAIM_RC=0
task_json=$(_make_reminder_task "rem-dmarker" "telegram" "333" "Delivered marker test")
echo "$task_json" > "${PENDING_DIR}/rem-dmarker.json"

# Override complete_task to check .delivered exists before cleanup
superpos_complete_task() {
    local task_id="$2"
    shift 2
    local n; n=$(cat "${_MOCK_DIR}/complete_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/complete_calls"
    echo "$task_id" > "${_MOCK_DIR}/complete_last_task"
    # Check .delivered marker while it still exists (before Step 5 cleanup)
    if [[ -f "${PENDING_DIR}/rem-dmarker.delivered" ]]; then
        echo "exists" > "${_MOCK_DIR}/delivered_check"
    else
        echo "missing" > "${_MOCK_DIR}/delivered_check"
    fi
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -r) echo "$2" > "${_MOCK_DIR}/complete_last_result"; shift 2 ;;
            *) shift ;;
        esac
    done
    return 0
}

_lifecycle_process_reminder "$task_json" "rem-dmarker"

assert_eq "$(_mock_read_n complete_calls)" "1" "dmarker: task completed"
assert_eq "$(_mock_read delivered_check)" "exists" "dmarker: .delivered exists during complete (before cleanup)"
assert_eq "$([ -f "${PENDING_DIR}/rem-dmarker.delivered" ] && echo exists || echo removed)" "removed" \
    "dmarker: .delivered cleaned up after success"
assert_eq "$([ -f "${PENDING_DIR}/rem-dmarker.json" ] && echo exists || echo removed)" "removed" \
    "dmarker: pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# P3: 409 response body parsing — _lifecycle_parse_409_status
# ═══════════════════════════════════════════════════════════════

describe "409 parser — extracts status from conflict response body"

_setup

# Standard Superpos 409 format
body='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: completed"}]}'
parsed=$(_lifecycle_parse_409_status "$body")
assert_eq "$parsed" "completed" "parse_409: extracts 'completed'"

body='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: failed"}]}'
parsed=$(_lifecycle_parse_409_status "$body")
assert_eq "$parsed" "failed" "parse_409: extracts 'failed'"

body='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: expired"}]}'
parsed=$(_lifecycle_parse_409_status "$body")
assert_eq "$parsed" "expired" "parse_409: extracts 'expired'"

# Empty / missing body
parsed=$(_lifecycle_parse_409_status "")
assert_eq "$parsed" "" "parse_409: empty string for empty body"

parsed=$(_lifecycle_parse_409_status '{"errors":[]}')
assert_eq "$parsed" "" "parse_409: empty string for no errors"

parsed=$(_lifecycle_parse_409_status '{"errors":[{"code":"other","message":"Something else"}]}')
assert_eq "$parsed" "" "parse_409: empty string for non-conflict code"


# ═══════════════════════════════════════════════════════════════
# P3: Delivered + complete 409 (already completed) → no false-fail
# ═══════════════════════════════════════════════════════════════

describe "409 handling — delivered + complete 409 (already completed) reconciles cleanly"

_setup
_COMPLETE_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: completed"}]}'

task_json=$(_make_reminder_task "rem-409-completed" "telegram" "42" "Already completed")
echo "$task_json" > "${PENDING_DIR}/rem-409-completed.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-409-completed"
rc=$?
set -e

assert_eq "$rc" "0" "409-completed: returns 0 (reconciled, not error)"
assert_eq "$(_mock_read_n send_calls)" "1" "409-completed: delivery was attempted"
assert_eq "$(_mock_read_n complete_calls)" "1" "409-completed: complete was attempted"
assert_eq "$(_mock_read_n fail_calls)" "0" "409-completed: fail NOT called"
assert_eq "$([ -f "${PENDING_DIR}/rem-409-completed.json" ] && echo exists || echo removed)" "removed" \
    "409-completed: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-409-completed.result.json" ] && echo exists || echo removed)" "removed" \
    "409-completed: no result artifact saved (reconciled)"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-409-completed.json" ] && echo exists || echo missing)" "exists" \
    "409-completed: trace written"


# ═══════════════════════════════════════════════════════════════
# P3: Delivered + complete 409 (failed — timeout race) → reconcile with warning
# ═══════════════════════════════════════════════════════════════

describe "409 handling — delivered + complete 409 (remote failed = timeout race) reconciles"

_setup
_COMPLETE_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: failed"}]}'

task_json=$(_make_reminder_task "rem-409-failed" "telegram" "42" "Timeout race")
echo "$task_json" > "${PENDING_DIR}/rem-409-failed.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-409-failed"
rc=$?
set -e

assert_eq "$rc" "0" "409-failed: returns 0 (reconciled despite timeout race)"
assert_eq "$(_mock_read_n send_calls)" "1" "409-failed: delivery was attempted"
assert_eq "$(_mock_read_n complete_calls)" "1" "409-failed: complete was attempted"
assert_eq "$(_mock_read_n fail_calls)" "0" "409-failed: fail NOT called (delivery succeeded)"
assert_eq "$([ -f "${PENDING_DIR}/rem-409-failed.json" ] && echo exists || echo removed)" "removed" \
    "409-failed: pending file cleaned up (not stuck)"
assert_eq "$([ -f "${PENDING_DIR}/rem-409-failed.result.json" ] && echo exists || echo removed)" "removed" \
    "409-failed: no result artifact saved"
assert_eq "$([ -f "${_tmp_dir}/traces/rem-409-failed.json" ] && echo exists || echo missing)" "exists" \
    "409-failed: trace written"


# ═══════════════════════════════════════════════════════════════
# P3: Step 0 artifact retry + 409 (delivered + remote failed) → reconcile
# ═══════════════════════════════════════════════════════════════

describe "409 handling — artifact retry with .delivered + 409 failed reconciles"

_setup
_COMPLETE_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: failed"}]}'

# Simulate: result artifact saved from prior run, .delivered marker exists
echo '{"task_id":"rem-art-409","status":"completed","summary":"delivered"}' > "${PENDING_DIR}/rem-art-409.result.json"
echo "rem-art-409" > "${PENDING_DIR}/rem-art-409.delivered"
_write_test_claimed_marker "rem-art-409"

task_json=$(_make_reminder_task "rem-art-409" "telegram" "42" "Artifact retry")
echo "$task_json" > "${PENDING_DIR}/rem-art-409.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-art-409"
rc=$?
set -e

assert_eq "$rc" "0" "art-409: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "art-409: delivery NOT re-attempted (artifact retry path)"
assert_eq "$(_mock_read_n complete_calls)" "1" "art-409: complete attempted via artifact"
assert_eq "$([ -f "${PENDING_DIR}/rem-art-409.result.json" ] && echo exists || echo removed)" "removed" \
    "art-409: result artifact cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-art-409.delivered" ] && echo exists || echo removed)" "removed" \
    "art-409: .delivered marker cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-art-409.json" ] && echo exists || echo removed)" "removed" \
    "art-409: pending file cleaned up"


# ═══════════════════════════════════════════════════════════════
# P3: .delivered reconciliation + 409 (already completed) → no false-fail
# ═══════════════════════════════════════════════════════════════

describe "409 handling — .delivered reconciliation + 409 completed = clean"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: completed"}]}'

_write_test_claimed_marker "rem-deliv-409"
echo "rem-deliv-409" > "${PENDING_DIR}/rem-deliv-409.delivered"

task_json=$(_make_reminder_task "rem-deliv-409" "telegram" "42" "Should not re-deliver")
echo "$task_json" > "${PENDING_DIR}/rem-deliv-409.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-deliv-409"
rc=$?
set -e

assert_eq "$rc" "0" "deliv-409: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "0" "deliv-409: delivery NOT attempted"
assert_eq "$(_mock_read_n complete_calls)" "1" "deliv-409: complete called for reconciliation"
assert_eq "$([ -f "${PENDING_DIR}/rem-deliv-409.json" ] && echo exists || echo removed)" "removed" \
    "deliv-409: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-deliv-409.delivered" ] && echo exists || echo removed)" "removed" \
    "deliv-409: .delivered marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# P3: .delivered reconciliation + 409 (failed = timeout race) → reconcile
# ═══════════════════════════════════════════════════════════════

describe "409 handling — .delivered reconciliation + 409 failed (timeout race) reconciles"

_setup
_CLAIM_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_RC=$SUPERPOS_ERR_CONFLICT
_COMPLETE_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: failed"}]}'

_write_test_claimed_marker "rem-deliv-race"
echo "rem-deliv-race" > "${PENDING_DIR}/rem-deliv-race.delivered"

task_json=$(_make_reminder_task "rem-deliv-race" "telegram" "42" "Timeout race via delivered")
echo "$task_json" > "${PENDING_DIR}/rem-deliv-race.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-deliv-race"
rc=$?
set -e

assert_eq "$rc" "0" "deliv-race: returns 0 (reconciled despite timeout race)"
assert_eq "$(_mock_read_n send_calls)" "0" "deliv-race: delivery NOT re-attempted"
assert_eq "$(_mock_read_n complete_calls)" "1" "deliv-race: complete attempted for reconciliation"
assert_eq "$([ -f "${PENDING_DIR}/rem-deliv-race.json" ] && echo exists || echo removed)" "removed" \
    "deliv-race: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-deliv-race.delivered" ] && echo exists || echo removed)" "removed" \
    "deliv-race: .delivered marker cleaned up"


# ═══════════════════════════════════════════════════════════════
# P3: Fail-path 409 also reconciles (no stuck tasks)
# ═══════════════════════════════════════════════════════════════

describe "409 handling — fail-path 409 reconciles cleanly"

_setup
_SEND_RC=1  # delivery fails
_FAIL_RC=$SUPERPOS_ERR_CONFLICT
_FAIL_BODY='{"errors":[{"code":"conflict","message":"Task is not in progress. Current status: failed"}]}'

task_json=$(_make_reminder_task "rem-fail-409" "telegram" "42" "Fail path 409")
echo "$task_json" > "${PENDING_DIR}/rem-fail-409.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-fail-409"
rc=$?
set -e

assert_eq "$rc" "0" "fail-409: returns 0 (reconciled)"
assert_eq "$(_mock_read_n send_calls)" "1" "fail-409: delivery was attempted (and failed)"
assert_eq "$(_mock_read_n complete_calls)" "0" "fail-409: complete NOT called"
assert_eq "$(_mock_read_n fail_calls)" "1" "fail-409: fail was attempted"
assert_eq "$([ -f "${PENDING_DIR}/rem-fail-409.json" ] && echo exists || echo removed)" "removed" \
    "fail-409: pending file cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-fail-409.result.json" ] && echo exists || echo removed)" "removed" \
    "fail-409: no result artifact saved"


# ═══════════════════════════════════════════════════════════════
# P4: Delivery stderr/detail propagated into fail payload
# ═══════════════════════════════════════════════════════════════

describe "Delivery failure — stderr detail propagated to fail payload"

_setup

# Override mock to set _WAKE_LAST_ERROR on failure (simulates real transport)
_wake_send_alert() {
    local n; n=$(cat "${_MOCK_DIR}/send_calls"); echo $(( n + 1 )) > "${_MOCK_DIR}/send_calls"
    echo "${1:-}" > "${_MOCK_DIR}/send_last_target"
    echo "${2:-}" > "${_MOCK_DIR}/send_last_channel"
    echo "${3:-}" > "${_MOCK_DIR}/send_last_message"
    echo "${4:-}" > "${_MOCK_DIR}/send_last_timeout"
    _WAKE_LAST_ERROR="openclaw message send rc=124: connection timed out"
    return 1
}

task_json=$(_make_reminder_task "rem-stderr" "telegram" "42" "Stderr test")
echo "$task_json" > "${PENDING_DIR}/rem-stderr.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-stderr"
rc=$?
set -e

assert_eq "$rc" "0" "stderr: returns 0"
assert_eq "$(_mock_read_n fail_calls)" "1" "stderr: fail called"
assert_contains "$(_mock_read fail_last_error)" "rc=124" "stderr: fail payload includes return code detail"
assert_contains "$(_mock_read fail_last_error)" "timed out" "stderr: fail payload includes timeout detail"
assert_contains "$(_mock_read fail_last_error)" "delivery_detail" "stderr: result JSON includes delivery_detail field"


# ═══════════════════════════════════════════════════════════════
# P4: Delivery failure without _WAKE_LAST_ERROR falls back to generic summary
# ═══════════════════════════════════════════════════════════════

describe "Delivery failure — fallback summary when no stderr detail"

_setup
_SEND_RC=1

task_json=$(_make_reminder_task "rem-no-stderr" "telegram" "42" "No stderr")
echo "$task_json" > "${PENDING_DIR}/rem-no-stderr.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-no-stderr"
rc=$?
set -e

assert_eq "$rc" "0" "no-stderr: returns 0"
assert_eq "$(_mock_read_n fail_calls)" "1" "no-stderr: fail called"
assert_contains "$(_mock_read fail_last_error)" "delivery failed" "no-stderr: fail payload includes generic delivery error"


# ═══════════════════════════════════════════════════════════════
# P4: Reminder uses configured send timeout (default 60s)
# ═══════════════════════════════════════════════════════════════

describe "Reminder — uses default reminder send timeout (60s)"

_setup
task_json=$(_make_reminder_task "rem-timeout-default" "telegram" "42" "Timeout default")
echo "$task_json" > "${PENDING_DIR}/rem-timeout-default.json"

_lifecycle_process_reminder "$task_json" "rem-timeout-default"

assert_eq "$(_mock_read send_last_timeout)" "60" "timeout-default: delivery called with 60s timeout"


# ═══════════════════════════════════════════════════════════════
# P4: Reminder send timeout is configurable via env
# ═══════════════════════════════════════════════════════════════

describe "Reminder — uses custom send timeout from env"

_setup
_WAKE_REMINDER_SEND_TIMEOUT=90

task_json=$(_make_reminder_task "rem-timeout-custom" "telegram" "42" "Timeout custom")
echo "$task_json" > "${PENDING_DIR}/rem-timeout-custom.json"

_lifecycle_process_reminder "$task_json" "rem-timeout-custom"

assert_eq "$(_mock_read send_last_timeout)" "90" "timeout-custom: delivery called with 90s timeout"


# ═══════════════════════════════════════════════════════════════
# P4: Retry backoff — skips tasks in backoff window
# ═══════════════════════════════════════════════════════════════

describe "Retry backoff — skips tasks in backoff window"

_setup
reminder_task=$(_make_reminder_task "rem-backoff" "telegram" "999" "Backoff test")
echo "$reminder_task" > "${PENDING_DIR}/rem-backoff.json"

# Write a retry_after in the future (1 hour from now)
future_ts=$(( $(date +%s) + 3600 ))
echo "$future_ts" > "${PENDING_DIR}/rem-backoff.retry_after"
echo "1" > "${PENDING_DIR}/rem-backoff.retry_count"

_lifecycle_retry_pending_handlers

assert_eq "$(_mock_read_n claim_calls)" "0" "backoff: task not attempted during backoff window"
assert_eq "$([ -f "${PENDING_DIR}/rem-backoff.json" ] && echo exists || echo removed)" "exists" \
    "backoff: pending file preserved"


# ═══════════════════════════════════════════════════════════════
# P4: Retry backoff — expired backoff allows processing
# ═══════════════════════════════════════════════════════════════

describe "Retry backoff — expired backoff allows processing"

_setup
reminder_task=$(_make_reminder_task "rem-backoff-expired" "telegram" "999" "Backoff expired")
echo "$reminder_task" > "${PENDING_DIR}/rem-backoff-expired.json"

# Write an expired retry_after (1 hour ago)
past_ts=$(( $(date +%s) - 3600 ))
echo "$past_ts" > "${PENDING_DIR}/rem-backoff-expired.retry_after"
echo "1" > "${PENDING_DIR}/rem-backoff-expired.retry_count"

_lifecycle_retry_pending_handlers

assert_eq "$(_mock_read_n claim_calls)" "1" "backoff-expired: task attempted after backoff expires"


# ═══════════════════════════════════════════════════════════════
# P4: Retry backoff — written on transient API failure
# ═══════════════════════════════════════════════════════════════

describe "Retry backoff — written on transient API failure"

_setup
_COMPLETE_RC=1  # API failure
task_json=$(_make_reminder_task "rem-backoff-write" "telegram" "42" "Backoff write")
echo "$task_json" > "${PENDING_DIR}/rem-backoff-write.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-backoff-write"
rc=$?
set -e

assert_eq "$rc" "1" "backoff-write: returns 1 (retryable)"
assert_eq "$([ -f "${PENDING_DIR}/rem-backoff-write.retry_count" ] && echo exists || echo missing)" "exists" \
    "backoff-write: retry_count written"
assert_eq "$([ -f "${PENDING_DIR}/rem-backoff-write.retry_after" ] && echo exists || echo missing)" "exists" \
    "backoff-write: retry_after written"
assert_eq "$(cat "${PENDING_DIR}/rem-backoff-write.retry_count")" "1" "backoff-write: retry_count is 1"


# ═══════════════════════════════════════════════════════════════
# P4: Retry backoff — increments on repeated failures
# ═══════════════════════════════════════════════════════════════

describe "Retry backoff — increments on repeated transient failures"

_setup
_COMPLETE_RC=1  # API failure
task_json=$(_make_reminder_task "rem-backoff-incr" "telegram" "42" "Backoff incr")
echo "$task_json" > "${PENDING_DIR}/rem-backoff-incr.json"

# First failure
set +e
_lifecycle_process_reminder "$task_json" "rem-backoff-incr"
set -e

first_count=$(cat "${PENDING_DIR}/rem-backoff-incr.retry_count")
first_after=$(cat "${PENDING_DIR}/rem-backoff-incr.retry_after")

# Reset artifact for second attempt (re-create pending file)
echo "$task_json" > "${PENDING_DIR}/rem-backoff-incr.json"
# Override to bypass result artifact (simulate fresh attempt)
rm -f "${PENDING_DIR}/rem-backoff-incr.result.json"

set +e
_lifecycle_process_reminder "$task_json" "rem-backoff-incr"
set -e

second_count=$(cat "${PENDING_DIR}/rem-backoff-incr.retry_count")

assert_eq "$first_count" "1" "backoff-incr: first failure count is 1"
assert_eq "$second_count" "2" "backoff-incr: second failure count is 2"


# ═══════════════════════════════════════════════════════════════
# P4: Retry backoff — cleared on success
# ═══════════════════════════════════════════════════════════════

describe "Retry backoff — cleared on success"

_setup
task_json=$(_make_reminder_task "rem-backoff-clear" "telegram" "42" "Backoff clear")
echo "$task_json" > "${PENDING_DIR}/rem-backoff-clear.json"

# Write stale backoff markers (already expired)
echo "3" > "${PENDING_DIR}/rem-backoff-clear.retry_count"
echo "0" > "${PENDING_DIR}/rem-backoff-clear.retry_after"

set +e
_lifecycle_process_reminder "$task_json" "rem-backoff-clear"
rc=$?
set -e

assert_eq "$rc" "0" "backoff-clear: returns 0"
assert_eq "$([ -f "${PENDING_DIR}/rem-backoff-clear.retry_count" ] && echo exists || echo removed)" "removed" \
    "backoff-clear: retry_count cleaned up"
assert_eq "$([ -f "${PENDING_DIR}/rem-backoff-clear.retry_after" ] && echo exists || echo removed)" "removed" \
    "backoff-clear: retry_after cleaned up"


test_summary
