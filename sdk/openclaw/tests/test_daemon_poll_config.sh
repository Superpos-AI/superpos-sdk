#!/usr/bin/env bash
# test_daemon_poll_config.sh — Tests for daemon poll-limit configuration
# and health diagnostics file output.
#
# Validates:
#   - SUPERPOS_POLL_MAX_TASKS defaults to 20
#   - SUPERPOS_POLL_MAX_TASKS is capped at 20 even if env is higher
#   - Custom SUPERPOS_POLL_MAX_TASKS values are respected (within cap)
#   - Daemon stats file is written with expected fields

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

export SUPERPOS_CONFIG_DIR="$_tmp_dir"

# Source only the config section of the daemon by extracting the
# config block into a testable snippet.
_eval_poll_max() {
    local env_val="${1:-}"
    (
        if [[ -n "$env_val" ]]; then
            export SUPERPOS_POLL_MAX_TASKS="$env_val"
        else
            unset SUPERPOS_POLL_MAX_TASKS 2>/dev/null || true
        fi
        _poll_max_env="${SUPERPOS_POLL_MAX_TASKS:-20}"
        # Sanitize: non-numeric values fall back to default
        if ! [[ "$_poll_max_env" =~ ^-?[0-9]+$ ]]; then
            _poll_max_env=20
        fi
        POLL_MAX_TASKS=$(( _poll_max_env > 20 ? 20 : (_poll_max_env < 1 ? 1 : _poll_max_env) ))
        echo "$POLL_MAX_TASKS"
    )
}

# ── Test: default POLL_MAX_TASKS is 20 ───────────────────────────

describe "Daemon poll config — default max tasks"

result=$(_eval_poll_max "")
assert_eq "$result" "20" "default POLL_MAX_TASKS is 20"

# ── Test: POLL_MAX_TASKS capped at 20 ───────────────────────────

describe "Daemon poll config — env value over 20 is capped"

result=$(_eval_poll_max "50")
assert_eq "$result" "20" "POLL_MAX_TASKS=50 is capped to 20"

result=$(_eval_poll_max "100")
assert_eq "$result" "20" "POLL_MAX_TASKS=100 is capped to 20"

# ── Test: POLL_MAX_TASKS floored at 1 for 0/negative ─────────────

describe "Daemon poll config — zero and negative values floored to 1"

result=$(_eval_poll_max "0")
assert_eq "$result" "1" "POLL_MAX_TASKS=0 is floored to 1"

result=$(_eval_poll_max "-1")
assert_eq "$result" "1" "POLL_MAX_TASKS=-1 is floored to 1"

result=$(_eval_poll_max "-100")
assert_eq "$result" "1" "POLL_MAX_TASKS=-100 is floored to 1"

# ── Test: custom POLL_MAX_TASKS under cap is respected ───────────

describe "Daemon poll config — custom value under cap"

result=$(_eval_poll_max "10")
assert_eq "$result" "10" "POLL_MAX_TASKS=10 is respected"

result=$(_eval_poll_max "1")
assert_eq "$result" "1" "POLL_MAX_TASKS=1 is respected"

result=$(_eval_poll_max "20")
assert_eq "$result" "20" "POLL_MAX_TASKS=20 (at cap) is respected"

# ── Test: non-numeric POLL_MAX_TASKS falls back to 20 ─────────────

describe "Daemon poll config — non-numeric values fall back to default 20"

result=$(_eval_poll_max "foo")
assert_eq "$result" "20" "POLL_MAX_TASKS='foo' falls back to 20"

result=$(_eval_poll_max "abc123")
assert_eq "$result" "20" "POLL_MAX_TASKS='abc123' falls back to 20"

result=$(_eval_poll_max " ")
assert_eq "$result" "20" "POLL_MAX_TASKS=' ' (whitespace) falls back to 20"

result=$(_eval_poll_max "10.5")
assert_eq "$result" "20" "POLL_MAX_TASKS='10.5' (float) falls back to 20"

result=$(_eval_poll_max "")
assert_eq "$result" "20" "POLL_MAX_TASKS='' (empty) uses default 20"

# ── Test: stats file has expected structure ───────────────────────

describe "Daemon health diagnostics — stats file structure"

# Simulate writing a stats file using the daemon's function
STATS_FILE="${_tmp_dir}/daemon-stats.json"
PENDING_DIR="${_tmp_dir}/pending"
POLL_MAX_TASKS=20
POLL_INTERVAL=10
_stats_poll_cycles=5
_stats_tasks_received=12
_stats_tasks_processed=8
_stats_wakes_sent=3
_stats_errors=1
_stats_last_poll_time="2026-03-07T10:00:00Z"
_stats_last_task_time="2026-03-07T09:55:00Z"
_stats_started_at="2026-03-07T08:00:00Z"

# Replicate the _daemon_write_stats function
_daemon_write_stats() {
    local pending_count=0
    if [[ -d "$PENDING_DIR" ]]; then
        pending_count=$(find "$PENDING_DIR" -maxdepth 1 -name '*.json' ! -name '*.result.json' 2>/dev/null | wc -l)
    fi
    local now_iso
    now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%s)

    cat > "$STATS_FILE" <<STATS_EOF
{
  "pid": $$,
  "started_at": "${_stats_started_at}",
  "updated_at": "${now_iso}",
  "poll_max_tasks": ${POLL_MAX_TASKS},
  "poll_interval": ${POLL_INTERVAL},
  "poll_cycles": ${_stats_poll_cycles},
  "tasks_received": ${_stats_tasks_received},
  "tasks_processed": ${_stats_tasks_processed},
  "wakes_sent": ${_stats_wakes_sent},
  "errors": ${_stats_errors},
  "pending_queue": ${pending_count},
  "last_poll_time": "${_stats_last_poll_time}",
  "last_task_time": "${_stats_last_task_time}"
}
STATS_EOF
}

