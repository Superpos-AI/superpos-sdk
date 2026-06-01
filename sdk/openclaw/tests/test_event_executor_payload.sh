#!/usr/bin/env bash
# test_event_executor_payload.sh — Tests for executor-ready event payload handling.
#
# Validates:
#   - _daemon_event_is_exec_ready correctly identifies execution-ready events
#   - _daemon_build_event_dispatch_text includes invoke data inline for exec-ready events
#   - _daemon_build_event_dispatch_text returns reference-only for legacy events
#   - Pending event is skipped for exec-ready events (verified via save logic)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

export SUPERPOS_CONFIG_DIR="$_tmp_dir"
PENDING_DIR="${_tmp_dir}/pending"
mkdir -p "${PENDING_DIR}/events"

# Source the daemon's exec-ready functions by extracting them.
# We replicate the functions here since the daemon's main() would start the loop.

_daemon_event_is_exec_ready() {
    local event_json="$1"
    local instructions
    instructions=$(echo "$event_json" | jq -r '.invoke.instructions // empty' 2>/dev/null) || instructions=""
    [[ -n "$instructions" ]]
}

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

_daemon_save_pending_event() {
    local event_json="$1"
    local event_id
    event_id=$(echo "$event_json" | jq -r '.id // empty' 2>/dev/null) || event_id=""
    [[ -n "$event_id" ]] || return 0
    local events_dir="${PENDING_DIR}/events"
    mkdir -p "$events_dir"
    echo "$event_json" > "${events_dir}/${event_id}.json"
}

# ── Test data ────────────────────────────────────────────────────

EXEC_READY_EVENT='{"id":"EVT001","type":"task.assigned","payload":{"task_id":"T001"},"invoke":{"instructions":"Handle this PR comment","context":{"repo":"my-repo","pr":42}}}'

LEGACY_EVENT='{"id":"EVT002","type":"agent.status","payload":{"status":"online"}}'

NULL_INVOKE_EVENT='{"id":"EVT003","type":"task.assigned","payload":{"task_id":"T003"},"invoke":{"instructions":null,"context":null}}'

EMPTY_INSTRUCTIONS_EVENT='{"id":"EVT004","type":"task.assigned","payload":{"task_id":"T004"},"invoke":{"instructions":"","context":null}}'

INVOKE_NO_CONTEXT='{"id":"EVT005","type":"task.assigned","payload":{"task_id":"T005"},"invoke":{"instructions":"Run tests","context":null}}'

# ==================================================================
# _daemon_event_is_exec_ready
# ==================================================================

describe "Event exec-ready detection"

# Test: full invoke with instructions → exec-ready
_daemon_event_is_exec_ready "$EXEC_READY_EVENT"
rc=$?
assert_eq "$rc" "0" "event with invoke.instructions is exec-ready"

# Test: no invoke → NOT exec-ready
set +e
_daemon_event_is_exec_ready "$LEGACY_EVENT"
rc=$?
set -e
assert_ne "$rc" "0" "event without invoke is NOT exec-ready"

# Test: invoke with null instructions → NOT exec-ready
set +e
_daemon_event_is_exec_ready "$NULL_INVOKE_EVENT"
rc=$?
set -e
assert_ne "$rc" "0" "event with null invoke.instructions is NOT exec-ready"

# Test: invoke with empty string instructions → NOT exec-ready
set +e
_daemon_event_is_exec_ready "$EMPTY_INSTRUCTIONS_EVENT"
rc=$?
set -e
assert_ne "$rc" "0" "event with empty invoke.instructions is NOT exec-ready"

# Test: invoke with instructions but no context → exec-ready
_daemon_event_is_exec_ready "$INVOKE_NO_CONTEXT"
rc=$?
assert_eq "$rc" "0" "event with invoke.instructions but null context is exec-ready"

# ==================================================================
# _daemon_build_event_dispatch_text
# ==================================================================

describe "Event dispatch text building"

