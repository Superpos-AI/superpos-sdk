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
    '{"data":[{"id":"e1","type":"topic","key":"config.timeout","slug":"config.timeout","title":"Timeout","body":"30","frontmatter":{"seconds":30}}],"meta":{"total":1,"query":"timeout"},"errors":null}'

result=$(superpos_search_knowledge "$HIVE" -q "timeout")
assert_eq "$(echo "$result" | jq 'length')" "1" "search_knowledge returns matching entries"
assert_eq "$(echo "$result" | jq -r '.[0].key')" "config.timeout" "search_knowledge result key"

url=$(mock_last_url)
assert_contains "$url" "q=timeout" "search_knowledge sends query param"

# ── Get knowledge ────────────────────────────────────────────────

describe "superpos_get_knowledge"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge/${ENTRY}" 200 \
    '{"data":{"id":"'"$ENTRY"'","type":"topic","key":"config.timeout","slug":"config.timeout","title":"Timeout","body":"30","frontmatter":{"seconds":30},"scope":"hive","version":1},"meta":{},"errors":null}'

result=$(superpos_get_knowledge "$HIVE" "$ENTRY")
assert_eq "$(echo "$result" | jq -r '.id')" "$ENTRY" "get_knowledge returns entry id"
assert_eq "$(echo "$result" | jq -r '.key')" "config.timeout" "get_knowledge returns entry key"
assert_eq "$(echo "$result" | jq -r '.body')" "30" "get_knowledge returns entry body"
assert_eq "$(echo "$result" | jq '.frontmatter.seconds')" "30" "get_knowledge returns entry frontmatter"
assert_eq "$(echo "$result" | jq '.version')" "1" "get_knowledge returns version"

url=$(mock_last_url)
assert_contains "$url" "/knowledge/${ENTRY}" "get_knowledge URL contains entry ID"

# ── Create knowledge ─────────────────────────────────────────────

describe "superpos_create_knowledge"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":{"id":"new-entry","type":"topic","slug":"config.greeting","key":"config.greeting","title":"Greeting","body":"hello","scope":"hive","version":1},"meta":{},"errors":null}'

result=$(superpos_create_knowledge "$HIVE" -t "topic" -s "config.greeting" --title "Greeting" -b "hello" --frontmatter '{"msg":"hello"}' -S "hive" -V "public")
assert_eq "$(echo "$result" | jq -r '.slug')" "config.greeting" "create_knowledge returns slug"
assert_eq "$(echo "$result" | jq '.version')" "1" "create_knowledge returns version 1"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.type')" "topic" "create_knowledge sends type"
assert_eq "$(echo "$body" | jq -r '.slug')" "config.greeting" "create_knowledge sends slug"
assert_eq "$(echo "$body" | jq -r '.title')" "Greeting" "create_knowledge sends title"
assert_eq "$(echo "$body" | jq -r '.body')" "hello" "create_knowledge sends body"
assert_eq "$(echo "$body" | jq -r '.frontmatter.msg')" "hello" "create_knowledge sends frontmatter"
assert_eq "$(echo "$body" | jq -r '.scope')" "hive" "create_knowledge sends scope"
assert_eq "$(echo "$body" | jq -r '.visibility')" "public" "create_knowledge sends visibility"

method=$(mock_last_method)
assert_eq "$method" "POST" "create_knowledge uses POST method"

# Create requires type + slug
mock_reset
if superpos_create_knowledge "$HIVE" -s "no-type" >/dev/null 2>&1; then
    assert_eq "1" "0" "create_knowledge fails without type"
else
    assert_eq "0" "0" "create_knowledge fails without type"
fi

# Create with tags + TTL
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":{"id":"ttl-entry","type":"log","slug":"temp","key":"temp","ttl":"2026-12-31T23:59:59Z"},"meta":{},"errors":null}'

