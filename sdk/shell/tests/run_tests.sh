#!/usr/bin/env bash
# run_tests.sh — Run all Shell SDK test suites.
#
# Usage:
#   bash tests/run_tests.sh            # run all tests
#   bash tests/run_tests.sh client     # run only client tests
#   bash tests/run_tests.sh agents     # run only agent tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Superpos Shell SDK — Test Suite"
echo "=============================="

suites=("$@")
if [[ ${#suites[@]} -eq 0 ]]; then
    suites=("client" "agents" "tasks" "knowledge" "schedules" "persona" "service_worker" "runner" "legacy_env" "sub_agent")
fi

total_pass=0
total_fail=0
failed_suites=()

for suite in "${suites[@]}"; do
    test_file="${SCRIPT_DIR}/test_${suite}.sh"
    if [[ ! -f "$test_file" ]]; then
        echo "ERROR: test file not found: $test_file" >&2
        failed_suites+=("$suite")
        total_fail=$((total_fail + 1))
        continue
    fi

    echo ""
    echo "--- test_${suite}.sh ---"

    set +e
    output=$(bash "$test_file" 2>&1)
    rc=$?
    set -e

    echo "$output"

    if [[ $rc -ne 0 ]]; then
        failed_suites+=("$suite")
    fi

    # Extract counts from summary line
    passed=$(echo "$output" | grep -oP 'Passed: \K[0-9]+' || echo 0)
    failed=$(echo "$output" | grep -oP 'Failed: \K[0-9]+' || echo 0)
    total_pass=$((total_pass + passed))
    total_fail=$((total_fail + failed))
done

echo ""
echo "=============================="
echo "Total: $((total_pass + total_fail))  Passed: $total_pass  Failed: $total_fail"

if [[ ${#failed_suites[@]} -gt 0 ]]; then
    echo "Failed suites: ${failed_suites[*]}"
    echo "FAILED"
    exit 1
else
    echo "ALL SUITES PASSED"
    exit 0
fi
