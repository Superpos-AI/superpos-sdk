#!/usr/bin/env bash
# test_daemon_start.sh — Tests for daemon start readiness-check behaviour.
#
# Validates that `_oc_daemon start` reports failure when the child daemon
# exits immediately or never signals readiness (PID file), and reports
# success only when the daemon writes its PID file after init.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

export SUPERPOS_CONFIG_DIR="$_tmp_dir"

# Create a fake daemon script that exits immediately with an error
_make_failing_daemon() {
    cat > "${_tmp_dir}/superpos-daemon.sh" <<'DAEMON'
#!/usr/bin/env bash
echo "[superpos-daemon] Simulated startup failure" >&2
exit 1
DAEMON
    chmod +x "${_tmp_dir}/superpos-daemon.sh"
}

# Create a fake daemon that writes its PID file (signals readiness)
_make_healthy_daemon() {
    cat > "${_tmp_dir}/superpos-daemon.sh" <<DAEMON
#!/usr/bin/env bash
# Write PID file to signal readiness (mirrors real daemon init)
mkdir -p "${_tmp_dir}"
echo \$\$ > "${_tmp_dir}/daemon.pid"
sleep 30
DAEMON
    chmod +x "${_tmp_dir}/superpos-daemon.sh"
}

# Create a daemon that stays alive briefly but never writes PID file
# (simulates crash after auth but before readiness)
_make_late_exit_daemon() {
    cat > "${_tmp_dir}/superpos-daemon.sh" <<'DAEMON'
#!/usr/bin/env bash
# Stay alive for 2s (passes naive kill -0 check) but never signal readiness
sleep 2
exit 1
DAEMON
    chmod +x "${_tmp_dir}/superpos-daemon.sh"
}

# Minimal _oc_daemon function that mirrors the real one but uses our
# temp SCRIPT_DIR — avoids sourcing the full SDK dependency tree.
_oc_daemon_under_test() {
    local action="${1:?usage: _oc_daemon_under_test start|stop|status}"
    local SCRIPT_DIR="$_tmp_dir"
    local pid_file="${SUPERPOS_CONFIG_DIR}/daemon.pid"
    local start_timeout="${SUPERPOS_DAEMON_START_TIMEOUT:-30}"

    case "$action" in
        start)
            rm -f "$pid_file"
            "${SCRIPT_DIR}/superpos-daemon.sh" </dev/null >/dev/null 2>&1 &
            local daemon_pid=$!
            local _deadline=$(( $(date +%s) + start_timeout ))
            while (( $(date +%s) < _deadline )); do
                if ! kill -0 "$daemon_pid" 2>/dev/null; then
                    wait "$daemon_pid" 2>/dev/null || true
                    echo "Daemon failed to start." >&2
                    return 1
                fi
                if [[ -f "$pid_file" ]] && [[ "$(cat "$pid_file" 2>/dev/null)" == "$daemon_pid" ]]; then
                    echo "Daemon started (PID $daemon_pid)."
                    return 0
                fi
                sleep 0.2
            done
            if kill -0 "$daemon_pid" 2>/dev/null; then
                echo "Daemon starting (PID $daemon_pid), still initializing..."
                return 0
            fi
            wait "$daemon_pid" 2>/dev/null || true
            echo "Daemon failed to start." >&2
            return 1
            ;;
    esac
}

# ── Test: failing daemon returns non-zero ────────────────────────

describe "Daemon start — child exits immediately"

_make_failing_daemon
rm -f "${_tmp_dir}/daemon.pid"

