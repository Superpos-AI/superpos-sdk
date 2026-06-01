#!/usr/bin/env bash
# test_schedules.sh — Schedule CRUD endpoint tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
SCHED="SSSSSSSSSSSSSSSSSSSSSSSSSS"

# ── List schedules ──────────────────────────────────────────────

describe "superpos_list_schedules"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/schedules" 200 \
    '{"data":[{"id":"s1","name":"nightly","status":"active"},{"id":"s2","name":"hourly","status":"paused"}],"meta":{"total":2},"errors":null}'

result=$(superpos_list_schedules "$HIVE")
assert_eq "$(echo "$result" | jq 'length')" "2" "list_schedules returns array"
assert_eq "$(echo "$result" | jq -r '.[0].name')" "nightly" "list_schedules first name"

method=$(mock_last_method)
assert_eq "$method" "GET" "list_schedules uses GET method"

# List with status filter
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/schedules" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_schedules "$HIVE" -s "active" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "status=active" "list_schedules sends status filter"

# ── Get schedule ────────────────────────────────────────────────

describe "superpos_get_schedule"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/schedules/${SCHED}" 200 \
    '{"data":{"id":"'"$SCHED"'","name":"nightly","trigger_type":"cron","cron_expression":"0 2 * * *","status":"active"},"meta":{},"errors":null}'

result=$(superpos_get_schedule "$HIVE" "$SCHED")
assert_eq "$(echo "$result" | jq -r '.id')" "$SCHED" "get_schedule returns id"
assert_eq "$(echo "$result" | jq -r '.name')" "nightly" "get_schedule returns name"
assert_eq "$(echo "$result" | jq -r '.trigger_type')" "cron" "get_schedule returns trigger_type"

url=$(mock_last_url)
assert_contains "$url" "/schedules/${SCHED}" "get_schedule URL contains schedule ID"

# ── Create schedule ─────────────────────────────────────────────

describe "superpos_create_schedule"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/schedules" 200 \
    '{"data":{"id":"new-sched","name":"nightly-report","trigger_type":"cron","task_type":"generate_report","status":"active"},"meta":{},"errors":null}'

result=$(superpos_create_schedule "$HIVE" -n "nightly-report" -g "cron" -t "generate_report" -c "0 2 * * *" -p 3)
assert_eq "$(echo "$result" | jq -r '.name')" "nightly-report" "create_schedule returns name"
assert_eq "$(echo "$result" | jq -r '.trigger_type')" "cron" "create_schedule returns trigger_type"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.name')" "nightly-report" "create_schedule sends name"
assert_eq "$(echo "$body" | jq -r '.trigger_type')" "cron" "create_schedule sends trigger_type"
assert_eq "$(echo "$body" | jq -r '.task_type')" "generate_report" "create_schedule sends task_type"
assert_eq "$(echo "$body" | jq -r '.cron_expression')" "0 2 * * *" "create_schedule sends cron_expression"
assert_eq "$(echo "$body" | jq '.task_priority')" "3" "create_schedule sends task_priority as number"

method=$(mock_last_method)
assert_eq "$method" "POST" "create_schedule uses POST method"

# Create requires name, trigger_type, task_type
assert_exit 1 superpos_create_schedule "$HIVE" -n "test" -g "cron" "create_schedule fails without task_type"

# ── Update schedule ─────────────────────────────────────────────

describe "superpos_update_schedule"

mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/schedules/${SCHED}" 200 \
    '{"data":{"id":"'"$SCHED"'","name":"nightly-report","cron_expression":"0 3 * * *","task_priority":5,"status":"active"},"meta":{},"errors":null}'

result=$(superpos_update_schedule "$HIVE" "$SCHED" -c "0 3 * * *" -p 5)
assert_eq "$(echo "$result" | jq -r '.cron_expression')" "0 3 * * *" "update_schedule returns updated cron"
assert_eq "$(echo "$result" | jq '.task_priority')" "5" "update_schedule returns updated priority"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.cron_expression')" "0 3 * * *" "update_schedule sends cron_expression"
assert_eq "$(echo "$body" | jq '.task_priority')" "5" "update_schedule sends task_priority as number"

method=$(mock_last_method)
assert_eq "$method" "PUT" "update_schedule uses PUT method"

url=$(mock_last_url)
assert_contains "$url" "/schedules/${SCHED}" "update_schedule URL contains schedule ID"

# Update with name only
mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/schedules/${SCHED}" 200 \
    '{"data":{"id":"'"$SCHED"'","name":"renamed"},"meta":{},"errors":null}'

superpos_update_schedule "$HIVE" "$SCHED" -n "renamed" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.name')" "renamed" "update_schedule sends only provided fields (name)"

# Update with overlap_policy and expires_at
mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/schedules/${SCHED}" 200 \
    '{"data":{"id":"'"$SCHED"'","overlap_policy":"skip","expires_at":"2026-12-31T23:59:59Z"},"meta":{},"errors":null}'

superpos_update_schedule "$HIVE" "$SCHED" -o "skip" -e "2026-12-31T23:59:59Z" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.overlap_policy')" "skip" "update_schedule sends overlap_policy"
assert_eq "$(echo "$body" | jq -r '.expires_at')" "2026-12-31T23:59:59Z" "update_schedule sends expires_at"

# ── Delete schedule ─────────────────────────────────────────────

describe "superpos_delete_schedule"

mock_reset
mock_response DELETE "/api/v1/hives/${HIVE}/schedules/${SCHED}" 204 ""

superpos_delete_schedule "$HIVE" "$SCHED"
rc=$?
assert_eq "$rc" "0" "delete_schedule returns success"

method=$(mock_last_method)
assert_eq "$method" "DELETE" "delete_schedule uses DELETE method"

url=$(mock_last_url)
assert_contains "$url" "/schedules/${SCHED}" "delete_schedule URL contains schedule ID"

# ── Pause schedule ──────────────────────────────────────────────

describe "superpos_pause_schedule"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/schedules/${SCHED}/pause" 200 \
    '{"data":{"id":"'"$SCHED"'","status":"paused"},"meta":{},"errors":null}'

result=$(superpos_pause_schedule "$HIVE" "$SCHED")
assert_eq "$(echo "$result" | jq -r '.status')" "paused" "pause_schedule returns paused status"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "pause_schedule uses PATCH method"

url=$(mock_last_url)
assert_contains "$url" "/schedules/${SCHED}/pause" "pause_schedule URL contains /pause"

# ── Resume schedule ─────────────────────────────────────────────

describe "superpos_resume_schedule"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/schedules/${SCHED}/resume" 200 \
    '{"data":{"id":"'"$SCHED"'","status":"active"},"meta":{},"errors":null}'

result=$(superpos_resume_schedule "$HIVE" "$SCHED")
assert_eq "$(echo "$result" | jq -r '.status')" "active" "resume_schedule returns active status"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "resume_schedule uses PATCH method"

url=$(mock_last_url)
assert_contains "$url" "/schedules/${SCHED}/resume" "resume_schedule URL contains /resume"

# ── Summary ─────────────────────────────────────────────────────

test_summary
