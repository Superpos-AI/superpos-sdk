#!/usr/bin/env bash
# test_cli_status_token_path.sh — Status command should respect SUPERPOS_CONFIG_DIR token path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

_tmp_config_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_config_dir"' EXIT

_setup() {
    unset SUPERPOS_TOKEN SUPERPOS_AGENT_ID SUPERPOS_AGENT_NAME SUPERPOS_HIVE_ID SUPERPOS_AGENT_REFRESH_TOKEN SUPERPOS_BASE_URL SUPERPOS_TOKEN_FILE 2>/dev/null || true
    export SUPERPOS_CONFIG_DIR="$_tmp_config_dir"
    rm -f "${_tmp_config_dir}/agent.json" "${_tmp_config_dir}/token" "${_tmp_config_dir}/refresh-token"
}

describe "superpos-cli status loads token from SUPERPOS_CONFIG_DIR before reporting status"

_setup
printf 'token-from-custom-config\n' > "${_tmp_config_dir}/token"
jq -n '{id:"agent-status-1", name:"status-bot", hive_id:"hive-status-1"}' > "${_tmp_config_dir}/agent.json"

set +e
output="$("${SCRIPT_DIR}/../bin/superpos-cli.sh" status 2>&1)"
rc=$?
set -e

assert_eq "$rc" "0" "status command succeeds"
assert_contains "$output" "Agent ID:    agent-status-1" "status loads agent metadata from SUPERPOS_CONFIG_DIR"
assert_contains "$output" "Token:       <set> (masked)" "status reports token loaded from SUPERPOS_CONFIG_DIR token file"
assert_contains "$output" "Auth:        unknown (SUPERPOS_BASE_URL not set)" "status avoids network auth check when base URL is unset"

test_summary
