#!/usr/bin/env bash
# test_legacy_env.sh — Tests for legacy APIARY_* env var fallbacks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"

# ── APIARY_BASE_URL fallback ────────────────────────────────────

describe "Legacy APIARY_* env var fallbacks"

# Test: APIARY_BASE_URL is picked up when SUPERPOS_BASE_URL is unset
_result=$(bash -c '
    unset SUPERPOS_BASE_URL SUPERPOS_TOKEN APIARY_TOKEN APIARY_API_TOKEN
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="legacy-tok"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "$SUPERPOS_BASE_URL"
')
assert_eq "$_result" "https://apiary.legacy" "APIARY_BASE_URL falls back to SUPERPOS_BASE_URL"

# Test: APIARY_API_TOKEN is picked up when SUPERPOS_TOKEN is unset
_result=$(bash -c '
    unset SUPERPOS_TOKEN SUPERPOS_BASE_URL
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="legacy-api-tok"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "$SUPERPOS_TOKEN"
')
assert_eq "$_result" "legacy-api-tok" "APIARY_API_TOKEN falls back to SUPERPOS_TOKEN"

# Test: APIARY_TOKEN is picked up when SUPERPOS_TOKEN and APIARY_API_TOKEN are unset
_result=$(bash -c '
    unset SUPERPOS_TOKEN SUPERPOS_BASE_URL APIARY_API_TOKEN
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_TOKEN="legacy-plain-tok"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "$SUPERPOS_TOKEN"
')
assert_eq "$_result" "legacy-plain-tok" "APIARY_TOKEN falls back to SUPERPOS_TOKEN"

# Test: APIARY_API_TOKEN takes precedence over APIARY_TOKEN
_result=$(bash -c '
    unset SUPERPOS_TOKEN SUPERPOS_BASE_URL
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="canonical"
    export APIARY_TOKEN="plain"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "$SUPERPOS_TOKEN"
')
assert_eq "$_result" "canonical" "APIARY_API_TOKEN takes precedence over APIARY_TOKEN"

# Test: APIARY_HIVE_ID is picked up
_result=$(bash -c '
    unset SUPERPOS_HIVE_ID SUPERPOS_BASE_URL SUPERPOS_TOKEN
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="tok"
    export APIARY_HIVE_ID="legacy-hive"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "${SUPERPOS_HIVE_ID:-EMPTY}"
')
assert_eq "$_result" "legacy-hive" "APIARY_HIVE_ID falls back to SUPERPOS_HIVE_ID"

# Test: APIARY_AGENT_ID is picked up
_result=$(bash -c '
    unset SUPERPOS_AGENT_ID SUPERPOS_BASE_URL SUPERPOS_TOKEN
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="tok"
    export APIARY_AGENT_ID="legacy-agent"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "${SUPERPOS_AGENT_ID:-EMPTY}"
')
assert_eq "$_result" "legacy-agent" "APIARY_AGENT_ID falls back to SUPERPOS_AGENT_ID"

# Test: APIARY_REFRESH_TOKEN is picked up
_result=$(bash -c '
    unset SUPERPOS_AGENT_REFRESH_TOKEN SUPERPOS_BASE_URL SUPERPOS_TOKEN
    export APIARY_BASE_URL="https://apiary.legacy"
    export APIARY_API_TOKEN="tok"
    export APIARY_REFRESH_TOKEN="legacy-refresh"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "${SUPERPOS_AGENT_REFRESH_TOKEN:-EMPTY}"
')
assert_eq "$_result" "legacy-refresh" "APIARY_REFRESH_TOKEN falls back to SUPERPOS_AGENT_REFRESH_TOKEN"

# ── SUPERPOS_* takes precedence over APIARY_* ───────────────────

describe "SUPERPOS_* takes precedence over APIARY_*"

_result=$(bash -c '
    export SUPERPOS_BASE_URL="https://superpos.new"
    export SUPERPOS_TOKEN="new-tok"
    export SUPERPOS_HIVE_ID="new-hive"
    export SUPERPOS_AGENT_ID="new-agent"
    export APIARY_BASE_URL="https://apiary.old"
    export APIARY_API_TOKEN="old-tok"
    export APIARY_HIVE_ID="old-hive"
    export APIARY_AGENT_ID="old-agent"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "$SUPERPOS_BASE_URL|$SUPERPOS_TOKEN|${SUPERPOS_HIVE_ID}|${SUPERPOS_AGENT_ID}"
')
assert_eq "$_result" "https://superpos.new|new-tok|new-hive|new-agent" \
    "SUPERPOS_* vars take precedence over APIARY_* vars"

# ── All APIARY_* vars together produce a working config ──────────

describe "Full APIARY_* config works end-to-end"

# Source in a subshell with only APIARY_* vars, verify all SUPERPOS_* vars are set
_result=$(bash -c '
    unset SUPERPOS_BASE_URL SUPERPOS_TOKEN SUPERPOS_HIVE_ID SUPERPOS_AGENT_ID
    export APIARY_BASE_URL="https://apiary.full"
    export APIARY_API_TOKEN="full-tok"
    export APIARY_HIVE_ID="full-hive"
    export APIARY_AGENT_ID="full-agent"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    echo "${SUPERPOS_BASE_URL}|${SUPERPOS_TOKEN}|${SUPERPOS_HIVE_ID}|${SUPERPOS_AGENT_ID}"
')
assert_eq "$_result" "https://apiary.full|full-tok|full-hive|full-agent" \
    "Full APIARY_* config populates all SUPERPOS_* vars"

# ── Summary ─────────────────────────────────────────────────────

test_summary
