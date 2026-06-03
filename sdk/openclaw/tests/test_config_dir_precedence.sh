#!/usr/bin/env bash
# test_config_dir_precedence.sh — Tests for _superpos_oc_config_dir() precedence.
#
# Validates the config directory resolution order:
#   1. SUPERPOS_CONFIG_DIR env var (highest priority)
#   2. APIARY_CONFIG_DIR env var (legacy fallback)
#   3. ~/.config/superpos directory (if exists)
#   4. ~/.config/apiary directory (if exists)
#   5. ~/.config/superpos (default, even if not present)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides _superpos_debug, SUPERPOS_OK, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# Source auth module (defines _superpos_oc_config_dir)
source "${SCRIPT_DIR}/../bin/superpos-auth.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_root=$(mktemp -d)
trap 'rm -rf "$_tmp_root"' EXIT

_setup() {
    # Clear env vars between tests
    unset SUPERPOS_CONFIG_DIR APIARY_CONFIG_DIR 2>/dev/null || true
}

# ── Test 1: SUPERPOS_CONFIG_DIR takes highest priority ───────────

describe "SUPERPOS_CONFIG_DIR takes priority (no dir needs to exist)"

_setup
export SUPERPOS_CONFIG_DIR="/some/nonexistent/superpos-dir"

result=$(_superpos_oc_config_dir)
assert_eq "$result" "/some/nonexistent/superpos-dir" \
    "returns SUPERPOS_CONFIG_DIR regardless of directory existence"

# ── Test 2: APIARY_CONFIG_DIR used when SUPERPOS_CONFIG_DIR unset ─

describe "APIARY_CONFIG_DIR used when SUPERPOS_CONFIG_DIR is unset"

_setup
_fake_home="${_tmp_root}/test2_home"
mkdir -p "${_fake_home}/.config/superpos"
export HOME="$_fake_home"
export APIARY_CONFIG_DIR="/legacy/apiary-config"

result=$(_superpos_oc_config_dir)
assert_eq "$result" "/legacy/apiary-config" \
    "returns APIARY_CONFIG_DIR even when ~/.config/superpos exists"

# ── Test 3: ~/.config/superpos when no env vars set ──────────────

describe "Falls back to ~/.config/superpos when it exists"

_setup
_fake_home="${_tmp_root}/test3_home"
mkdir -p "${_fake_home}/.config/superpos"
export HOME="$_fake_home"

result=$(_superpos_oc_config_dir)
assert_eq "$result" "${_fake_home}/.config/superpos" \
    "returns ~/.config/superpos when directory exists and no env vars set"

# ── Test 4: ~/.config/apiary when superpos dir doesn't exist ─────

describe "Falls back to ~/.config/apiary when superpos dir absent"

_setup
_fake_home="${_tmp_root}/test4_home"
mkdir -p "${_fake_home}/.config/apiary"
# Do NOT create ~/.config/superpos
export HOME="$_fake_home"

result=$(_superpos_oc_config_dir)
assert_eq "$result" "${_fake_home}/.config/apiary" \
    "returns ~/.config/apiary when ~/.config/superpos does not exist"

# ── Test 5: default ~/.config/superpos when nothing exists ───────

describe "Defaults to ~/.config/superpos when nothing is configured"

_setup
_fake_home="${_tmp_root}/test5_home"
mkdir -p "${_fake_home}"
# Do NOT create any .config directories
export HOME="$_fake_home"

result=$(_superpos_oc_config_dir)
assert_eq "$result" "${_fake_home}/.config/superpos" \
    "defaults to ~/.config/superpos when no env vars and no directories exist"

# ── Summary ──────────────────────────────────────────────────────

test_summary
