#!/usr/bin/env bash
# test_harness.sh — Minimal test framework for superpos-sdk.sh
#
# Usage:
#   source tests/test_harness.sh
#
# Functions:
#   describe GROUP_NAME           — start a test group
#   it TEST_NAME                  — declare a test (for display)
#   assert_eq ACTUAL EXPECTED MSG — assert equality
#   assert_ne ACTUAL EXPECTED MSG — assert inequality
#   assert_contains STR SUB MSG  — assert substring
#   assert_exit CODE CMD...       — assert exit code
#   test_summary                  — print summary and exit with status

_TEST_PASS=0
_TEST_FAIL=0
_TEST_TOTAL=0
_TEST_GROUP=""

# Temp dir for mock capture files
_MOCK_DIR=$(mktemp -d)
trap 'rm -rf "$_MOCK_DIR"' EXIT

describe() {
    _TEST_GROUP="$1"
    echo ""
    echo "  $1"
}

it() {
    _TEST_TOTAL=$((_TEST_TOTAL + 1))
}

_pass() {
    _TEST_PASS=$((_TEST_PASS + 1))
    echo "    ok  $1"
}

_fail() {
    _TEST_FAIL=$((_TEST_FAIL + 1))
    echo "    FAIL  $1"
    [[ -n "${2:-}" ]] && echo "          $2"
}

