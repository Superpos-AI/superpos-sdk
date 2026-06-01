#!/usr/bin/env bash
# test_lifecycle_config_dir.sh — Tests for _LIFECYCLE_CONFIG_DIR resolution.
#
# Validates that the lifecycle module's _LIFECYCLE_CONFIG_DIR uses the
# shared _superpos_oc_config_dir() resolver, inheriting the full
# precedence chain:
#   1. SUPERPOS_CONFIG_DIR env var (highest priority)
#   2. APIARY_CONFIG_DIR env var (legacy fallback)
#   3. ~/.config/superpos (default)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides _superpos_debug, SUPERPOS_OK, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# ── helpers ──────────────────────────────────────────────────────

_tmp_root=$(mktemp -d)
trap 'rm -rf "$_tmp_root"' EXIT

# Source the lifecycle module in a subshell with controlled env,
# then print _LIFECYCLE_CONFIG_DIR.  This avoids global variable
# pollution between test cases.
_get_lifecycle_config_dir() {
    (
        # Unset any previous config dir variables
        unset SUPERPOS_CONFIG_DIR APIARY_CONFIG_DIR 2>/dev/null || true

        # Apply caller's env overrides (passed as arguments)
        eval "$@"

        # Source auth (defines _superpos_oc_config_dir)
        source "${SCRIPT_DIR}/../bin/superpos-auth.sh"

        # Source lifecycle (sets _LIFECYCLE_CONFIG_DIR)
        source "${SCRIPT_DIR}/../bin/superpos-task-lifecycle.sh"

        echo "$_LIFECYCLE_CONFIG_DIR"
    )
}

# ── Test 1: SUPERPOS_CONFIG_DIR takes highest priority ───────────

describe "lifecycle: SUPERPOS_CONFIG_DIR takes priority"

result=$(_get_lifecycle_config_dir \
    'export SUPERPOS_CONFIG_DIR="/custom/superpos-dir"')

assert_eq "$result" "/custom/superpos-dir" \
    "_LIFECYCLE_CONFIG_DIR uses SUPERPOS_CONFIG_DIR when set"

# ── Test 2: APIARY_CONFIG_DIR used when SUPERPOS_CONFIG_DIR unset ─

describe "lifecycle: APIARY_CONFIG_DIR used as legacy fallback"

_fake_home="${_tmp_root}/test2_home"
mkdir -p "${_fake_home}"

result=$(_get_lifecycle_config_dir \
    "export HOME=\"${_fake_home}\"" \
    'export APIARY_CONFIG_DIR="/legacy/apiary-config"')

assert_eq "$result" "/legacy/apiary-config" \
    "_LIFECYCLE_CONFIG_DIR falls back to APIARY_CONFIG_DIR"

# ── Test 3: default ~/.config/superpos when nothing is configured ─

describe "lifecycle: defaults to ~/.config/superpos when nothing configured"

_fake_home="${_tmp_root}/test3_home"
mkdir -p "${_fake_home}"

result=$(_get_lifecycle_config_dir \
    "export HOME=\"${_fake_home}\"")

assert_eq "$result" "${_fake_home}/.config/superpos" \
    "_LIFECYCLE_CONFIG_DIR defaults to ~/.config/superpos"

# ── Summary ──────────────────────────────────────────────────────

test_summary