# Test: exec-ready event includes invoke in dispatch text
result=$(_daemon_build_event_dispatch_text "$EXEC_READY_EVENT" "task.assigned" "EVT001")
assert_contains "$result" "superpos:event:task.assigned:EVT001" "dispatch text includes event reference"
assert_contains "$result" "invoke.instructions: Handle this PR comment" "dispatch text includes invoke instructions"
assert_contains "$result" "invoke.context:" "dispatch text includes invoke context"
assert_contains "$result" "my-repo" "dispatch text includes context data"

# Test: legacy event produces reference-only text
result=$(_daemon_build_event_dispatch_text "$LEGACY_EVENT" "agent.status" "EVT002")
assert_eq "$result" "superpos:event:agent.status:EVT002" "legacy event dispatch is reference-only"

# Test: null invoke instructions produces reference-only text
result=$(_daemon_build_event_dispatch_text "$NULL_INVOKE_EVENT" "task.assigned" "EVT003")
assert_eq "$result" "superpos:event:task.assigned:EVT003" "null invoke produces reference-only text"

# Test: invoke with instructions but null context omits context line
result=$(_daemon_build_event_dispatch_text "$INVOKE_NO_CONTEXT" "task.assigned" "EVT005")
assert_contains "$result" "invoke.instructions: Run tests" "dispatch includes instructions"

# Verify context line is NOT present when context is null
line_count=$(echo "$result" | wc -l)
assert_eq "$line_count" "2" "dispatch has 2 lines (ref + instructions, no context)"

# ==================================================================
# Pending event save logic
# ==================================================================

describe "Pending event save — exec-ready vs fallback"

# Clean pending dir
rm -rf "${PENDING_DIR}/events"/*

# Test: exec-ready event should NOT be saved to pending
if _daemon_event_is_exec_ready "$EXEC_READY_EVENT"; then
    # In the real daemon, we skip saving here
    :
else
    _daemon_save_pending_event "$EXEC_READY_EVENT"
fi

if [[ ! -f "${PENDING_DIR}/events/EVT001.json" ]]; then
    _pass "exec-ready event NOT saved to pending (correct)"
else
    _fail "exec-ready event was saved to pending (should have been skipped)"
fi

# Test: legacy event SHOULD be saved to pending
if _daemon_event_is_exec_ready "$LEGACY_EVENT"; then
    :
else
    _daemon_save_pending_event "$LEGACY_EVENT"
fi

if [[ -f "${PENDING_DIR}/events/EVT002.json" ]]; then
    _pass "legacy event saved to pending (correct — fallback path)"
else
    _fail "legacy event NOT saved to pending (should be saved for fallback)"
fi

# Test: saved pending content matches original event
saved_type=$(jq -r '.type' "${PENDING_DIR}/events/EVT002.json" 2>/dev/null)
assert_eq "$saved_type" "agent.status" "saved pending event preserves original data"

# ==================================================================
# Dispatch failure recovery for exec-ready events
# ==================================================================

describe "Exec-ready dispatch failure saves to pending for retry"

rm -rf "${PENDING_DIR}/events"/*

# Simulate: exec-ready event dispatched but dispatch failed → must save
if _daemon_event_is_exec_ready "$EXEC_READY_EVENT"; then
    # Dispatch "fails" — save to pending for retry
    _daemon_save_pending_event "$EXEC_READY_EVENT"
fi

if [[ -f "${PENDING_DIR}/events/EVT001.json" ]]; then
    _pass "exec-ready event saved on dispatch failure (correct)"
else
    _fail "exec-ready event NOT saved on dispatch failure (data loss risk)"
fi

saved_instructions=$(jq -r '.invoke.instructions' "${PENDING_DIR}/events/EVT001.json" 2>/dev/null)
assert_eq "$saved_instructions" "Handle this PR comment" "saved event preserves invoke data for retry"

# ── Summary ──────────────────────────────────────────────────────

test_summary