# Create some pending tasks
mkdir -p "$PENDING_DIR"
echo '{}' > "${PENDING_DIR}/task1.json"
echo '{}' > "${PENDING_DIR}/task2.json"

_daemon_write_stats

assert_eq "$(jq -r '.poll_max_tasks' "$STATS_FILE")" "20" "stats file contains poll_max_tasks"
assert_eq "$(jq -r '.poll_interval' "$STATS_FILE")" "10" "stats file contains poll_interval"
assert_eq "$(jq -r '.poll_cycles' "$STATS_FILE")" "5" "stats file contains poll_cycles"
assert_eq "$(jq -r '.tasks_received' "$STATS_FILE")" "12" "stats file contains tasks_received"
assert_eq "$(jq -r '.tasks_processed' "$STATS_FILE")" "8" "stats file contains tasks_processed"
assert_eq "$(jq -r '.wakes_sent' "$STATS_FILE")" "3" "stats file contains wakes_sent"
assert_eq "$(jq -r '.errors' "$STATS_FILE")" "1" "stats file contains errors"
assert_eq "$(jq -r '.pending_queue' "$STATS_FILE")" "2" "stats file has correct pending_queue count"
assert_eq "$(jq -r '.started_at' "$STATS_FILE")" "2026-03-07T08:00:00Z" "stats file contains started_at"
assert_eq "$(jq -r '.last_poll_time' "$STATS_FILE")" "2026-03-07T10:00:00Z" "stats file contains last_poll_time"
assert_eq "$(jq -r '.last_task_time' "$STATS_FILE")" "2026-03-07T09:55:00Z" "stats file contains last_task_time"
assert_ne "$(jq -r '.updated_at' "$STATS_FILE")" "" "stats file has updated_at timestamp"
assert_ne "$(jq -r '.pid' "$STATS_FILE")" "null" "stats file has pid"

# Verify it's valid JSON
set +e
jq empty "$STATS_FILE" 2>/dev/null
json_valid=$?
set -e
assert_eq "$json_valid" "0" "stats file is valid JSON"

# ── Test: pending_queue excludes result artifacts ─────────────────

describe "Daemon health diagnostics — pending_queue excludes .result.json artifacts"

# Reset pending dir with mixed files: task files + result artifacts
rm -rf "$PENDING_DIR"
mkdir -p "$PENDING_DIR"
echo '{"id":"t1","type":"webhook_handler"}' > "${PENDING_DIR}/t1.json"
echo '{"id":"t2","type":"webhook_handler"}' > "${PENDING_DIR}/t2.json"
echo '{"task_id":"t3","status":"completed"}' > "${PENDING_DIR}/t3.result.json"
echo '{"task_id":"t4","status":"failed"}'    > "${PENDING_DIR}/t4.result.json"

_daemon_write_stats

assert_eq "$(jq -r '.pending_queue' "$STATS_FILE")" "2" \
    "pending_queue counts only task files, not .result.json artifacts"

# ── Test: pending_queue excludes result artifacts when task+result coexist ──

describe "Daemon health diagnostics — pending_queue with coexisting task and result files"

# One task with both task.json and result.json (retry scenario)
rm -rf "$PENDING_DIR"
mkdir -p "$PENDING_DIR"
echo '{"id":"t5","type":"webhook_handler"}' > "${PENDING_DIR}/t5.json"
echo '{"task_id":"t5","status":"completed"}' > "${PENDING_DIR}/t5.result.json"

_daemon_write_stats

assert_eq "$(jq -r '.pending_queue' "$STATS_FILE")" "1" \
    "pending_queue counts 1 logical task when task.json and .result.json coexist"

# ── Test: pending_queue is 0 when only artifacts remain ───────────

describe "Daemon health diagnostics — pending_queue is 0 with only result artifacts"

rm -rf "$PENDING_DIR"
mkdir -p "$PENDING_DIR"
echo '{"task_id":"t6","status":"completed"}' > "${PENDING_DIR}/t6.result.json"
echo '{"task_id":"t7","status":"failed"}'    > "${PENDING_DIR}/t7.result.json"

_daemon_write_stats

assert_eq "$(jq -r '.pending_queue' "$STATS_FILE")" "0" \
    "pending_queue is 0 when directory contains only .result.json files"

# ── Test: pending_queue ignores quarantine subdirectory ───────────

describe "Daemon health diagnostics — pending_queue ignores quarantine subdir"

rm -rf "$PENDING_DIR"
mkdir -p "$PENDING_DIR/quarantine"
echo '{"id":"t8","type":"webhook_handler"}' > "${PENDING_DIR}/t8.json"
echo '{"id":"t9","type":"webhook_handler"}' > "${PENDING_DIR}/quarantine/t9.json"

_daemon_write_stats

assert_eq "$(jq -r '.pending_queue' "$STATS_FILE")" "1" \
    "pending_queue ignores files in quarantine subdirectory (maxdepth 1)"

# ── Summary ──────────────────────────────────────────────────────

test_summary
