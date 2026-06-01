#!/usr/bin/env bash
# test_workflows.sh — Workflow CRUD, run management, and versioning tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
WF="WWWWWWWWWWWWWWWWWWWWWWWWWW"
RUN="RRRRRRRRRRRRRRRRRRRRRRRRRR"

# ── List workflows ─────────────────────────────────────────────────

describe "superpos_list_workflows"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":[{"id":"w1","name":"deploy"},{"id":"w2","name":"test"}],"meta":{"total":2},"errors":null}'

result=$(superpos_list_workflows "$HIVE")
assert_eq "$(echo "$result" | jq 'length')" "2" "list_workflows returns array"
assert_eq "$(echo "$result" | jq -r '.[0].name')" "deploy" "list_workflows first name"

method=$(mock_last_method)
assert_eq "$method" "GET" "list_workflows uses GET method"

# List with pagination
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_workflows "$HIVE" -p 2 -l 10 >/dev/null
url=$(mock_last_url)
assert_contains "$url" "page=2" "list_workflows sends page param"
assert_contains "$url" "per_page=10" "list_workflows sends per_page param"

# List with is_active filter
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":[{"id":"w1","name":"deploy","is_active":true}],"meta":{"total":1},"errors":null}'

superpos_list_workflows "$HIVE" -a true >/dev/null
url=$(mock_last_url)
assert_contains "$url" "is_active=true" "list_workflows sends is_active param"

# List with search filter
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":[{"id":"w1","name":"deploy"}],"meta":{"total":1},"errors":null}'

superpos_list_workflows "$HIVE" -q "deploy" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "search=deploy" "list_workflows sends search param"

# List with all filters combined
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_workflows "$HIVE" -p 1 -l 20 -a false -q "pipe" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "page=1" "list_workflows sends page with all filters"
assert_contains "$url" "per_page=20" "list_workflows sends per_page with all filters"
assert_contains "$url" "is_active=false" "list_workflows sends is_active with all filters"
assert_contains "$url" "search=pipe" "list_workflows sends search with all filters"

# ── Get workflow ───────────────────────────────────────────────────

describe "superpos_get_workflow"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}" 200 \
    '{"data":{"id":"'"$WF"'","name":"deploy","slug":"deploy","trigger_config":{"type":"manual"},"version":1,"is_active":true,"steps":{},"settings":{}},"meta":{},"errors":null}'

result=$(superpos_get_workflow "$HIVE" "$WF")
assert_eq "$(echo "$result" | jq -r '.id')" "$WF" "get_workflow returns id"
assert_eq "$(echo "$result" | jq -r '.name')" "deploy" "get_workflow returns name"
assert_eq "$(echo "$result" | jq -r '.trigger_config.type')" "manual" "get_workflow returns trigger_config"

url=$(mock_last_url)
assert_contains "$url" "/workflows/${WF}" "get_workflow URL contains workflow ID"

# ── Create workflow ────────────────────────────────────────────────

describe "superpos_create_workflow"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":{"id":"new-wf","slug":"build-pipeline","name":"build-pipeline","version":1},"meta":{},"errors":null}'

result=$(superpos_create_workflow "$HIVE" -S "build-pipeline" -n "build-pipeline" -s '{"build":{"type":"task"}}')
assert_eq "$(echo "$result" | jq -r '.name')" "build-pipeline" "create_workflow returns name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.slug')" "build-pipeline" "create_workflow sends slug"
assert_eq "$(echo "$body" | jq -r '.name')" "build-pipeline" "create_workflow sends name"
assert_eq "$(echo "$body" | jq -r '.steps.build.type')" "task" "create_workflow sends steps"
assert_eq "$(echo "$body" | jq -r '.trigger_type')" "null" "create_workflow does not send trigger_type"

method=$(mock_last_method)
assert_eq "$method" "POST" "create_workflow uses POST method"

# Create with all options
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":{"id":"new-wf","slug":"hook-pipeline","name":"hook-pipeline"},"meta":{},"errors":null}'

