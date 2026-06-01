#!/usr/bin/env bash
# test_tasks.sh — Task lifecycle endpoint tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
TASK="TTTTTTTTTTTTTTTTTTTTTTTTTT"

# ── Create task ──────────────────────────────────────────────────

describe "superpos_create_task"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"summarize","status":"pending","priority":2,"hive_id":"'"$HIVE"'"},"meta":{},"errors":null}'

result=$(superpos_create_task "$HIVE" -t "summarize")
assert_eq "$(echo "$result" | jq -r '.id')" "$TASK" "create_task returns task id"
assert_eq "$(echo "$result" | jq -r '.type')" "summarize" "create_task returns task type"
assert_eq "$(echo "$result" | jq -r '.status')" "pending" "create_task returns pending status"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.type')" "summarize" "create_task sends type in body"

method=$(mock_last_method)
assert_eq "$method" "POST" "create_task uses POST method"

# Create task with all optional fields
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"process","priority":1},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "process" -p 1 -a "AGENT123" -c "code" \
    -d '{"input":"data"}' -T 300 -r 5 >/dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.type')" "process" "create_task with options sends type"
assert_eq "$(echo "$body" | jq '.priority')" "1" "create_task sends priority as number"
assert_eq "$(echo "$body" | jq -r '.target_agent_id')" "AGENT123" "create_task sends target_agent_id"
assert_eq "$(echo "$body" | jq -r '.target_capability')" "code" "create_task sends target_capability"
assert_eq "$(echo "$body" | jq -r '.payload.input')" "data" "create_task sends payload object"
assert_eq "$(echo "$body" | jq '.timeout_seconds')" "300" "create_task sends timeout_seconds"
assert_eq "$(echo "$body" | jq '.max_retries')" "5" "create_task sends max_retries"

# Create task with first-class invoke fields (and legacy payload passthrough)
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"'"$TASK"'","type":"process","priority":1},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "process" \
    -d '{"invoke":{"instructions":"legacy payload instructions","context":{"origin":"payload"}}}' \
    -I "first-class instructions" \
    -X '{"origin":"top-level","attempt":2}' >/dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.payload.invoke.instructions')" "legacy payload instructions" \
    "create_task preserves payload.invoke.instructions passthrough"
assert_eq "$(echo "$body" | jq -r '.invoke.instructions')" "first-class instructions" \
    "create_task sends invoke.instructions as top-level field"
assert_eq "$(echo "$body" | jq -r '.invoke.context.origin')" "top-level" \
    "create_task sends invoke.context as top-level field"
assert_eq "$(echo "$body" | jq '.invoke.context.attempt')" "2" \
    "create_task sends invoke.context JSON payload"

# ── Poll tasks ───────────────────────────────────────────────────

describe "superpos_poll_tasks"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/tasks/poll" 200 \
    '{"data":[{"id":"t1","type":"summarize","status":"pending"},{"id":"t2","type":"code","status":"pending"}],"meta":{"total":2,"next_poll_ms":2000},"errors":null}'

result=$(superpos_poll_tasks "$HIVE")
assert_eq "$(echo "$result" | jq '.data | length')" "2" "poll_tasks returns full envelope with data array"
assert_eq "$(echo "$result" | jq -r '.data[0].id')" "t1" "poll_tasks full envelope first task id correct"
assert_eq "$(echo "$result" | jq '.meta.next_poll_ms')" "2000" "poll_tasks full envelope contains meta.next_poll_ms"
assert_eq "$_SUPERPOS_NEXT_POLL_MS" "2000" "poll_tasks sets _SUPERPOS_NEXT_POLL_MS from meta"

method=$(mock_last_method)
assert_eq "$method" "GET" "poll_tasks uses GET method"

# Poll with filters
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/tasks/poll" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_poll_tasks "$HIVE" -c "code" -l 3 >/dev/null
url=$(mock_last_url)
assert_contains "$url" "capability=code" "poll_tasks sends capability query param"
assert_contains "$url" "limit=3" "poll_tasks sends limit query param"

# ── Claim task ───────────────────────────────────────────────────

describe "superpos_claim_task"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK}/claim" 200 \
    '{"data":{"id":"'"$TASK"'","status":"in_progress","claimed_by":"agent-1","claimed_at":"2026-02-26T12:00:00Z"},"meta":{},"errors":null}'

result=$(superpos_claim_task "$HIVE" "$TASK")
assert_eq "$(echo "$result" | jq -r '.status')" "in_progress" "claim_task returns in_progress status"
assert_eq "$(echo "$result" | jq -r '.claimed_by')" "agent-1" "claim_task returns claimed_by"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "claim_task uses PATCH method"

url=$(mock_last_url)
assert_contains "$url" "/tasks/${TASK}/claim" "claim_task URL contains task ID"

# ── Update progress ──────────────────────────────────────────────

describe "superpos_update_progress"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK}/progress" 200 \
    '{"data":{"id":"'"$TASK"'","progress":50,"status_message":"Halfway there"},"meta":{},"errors":null}'

result=$(superpos_update_progress "$HIVE" "$TASK" -p 50 -m "Halfway there")
assert_eq "$(echo "$result" | jq '.progress')" "50" "update_progress returns progress value"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq '.progress')" "50" "update_progress sends progress as number"
assert_eq "$(echo "$body" | jq -r '.status_message')" "Halfway there" "update_progress sends status_message"

# ── Complete task ────────────────────────────────────────────────

describe "superpos_complete_task"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK}/complete" 200 \
    '{"data":{"id":"'"$TASK"'","status":"completed","progress":100,"result":{"output":"done"}},"meta":{},"errors":null}'

result=$(superpos_complete_task "$HIVE" "$TASK" -r '{"output":"done"}' -m "All done")
assert_eq "$(echo "$result" | jq -r '.status')" "completed" "complete_task returns completed status"
assert_eq "$(echo "$result" | jq '.progress')" "100" "complete_task returns progress 100"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.result.output')" "done" "complete_task sends result object"
assert_eq "$(echo "$body" | jq -r '.status_message')" "All done" "complete_task sends status_message"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "complete_task uses PATCH method"

# Complete without optional fields
mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK}/complete" 200 \
    '{"data":{"id":"'"$TASK"'","status":"completed"},"meta":{},"errors":null}'

superpos_complete_task "$HIVE" "$TASK" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq 'has("result")')" "false" "complete_task omits result when not provided"

# ── Fail task ────────────────────────────────────────────────────

describe "superpos_fail_task"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK}/fail" 200 \
    '{"data":{"id":"'"$TASK"'","status":"failed"},"meta":{},"errors":null}'

result=$(superpos_fail_task "$HIVE" "$TASK" -e '{"type":"ValueError","message":"Bad input"}' -m "Unhandled error")
assert_eq "$(echo "$result" | jq -r '.status')" "failed" "fail_task returns failed status"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.error.type')" "ValueError" "fail_task sends error object"
assert_eq "$(echo "$body" | jq -r '.status_message')" "Unhandled error" "fail_task sends status_message"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "fail_task uses PATCH method"

# ── Summary ──────────────────────────────────────────────────────

test_summary
