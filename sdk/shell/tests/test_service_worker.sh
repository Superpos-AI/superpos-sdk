#!/usr/bin/env bash
# test_service_worker.sh — Service worker helper tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
TASK="TTTTTTTTTTTTTTTTTTTTTTTTTT"

# ── superpos_data_request ──────────────────────────────────────────

describe "superpos_data_request"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"data_request","status":"pending","hive_id":"'"$HIVE"'"},"meta":{},"errors":null}'

result=$(superpos_data_request "$HIVE" -c "data:gmail" -o "fetch_emails")
assert_eq "$(echo "$result" | jq -r '.id')" "$TASK" "data_request returns task id"
assert_eq "$(echo "$result" | jq -r '.type')" "data_request" "data_request returns data_request type"
assert_eq "$(echo "$result" | jq -r '.status')" "pending" "data_request returns pending status"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.type')" "data_request" "data_request sends type=data_request"
assert_eq "$(echo "$body" | jq -r '.target_capability')" "data:gmail" "data_request sends capability"
assert_eq "$(echo "$body" | jq -r '.payload.operation')" "fetch_emails" "data_request sends operation in payload"
assert_eq "$(echo "$body" | jq -r '.payload.delivery')" "task_result" "data_request defaults delivery to task_result"

method=$(mock_last_method)
assert_eq "$method" "POST" "data_request uses POST"

# With params
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"data_request","status":"pending"},"meta":{},"errors":null}'

superpos_data_request "$HIVE" \
    -c "data:crm" \
    -o "search_deals" \
    -p '{"query":"license","limit":20}' \
    -d "knowledge" \
    -f "array" \
    -C "prev_task_id" >/dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.target_capability')" "data:crm" "data_request sends custom capability"
assert_eq "$(echo "$body" | jq -r '.payload.operation')" "search_deals" "data_request sends operation"
assert_eq "$(echo "$body" | jq -r '.payload.delivery')" "knowledge" "data_request sends custom delivery"
assert_eq "$(echo "$body" | jq -r '.payload.result_format')" "array" "data_request sends result_format"
assert_eq "$(echo "$body" | jq -r '.payload.continuation_of')" "prev_task_id" "data_request sends continuation_of"
assert_eq "$(echo "$body" | jq -r '.payload.params.query')" "license" "data_request sends params"
assert_eq "$(echo "$body" | jq '.payload.params.limit')" "20" "data_request sends params with number"

# With timeout and idempotency key
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"data_request","status":"pending"},"meta":{},"errors":null}'

superpos_data_request "$HIVE" \
    -c "data:http" \
    -o "get" \
    -t 120 \
    -k "idem-key-abc" >/dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq '.timeout_seconds')" "120" "data_request sends timeout_seconds"
assert_eq "$(echo "$body" | jq -r '.idempotency_key')" "idem-key-abc" "data_request sends idempotency_key"

# Missing required args
assert_exit 1 superpos_data_request "$HIVE" -o "fetch_emails" \
    "data_request errors without capability"
assert_exit 1 superpos_data_request "$HIVE" -c "data:gmail" \
    "data_request errors without operation"

# ── superpos_discover_services ─────────────────────────────────────

describe "superpos_discover_services"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/agents" 200 \
    '{"data":[{"id":"A1","name":"gmail-worker","capabilities":["data:gmail"],"type":"service_worker"}],"meta":{},"errors":null}'

result=$(superpos_discover_services "$HIVE")
assert_eq "$(echo "$result" | jq -r '.[0].name')" "gmail-worker" "discover_services returns worker name"
assert_eq "$(echo "$result" | jq -r '.[0].capabilities[0]')" "data:gmail" "discover_services returns capabilities"

method=$(mock_last_method)
assert_eq "$method" "GET" "discover_services uses GET"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/hives/${HIVE}/agents" "discover_services hits agents endpoint"
assert_contains "$url" "data%3A" "discover_services URL-encodes default capability prefix"

# Custom prefix
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/agents" 200 \
    '{"data":[{"id":"B1","name":"custom-worker","capabilities":["custom:foo"],"type":"service_worker"}],"meta":{},"errors":null}'

result=$(superpos_discover_services "$HIVE" -p "custom:")
assert_eq "$(echo "$result" | jq -r '.[0].name')" "custom-worker" "discover_services with custom prefix returns worker"

url=$(mock_last_url)
assert_contains "$url" "custom%3A" "discover_services URL-encodes custom prefix in URL"

# Special characters: % in prefix must be percent-encoded (not reinterpreted by the server)
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/agents" 200 \
    '{"data":[],"meta":{},"errors":null}'

superpos_discover_services "$HIVE" -p "data:foo%bar" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "data%3Afoo%25bar" "discover_services encodes % in prefix"

# Special characters: & in prefix must be percent-encoded (not split the query string)
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/agents" 200 \
    '{"data":[],"meta":{},"errors":null}'

superpos_discover_services "$HIVE" -p "data:foo&bar" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "data%3Afoo%26bar" "discover_services encodes & in prefix"

# Empty result
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/agents" 200 \
    '{"data":[],"meta":{},"errors":null}'