assert_eq() {
    local actual="$1" expected="$2" msg="${3:-values should be equal}"
    it "$msg"
    if [[ "$actual" == "$expected" ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected: '$expected', got: '$actual'"
    fi
}

assert_ne() {
    local actual="$1" expected="$2" msg="${3:-values should differ}"
    it "$msg"
    if [[ "$actual" != "$expected" ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected not: '$expected', got: '$actual'"
    fi
}

assert_contains() {
    local str="$1" sub="$2" msg="${3:-string should contain substring}"
    it "$msg"
    if [[ "$str" == *"$sub"* ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected '$str' to contain '$sub'"
    fi
}

assert_not_contains() {
    local str="$1" sub="$2" msg="${3:-string should not contain substring}"
    it "$msg"
    if [[ "$str" != *"$sub"* ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected '$str' to not contain '$sub'"
    fi
}

assert_num_eq() {
    local actual="$1" expected="$2" msg="${3:-numeric values should be equal}"
    it "$msg"
    local eq
    eq=$(jq -n --argjson a "$actual" --argjson b "$expected" 'if $a == $b then "yes" else "no" end' 2>/dev/null) || eq="no"
    if [[ "$eq" == '"yes"' ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected: '$expected', got: '$actual'"
    fi
}

assert_exit() {
    local expected_code="$1"
    shift
    local msg="${*: -1}"
    local cmd_len=$(($# - 1))
    local cmd=("${@:1:$cmd_len}")
    it "$msg"
    set +e
    "${cmd[@]}" >/dev/null 2>&1
    local actual_code=$?
    set -e
    if [[ "$actual_code" -eq "$expected_code" ]]; then
        _pass "$msg"
    else
        _fail "$msg" "expected exit code $expected_code, got $actual_code"
    fi
}

test_summary() {
    echo ""
    echo "  ──────────────────────────────────────────"
    echo "  Tests: $_TEST_TOTAL  Passed: $_TEST_PASS  Failed: $_TEST_FAIL"
    echo "  ──────────────────────────────────────────"
    if [[ $_TEST_FAIL -gt 0 ]]; then
        echo "  FAILED"
        return 1
    else
        echo "  ALL PASSED"
        return 0
    fi
}

# ── Mock HTTP server ─────────────────────────────────────────────
# We mock curl by replacing it with a function that returns canned responses.
# Captured args are written to temp files to survive subshell boundaries.

declare -gA _MOCK_RESPONSES=()
declare -gA _MOCK_RESPONSE_HEADERS=()

mock_response() {
    local method="$1" path="$2" status="$3" body="${4:-}"
    _MOCK_RESPONSES["${method} ${path}"]="${status}|${body}"
}

# mock_response_headers METHOD PATH HEADER_LINES
#   Register response headers for a mock endpoint.
#   HEADER_LINES should be newline-separated "Header: value" strings.
mock_response_headers() {
    local method="$1" path="$2" header_lines="$3"
    _MOCK_RESPONSE_HEADERS["${method} ${path}"]="$header_lines"
}

mock_reset() {
    _MOCK_RESPONSES=()
    _MOCK_RESPONSE_HEADERS=()
    rm -f "${_MOCK_DIR}/args" "${_MOCK_DIR}/body" "${_MOCK_DIR}/method" \
          "${_MOCK_DIR}/url" "${_MOCK_DIR}/headers" "${_MOCK_DIR}/url_log"
}

# Override curl for testing — writes capture data to temp files
curl() {
    local method="GET" url="" body="" dump_header_file=""
    local -a headers=()
    local -a all_args=("$@")

    # Write all args to file for inspection
    printf '%s\n' "${all_args[@]}" > "${_MOCK_DIR}/args"

    # Parse curl args to extract method, URL, body, headers
    local i=0
    while [[ $i -lt ${#all_args[@]} ]]; do
        case "${all_args[$i]}" in
            -X)
                ((i++))
                method="${all_args[$i]}"
                ;;
            -d)
                ((i++))
                body="${all_args[$i]}"
                ;;
            -H)
                ((i++))
                headers+=("${all_args[$i]}")
                ;;
            -D)
                ((i++))
                dump_header_file="${all_args[$i]}"
                ;;
            --silent|--show-error|--verbose) ;;
            --max-time|--write-out)
                ((i++)) # skip value
                ;;
            http*|https*)
                url="${all_args[$i]}"
                ;;
        esac
        ((i++))
    done

    # Persist captured data to files
    echo "$method" > "${_MOCK_DIR}/method"
    echo "$url" > "${_MOCK_DIR}/url"
    echo "$body" > "${_MOCK_DIR}/body"
    printf '%s\n' "${headers[@]}" > "${_MOCK_DIR}/headers"
    # Append to URL log for multi-call sequence inspection
    echo "${method} ${url}" >> "${_MOCK_DIR}/url_log"

    # Extract path from URL (remove scheme + host)
    local path="${url#*://*/}"
    path="/${path}"
    # Remove query string for matching
    local match_path="${path%%\?*}"

    local key="${method} ${match_path}"
    if [[ -v "_MOCK_RESPONSES[$key]" ]]; then
        local entry="${_MOCK_RESPONSES[$key]}"
        local status="${entry%%|*}"
        local resp_body="${entry#*|}"
        # Write mock response headers to dump file if -D was used
        if [[ -n "$dump_header_file" ]]; then
            printf 'HTTP/1.1 %s\r\n' "$status" > "$dump_header_file"
            if [[ -v "_MOCK_RESPONSE_HEADERS[$key]" ]]; then
                printf '%s\r\n' "${_MOCK_RESPONSE_HEADERS[$key]}" >> "$dump_header_file"
            fi
            printf '\r\n' >> "$dump_header_file"
        fi
        if [[ -n "$resp_body" ]]; then
            printf '%s' "$resp_body"
        fi
        printf '\n%s' "$status"
        return 0
    fi

    # Default: 404
    if [[ -n "$dump_header_file" ]]; then
        printf 'HTTP/1.1 404\r\n\r\n' > "$dump_header_file"
    fi
    printf '{"data":null,"meta":{},"errors":[{"message":"Not found","code":"not_found"}]}\n404'
    return 0
}

# ── Capture helpers (read from temp files) ───────────────────────

mock_last_body() {
    cat "${_MOCK_DIR}/body" 2>/dev/null || echo ""
}

mock_last_method() {
    cat "${_MOCK_DIR}/method" 2>/dev/null || echo "GET"
}

mock_last_url() {
    cat "${_MOCK_DIR}/url" 2>/dev/null || echo ""
}

mock_last_has_auth() {
    if grep -q "^Authorization:" "${_MOCK_DIR}/headers" 2>/dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

mock_last_auth_header() {
    grep "^Authorization:" "${_MOCK_DIR}/headers" 2>/dev/null || echo ""
}

mock_was_called() {
    [[ -f "${_MOCK_DIR}/method" ]] && echo "true" || echo "false"
}

# Return the full call log (one "METHOD URL" per line)
mock_url_log() {
    cat "${_MOCK_DIR}/url_log" 2>/dev/null || echo ""
}
