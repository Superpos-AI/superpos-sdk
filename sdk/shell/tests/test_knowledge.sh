#!/usr/bin/env bash
# test_knowledge.sh — Knowledge CRUD endpoint tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
ENTRY="EEEEEEEEEEEEEEEEEEEEEEEEEE"

# ── List knowledge ───────────────────────────────────────────────

describe "superpos_list_knowledge"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":[{"id":"e1","key":"config.timeout","scope":"hive"},{"id":"e2","key":"config.name","scope":"hive"}],"meta":{"total":2},"errors":null}'

result=$(superpos_list_knowledge "$HIVE")
assert_eq "$(echo "$result" | jq 'length')" "2" "list_knowledge returns array of entries"
assert_eq "$(echo "$result" | jq -r '.[0].key')" "config.timeout" "list_knowledge first entry key"

method=$(mock_last_method)
assert_eq "$method" "GET" "list_knowledge uses GET method"

# List with filters
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_knowledge "$HIVE" -k "config key" -s "hive" -l 10 >/dev/null
url=$(mock_last_url)
assert_contains "$url" "key=config%20key" "list_knowledge sends key filter (URL-encoded)"
assert_contains "$url" "scope=hive" "list_knowledge sends scope filter"
assert_contains "$url" "limit=10" "list_knowledge sends limit"

# ── Search knowledge ─────────────────────────────────────────────

describe "superpos_search_knowledge"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge/search" 200 \
    '{"data":[{"id":"e1","key":"config.timeout","value":{"seconds":30}}],"meta":{"total":1,"query":"timeout"},"errors":null}'

result=$(superpos_search_knowledge "$HIVE" -q "timeout")
assert_eq "$(echo "$result" | jq 'length')" "1" "search_knowledge returns matching entries"
assert_eq "$(echo "$result" | jq -r '.[0].key')" "config.timeout" "search_knowledge result key"

url=$(mock_last_url)
assert_contains "$url" "q=timeout" "search_knowledge sends query param"

# ── Get knowledge ────────────────────────────────────────────────

describe "superpos_get_knowledge"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge/${ENTRY}" 200 \
    '{"data":{"id":"'"$ENTRY"'","key":"config.timeout","value":{"seconds":30},"scope":"hive","version":1},"meta":{},"errors":null}'

result=$(superpos_get_knowledge "$HIVE" "$ENTRY")
assert_eq "$(echo "$result" | jq -r '.id')" "$ENTRY" "get_knowledge returns entry id"
assert_eq "$(echo "$result" | jq -r '.key')" "config.timeout" "get_knowledge returns entry key"
assert_eq "$(echo "$result" | jq '.value.seconds')" "30" "get_knowledge returns entry value"
assert_eq "$(echo "$result" | jq '.version')" "1" "get_knowledge returns version"

url=$(mock_last_url)
assert_contains "$url" "/knowledge/${ENTRY}" "get_knowledge URL contains entry ID"

# ── Create knowledge ─────────────────────────────────────────────

describe "superpos_create_knowledge"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":{"id":"new-entry","key":"config.greeting","value":{"msg":"hello"},"scope":"hive","version":1},"meta":{},"errors":null}'

result=$(superpos_create_knowledge "$HIVE" -k "config.greeting" -v '{"msg":"hello"}' -s "hive" -V "public")
assert_eq "$(echo "$result" | jq -r '.key')" "config.greeting" "create_knowledge returns key"
assert_eq "$(echo "$result" | jq '.version')" "1" "create_knowledge returns version 1"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.key')" "config.greeting" "create_knowledge sends key"
assert_eq "$(echo "$body" | jq -r '.value.msg')" "hello" "create_knowledge sends value"
assert_eq "$(echo "$body" | jq -r '.scope')" "hive" "create_knowledge sends scope"
assert_eq "$(echo "$body" | jq -r '.visibility')" "public" "create_knowledge sends visibility"

method=$(mock_last_method)
assert_eq "$method" "POST" "create_knowledge uses POST method"

# Create with TTL
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":{"id":"ttl-entry","key":"temp","ttl":"2026-12-31T23:59:59Z"},"meta":{},"errors":null}'

superpos_create_knowledge "$HIVE" -k "temp" -v '{"x":1}' -t "2026-12-31T23:59:59Z" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.ttl')" "2026-12-31T23:59:59Z" "create_knowledge sends TTL"

# ── Update knowledge ─────────────────────────────────────────────

describe "superpos_update_knowledge"

mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/knowledge/${ENTRY}" 200 \
    '{"data":{"id":"'"$ENTRY"'","key":"config.timeout","value":{"seconds":60},"version":2},"meta":{},"errors":null}'

result=$(superpos_update_knowledge "$HIVE" "$ENTRY" -v '{"seconds":60}')
assert_eq "$(echo "$result" | jq '.value.seconds')" "60" "update_knowledge returns new value"
assert_eq "$(echo "$result" | jq '.version')" "2" "update_knowledge returns bumped version"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq '.value.seconds')" "60" "update_knowledge sends value"

method=$(mock_last_method)
assert_eq "$method" "PUT" "update_knowledge uses PUT method"

url=$(mock_last_url)
assert_contains "$url" "/knowledge/${ENTRY}" "update_knowledge URL contains entry ID"

# ── Delete knowledge ─────────────────────────────────────────────

describe "superpos_delete_knowledge"

mock_reset
mock_response DELETE "/api/v1/hives/${HIVE}/knowledge/${ENTRY}" 204 ""

superpos_delete_knowledge "$HIVE" "$ENTRY"
rc=$?
assert_eq "$rc" "0" "delete_knowledge returns success"

method=$(mock_last_method)
assert_eq "$method" "DELETE" "delete_knowledge uses DELETE method"

url=$(mock_last_url)
assert_contains "$url" "/knowledge/${ENTRY}" "delete_knowledge URL contains entry ID"

# ── Summary ──────────────────────────────────────────────────────

test_summary