superpos_create_workflow "$HIVE" \
    -S "hook-pipeline" \
    -n "hook-pipeline" \
    -s '{"build":{"type":"task"}}' \
    -c '{"type":"webhook","url":"https://example.com/hook"}' \
    -d "A webhook workflow" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.trigger_type')" "null" "create_workflow does not send trigger_type"
assert_eq "$(echo "$body" | jq -r '.trigger_config.url')" "https://example.com/hook" "create_workflow sends trigger_config"
assert_eq "$(echo "$body" | jq -r '.description')" "A webhook workflow" "create_workflow sends description"

# Create requires slug, name and steps
assert_exit 1 superpos_create_workflow "$HIVE" -n "test" -s '{"build":{"type":"task"}}' "create_workflow fails without slug"
assert_exit 1 superpos_create_workflow "$HIVE" -S "test" -n "test" "create_workflow fails without steps"

# Create with is_active and settings
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows" 200 \
    '{"data":{"id":"new-wf","slug":"bg-pipeline","name":"bg-pipeline","is_active":false,"settings":{"timeout":300}},"meta":{},"errors":null}'

result=$(superpos_create_workflow "$HIVE" \
    -S "bg-pipeline" \
    -n "bg-pipeline" \
    -s '{"build":{"type":"task"}}' \
    -a false \
    -e '{"timeout":300}')
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.is_active')" "false" "create_workflow sends is_active"
assert_eq "$(echo "$body" | jq -r '.settings.timeout')" "300" "create_workflow sends settings"

# ── Update workflow ────────────────────────────────────────────────

describe "superpos_update_workflow"

mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/workflows/${WF}" 200 \
    '{"data":{"id":"'"$WF"'","name":"renamed","version":2},"meta":{},"errors":null}'

result=$(superpos_update_workflow "$HIVE" "$WF" -n "renamed")
assert_eq "$(echo "$result" | jq -r '.name')" "renamed" "update_workflow returns updated name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.name')" "renamed" "update_workflow sends name"

method=$(mock_last_method)
assert_eq "$method" "PUT" "update_workflow uses PUT method"

url=$(mock_last_url)
assert_contains "$url" "/workflows/${WF}" "update_workflow URL contains workflow ID"

# Update with is_active and settings
mock_reset
mock_response PUT "/api/v1/hives/${HIVE}/workflows/${WF}" 200 \
    '{"data":{"id":"'"$WF"'","name":"deploy","is_active":false,"settings":{"retry_count":5},"version":3},"meta":{},"errors":null}'

result=$(superpos_update_workflow "$HIVE" "$WF" -a false -e '{"retry_count":5}')
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.is_active')" "false" "update_workflow sends is_active"
assert_eq "$(echo "$body" | jq -r '.settings.retry_count')" "5" "update_workflow sends settings"

# ── Delete workflow ────────────────────────────────────────────────

describe "superpos_delete_workflow"

mock_reset
mock_response DELETE "/api/v1/hives/${HIVE}/workflows/${WF}" 204 ""

superpos_delete_workflow "$HIVE" "$WF"
rc=$?
assert_eq "$rc" "0" "delete_workflow returns success"

method=$(mock_last_method)
assert_eq "$method" "DELETE" "delete_workflow uses DELETE method"

url=$(mock_last_url)
assert_contains "$url" "/workflows/${WF}" "delete_workflow URL contains workflow ID"

# ── Run workflow ───────────────────────────────────────────────────

describe "superpos_run_workflow"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":{"id":"run-1","workflow_id":"'"$WF"'","status":"running"},"meta":{},"errors":null}'

result=$(superpos_run_workflow "$HIVE" "$WF")
assert_eq "$(echo "$result" | jq -r '.status')" "running" "run_workflow returns running status"

method=$(mock_last_method)
assert_eq "$method" "POST" "run_workflow uses POST method"

# Run with payload
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":{"id":"run-2","status":"running"},"meta":{},"errors":null}'

superpos_run_workflow "$HIVE" "$WF" -d '{"env":"staging"}' >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.payload.env')" "staging" "run_workflow sends payload"

# ── List workflow runs ─────────────────────────────────────────────

describe "superpos_list_workflow_runs"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":[{"id":"r1","status":"completed"},{"id":"r2","status":"running"}],"meta":{"total":2},"errors":null}'

