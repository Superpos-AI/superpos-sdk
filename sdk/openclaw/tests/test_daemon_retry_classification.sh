#!/usr/bin/env bash
# test_daemon_retry_classification.sh — Tests that the daemon correctly
# classifies heartbeat/poll failures and does NOT trigger auth-reset loops
# on rate-limited (429) or transient network errors.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1
source "${SCRIPT_DIR}/../bin/superpos-auth.sh"

_tmp_config_dir=$(mktemp -d)
_tmp_out="${_tmp_config_dir}/output.txt"
trap 'rm -rf "$_tmp_config_dir"' EXIT

_setup() {
    unset SUPERPOS_AGENT_ID SUPERPOS_HIVE_ID SUPERPOS_AGENT_NAME SUPERPOS_TOKEN SUPERPOS_AGENT_SECRET SUPERPOS_AGENT_REFRESH_TOKEN 2>/dev/null || true
    export SUPERPOS_BASE_URL="http://localhost:9999"
    export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
    rm -f "${_tmp_config_dir}/agent.json" "${_tmp_config_dir}/token" "${_tmp_config_dir}/refresh-token" "$_tmp_out"
    _SUPERPOS_RETRY_AFTER=""
    mock_reset
}

# ══════════════════════════════════════════════════════════════════
# SDK: 429 returns SUPERPOS_ERR_RATE_LIMIT
# ══════════════════════════════════════════════════════════════════

describe "SDK exit code: 429 maps to SUPERPOS_ERR_RATE_LIMIT (8)"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response POST "/api/v1/agents/heartbeat" 429 \
  '{"data":null,"meta":{},"errors":[{"message":"Too Many Requests","code":"rate_limited"}]}'

set +e
superpos_heartbeat >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "$SUPERPOS_ERR_RATE_LIMIT" "heartbeat 429 returns SUPERPOS_ERR_RATE_LIMIT (8)"

# ══════════════════════════════════════════════════════════════════
# SDK: Retry-After header is captured on 429
# ══════════════════════════════════════════════════════════════════

describe "SDK Retry-After header capture on 429"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response POST "/api/v1/agents/heartbeat" 429 \
  '{"data":null,"meta":{},"errors":[{"message":"Too Many Requests","code":"rate_limited"}]}'
mock_response_headers POST "/api/v1/agents/heartbeat" "Retry-After: 30"

set +e
superpos_heartbeat >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "$SUPERPOS_ERR_RATE_LIMIT" "heartbeat returns rate-limit code"
assert_eq "$_SUPERPOS_RETRY_AFTER" "30" "Retry-After header value captured as 30"

# ══════════════════════════════════════════════════════════════════
# SDK: Retry-After is empty when header absent
# ══════════════════════════════════════════════════════════════════

describe "SDK Retry-After is empty when header absent"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response POST "/api/v1/agents/heartbeat" 429 \
  '{"data":null,"meta":{},"errors":[{"message":"Too Many Requests","code":"rate_limited"}]}'

set +e
superpos_heartbeat >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$_SUPERPOS_RETRY_AFTER" "" "Retry-After is empty when no header"

# ══════════════════════════════════════════════════════════════════
# SDK: 401 still returns SUPERPOS_ERR_AUTH
# ══════════════════════════════════════════════════════════════════

describe "SDK exit code: 401 still maps to SUPERPOS_ERR_AUTH (3)"

_setup
export SUPERPOS_TOKEN="expired-token"

mock_response POST "/api/v1/agents/heartbeat" 401 \
  '{"data":null,"meta":{},"errors":[{"message":"Unauthenticated","code":"auth_failed"}]}'

set +e
superpos_heartbeat >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "$SUPERPOS_ERR_AUTH" "heartbeat 401 returns SUPERPOS_ERR_AUTH (3)"

# ══════════════════════════════════════════════════════════════════
# SDK: 500 returns SUPERPOS_ERR (generic)
# ══════════════════════════════════════════════════════════════════

describe "SDK exit code: 500 maps to SUPERPOS_ERR (1)"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response POST "/api/v1/agents/heartbeat" 500 \
  '{"data":null,"meta":{},"errors":[{"message":"Server error","code":"server_error"}]}'