set +e
output=$(_oc_daemon_under_test start 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero when daemon exits immediately"
assert_contains "$output" "failed to start" "output mentions startup failure"

# ── Test: healthy daemon (writes PID file) returns zero ──────────

describe "Daemon start — child signals readiness via PID file"

_make_healthy_daemon
rm -f "${_tmp_dir}/daemon.pid"

set +e
output=$(_oc_daemon_under_test start 2>&1)
rc=$?
set -e

# Clean up the background sleep process
pkill -f "${_tmp_dir}/superpos-daemon.sh" 2>/dev/null || true

assert_eq "$rc" "0" "returns 0 when daemon writes PID file"
assert_contains "$output" "Daemon started" "output confirms successful start"

# ── Test: late-exit daemon (dies after timeout) fails ────────────

describe "Daemon start — child exits without writing PID file"

_make_late_exit_daemon
rm -f "${_tmp_dir}/daemon.pid"

# Use a short timeout so the daemon (sleeps 2s) exits before the deadline
export SUPERPOS_DAEMON_START_TIMEOUT=4
set +e
output=$(_oc_daemon_under_test start 2>&1)
rc=$?
set -e
unset SUPERPOS_DAEMON_START_TIMEOUT

pkill -f "${_tmp_dir}/superpos-daemon.sh" 2>/dev/null || true

assert_ne "$rc" "0" "returns non-zero when daemon exits without PID file"
assert_contains "$output" "failed to start" "output mentions startup failure"

# ── Test: slow-start daemon (alive at timeout) succeeds ──────────

describe "Daemon start — slow init still alive at timeout returns success"

# Daemon that stays alive but never writes PID file (slow auth scenario)
cat > "${_tmp_dir}/superpos-daemon.sh" <<'DAEMON'
#!/usr/bin/env bash
# Simulate slow auth/init: stays alive well past the short timeout
sleep 60
DAEMON
chmod +x "${_tmp_dir}/superpos-daemon.sh"
rm -f "${_tmp_dir}/daemon.pid"

export SUPERPOS_DAEMON_START_TIMEOUT=1
set +e
output=$(_oc_daemon_under_test start 2>&1)
rc=$?
set -e
unset SUPERPOS_DAEMON_START_TIMEOUT

pkill -f "${_tmp_dir}/superpos-daemon.sh" 2>/dev/null || true

assert_eq "$rc" "0" "returns 0 when daemon is still alive at timeout (slow init)"
assert_contains "$output" "still initializing" "output indicates daemon is still initializing"

# ── Test: captured-output context doesn't hang ────────────────────

describe "Daemon start — captured output returns promptly (stdio detached)"

_make_healthy_daemon
rm -f "${_tmp_dir}/daemon.pid"

cat > "${_tmp_dir}/test_capture.sh" <<TESTEOF
#!/usr/bin/env bash
set -euo pipefail
dir="$_tmp_dir"
pid_file="${_tmp_dir}/daemon.pid"
start_timeout=30
_oc_daemon_captured() {
    rm -f "\$pid_file"
    "\${1}/superpos-daemon.sh" </dev/null >/dev/null 2>&1 &
    local daemon_pid=\$!
    local _deadline=\$(( \$(date +%s) + start_timeout ))
    while (( \$(date +%s) < _deadline )); do
        if ! kill -0 "\$daemon_pid" 2>/dev/null; then
            wait "\$daemon_pid" 2>/dev/null || true
            echo "Daemon failed to start." >&2
            return 1
        fi
        if [[ -f "\$pid_file" ]] && [[ "\$(cat "\$pid_file" 2>/dev/null)" == "\$daemon_pid" ]]; then
            echo "Daemon started (PID \$daemon_pid)."
            return 0
        fi
        sleep 0.2
    done
    if kill -0 "\$daemon_pid" 2>/dev/null; then
        echo "Daemon starting (PID \$daemon_pid), still initializing..."
        return 0
    fi
    wait "\$daemon_pid" 2>/dev/null || true
    echo "Daemon failed to start." >&2
    return 1
}
output=\$(_oc_daemon_captured "\$dir" 2>&1)
echo "\$output"
TESTEOF
chmod +x "${_tmp_dir}/test_capture.sh"

set +e
output=$(timeout 10 "${_tmp_dir}/test_capture.sh" 2>&1)
rc=$?
set -e

# Clean up the background sleep process
pkill -f "${_tmp_dir}/superpos-daemon.sh" 2>/dev/null || true

assert_ne "$rc" "124" "captured-output returns before timeout (not hung)"
assert_eq "$rc" "0" "returns 0 in captured-output context"
assert_contains "$output" "Daemon started" "output confirms start in captured context"

# ── Summary ──────────────────────────────────────────────────────

test_summary
