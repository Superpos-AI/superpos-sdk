#!/usr/bin/env bash
# test_agents.sh — Agent auth and lifecycle endpoint tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"

# ── Register ─────────────────────────────────────────────────────

describe "superpos_register"

mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"agent-1","name":"my-bot","type":"custom","hive_id":"'"$HIVE"'"},"token":"tok-123","refresh_token":"rt-123"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
SUPERPOS_AGENT_REFRESH_TOKEN=""
result=$(superpos_register -n "my-bot" -h "$HIVE" -s "ssssssssssssssss" -t "custom")
assert_eq "$(echo "$result" | jq -r '.agent.name')" "my-bot" "register returns agent name"
assert_eq "$(echo "$result" | jq -r '.token')" "tok-123" "register returns token"

SUPERPOS_AGENT_REFRESH_TOKEN=""
superpos_register -n "my-bot" -h "$HIVE" -s "ssssssssssssssss" -t "custom" >/dev/null
assert_eq "$SUPERPOS_AGENT_REFRESH_TOKEN" "rt-123" "register stores refresh token"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.name')" "my-bot" "register sends name in body"
assert_eq "$(echo "$body" | jq -r '.hive_id')" "$HIVE" "register sends hive_id in body"
assert_eq "$(echo "$body" | jq -r '.secret')" "ssssssssssssssss" "register sends secret in body"

method=$(mock_last_method)
assert_eq "$method" "POST" "register uses POST method"

# Register with optional fields
mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"agent-2"},"token":"tok-456","refresh_token":"rt-456"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
superpos_register -n "bot2" -h "$HIVE" -s "ssssssssssssssss" \
    -c '["code","summarize"]' -m '{"version":"1.0"}' >/dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq '.capabilities | length')" "2" "register sends capabilities array"
assert_eq "$(echo "$body" | jq -r '.metadata.version')" "1.0" "register sends metadata object"

# ── Login ────────────────────────────────────────────────────────

describe "superpos_login"

mock_reset
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-1"},"token":"tok-login","refresh_token":"rt-login"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
SUPERPOS_AGENT_REFRESH_TOKEN=""
result=$(superpos_login -i "agent-1" -s "secret123456789a")
assert_eq "$(echo "$result" | jq -r '.token')" "tok-login" "login returns token"

# Credential storage must be tested without $() subshell
SUPERPOS_TOKEN=""
SUPERPOS_AGENT_REFRESH_TOKEN=""
superpos_login -i "agent-1" -s "secret123456789a" >/dev/null
assert_eq "$SUPERPOS_TOKEN" "tok-login" "login stores token"
assert_eq "$SUPERPOS_AGENT_REFRESH_TOKEN" "rt-login" "login stores refresh token"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.agent_id')" "agent-1" "login sends agent_id"
assert_eq "$(echo "$body" | jq -r '.secret')" "secret123456789a" "login sends secret"

# Login with a numeric-looking secret — must stay a string
mock_reset
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-1"},"token":"tok-num","refresh_token":"rt-num"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
superpos_login -i "agent-1" -s "9999999999999999" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.secret')" "9999999999999999" "numeric-looking secret value preserved"
assert_eq "$(echo "$body" | jq -r '.secret | type')" "string" "numeric-looking secret stays JSON string type"

# ── Refresh token ────────────────────────────────────────────────

describe "superpos_refresh_agent_token"

mock_reset
mock_response POST "/api/v1/agents/token/refresh" 200 \
    '{"data":{"agent":{"id":"agent-1"},"token":"tok-refreshed","refresh_token":"rt-refreshed"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
SUPERPOS_AGENT_REFRESH_TOKEN=""
result=$(superpos_refresh_agent_token -i "agent-1" -r "rt-old")
assert_eq "$(echo "$result" | jq -r '.token')" "tok-refreshed" "refresh returns access token"

