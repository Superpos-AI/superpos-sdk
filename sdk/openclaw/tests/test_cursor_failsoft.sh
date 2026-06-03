#!/usr/bin/env bash
# test_cursor_failsoft.sh — Tests for cursor.json fail-soft behaviour.
#
# Validates that _superpos_oc_load_cursor handles malformed, empty,
# truncated, and missing cursor.json without aborting under set -e.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides _superpos_request, SUPERPOS_OK, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# Source events module (defines _superpos_oc_load_cursor)
source "${SCRIPT_DIR}/../bin/superpos-events.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_config_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_config_dir"' EXIT

_setup() {
    export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
    rm -f "${_tmp_config_dir}/cursor.json"
}

# ── Test: malformed JSON does not abort ──────────────────────────

describe "Malformed cursor.json"

_setup
echo "NOT VALID JSON{{{" > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on malformed cursor.json"
assert_eq "$cursor" "" "cursor is empty on malformed file"

# Verify warning is emitted to stderr
set +e
stderr=$(_superpos_oc_load_cursor 2>&1 1>/dev/null)
set -e

assert_contains "$stderr" "malformed cursor.json" "emits warning on malformed file"

# ── Test: empty file does not abort ──────────────────────────────

describe "Empty cursor.json"

_setup
: > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on empty cursor.json"
assert_eq "$cursor" "" "cursor is empty on empty file"

# ── Test: truncated JSON does not abort ──────────────────────────

describe "Truncated cursor.json"

_setup
echo '{"last_event_id":' > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on truncated JSON"
assert_eq "$cursor" "" "cursor is empty on truncated file"

# ── Test: valid cursor.json loads correctly ──────────────────────

describe "Valid cursor.json"

_setup
echo '{"last_event_id": "evt-abc-123"}' > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on valid cursor.json"
assert_eq "$cursor" "evt-abc-123" "loads cursor value from valid file"

# ── Test: missing cursor.json is fine ────────────────────────────

describe "Missing cursor.json"

_setup
# No file created

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 when cursor.json does not exist"
assert_eq "$cursor" "" "cursor is empty when file missing"

# ── Test: cursor.json with null last_event_id ────────────────────

describe "cursor.json with null last_event_id"

_setup
echo '{"last_event_id": null}' > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on null cursor value"
assert_eq "$cursor" "" "cursor is empty on null value"

# ── Test: binary garbage file does not abort ─────────────────────

describe "Binary garbage cursor.json"

_setup
printf '\x00\xff\xfe\x80' > "${_tmp_config_dir}/cursor.json"

set +e
cursor=$(_superpos_oc_load_cursor 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on binary garbage"
assert_eq "$cursor" "" "cursor is empty on binary garbage"

# ── Test: poll_raw does not advance cursor before handling ──────

describe "poll_raw does not advance cursor"

_setup
export SUPERPOS_HIVE_ID="hive-test-001"
# Seed existing cursor
_superpos_oc_save_cursor "evt-prev"

_superpos_request() {
    echo '[{"id":"evt-new-1","type":"test"}]'
    return 0
}

set +e
result=$(superpos_oc_events_poll_raw)
rc=$?
set -e

assert_eq "$rc" "0" "poll_raw succeeds"
assert_contains "$result" "evt-new-1" "poll_raw returns fetched events"
assert_eq "$(_superpos_oc_load_cursor 2>/dev/null)" "evt-prev" "cursor unchanged after poll_raw"

# ── Test: explicit cursor commit persists last handled event ────

describe "commit_cursor persists last handled event id"

_setup
superpos_oc_events_commit_cursor "evt-committed"

assert_eq "$(_superpos_oc_load_cursor 2>/dev/null)" "evt-committed" "commit_cursor writes cursor"

# ── Summary ──────────────────────────────────────────────────────

test_summary