superpos_create_knowledge "$HIVE" -t "log" -s "temp" --tags '["a","b"]' --ttl "2026-12-31T23:59:59Z" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.ttl')" "2026-12-31T23:59:59Z" "create_knowledge sends TTL"
assert_eq "$(echo "$body" | jq -c '.tags')" '["a","b"]' "create_knowledge sends tags array"

# ── Update knowledge ─────────────────────────────────────────────

describe "superpos_update_knowledge"

mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/knowledge/${ENTRY}" 200 \
    '{"data":{"id":"'"$ENTRY"'","key":"config.timeout","slug":"config.timeout","body":"60 seconds","version":2},"meta":{},"errors":null}'

result=$(superpos_update_knowledge "$HIVE" "$ENTRY" -b "60 seconds" --frontmatter '{"seconds":60}')
assert_eq "$(echo "$result" | jq -r '.body')" "60 seconds" "update_knowledge returns new body"
assert_eq "$(echo "$result" | jq '.version')" "2" "update_knowledge returns bumped version"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.body')" "60 seconds" "update_knowledge sends body"
assert_eq "$(echo "$body" | jq -r '.frontmatter.seconds')" "60" "update_knowledge sends frontmatter"

method=$(mock_last_method)
assert_eq "$method" "PUT" "update_knowledge uses PUT method"

url=$(mock_last_url)
assert_contains "$url" "/knowledge/${ENTRY}" "update_knowledge URL contains entry ID"

# Update requires at least one typed field
mock_reset
if superpos_update_knowledge "$HIVE" "$ENTRY" >/dev/null 2>&1; then
    assert_eq "1" "0" "update_knowledge fails with no fields"
else
    assert_eq "0" "0" "update_knowledge fails with no fields"
fi

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

# ── CLI usage strings — typed contract (drift guard) ─────────────
# These assertions guard the bin/superpos-cli wrapper against drifting
# from superpos_create_knowledge / superpos_update_knowledge. The CLI
# usage/help must advertise the typed flags the SDK functions actually
# accept and must NOT mention the dropped legacy "-k KEY" / "-v VALUE_JSON"
# contract.

CLI="${SCRIPT_DIR}/../bin/superpos-cli"

describe "superpos-cli knowledge-create usage (typed flags)"

set +e
create_usage=$(bash "$CLI" knowledge-create 2>&1)
create_rc=$?
set -e

assert_ne "$create_rc" "0" "knowledge-create without args exits non-zero"
assert_contains "$create_usage" "-t TYPE" "knowledge-create usage advertises -t TYPE"
assert_contains "$create_usage" "-s SLUG" "knowledge-create usage advertises -s SLUG"
assert_contains "$create_usage" "-b BODY" "knowledge-create usage advertises -b BODY"
assert_contains "$create_usage" "--frontmatter" "knowledge-create usage advertises --frontmatter"
assert_contains "$create_usage" "-S SCOPE" "knowledge-create usage advertises -S SCOPE"
assert_contains "$create_usage" "--ttl" "knowledge-create usage advertises --ttl"
assert_not_contains "$create_usage" "-k KEY" "knowledge-create usage drops legacy -k KEY"
assert_not_contains "$create_usage" "VALUE_JSON" "knowledge-create usage drops legacy VALUE_JSON"

describe "superpos-cli knowledge-update usage (typed flags)"

set +e
update_usage=$(bash "$CLI" knowledge-update HIVE 2>&1)
update_rc=$?
set -e

assert_ne "$update_rc" "0" "knowledge-update with too few args exits non-zero"
assert_contains "$update_usage" "-b BODY" "knowledge-update usage advertises -b BODY"
assert_contains "$update_usage" "--frontmatter" "knowledge-update usage advertises --frontmatter"
assert_contains "$update_usage" "-V VISIBILITY" "knowledge-update usage advertises -V VISIBILITY"
assert_contains "$update_usage" "--ttl" "knowledge-update usage advertises --ttl"
assert_not_contains "$update_usage" "VALUE_JSON" "knowledge-update usage drops legacy VALUE_JSON"

# ── Summary ──────────────────────────────────────────────────────

test_summary
