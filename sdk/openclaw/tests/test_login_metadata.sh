#!/usr/bin/env bash
# test_login_metadata.sh — Tests that superpos_oc_login persists agent metadata.
#
# Validates that after login, agent metadata (hive_id, name) is saved
# to agent.json and exported, consistent with the register flow.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# Set up test config dir
_tmp_config_dir=$(mktemp -d)
_tmp_out="${_tmp_config_dir}/output.txt"
export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN=""

# Load Shell SDK with mocked curl from harness
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# Source auth module
source "${SCRIPT_DIR}/../bin/superpos-auth.sh"

# ── helpers ──────────────────────────────────────────────────────

_setup() {
    unset SUPERPOS_AGENT_ID SUPERPOS_HIVE_ID SUPERPOS_AGENT_NAME SUPERPOS_TOKEN 2>/dev/null || true
    export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
    export SUPERPOS_BASE_URL="http://localhost:9999"
    rm -f "${_tmp_config_dir}/agent.json" "${_tmp_config_dir}/token" "$_tmp_out"
    mock_reset
}

# ── Test: login persists agent metadata ──────────────────────────

describe "Login persists agent metadata to agent.json"

_setup
export SUPERPOS_AGENT_ID="agent-login-01"
export SUPERPOS_AGENT_SECRET="test-secret"

# Mock login response with agent metadata (wrapped in data envelope)
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-login-01","name":"my-openclaw","hive_id":"hive-77"},"token":"tok-abc-123"}}'

# Call directly (not in $()) so env var exports propagate
set +e
superpos_oc_login > "$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "0" "login returns 0"
assert_eq "${SUPERPOS_HIVE_ID:-}" "hive-77" "SUPERPOS_HIVE_ID exported after login"
assert_eq "${SUPERPOS_AGENT_NAME:-}" "my-openclaw" "SUPERPOS_AGENT_NAME exported after login"

# Verify agent.json was written
agent_file="${_tmp_config_dir}/agent.json"
assert_eq "$(jq -r '.hive_id' "$agent_file")" "hive-77" "agent.json contains hive_id"
assert_eq "$(jq -r '.name' "$agent_file")" "my-openclaw" "agent.json contains name"
assert_eq "$(jq -r '.id' "$agent_file")" "agent-login-01" "agent.json contains id"

# ── Test: login with minimal response metadata ───────────────────

describe "Login with minimal response metadata"

_setup
export SUPERPOS_AGENT_ID="agent-login-02"
export SUPERPOS_AGENT_SECRET="test-secret"

# Mock login response without name/hive_id in agent
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-login-02"},"token":"tok-xyz-456"}}'

set +e
superpos_oc_login > "$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "0" "login returns 0 with minimal metadata"

# agent.json should still be written
agent_file="${_tmp_config_dir}/agent.json"
assert_eq "$(jq -r '.id' "$agent_file")" "agent-login-02" "agent.json contains id"

# ── Test: login does not overwrite existing env hive_id ──────────

describe "Login preserves env SUPERPOS_HIVE_ID when response has no hive_id"

_setup
export SUPERPOS_AGENT_ID="agent-login-03"
export SUPERPOS_AGENT_SECRET="test-secret"
export SUPERPOS_HIVE_ID="env-hive-99"

# Mock login response with no hive_id
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-login-03","name":"agent-three"},"token":"tok-789"}}'

set +e
superpos_oc_login > "$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "0" "login returns 0"
assert_eq "${SUPERPOS_HIVE_ID:-}" "env-hive-99" "preserves existing SUPERPOS_HIVE_ID when response has no hive_id"
assert_eq "${SUPERPOS_AGENT_NAME:-}" "agent-three" "SUPERPOS_AGENT_NAME set from response"

# Verify agent.json retains existing hive_id (not overwritten with empty)
agent_file="${_tmp_config_dir}/agent.json"
assert_eq "$(jq -r '.hive_id' "$agent_file")" "env-hive-99" "agent.json retains existing hive_id when response omits it"

# ── Test: previously-persisted hive_id survives login ────────────

describe "Login preserves previously-persisted hive_id from agent.json"

_setup
export SUPERPOS_AGENT_ID="agent-login-05"
export SUPERPOS_AGENT_SECRET="test-secret"
# No SUPERPOS_HIVE_ID in env, but write one to agent.json (simulates prior session)
mkdir -p "$_tmp_config_dir"
jq -n '{id: "agent-login-05", name: "old-name", hive_id: "persisted-hive-88"}' > "${_tmp_config_dir}/agent.json"

# Load persisted agent state (as ensure_auth would)
_superpos_oc_load_agent

# Mock login response with no hive_id
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-login-05","name":"new-name"},"token":"tok-persist"}}'

set +e
superpos_oc_login > "$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "0" "login returns 0"
assert_eq "${SUPERPOS_HIVE_ID:-}" "persisted-hive-88" "SUPERPOS_HIVE_ID retained from prior agent.json"
assert_eq "${SUPERPOS_AGENT_NAME:-}" "new-name" "SUPERPOS_AGENT_NAME updated from response"

agent_file="${_tmp_config_dir}/agent.json"
assert_eq "$(jq -r '.hive_id' "$agent_file")" "persisted-hive-88" "agent.json hive_id preserved from prior session"
assert_eq "$(jq -r '.name' "$agent_file")" "new-name" "agent.json name updated from response"

# ── Test: login response hive_id populates empty env ─────────────

describe "Login response hive_id populates empty env"

_setup
export SUPERPOS_AGENT_ID="agent-login-04"
export SUPERPOS_AGENT_SECRET="test-secret"
# SUPERPOS_HIVE_ID intentionally not set

mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-login-04","name":"agent-four","hive_id":"hive-new-42"},"token":"tok-new"}}'

set +e
superpos_oc_login > "$_tmp_out" 2>&1
rc=$?
set -e

assert_eq "$rc" "0" "login returns 0"
assert_eq "${SUPERPOS_HIVE_ID:-}" "hive-new-42" "SUPERPOS_HIVE_ID populated from login response"
assert_eq "${SUPERPOS_AGENT_NAME:-}" "agent-four" "SUPERPOS_AGENT_NAME populated from login response"

# Verify agent.json
agent_file="${_tmp_config_dir}/agent.json"
assert_eq "$(jq -r '.hive_id' "$agent_file")" "hive-new-42" "agent.json hive_id from login response"

# ── Summary ──────────────────────────────────────────────────────

test_summary