SUPERPOS_TOKEN=""
SUPERPOS_AGENT_REFRESH_TOKEN=""
superpos_refresh_agent_token -i "agent-1" -r "rt-old" >/dev/null
assert_eq "$SUPERPOS_TOKEN" "tok-refreshed" "refresh stores access token"
assert_eq "$SUPERPOS_AGENT_REFRESH_TOKEN" "rt-refreshed" "refresh stores rotated refresh token"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.agent_id')" "agent-1" "refresh sends agent_id"
assert_eq "$(echo "$body" | jq -r '.refresh_token')" "rt-old" "refresh sends refresh token"

# ── Rotate key ───────────────────────────────────────────────────

describe "superpos_rotate_key"

mock_reset
mock_response POST "/api/v1/agents/key/rotate" 200 \
    '{"data":{"token":"tok-rotated","refresh_token":"rt-rotated","grace_period_minutes":15},"meta":{},"errors":null}'

SUPERPOS_TOKEN="tok-old"
SUPERPOS_AGENT_REFRESH_TOKEN="rt-old"
result=$(superpos_rotate_key -s "new-secret-12345678" -g 15)
assert_eq "$(echo "$result" | jq -r '.token')" "tok-rotated" "rotate returns token"
assert_eq "$(echo "$result" | jq -r '.refresh_token')" "rt-rotated" "rotate returns refresh token"

SUPERPOS_TOKEN="tok-old"
SUPERPOS_AGENT_REFRESH_TOKEN="rt-old"
superpos_rotate_key -s "new-secret-12345678" -g 15 >/dev/null
assert_eq "$SUPERPOS_TOKEN" "tok-rotated" "rotate stores new token"
assert_eq "$SUPERPOS_AGENT_REFRESH_TOKEN" "rt-rotated" "rotate stores new refresh token"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.new_secret')" "new-secret-12345678" "rotate sends new secret"
assert_eq "$(echo "$body" | jq -r '.grace_period_minutes')" "15" "rotate sends grace period minutes"

# ── Me ───────────────────────────────────────────────────────────

describe "superpos_me"

mock_reset
mock_response GET "/api/v1/agents/me" 200 \
    '{"data":{"id":"agent-1","name":"bot","status":"online","type":"custom","hive_id":"'"$HIVE"'","capabilities":["code"]},"meta":{},"errors":null}'

SUPERPOS_TOKEN="test-token"
result=$(superpos_me)
assert_eq "$(echo "$result" | jq -r '.id')" "agent-1" "me returns agent id"
assert_eq "$(echo "$result" | jq -r '.status')" "online" "me returns agent status"
assert_eq "$(echo "$result" | jq -r '.capabilities[0]')" "code" "me returns capabilities"

method=$(mock_last_method)
assert_eq "$method" "GET" "me uses GET method"

# ── Heartbeat ────────────────────────────────────────────────────

describe "superpos_heartbeat"

mock_reset
mock_response POST "/api/v1/agents/heartbeat" 200 \
    '{"data":{"id":"agent-1","status":"online","last_heartbeat":"2026-02-26T12:00:00Z"},"meta":{},"errors":null}'

SUPERPOS_TOKEN="test-token"
result=$(superpos_heartbeat)
assert_eq "$(echo "$result" | jq -r '.status')" "online" "heartbeat returns status"

method=$(mock_last_method)
assert_eq "$method" "POST" "heartbeat uses POST method"

# Heartbeat with metadata
mock_reset
mock_response POST "/api/v1/agents/heartbeat" 200 \
    '{"data":{"id":"agent-1","status":"online","metadata":{"cpu":42}},"meta":{},"errors":null}'

superpos_heartbeat -m '{"cpu":42}' >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq '.metadata.cpu')" "42" "heartbeat sends metadata in body"

# ── Update status ────────────────────────────────────────────────

describe "superpos_update_status"

mock_reset
mock_response PATCH "/api/v1/agents/status" 200 \
    '{"data":{"id":"agent-1","status":"busy","status_changed_at":"2026-02-26T12:00:00Z"},"meta":{},"errors":null}'

SUPERPOS_TOKEN="test-token"
result=$(superpos_update_status "busy")
assert_eq "$(echo "$result" | jq -r '.status')" "busy" "update_status returns new status"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.status')" "busy" "update_status sends status in body"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "update_status uses PATCH method"

# ── Summary ──────────────────────────────────────────────────────

test_summary
