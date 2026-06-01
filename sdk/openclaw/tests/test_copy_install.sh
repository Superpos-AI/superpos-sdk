#!/usr/bin/env bash
# test_copy_install.sh — Tests that SDK resolution works for copy-installed skills.
#
# Simulates the copy-install layout where sdk/shell/ is NOT alongside
# sdk/openclaw/ and the SDK must be found via the bundled lib/ path
# or SUPERPOS_SHELL_SDK env var.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

REAL_BIN="${SCRIPT_DIR}/../bin"
REAL_SDK="${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"

# Create a copy-installed layout (no sdk/shell/ sibling)
_copy_dir="${_tmp_dir}/skills/superpos"
mkdir -p "${_copy_dir}/bin" "${_copy_dir}/lib"
cp "${REAL_BIN}/superpos-cli.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/_resolve-sdk.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/superpos-auth.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/superpos-tasks.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/superpos-knowledge.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/superpos-events.sh" "${_copy_dir}/bin/"
cp "${REAL_BIN}/superpos-daemon.sh" "${_copy_dir}/bin/"

# ── Test: copy install without bundled SDK fails clearly ──────────

describe "Copy install — missing SDK fails with clear error"

set +e
output=$(bash "${_copy_dir}/bin/superpos-cli.sh" help 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "exits non-zero when SDK is missing"
assert_contains "$output" "Fatal: Superpos Shell SDK not found" "error message is descriptive"
assert_contains "$output" "SUPERPOS_SHELL_SDK" "error mentions env var fix"

# ── Test: copy install with bundled lib/ SDK works ────────────────

describe "Copy install — bundled lib/superpos-sdk.sh"

cp "$REAL_SDK" "${_copy_dir}/lib/superpos-sdk.sh"

set +e
output=$(bash "${_copy_dir}/bin/superpos-cli.sh" help 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "exits cleanly with bundled SDK in lib/"
assert_contains "$output" "Usage:" "help output displayed"

# Remove bundled SDK for next test
rm -f "${_copy_dir}/lib/superpos-sdk.sh"

# ── Test: SUPERPOS_SHELL_SDK env var override ───────────────────────

describe "Copy install — SUPERPOS_SHELL_SDK env override"

set +e
output=$(SUPERPOS_SHELL_SDK="$REAL_SDK" bash "${_copy_dir}/bin/superpos-cli.sh" help 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "exits cleanly with SUPERPOS_SHELL_SDK set"
assert_contains "$output" "Usage:" "help output displayed with env override"

# ── Test: repo layout still works (regression) ───────────────────

describe "Repo layout — relative path still resolves"

set +e
output=$(bash "${REAL_BIN}/superpos-cli.sh" help 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "repo-layout invocation exits cleanly"
assert_contains "$output" "Usage:" "help output from repo layout"

# ── Test: module standalone sourcing with bundled SDK ─────────────

describe "Module standalone source — bundled lib/"

cp "$REAL_SDK" "${_copy_dir}/lib/superpos-sdk.sh"

# Source superpos-auth.sh standalone (without cli.sh pre-loading)
set +e
output=$(bash -c '
    unset _SUPERPOS_SDK_LOADED
    source "'"${_copy_dir}/bin/superpos-auth.sh"'" 2>&1
    if declare -f superpos_oc_ensure_auth >/dev/null 2>&1; then
        echo "LOADED_OK"
    else
        echo "LOAD_FAILED"
    fi
' 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "module sources cleanly with bundled SDK"
assert_contains "$output" "LOADED_OK" "auth functions available after standalone load"

# ── Test: SUPERPOS_SHELL_SDK takes priority over other paths ────────

describe "Priority — SUPERPOS_SHELL_SDK wins over lib/"

# Create a marker SDK in lib/ that sets a canary variable
cat > "${_copy_dir}/lib/superpos-sdk.sh" <<'CANARY'
SUPERPOS_SDK_VERSION="canary-lib"
_superpos_debug() { :; }
_superpos_err() { echo "$*" >&2; }
superpos_check_deps() { return 0; }
superpos_load_token() { :; }
SUPERPOS_OK=0
CANARY

# Create a different marker for the env var path
_env_sdk="${_tmp_dir}/env-sdk.sh"
cat > "$_env_sdk" <<'CANARY2'
SUPERPOS_SDK_VERSION="canary-env"
_superpos_debug() { :; }
_superpos_err() { echo "$*" >&2; }
superpos_check_deps() { return 0; }
superpos_load_token() { :; }
SUPERPOS_OK=0
CANARY2

set +e
output=$(SUPERPOS_SHELL_SDK="$_env_sdk" bash "${_copy_dir}/bin/superpos-cli.sh" version 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "exits cleanly with both env and lib/ present"
assert_contains "$output" "canary-env" "SUPERPOS_SHELL_SDK took priority over lib/"

# ── Summary ──────────────────────────────────────────────────────

test_summary