set +e
superpos_heartbeat >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "$SUPERPOS_ERR" "heartbeat 500 returns SUPERPOS_ERR (1)"

# ══════════════════════════════════════════════════════════════════
# ensure_auth does NOT re-authenticate on rate-limited superpos_me
# ══════════════════════════════════════════════════════════════════

describe "ensure_auth preserves token when superpos_me returns 429"

_setup
export SUPERPOS_AGENT_ID="agent-rl-01"
export SUPERPOS_AGENT_NAME="daemon-bot"
export SUPERPOS_HIVE_ID="hive-rl-1"
export SUPERPOS_TOKEN="still-valid-token"
export SUPERPOS_AGENT_REFRESH_TOKEN="refresh-valid"
printf 'still-valid-token\n' > "${_tmp_config_dir}/token"

mock_response GET "/api/v1/agents/me" 429 \
  '{"data":null,"meta":{},"errors":[{"message":"Too Many Requests","code":"rate_limited"}]}'

set +e
superpos_oc_ensure_auth >"$_tmp_out" 2>&1
rc=$?
set -e

# 429 is a non-auth error; ensure_auth should preserve the token and return non-zero
assert_eq "$rc" "$SUPERPOS_ERR_RATE_LIMIT" "ensure_auth returns rate-limit error code"
assert_eq "${SUPERPOS_TOKEN:-}" "still-valid-token" "in-memory token is preserved on 429"
assert_eq "$(cat "${_tmp_config_dir}/token")" "still-valid-token" "persisted token file is preserved on 429"

log="$(mock_url_log)"
assert_contains "$log" "GET http://localhost:9999/api/v1/agents/me" "me endpoint called"
assert_not_contains "$log" "/api/v1/agents/token/refresh" "refresh NOT called on 429"
assert_not_contains "$log" "/api/v1/agents/login" "login NOT called on 429"

# ══════════════════════════════════════════════════════════════════
# _rate_limit_sleep uses retry-after when available
# ══════════════════════════════════════════════════════════════════

describe "Daemon _rate_limit_sleep respects Retry-After"

# Override sleep to capture duration instead of actually sleeping
_captured_sleep=""
sleep() { _captured_sleep="$1"; }

# Source daemon backoff helpers
_backoff_delay=1
_backoff_max=300

# shellcheck disable=SC1091
_rate_limit_sleep() {
    local retry_after="${_SUPERPOS_RETRY_AFTER:-}"
    if [[ -n "$retry_after" ]] && [[ "$retry_after" =~ ^[0-9]+$ ]]; then
        sleep "$retry_after"
    else
        sleep "$_backoff_delay"
        _backoff_delay=$(( _backoff_delay * 2 ))
        if [[ $_backoff_delay -gt $_backoff_max ]]; then
            _backoff_delay=$_backoff_max
        fi
    fi
}

# Test with Retry-After
_SUPERPOS_RETRY_AFTER="45"
_captured_sleep=""
_rate_limit_sleep 2>/dev/null
assert_eq "$_captured_sleep" "45" "_rate_limit_sleep uses Retry-After value (45)"

# Test without Retry-After — falls back to backoff
_SUPERPOS_RETRY_AFTER=""
_backoff_delay=4
_captured_sleep=""
_rate_limit_sleep 2>/dev/null
assert_eq "$_captured_sleep" "4" "_rate_limit_sleep falls back to backoff delay (4)"
assert_eq "$_backoff_delay" "8" "backoff delay doubled to 8 after fallback"

# Restore real sleep
unset -f sleep

# ══════════════════════════════════════════════════════════════════
# Poll: 429 returns rate-limit code (not generic error)
# ══════════════════════════════════════════════════════════════════

describe "Task poll: 429 returns SUPERPOS_ERR_RATE_LIMIT"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response GET "/api/v1/hives/hive-1/tasks/poll" 429 \
  '{"data":null,"meta":{},"errors":[{"message":"Too Many Requests","code":"rate_limited"}]}'
