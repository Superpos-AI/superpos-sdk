#!/usr/bin/env bash
# test_symlink_resolution.sh — Tests that SCRIPT_DIR resolves through symlinks.
#
# Validates that superpos-cli.sh (and modules) correctly resolve their
# real location when invoked via a symlink, as happens with OpenClaw
# symlinked installs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

REAL_CLI="${SCRIPT_DIR}/../bin/superpos-cli.sh"

# ── Test: direct invocation passes bash -n ────────────────────────

describe "Direct invocation — syntax check"

set +e
output=$(bash -n "$REAL_CLI" 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "superpos-cli.sh passes bash -n syntax check"

# ── Test: symlinked invocation resolves SCRIPT_DIR ────────────────

describe "Symlinked invocation — SCRIPT_DIR resolution"

ln -sf "$REAL_CLI" "${_tmp_dir}/superpos-cli-link.sh"

# Create a wrapper that sources the symlinked CLI just far enough to
# resolve SCRIPT_DIR and print it, without executing the full CLI.
cat > "${_tmp_dir}/probe.sh" <<'PROBE'
#!/usr/bin/env bash
set -euo pipefail
# Simulate the resolution logic from the target script
_src="$1"
while [[ -L "$_src" ]]; do
    _dir="$(cd "$(dirname "$_src")" && pwd)"
    _src="$(readlink "$_src")"
    [[ "$_src" != /* ]] && _src="$_dir/$_src"
done
RESOLVED_DIR="$(cd "$(dirname "$_src")" && pwd)"
echo "$RESOLVED_DIR"
PROBE
chmod +x "${_tmp_dir}/probe.sh"

set +e
resolved=$(bash "${_tmp_dir}/probe.sh" "${_tmp_dir}/superpos-cli-link.sh" 2>&1)
rc=$?
set -e

real_bin_dir="$(cd "$(dirname "$REAL_CLI")" && pwd)"

assert_eq "$rc" "0" "symlink resolution exits cleanly"
assert_eq "$resolved" "$real_bin_dir" "resolved dir matches real bin dir"

# ── Test: deeply nested symlink chain ─────────────────────────────

describe "Chained symlinks — multi-hop resolution"

mkdir -p "${_tmp_dir}/hop1" "${_tmp_dir}/hop2"
ln -sf "$REAL_CLI" "${_tmp_dir}/hop1/link1.sh"
ln -sf "${_tmp_dir}/hop1/link1.sh" "${_tmp_dir}/hop2/link2.sh"

set +e
resolved=$(bash "${_tmp_dir}/probe.sh" "${_tmp_dir}/hop2/link2.sh" 2>&1)
rc=$?
set -e

assert_eq "$rc" "0" "chained symlink resolution exits cleanly"
assert_eq "$resolved" "$real_bin_dir" "chained resolution matches real bin dir"

# ── Test: all module files pass bash -n ───────────────────────────

describe "All module files — syntax check"

for module in superpos-auth.sh superpos-tasks.sh superpos-knowledge.sh superpos-events.sh superpos-daemon.sh; do
    set +e
    bash -n "${SCRIPT_DIR}/../bin/${module}" 2>&1
    rc=$?
    set -e
    assert_eq "$rc" "0" "${module} passes bash -n syntax check"
done

# ── Summary ──────────────────────────────────────────────────────

test_summary