result=$(superpos_list_workflow_runs "$HIVE" "$WF")
assert_eq "$(echo "$result" | jq 'length')" "2" "list_workflow_runs returns array"
assert_eq "$(echo "$result" | jq -r '.[0].status')" "completed" "list_workflow_runs first status"

method=$(mock_last_method)
assert_eq "$method" "GET" "list_workflow_runs uses GET method"

# List runs with pagination
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_workflow_runs "$HIVE" "$WF" -p 3 -l 5 >/dev/null
url=$(mock_last_url)
assert_contains "$url" "page=3" "list_workflow_runs sends page param"
assert_contains "$url" "per_page=5" "list_workflow_runs sends per_page param"

# List runs with status filter
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":[{"id":"r1","status":"completed"}],"meta":{"total":1},"errors":null}'

superpos_list_workflow_runs "$HIVE" "$WF" -s completed >/dev/null
url=$(mock_last_url)
assert_contains "$url" "status=completed" "list_workflow_runs sends status param"

# List runs with status and pagination
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/runs" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_workflow_runs "$HIVE" "$WF" -p 2 -l 10 -s failed >/dev/null
url=$(mock_last_url)
assert_contains "$url" "page=2" "list_workflow_runs sends page with status"
assert_contains "$url" "per_page=10" "list_workflow_runs sends per_page with status"
assert_contains "$url" "status=failed" "list_workflow_runs sends status with pagination"

# ── Get workflow run ───────────────────────────────────────────────

describe "superpos_get_workflow_run"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/runs/${RUN}" 200 \
    '{"data":{"id":"'"$RUN"'","workflow_id":"'"$WF"'","status":"completed"},"meta":{},"errors":null}'

result=$(superpos_get_workflow_run "$HIVE" "$WF" "$RUN")
assert_eq "$(echo "$result" | jq -r '.id')" "$RUN" "get_workflow_run returns id"
assert_eq "$(echo "$result" | jq -r '.status')" "completed" "get_workflow_run returns status"

url=$(mock_last_url)
assert_contains "$url" "/runs/${RUN}" "get_workflow_run URL contains run ID"

# ── Cancel workflow run ────────────────────────────────────────────

describe "superpos_cancel_workflow_run"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows/${WF}/runs/${RUN}/cancel" 200 \
    '{"data":{"id":"'"$RUN"'","status":"cancelled"},"meta":{},"errors":null}'

result=$(superpos_cancel_workflow_run "$HIVE" "$WF" "$RUN")
assert_eq "$(echo "$result" | jq -r '.status')" "cancelled" "cancel_workflow_run returns cancelled status"

method=$(mock_last_method)
assert_eq "$method" "POST" "cancel_workflow_run uses POST method"

url=$(mock_last_url)
assert_contains "$url" "/runs/${RUN}/cancel" "cancel_workflow_run URL contains /cancel"

# ── Retry workflow run ─────────────────────────────────────────────

describe "superpos_retry_workflow_run"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows/${WF}/runs/${RUN}/retry" 200 \
    '{"data":{"id":"'"$RUN"'","status":"running"},"meta":{},"errors":null}'

result=$(superpos_retry_workflow_run "$HIVE" "$WF" "$RUN")
assert_eq "$(echo "$result" | jq -r '.status')" "running" "retry_workflow_run returns running status"

method=$(mock_last_method)
assert_eq "$method" "POST" "retry_workflow_run uses POST method"

url=$(mock_last_url)
assert_contains "$url" "/runs/${RUN}/retry" "retry_workflow_run URL contains /retry"

# ── List workflow versions ─────────────────────────────────────────

describe "superpos_list_workflow_versions"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/versions" 200 \
    '{"data":[{"version":1,"created_at":"2026-03-01T12:00:00Z"},{"version":2,"created_at":"2026-03-02T12:00:00Z"}],"meta":{},"errors":null}'

result=$(superpos_list_workflow_versions "$HIVE" "$WF")
assert_eq "$(echo "$result" | jq 'length')" "2" "list_workflow_versions returns array"
assert_eq "$(echo "$result" | jq '.[0].version')" "1" "list_workflow_versions first version"

