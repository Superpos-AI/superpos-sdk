#!/usr/bin/env bash
# test_load_agent.sh — Tests for _superpos_oc_load_agent fail-soft behaviour.
#
# Validates that malformed agent.json does not abort the CLI under set -e,
# while valid agent.json still populates env vars correctly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides _superpos_debug, SUPERPOS_OK, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# Source auth module (defines _superpos_oc_load_agent)
source "${SCRIPT_DIR}/../bin/superpos-auth.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_config_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_config_dir"' EXIT

_setup() {
    # Reset env vars between tests
    unset SUPERPOS_AGENT_ID SUPERPOS_HIVE_ID SUPERPOS_AGENT_NAME 2>/dev/null || true
    export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
    rm -f "${_tmp_config_dir}/agent.json"
}

# ── Test: malformed JSON does not abort ──────────────────────────

describe "Malformed agent.json"

_setup
echo "NOT VALID JSON{{{" > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on malformed agent.json"
assert_eq "${SUPERPOS_AGENT_ID:-}" "" "SUPERPOS_AGENT_ID stays empty on malformed file"
assert_eq "${SUPERPOS_HIVE_ID:-}" "" "SUPERPOS_HIVE_ID stays empty on malformed file"
assert_eq "${SUPERPOS_AGENT_NAME:-}" "" "SUPERPOS_AGENT_NAME stays empty on malformed file"

# ── Test: empty file does not abort ──────────────────────────────

describe "Empty agent.json"

_setup
: > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on empty agent.json"
assert_eq "${SUPERPOS_AGENT_ID:-}" "" "SUPERPOS_AGENT_ID stays empty on empty file"

# ── Test: truncated JSON does not abort ──────────────────────────

describe "Truncated JSON agent.json"

_setup
echo '{"id": "abc-123", "hive_id":' > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on truncated JSON"
assert_eq "${SUPERPOS_AGENT_ID:-}" "" "SUPERPOS_AGENT_ID stays empty on truncated JSON"

# ── Test: valid JSON loads correctly ─────────────────────────────

describe "Valid agent.json"

_setup
jq -n '{id: "agent-001", hive_id: "hive-42", name: "test-agent"}' \
    > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on valid agent.json"
assert_eq "${SUPERPOS_AGENT_ID}" "agent-001" "loads SUPERPOS_AGENT_ID from valid file"
assert_eq "${SUPERPOS_HIVE_ID}" "hive-42" "loads SUPERPOS_HIVE_ID from valid file"
assert_eq "${SUPERPOS_AGENT_NAME}" "test-agent" "loads SUPERPOS_AGENT_NAME from valid file"

# ── Test: env vars take precedence over file ─────────────────────

describe "Env vars take precedence"

_setup
export SUPERPOS_AGENT_ID="env-id-999"
export SUPERPOS_HIVE_ID="env-hive-99"
jq -n '{id: "file-id", hive_id: "file-hive", name: "file-agent"}' \
    > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 when env vars already set"
assert_eq "${SUPERPOS_AGENT_ID}" "env-id-999" "keeps env SUPERPOS_AGENT_ID over file"
assert_eq "${SUPERPOS_HIVE_ID}" "env-hive-99" "keeps env SUPERPOS_HIVE_ID over file"
assert_eq "${SUPERPOS_AGENT_NAME}" "file-agent" "loads SUPERPOS_AGENT_NAME when not in env"

# ── Test: missing file is fine ───────────────────────────────────

describe "Missing agent.json"

_setup
# No file created

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 when agent.json does not exist"
assert_eq "${SUPERPOS_AGENT_ID:-}" "" "SUPERPOS_AGENT_ID stays empty when file missing"

# ── Test: malformed JSON + env vars = env vars preserved ─────────

describe "Malformed JSON with env vars set"

_setup
export SUPERPOS_AGENT_ID="env-agent-id"
export SUPERPOS_TOKEN="test-token-123"
echo "CORRUPT!!!" > "${_tmp_config_dir}/agent.json"

set +e
_superpos_oc_load_agent
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 with malformed file and env vars"
assert_eq "${SUPERPOS_AGENT_ID}" "env-agent-id" "preserves SUPERPOS_AGENT_ID from env on malformed file"
assert_eq "${SUPERPOS_TOKEN}" "test-token-123" "preserves SUPERPOS_TOKEN on malformed file"

# ── Summary ──────────────────────────────────────────────────────

test_summary