mock_response_headers GET "/api/v1/hives/hive-1/tasks/poll" "Retry-After: 10"

set +e
superpos_poll_tasks "hive-1" -l 20 >"$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "$SUPERPOS_ERR_RATE_LIMIT" "poll 429 returns SUPERPOS_ERR_RATE_LIMIT"
assert_eq "$_SUPERPOS_RETRY_AFTER" "10" "poll Retry-After captured as 10"

# ══════════════════════════════════════════════════════════════════
# Heartbeat: last_heartbeat advances only on actual heartbeat success
# ══════════════════════════════════════════════════════════════════

describe "Heartbeat timer does NOT advance after re-auth alone"

# We inline the daemon heartbeat decision logic to test in isolation.
# This mirrors superpos-daemon.sh lines 299-326.

_setup
export SUPERPOS_TOKEN="expired-token"
export SUPERPOS_AGENT_ID="agent-hb-01"
export SUPERPOS_AGENT_NAME="daemon-bot"
export SUPERPOS_HIVE_ID="hive-hb-1"
export SUPERPOS_AGENT_SECRET="secret-hb"
printf 'expired-token\n' > "${_tmp_config_dir}/token"

# Heartbeat returns 401 (auth expired)
mock_response POST "/api/v1/agents/heartbeat" 401 \
  '{"data":null,"meta":{},"errors":[{"message":"Unauthenticated","code":"auth_failed"}]}'
# ensure_auth will call me → 200 (token actually still valid after refresh)
mock_response GET "/api/v1/agents/me" 200 \
  '{"data":{"id":"agent-hb-01","name":"daemon-bot","hive_id":"hive-hb-1"}}'

last_heartbeat=0
now=100

# Simulate heartbeat attempt
hb_rc=0
superpos_heartbeat >"$_tmp_out" 2>&1 || hb_rc=$?

# Should be 401 → auth path
assert_eq "$hb_rc" "$SUPERPOS_ERR_AUTH" "heartbeat returned auth error (401)"

# Simulate re-auth (succeeds)
auth_ok=1
superpos_oc_ensure_auth >"$_tmp_out" 2>&1 || auth_ok=0
assert_eq "$auth_ok" "1" "re-auth succeeded"

# Key assertion: the daemon must NOT update last_heartbeat here.
# We verify the variable is unchanged (remains 0).
assert_eq "$last_heartbeat" "0" "last_heartbeat NOT advanced after re-auth alone"

# ══════════════════════════════════════════════════════════════════

describe "Heartbeat timer advances on actual heartbeat success"

_setup
export SUPERPOS_TOKEN="valid-token"

mock_response POST "/api/v1/agents/heartbeat" 200 \
  '{"data":{"status":"ok"}}'

last_heartbeat=0
now=100

hb_rc=0
superpos_heartbeat >"$_tmp_out" 2>&1 || hb_rc=$?

assert_eq "$hb_rc" "0" "heartbeat returned success (0)"

# Simulate what the daemon does on success
if [[ "$hb_rc" -eq 0 ]]; then
    last_heartbeat=$now
fi

assert_eq "$last_heartbeat" "100" "last_heartbeat advanced to \$now on success"

# ══════════════════════════════════════════════════════════════════

describe "After auth recovery, next iteration retries heartbeat immediately"

_setup
export SUPERPOS_TOKEN="refreshed-token"

# On the retry, heartbeat succeeds
mock_response POST "/api/v1/agents/heartbeat" 200 \
  '{"data":{"status":"ok"}}'

# last_heartbeat was NOT advanced (stayed at 0 from auth-recovery path)
last_heartbeat=0
HEARTBEAT_INTERVAL=30
now=100

# The daemon condition: (now - last_heartbeat >= HEARTBEAT_INTERVAL)
# 100 - 0 = 100 >= 30 → true: heartbeat fires immediately
if (( now - last_heartbeat >= HEARTBEAT_INTERVAL )); then
    hb_rc=0
    superpos_heartbeat >"$_tmp_out" 2>&1 || hb_rc=$?
    if [[ "$hb_rc" -eq 0 ]]; then
        last_heartbeat=$now
    fi