result=$(superpos_discover_services "$HIVE")
assert_eq "$(echo "$result" | jq 'length')" "0" "discover_services returns empty array when no workers"

# ── poll-loop sleep logic (_SUPERPOS_NEXT_POLL_MS) ─────────────────
#
# The example script uses this logic when the queue is empty:
#
#   _wait_ms="${_SUPERPOS_NEXT_POLL_MS:-0}"
#   if [[ "$_wait_ms" -gt 0 ]]; then
#       sleep "$(( (_wait_ms + 999) / 1000 ))"
#   else
#       sleep "$POLL_INTERVAL"
#   fi
#
# We extract and test that logic here without running the full worker loop.

describe "service_worker poll-loop sleep selection"

# Helper: mirrors the empty-queue sleep logic from service_worker_example.sh.
# Returns what would be passed to sleep when count==0.
_poll_sleep_arg() {
    local next_poll_ms="${1:-}"
    local poll_interval="${2:-5}"
    local _wait_ms="${next_poll_ms:-0}"
    if [[ "$_wait_ms" -gt 0 ]]; then
        echo "$(( (_wait_ms + 999) / 1000 ))"
    else
        echo "$poll_interval"
    fi
}

# When _SUPERPOS_NEXT_POLL_MS is non-zero, sleep arg = ceil(ms/1000)
result=$(_poll_sleep_arg 5000 5)
assert_eq "$result" "5" "_SUPERPOS_NEXT_POLL_MS=5000 yields sleep 5"

result=$(_poll_sleep_arg 2500 5)
assert_eq "$result" "3" "_SUPERPOS_NEXT_POLL_MS=2500 yields sleep 3 (ceiling)"

result=$(_poll_sleep_arg 1000 5)
assert_eq "$result" "1" "_SUPERPOS_NEXT_POLL_MS=1000 yields sleep 1"

result=$(_poll_sleep_arg 500 5)
assert_eq "$result" "1" "_SUPERPOS_NEXT_POLL_MS=500 yields sleep 1 (ceiling, never 0)"

# When _SUPERPOS_NEXT_POLL_MS is 0, fall back to POLL_INTERVAL
result=$(_poll_sleep_arg 0 5)
assert_eq "$result" "5" "_SUPERPOS_NEXT_POLL_MS=0 falls back to POLL_INTERVAL"

result=$(_poll_sleep_arg 0 10)
assert_eq "$result" "10" "_SUPERPOS_NEXT_POLL_MS=0 uses custom POLL_INTERVAL"

# When _SUPERPOS_NEXT_POLL_MS is unset (empty), fall back to POLL_INTERVAL
result=$(_poll_sleep_arg "" 5)
assert_eq "$result" "5" "unset _SUPERPOS_NEXT_POLL_MS falls back to POLL_INTERVAL"

result=$(_poll_sleep_arg "" 30)
assert_eq "$result" "30" "unset _SUPERPOS_NEXT_POLL_MS uses custom POLL_INTERVAL"

# ── post-processing backpressure sleep (tasks returned + next_poll_ms > 0) ──
#
# PollBackpressureService may return next_poll_ms > 0 together with tasks
# (rate-limit / high-load).  The worker must sleep AFTER processing the task,
# not only when the queue was empty.
#
# The example script now captures _SUPERPOS_NEXT_POLL_MS before the empty-queue
# branch and, after task processing, runs:
#
#   if [[ "$_next_poll_ms" -gt 0 ]]; then
#       sleep "$(( (_next_poll_ms + 999) / 1000 ))"
#   fi
#
# We extract and test that logic here.

describe "service_worker post-processing backpressure sleep"

# Helper: mirrors the post-task sleep guard from service_worker_example.sh.
# Returns the sleep argument when next_poll_ms > 0, or "no-sleep" otherwise.
_post_task_sleep_arg() {
    local next_poll_ms="${1:-0}"
    if [[ "$next_poll_ms" -gt 0 ]]; then
        echo "$(( (next_poll_ms + 999) / 1000 ))"
    else
        echo "no-sleep"
    fi
}

# Tasks returned + next_poll_ms=2000 → sleep 2 after processing
result=$(_post_task_sleep_arg 2000)
assert_eq "$result" "2" "tasks + next_poll_ms=2000 yields post-task sleep 2"

result=$(_post_task_sleep_arg 500)
assert_eq "$result" "1" "tasks + next_poll_ms=500 yields post-task sleep 1 (ceiling, never 0)"

result=$(_post_task_sleep_arg 1000)
assert_eq "$result" "1" "tasks + next_poll_ms=1000 yields post-task sleep 1"

# Tasks returned + next_poll_ms=0 → no post-task sleep (loop immediately)
result=$(_post_task_sleep_arg 0)
assert_eq "$result" "no-sleep" "tasks + next_poll_ms=0 skips post-task sleep"

# Tasks returned + next_poll_ms unset → no post-task sleep
result=$(_post_task_sleep_arg "")
assert_eq "$result" "no-sleep" "tasks + unset next_poll_ms skips post-task sleep"

test_summary