method=$(mock_last_method)
assert_eq "$method" "GET" "list_workflow_versions uses GET method"

# List versions with pagination
mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/versions" 200 \
    '{"data":[],"meta":{"total":0},"errors":null}'

superpos_list_workflow_versions "$HIVE" "$WF" -p 2 -l 10 >/dev/null
url=$(mock_last_url)
assert_contains "$url" "page=2" "list_workflow_versions sends page param"
assert_contains "$url" "per_page=10" "list_workflow_versions sends per_page param"

# ── Get workflow version ───────────────────────────────────────────

describe "superpos_get_workflow_version"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/versions/2" 200 \
    '{"data":{"version":2,"steps":{"build":{"type":"task"}}},"meta":{},"errors":null}'

result=$(superpos_get_workflow_version "$HIVE" "$WF" 2)
assert_eq "$(echo "$result" | jq '.version')" "2" "get_workflow_version returns version"
assert_eq "$(echo "$result" | jq -r '.steps.build.type')" "task" "get_workflow_version returns steps"

url=$(mock_last_url)
assert_contains "$url" "/versions/2" "get_workflow_version URL contains version"

# ── Diff workflow versions ─────────────────────────────────────────

describe "superpos_diff_workflow_versions"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/workflows/${WF}/versions/1/diff/3" 200 \
    '{"data":{"from_version":1,"to_version":3,"steps":{"added":["deploy"],"removed":[],"changed":["build"]},"trigger_config_changed":false,"settings_changed":true,"from":{"id":"v1","workflow_id":"'"$WF"'","version":1,"steps":{},"trigger_config":{},"settings":{},"created_by":"u1","created_at":"2026-03-01T12:00:00+00:00"},"to":{"id":"v3","workflow_id":"'"$WF"'","version":3,"steps":{},"trigger_config":{},"settings":{},"created_by":"u1","created_at":"2026-03-03T12:00:00+00:00"}},"meta":{},"errors":null}'

result=$(superpos_diff_workflow_versions "$HIVE" "$WF" 1 3)
assert_eq "$(echo "$result" | jq '.from_version')" "1" "diff_workflow_versions returns from_version"
assert_eq "$(echo "$result" | jq '.to_version')" "3" "diff_workflow_versions returns to_version"
assert_eq "$(echo "$result" | jq '.steps.added[0]')" '"deploy"' "diff_workflow_versions returns added steps"
assert_eq "$(echo "$result" | jq '.steps.changed[0]')" '"build"' "diff_workflow_versions returns changed steps"
assert_eq "$(echo "$result" | jq '.trigger_config_changed')" "false" "diff_workflow_versions returns trigger_config_changed"
assert_eq "$(echo "$result" | jq '.settings_changed')" "true" "diff_workflow_versions returns settings_changed"
assert_eq "$(echo "$result" | jq '.from.version')" "1" "diff_workflow_versions returns from version object"
assert_eq "$(echo "$result" | jq '.to.version')" "3" "diff_workflow_versions returns to version object"

url=$(mock_last_url)
assert_contains "$url" "/versions/1/diff/3" "diff_workflow_versions URL contains version range"

# ── Rollback workflow version ──────────────────────────────────────

describe "superpos_rollback_workflow_version"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/workflows/${WF}/versions/1/rollback" 200 \
    '{"data":{"workflow":{"id":"'"$WF"'","name":"deploy","version":4},"restored_from_version":1,"new_version":4},"meta":{},"errors":null}'

result=$(superpos_rollback_workflow_version "$HIVE" "$WF" 1)
assert_eq "$(echo "$result" | jq '.new_version')" "4" "rollback_workflow_version returns new_version"
assert_eq "$(echo "$result" | jq '.restored_from_version')" "1" "rollback_workflow_version returns restored_from_version"
assert_eq "$(echo "$result" | jq '.workflow.version')" "4" "rollback_workflow_version returns workflow version"

method=$(mock_last_method)
assert_eq "$method" "POST" "rollback_workflow_version uses POST method"

url=$(mock_last_url)
assert_contains "$url" "/versions/1/rollback" "rollback_workflow_version URL contains /rollback"

# ── Summary ────────────────────────────────────────────────────────

test_summary