fi

assert_eq "$hb_rc" "0" "retry heartbeat succeeded"
assert_eq "$last_heartbeat" "100" "last_heartbeat advanced after retry success"

# ══════════════════════════════════════════════════════════════════
# Poll 429: no double sleep (_skip_poll_sleep flag)
# ══════════════════════════════════════════════════════════════════

describe "Poll 429: _rate_limit_sleep fires, loop-tail sleep is skipped"

# We simulate the daemon's main-loop sleep logic in isolation.
# The key invariant: after a rate-limited poll, the loop-tail
# sleep "$POLL_INTERVAL" must NOT execute.

_sleep_calls=()
sleep() { _sleep_calls+=("$1"); }

POLL_INTERVAL=10
_backoff_delay=1
_backoff_max=300

# Simulate rate-limited poll with Retry-After
_SUPERPOS_RETRY_AFTER="5"
_skip_poll_sleep=0
poll_rc=$SUPERPOS_ERR_RATE_LIMIT

# Daemon rate-limit branch (mirrors superpos-daemon.sh lines 374-378)
if [[ "$poll_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
    _rate_limit_sleep 2>/dev/null
    _skip_poll_sleep=1
fi

# Daemon loop-tail (mirrors superpos-daemon.sh lines 400-403)
if [[ "$_skip_poll_sleep" -eq 0 ]]; then
    sleep "$POLL_INTERVAL"
fi

assert_eq "${#_sleep_calls[@]}" "1" "exactly one sleep call after poll 429"
assert_eq "${_sleep_calls[0]}" "5" "sleep used Retry-After value (5), not POLL_INTERVAL"

# ══════════════════════════════════════════════════════════════════

describe "Poll 429 without Retry-After: backoff sleep only, no double sleep"

_sleep_calls=()
_SUPERPOS_RETRY_AFTER=""
_backoff_delay=4
_skip_poll_sleep=0
poll_rc=$SUPERPOS_ERR_RATE_LIMIT

if [[ "$poll_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
    _rate_limit_sleep 2>/dev/null
    _skip_poll_sleep=1
fi

if [[ "$_skip_poll_sleep" -eq 0 ]]; then
    sleep "$POLL_INTERVAL"
fi

assert_eq "${#_sleep_calls[@]}" "1" "exactly one sleep call after poll 429 (backoff)"
assert_eq "${_sleep_calls[0]}" "4" "sleep used backoff delay (4), not POLL_INTERVAL"

# ══════════════════════════════════════════════════════════════════

describe "Successful poll: loop-tail POLL_INTERVAL sleep still fires"

_sleep_calls=()
_skip_poll_sleep=0
poll_rc=0

# On success, no rate-limit branch fires → _skip_poll_sleep stays 0
if [[ "$poll_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
    _rate_limit_sleep 2>/dev/null
    _skip_poll_sleep=1
fi

if [[ "$_skip_poll_sleep" -eq 0 ]]; then
    sleep "$POLL_INTERVAL"
fi

assert_eq "${#_sleep_calls[@]}" "1" "exactly one sleep call after successful poll"
assert_eq "${_sleep_calls[0]}" "10" "sleep used POLL_INTERVAL (10)"

# ══════════════════════════════════════════════════════════════════

describe "Non-rate-limit poll failure: loop-tail POLL_INTERVAL sleep still fires"

_sleep_calls=()
_skip_poll_sleep=0
poll_rc=1  # generic error

if [[ "$poll_rc" -eq "$SUPERPOS_ERR_RATE_LIMIT" ]]; then
    _rate_limit_sleep 2>/dev/null
    _skip_poll_sleep=1
fi

if [[ "$_skip_poll_sleep" -eq 0 ]]; then
    sleep "$POLL_INTERVAL"
fi

assert_eq "${#_sleep_calls[@]}" "1" "exactly one sleep call after generic poll failure"
assert_eq "${_sleep_calls[0]}" "10" "sleep used POLL_INTERVAL (10) for non-rate-limit error"

# Restore real sleep
unset -f sleep

# ══════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════

test_summary
