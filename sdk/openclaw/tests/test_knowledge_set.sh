#!/usr/bin/env bash
# test_knowledge_set.sh — Tests for idempotent knowledge set semantics.
#
# Validates that superpos_oc_knowledge_set creates on first call
# and updates (instead of 409) when the key already exists.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness (provides mock_response, assertions)
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# Load Shell SDK with mocked curl from harness
export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_HIVE_ID="hive-test-01"
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# Source the module under test
source "${SCRIPT_DIR}/../bin/superpos-knowledge.sh"

# ── Test: create succeeds on new key ──────────────────────────────

describe "Knowledge set — new key (create succeeds)"

mock_reset
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 201 \
    '{"data":{"id":"ke-001","key":"my-key","value":"hello"}}'

set +e
output=$(superpos_oc_knowledge_set "my-key" '"hello"' 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on successful create"
assert_contains "$output" "created" "output says created"
assert_contains "$output" "ke-001" "output contains new entry ID"

# Verify the POST was sent
assert_eq "$(mock_last_method)" "POST" "sends POST request"

# ── Test: create-or-update on existing key (409 → lookup → PUT) ───

describe "Knowledge set — existing key (409 → update)"

mock_reset

# First call: create returns 409 Conflict
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists","code":"conflict"}]}'

# Second call: list by key returns the existing entry
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[{"id":"ke-existing-99","key":"my-key","value":"old-val"}]}'

# Third call: update succeeds
mock_response PUT "/api/v1/hives/hive-test-01/knowledge/ke-existing-99" 200 \
    '{"data":{"id":"ke-existing-99","key":"my-key","value":"new-val"}}'

set +e
output=$(superpos_oc_knowledge_set "my-key" '"new-val"' 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after create-then-update fallback"
assert_contains "$output" "updated" "output says updated"
assert_contains "$output" "ke-existing-99" "output contains existing entry ID"

# ── Test: non-conflict error propagates ───────────────────────────

describe "Knowledge set — server error propagates"

mock_reset
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 500 \
    '{"data":null,"errors":[{"message":"Internal error"}]}'

set +e
output=$(superpos_oc_knowledge_set "bad-key" '"val"' 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero on server error"

# ── Test: 409 but list returns empty fails gracefully ─────────────

describe "Knowledge set — 409 but entry not found on list"

mock_reset
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists"}]}'
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[]}'

set +e
output=$(superpos_oc_knowledge_set "ghost-key" '"val"' 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero when entry not found after 409"
assert_contains "$output" "no exact match found" "output mentions no exact match"

# ── Test: set with scope and visibility passes through ────────────

describe "Knowledge set — scope and visibility on create"

mock_reset
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 201 \
    '{"data":{"id":"ke-scoped","key":"scoped-key","value":"v","scope":"apiary"}}'

set +e
output=$(superpos_oc_knowledge_set "scoped-key" '"v"' "apiary" "public" 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 with scope and visibility"
assert_contains "$output" "ke-scoped" "output contains entry ID"

# Check that the POST body included scope
body=$(mock_last_body)
assert_contains "$body" "apiary" "request body includes scope"

# ── Test: 409 with scope preserves scope in lookup ─────────────────

describe "Knowledge set — 409 with scope filters lookup by key+scope"

mock_reset

# Create with scope=apiary returns 409 (key exists at that scope)
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists","code":"conflict"}]}'

# List filtered by key+scope returns the correct scoped entry
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[{"id":"ke-apiary-01","key":"shared-key","value":"old","scope":"apiary"}]}'

# Update the correct entry
mock_response PUT "/api/v1/hives/hive-test-01/knowledge/ke-apiary-01" 200 \
    '{"data":{"id":"ke-apiary-01","key":"shared-key","value":"new","scope":"apiary"}}'

set +e
output=$(superpos_oc_knowledge_set "shared-key" '"new"' "apiary" 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after scoped conflict resolution"
assert_contains "$output" "updated" "output says updated"
assert_contains "$output" "ke-apiary-01" "output contains correct scoped entry ID"

# Verify the GET (list) request included the scope parameter
url_log=$(mock_url_log)
assert_contains "$url_log" "scope=apiary" "list lookup includes scope filter"

# ── Test: 409 without scope omits scope from lookup ──────────────

describe "Knowledge set — 409 without scope omits scope from lookup"

mock_reset

# Create without scope returns 409
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists","code":"conflict"}]}'

# List by key only returns the hive-scoped entry
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[{"id":"ke-hive-01","key":"my-key","value":"old","scope":"hive"}]}'

# Update
mock_response PUT "/api/v1/hives/hive-test-01/knowledge/ke-hive-01" 200 \
    '{"data":{"id":"ke-hive-01","key":"my-key","value":"new","scope":"hive"}}'

set +e
output=$(superpos_oc_knowledge_set "my-key" '"new"' 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after unscoped conflict resolution"
assert_contains "$output" "ke-hive-01" "output contains correct entry ID"

# Verify the GET (list) request did NOT include a scope parameter
url_log=$(mock_url_log)
# The GET line should have key= but not scope=
get_line=$(echo "$url_log" | grep "^GET" || echo "")
assert_contains "$get_line" "key=" "list lookup includes key filter"
assert_not_contains "$get_line" "scope=" "list lookup omits scope when not provided"

# ── Test: 409 exact key match among pattern-similar keys ──────────

describe "Knowledge set — 409 exact key match filters out similar keys"

mock_reset

# Create returns 409
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists","code":"conflict"}]}'

# List returns multiple entries with similar keys (pattern match)
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[{"id":"ke-wrong-1","key":"config-backup","value":"old","scope":"hive"},{"id":"ke-right","key":"config","value":"old","scope":"hive"},{"id":"ke-wrong-2","key":"my-config","value":"old","scope":"hive"}]}'

# Update the correct entry
mock_response PUT "/api/v1/hives/hive-test-01/knowledge/ke-right" 200 \
    '{"data":{"id":"ke-right","key":"config","value":"new","scope":"hive"}}'

set +e
output=$(superpos_oc_knowledge_set "config" '"new"' 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 after exact key match"
assert_contains "$output" "updated" "output says updated"
assert_contains "$output" "ke-right" "selects exact key match, not pattern match"

# ── Test: 409 wrong scope is not selected ────────────────────────

describe "Knowledge set — 409 rejects entry with wrong scope"

mock_reset

# Create with scope=apiary returns 409
mock_response POST "/api/v1/hives/hive-test-01/knowledge" 409 \
    '{"data":null,"errors":[{"message":"Key already exists","code":"conflict"}]}'

# List returns an entry with the right key but wrong scope
mock_response GET "/api/v1/hives/hive-test-01/knowledge" 200 \
    '{"data":[{"id":"ke-wrong-scope","key":"shared-key","value":"old","scope":"hive"}]}'

set +e
output=$(superpos_oc_knowledge_set "shared-key" '"new"' "apiary" 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero when only wrong-scope entry exists"
assert_contains "$output" "no exact match found" "output mentions no exact match"
assert_contains "$output" "scope='apiary'" "error includes requested scope"

# ── Summary ──────────────────────────────────────────────────────

test_summary
