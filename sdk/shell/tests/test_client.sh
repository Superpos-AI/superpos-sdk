#!/usr/bin/env bash
# test_client.sh — Core client tests: envelope parsing, auth headers, error mapping, JSON builder.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token-abc"
export SUPERPOS_DEBUG=0

# ── Envelope parsing ─────────────────────────────────────────────

describe "Envelope parsing"

mock_reset
mock_response GET "/api/v1/agents/me" 200 \
    '{"data":{"id":"abc","name":"bot"},"meta":{},"errors":null}'

result=$(superpos_me)
assert_eq "$(echo "$result" | jq -r '.id')" "abc" "unwraps .data from envelope"
assert_eq "$(echo "$result" | jq -r '.name')" "bot" "preserves all data fields"

mock_reset
mock_response POST "/api/v1/agents/logout" 204 ""

SUPERPOS_TOKEN="test-token"
result=$(superpos_logout 2>/dev/null) || true
assert_eq "$result" "" "204 returns empty output"

# ── Auth headers ─────────────────────────────────────────────────

describe "Auth headers"

mock_reset
mock_response GET "/api/v1/agents/me" 200 \
    '{"data":{"id":"x"},"meta":{},"errors":null}'

SUPERPOS_TOKEN="my-secret-token"
superpos_me >/dev/null
auth_header=$(mock_last_auth_header)
assert_eq "$auth_header" "Authorization: Bearer my-secret-token" "sends Bearer token in Authorization header"

mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"a"},"token":"new-tok"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
superpos_register -n "test" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss" >/dev/null
has_auth=$(mock_last_has_auth)
assert_eq "$has_auth" "false" "no auth header when SUPERPOS_TOKEN is empty"

# ── Error mapping ────────────────────────────────────────────────

describe "Error mapping — exit codes"

SUPERPOS_TOKEN="test-token"

mock_reset
mock_response GET "/api/v1/agents/me" 401 \
    '{"data":null,"meta":{},"errors":[{"message":"Unauthenticated.","code":"auth_failed"}]}'
set +e
superpos_me >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_AUTH" "401 maps to exit code $SUPERPOS_ERR_AUTH (auth)"

mock_reset
mock_response GET "/api/v1/agents/me" 403 \
    '{"data":null,"meta":{},"errors":[{"message":"Forbidden.","code":"forbidden"}]}'
set +e
superpos_me >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_PERMISSION" "403 maps to exit code $SUPERPOS_ERR_PERMISSION (permission)"

mock_reset
mock_response GET "/api/v1/hives/HHHHHHHHHHHHHHHHHHHHHHHHHH/knowledge/NOTFOUND" 404 \
    '{"data":null,"meta":{},"errors":[{"message":"Not found.","code":"not_found"}]}'
set +e
superpos_get_knowledge "HHHHHHHHHHHHHHHHHHHHHHHHHH" "NOTFOUND" >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_NOT_FOUND" "404 maps to exit code $SUPERPOS_ERR_NOT_FOUND (not found)"

mock_reset
mock_response PATCH "/api/v1/hives/HHHHHHHHHHHHHHHHHHHHHHHHHH/tasks/TTTTTTTTTTTTTTTTTTTTTTTTTT/claim" 409 \
    '{"data":null,"meta":{},"errors":[{"message":"Task is no longer available.","code":"conflict"}]}'
set +e
superpos_claim_task "HHHHHHHHHHHHHHHHHHHHHHHHHH" "TTTTTTTTTTTTTTTTTTTTTTTTTT" >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_CONFLICT" "409 maps to exit code $SUPERPOS_ERR_CONFLICT (conflict)"

mock_reset
mock_response POST "/api/v1/agents/register" 422 \
    '{"data":null,"meta":{},"errors":[{"message":"The name has already been taken.","code":"validation_error","field":"name"}]}'
set +e
SUPERPOS_TOKEN=""
superpos_register -n "dup" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss" >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_VALIDATION" "422 maps to exit code $SUPERPOS_ERR_VALIDATION (validation)"

mock_reset
mock_response GET "/api/v1/agents/me" 500 \
    '{"data":null,"meta":{},"errors":[{"message":"Internal error","code":"server_error"}]}'
SUPERPOS_TOKEN="test-token"
set +e
superpos_me >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "500 maps to exit code $SUPERPOS_ERR (generic)"

# ── Error output to stderr ──────────────────────────────────────

describe "Error messages to stderr"

mock_reset
mock_response GET "/api/v1/agents/me" 401 \
    '{"data":null,"meta":{},"errors":[{"message":"Unauthenticated.","code":"auth_failed"}]}'
SUPERPOS_TOKEN="bad"
stderr_output=$(superpos_me 2>&1 >/dev/null || true)
assert_contains "$stderr_output" "auth_failed" "error code appears in stderr"
assert_contains "$stderr_output" "Unauthenticated" "error message appears in stderr"

mock_reset
mock_response POST "/api/v1/agents/register" 422 \
    '{"data":null,"meta":{},"errors":{"name":["The name field is required."],"secret":["Too short.","Required."]}}'
SUPERPOS_TOKEN=""
stderr_output=$(superpos_register -n "x" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss" 2>&1 >/dev/null || true)
assert_contains "$stderr_output" "name" "Laravel object errors: field name in stderr"
assert_contains "$stderr_output" "The name field is required" "Laravel object errors: message in stderr"

# ── JSON builder ─────────────────────────────────────────────────

describe "JSON builder (_superpos_build_json)"

result=$(_superpos_build_json "name" "bot" "type" "custom")
assert_eq "$(echo "$result" | jq -r '.name')" "bot" "string values serialized correctly"
assert_eq "$(echo "$result" | jq -r '.type')" "custom" "multiple string values work"

result=$(_superpos_build_json "priority:n" "3" "name" "test")
assert_eq "$(echo "$result" | jq '.priority')" "3" "':n' suffix forces numeric JSON value"

result=$(_superpos_build_json "secret" "1234567890123456" "agent_id" "0099")
assert_eq "$(echo "$result" | jq -r '.secret')" "1234567890123456" "digit-only secret stays a string"
assert_eq "$(echo "$result" | jq -r '.secret | type')" "string" "digit-only secret has JSON type string"
assert_eq "$(echo "$result" | jq -r '.agent_id')" "0099" "digit-only agent_id stays a string"

result=$(_superpos_build_json "name" "bot" "optional" "" "type" "custom")
assert_eq "$(echo "$result" | jq 'has("optional")')" "false" "empty values are omitted"
assert_eq "$(echo "$result" | jq -r '.name')" "bot" "non-empty values preserved around omitted"

result=$(_superpos_build_json "caps" '["code","summarize"]' "meta" '{"cpu":42}')
assert_eq "$(echo "$result" | jq '.caps | length')" "2" "JSON arrays passed through as raw"
assert_eq "$(echo "$result" | jq '.meta.cpu')" "42" "JSON objects passed through as raw"

result=$(_superpos_build_json "flag" "true" "empty" "null")
assert_eq "$(echo "$result" | jq '.flag')" "true" "boolean true treated as raw JSON"
assert_eq "$(echo "$result" | jq '.empty')" "null" "null treated as raw JSON"

# ── Numeric validation in JSON builder ────────────────────────────

describe "JSON builder — invalid numeric values"

set +e
stderr_output=$(_superpos_build_json "priority:n" "high" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "invalid numeric ':n' value returns SUPERPOS_ERR"
assert_contains "$stderr_output" "invalid numeric value" "invalid numeric ':n' value emits error to stderr"
assert_contains "$stderr_output" "priority" "error message includes field name"

set +e
result=$(_superpos_build_json "priority:n" "3" "name" "test" 2>&1)
rc=$?
set -e
assert_eq "$rc" "0" "valid numeric ':n' value still succeeds"

# Reject non-numeric JSON types through :n
set +e
stderr_output=$(_superpos_build_json "count:n" "true" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "boolean 'true' rejected by ':n'"

set +e
stderr_output=$(_superpos_build_json "count:n" "false" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "boolean 'false' rejected by ':n'"

set +e
stderr_output=$(_superpos_build_json "count:n" "null" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "null rejected by ':n'"

set +e
stderr_output=$(_superpos_build_json "count:n" '[1,2]' 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "array rejected by ':n'"

set +e
stderr_output=$(_superpos_build_json "count:n" '{"a":1}' 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "object rejected by ':n'"

set +e
stderr_output=$(_superpos_build_json "count:n" '"hello"' 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "quoted string rejected by ':n'"

# Valid numeric forms should still pass
result=$(_superpos_build_json "val:n" "-5")
assert_eq "$(echo "$result" | jq '.val')" "-5" "negative integer accepted by ':n'"

result=$(_superpos_build_json "val:n" "3.14")
assert_eq "$(echo "$result" | jq '.val')" "3.14" "float accepted by ':n'"

result=$(_superpos_build_json "val:n" "1e10")
assert_num_eq "$(echo "$result" | jq '.val')" "10000000000" "scientific notation accepted by ':n'"

result=$(_superpos_build_json "val:n" "2.5E-3")
assert_num_eq "$(echo "$result" | jq '.val')" "0.0025" "float with exponent accepted by ':n'"

# ── Invalid raw JSON in --argjson path ─────────────────────────────

describe "JSON builder — invalid raw JSON (--argjson failure)"

set +e
stderr_output=$(_superpos_build_json "payload" "{broken" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "invalid raw JSON returns SUPERPOS_ERR"
assert_contains "$stderr_output" "invalid JSON value" "invalid raw JSON emits error to stderr"
assert_contains "$stderr_output" "payload" "error message includes key name"

set +e
stderr_output=$(_superpos_build_json "items" "[not,json" 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "invalid raw JSON array returns SUPERPOS_ERR"

# ── URL encoding ─────────────────────────────────────────────────

describe "URL encoding (_superpos_urlencode)"

assert_eq "$(_superpos_urlencode "hello world")" "hello%20world" "encodes spaces"
assert_eq "$(_superpos_urlencode "a&b=c")" "a%26b%3Dc" "encodes ampersands and equals"
assert_eq "$(_superpos_urlencode "foo+bar")" "foo%2Bbar" "encodes plus signs"
assert_eq "$(_superpos_urlencode "path/to/thing")" "path%2Fto%2Fthing" "encodes slashes"
assert_eq "$(_superpos_urlencode "simple")" "simple" "leaves plain ASCII unchanged"
assert_eq "$(_superpos_urlencode "café")" "caf%C3%A9" "encodes unicode characters"

# ── Query encoding in SDK functions ──────────────────────────────

describe "Query param encoding in search/poll/list"

SUPERPOS_TOKEN="test-token"
HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge/search" 200 \
    '{"data":[],"meta":{},"errors":null}'

superpos_search_knowledge "$HIVE" -q "hello world" -s "agent:a&b" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "q=hello%20world" "search_knowledge encodes query with spaces"
assert_contains "$url" "scope=agent%3Aa%26b" "search_knowledge encodes scope with special chars"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/tasks/poll" 200 \
    '{"data":[],"meta":{},"errors":null}'

superpos_poll_tasks "$HIVE" -c "code review" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "capability=code%20review" "poll_tasks encodes capability with spaces"

mock_reset
mock_response GET "/api/v1/hives/${HIVE}/knowledge" 200 \
    '{"data":[],"meta":{},"errors":null}'

superpos_list_knowledge "$HIVE" -k "a+b/c" >/dev/null
url=$(mock_last_url)
assert_contains "$url" "key=a%2Bb%2Fc" "list_knowledge encodes key with plus and slash"

# ── Token auto-storage ───────────────────────────────────────────

describe "Token auto-storage"

mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"agent-1"},"token":"tok-from-register"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
superpos_register -n "test" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss" >/dev/null
assert_eq "$SUPERPOS_TOKEN" "tok-from-register" "register stores token in SUPERPOS_TOKEN"

mock_reset
mock_response POST "/api/v1/agents/login" 200 \
    '{"data":{"agent":{"id":"agent-1"},"token":"tok-from-login"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
superpos_login -i "agent-1" -s "secret123456789a" >/dev/null
assert_eq "$SUPERPOS_TOKEN" "tok-from-login" "login stores token in SUPERPOS_TOKEN"

# ── Token persistence — subshell vs direct call ──────────────────

describe "Token persistence — subshell vs temp-file pattern"

mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"agent-sub"},"token":"tok-subshell"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
# Anti-pattern: command substitution runs in a subshell — token is lost
_out=$(superpos_register -n "test" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss")
assert_eq "$SUPERPOS_TOKEN" "" "command substitution loses SUPERPOS_TOKEN (known limitation)"

mock_reset
mock_response POST "/api/v1/agents/register" 200 \
    '{"data":{"agent":{"id":"agent-tmp"},"token":"tok-tmpfile"},"meta":{},"errors":null}'

SUPERPOS_TOKEN=""
# Correct pattern: redirect to temp file, token persists in current shell
_tmp=$(mktemp)
superpos_register -n "test" -h "HHHHHHHHHHHHHHHHHHHHHHHHHH" -s "ssssssssssssssss" > "$_tmp"
_out=$(<"$_tmp"); rm -f "$_tmp"
assert_eq "$SUPERPOS_TOKEN" "tok-tmpfile" "temp-file pattern preserves SUPERPOS_TOKEN"
assert_contains "$_out" "tok-tmpfile" "output captured via temp file"

# ── Logout clears token ─────────────────────────────────────────

describe "Logout clears token"

mock_reset
mock_response POST "/api/v1/agents/logout" 204 ""

SUPERPOS_TOKEN="will-be-cleared"
superpos_logout 2>/dev/null || true
assert_eq "$SUPERPOS_TOKEN" "" "logout clears SUPERPOS_TOKEN on success"

mock_reset
mock_response POST "/api/v1/agents/logout" 500 \
    '{"data":null,"meta":{},"errors":[{"message":"Internal error","code":"server_error"}]}'

SUPERPOS_TOKEN="will-be-cleared-on-error"
superpos_logout >/dev/null 2>/dev/null || true
assert_eq "$SUPERPOS_TOKEN" "" "logout clears SUPERPOS_TOKEN even on error"

# ── Token file persistence ────────────────────────────────────────

describe "Token file persistence"

_tok_dir=$(mktemp -d)
export SUPERPOS_TOKEN_FILE="${_tok_dir}/token"

# save_token writes file with correct content and permissions
SUPERPOS_TOKEN="persist-me"
superpos_save_token
assert_eq "$(< "$SUPERPOS_TOKEN_FILE")" "persist-me" "save_token writes token to file"
_perms=$(stat -c '%a' "$SUPERPOS_TOKEN_FILE" 2>/dev/null || stat -f '%Lp' "$SUPERPOS_TOKEN_FILE" 2>/dev/null)
assert_eq "$_perms" "600" "token file has mode 600"

# load_token reads from file when SUPERPOS_TOKEN is empty
SUPERPOS_TOKEN=""
superpos_load_token
assert_eq "$SUPERPOS_TOKEN" "persist-me" "load_token restores token from file"

# load_token does not override existing SUPERPOS_TOKEN
SUPERPOS_TOKEN="already-set"
printf '%s\n' "from-file" > "$SUPERPOS_TOKEN_FILE"
superpos_load_token
assert_eq "$SUPERPOS_TOKEN" "already-set" "load_token does not override existing token"

# clear_token_file removes the file
superpos_clear_token_file
assert_eq "$(test -f "$SUPERPOS_TOKEN_FILE" && echo exists || echo gone)" "gone" "clear_token_file removes token file"

# load_token with no file is a no-op
SUPERPOS_TOKEN=""
superpos_load_token
assert_eq "$SUPERPOS_TOKEN" "" "load_token with no file leaves SUPERPOS_TOKEN empty"

rm -rf "$_tok_dir"
unset SUPERPOS_TOKEN_FILE

# ── Sourcing library does not alter caller shell options ──────────

describe "Sourcing library does not alter caller shell options"

# Subshell without strict mode — options should remain unchanged
_opts_result=$(bash -c '
    set +e +u +o pipefail 2>/dev/null
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    if [[ $- == *e* ]] || [[ $- == *u* ]]; then
        echo "CHANGED"
    elif [[ "$(set -o pipefail 2>&1; echo $?)" == "0" ]] && set -o | grep -q "pipefail.*on"; then
        echo "CHANGED"
    else
        echo "UNCHANGED"
    fi
' 2>/dev/null)
assert_eq "$_opts_result" "UNCHANGED" "sourcing SDK does not enable errexit/nounset/pipefail"

# Subshell with strict mode — options should be preserved
_opts_result2=$(bash -c '
    set -euo pipefail
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    if [[ $- == *e* ]] && [[ $- == *u* ]]; then
        echo "PRESERVED"
    else
        echo "CHANGED"
    fi
' 2>/dev/null)
assert_eq "$_opts_result2" "PRESERVED" "sourcing SDK preserves existing strict mode"

# ── Logout clears token under set -e ──────────────────────────────

describe "Logout clears token (set -e resilience)"

mock_reset
mock_response POST "/api/v1/agents/logout" 500 \
    '{"data":null,"meta":{},"errors":[{"message":"Internal error","code":"server_error"}]}'

SUPERPOS_TOKEN="cleared-under-set-e"
set +e
superpos_logout >/dev/null 2>/dev/null
_rc=$?
set -e
assert_eq "$SUPERPOS_TOKEN" "" "logout clears SUPERPOS_TOKEN under set -e (no || true)"
assert_ne "$_rc" "0" "logout returns non-zero on server error"

# ── CLI logout clears token file on server failure ────────────────

describe "CLI logout clears token file on server failure"

_tok_dir=$(mktemp -d)
export SUPERPOS_TOKEN_FILE="${_tok_dir}/token"
printf '%s\n' "tok-to-remove" > "$SUPERPOS_TOKEN_FILE"
SUPERPOS_TOKEN="tok-to-remove"

mock_reset
mock_response POST "/api/v1/agents/logout" 500 \
    '{"data":null,"meta":{},"errors":[{"message":"Internal error","code":"server_error"}]}'

# Simulate the CLI logout path: capture error, always clear file
_logout_rc=0
superpos_logout >/dev/null 2>/dev/null || _logout_rc=$?
superpos_clear_token_file

assert_eq "$(test -f "$SUPERPOS_TOKEN_FILE" && echo exists || echo gone)" "gone" \
    "CLI logout clears token file even when server returns 500"
assert_eq "$SUPERPOS_TOKEN" "" \
    "CLI logout clears in-memory token even when server returns 500"
assert_ne "$_logout_rc" "0" \
    "CLI logout preserves non-zero exit from failed server request"

rm -rf "$_tok_dir"
unset SUPERPOS_TOKEN_FILE

# ── JSON build failure aborts request ────────────────────────────

describe "JSON build failure aborts request (no request sent)"

SUPERPOS_TOKEN="test-token"
HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
TASK="TTTTTTTTTTTTTTTTTTTTTTTTTT"
ENTRY="EEEEEEEEEEEEEEEEEEEEEEEEEE"

# create_task with invalid priority — should fail before sending
mock_reset
set +e
superpos_create_task "$HIVE" -t "summarize" -p "not-a-number" >/dev/null 2>/dev/null
rc=$?
set -e
assert_ne "$rc" "0" "create_task fails when build_json fails (invalid priority)"
assert_eq "$(mock_was_called)" "false" "create_task does not send request when build_json fails"

# update_progress with invalid progress — should fail before sending
mock_reset
set +e
superpos_update_progress "$HIVE" "$TASK" -p "high" >/dev/null 2>/dev/null
rc=$?
set -e
assert_ne "$rc" "0" "update_progress fails when build_json fails (invalid progress)"
assert_eq "$(mock_was_called)" "false" "update_progress does not send request when build_json fails"

# complete_task with invalid JSON result — should fail before sending
mock_reset
set +e
superpos_complete_task "$HIVE" "$TASK" -r "{broken" >/dev/null 2>/dev/null
rc=$?
set -e
assert_ne "$rc" "0" "complete_task fails when build_json fails (invalid JSON)"
assert_eq "$(mock_was_called)" "false" "complete_task does not send request when build_json fails"

# heartbeat with invalid metadata JSON — should fail before sending
mock_reset
set +e
superpos_heartbeat -m "{broken" >/dev/null 2>/dev/null
rc=$?
set -e
assert_ne "$rc" "0" "heartbeat fails when build_json fails (invalid metadata JSON)"
assert_eq "$(mock_was_called)" "false" "heartbeat does not send request when build_json fails"

# create_knowledge with invalid value JSON — should fail before sending
mock_reset
set +e
superpos_create_knowledge "$HIVE" -k "mykey" -v "{broken" >/dev/null 2>/dev/null
rc=$?
set -e
assert_ne "$rc" "0" "create_knowledge fails when build_json fails (invalid value JSON)"
assert_eq "$(mock_was_called)" "false" "create_knowledge does not send request when build_json fails"

# ── JSON build failure in non-errexit shell ──────────────────────

describe "JSON build failure in non-errexit shell"

# Verify that without the fix, a non-errexit shell would proceed;
# with the fix, it aborts before sending.
_noexit_result=$(bash -c '
    source "'"${SCRIPT_DIR}/test_harness.sh"'"
    source "'"${SCRIPT_DIR}/../src/superpos-sdk.sh"'"
    export SUPERPOS_BASE_URL="http://localhost:9999"
    export SUPERPOS_TOKEN="test-token"
    set +e  # non-errexit mode
    mock_reset
    superpos_create_task "HHHHHHHHHHHHHHHHHHHHHHHHHH" -t "test" -p "not-a-number" >/dev/null 2>/dev/null
    rc=$?
    called=$(mock_was_called)
    echo "rc=${rc} called=${called}"
' 2>/dev/null)
assert_contains "$_noexit_result" "rc=1" "non-errexit shell: create_task returns error on bad JSON"
assert_contains "$_noexit_result" "called=false" "non-errexit shell: no request sent on bad JSON"

# ── 2xx + non-JSON response must fail ─────────────────────────────

describe "2xx + non-JSON response returns error"

SUPERPOS_TOKEN="test-token"

mock_reset
mock_response GET "/api/v1/agents/me" 200 "this is not json at all"
set +e
result=$(superpos_me 2>/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "200 + invalid JSON returns SUPERPOS_ERR"
assert_eq "$result" "" "200 + invalid JSON produces no stdout data"

mock_reset
mock_response GET "/api/v1/agents/me" 200 "<html>Server OK</html>"
set +e
stderr_output=$(superpos_me 2>&1 >/dev/null)
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "200 + HTML body returns SUPERPOS_ERR"
assert_contains "$stderr_output" "non-JSON response" "200 + HTML body reports non-JSON in stderr"
assert_contains "$stderr_output" "200" "error message includes HTTP status"

mock_reset
mock_response GET "/api/v1/agents/me" 201 "not-json"
set +e
superpos_me >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR" "201 + non-JSON returns SUPERPOS_ERR (no false success)"

# Confirm valid 200 JSON still succeeds (regression guard)
mock_reset
mock_response GET "/api/v1/agents/me" 200 \
    '{"data":{"id":"ok"},"meta":{},"errors":null}'
result=$(superpos_me)
rc=$?
assert_eq "$rc" "0" "200 + valid JSON still returns success"
assert_eq "$(echo "$result" | jq -r '.id')" "ok" "200 + valid JSON unwraps data correctly"

# ── Secure temp file for response headers ─────────────────────────

describe "Secure temp file for response headers"

# Verify mktemp is used (not predictable PID-based path) by inspecting
# the -D argument captured by mock curl.  The path should contain the
# random suffix generated by mktemp, NOT just the shell PID.

SUPERPOS_TOKEN="test-token"
mock_reset
mock_response GET "/api/v1/agents/me" 200 \
    '{"data":{"id":"tmp-check"},"meta":{},"errors":null}'

superpos_me >/dev/null 2>/dev/null

# The mock curl writes all args to _MOCK_DIR/args; extract the -D path.
_dump_path=""
_prev_was_D=false
while IFS= read -r line; do
    if $_prev_was_D; then
        _dump_path="$line"
        break
    fi
    [[ "$line" == "-D" ]] && _prev_was_D=true
done < "${_MOCK_DIR}/args"

assert_contains "$_dump_path" "superpos-sdk-headers." "header dump file uses mktemp naming pattern"
# Must contain a random alphanumeric suffix (mktemp XXXXXXXXXX), not just PID digits
if [[ "$_dump_path" =~ superpos-sdk-headers\.[a-zA-Z0-9]{10}$ ]]; then
    _has_random_suffix=true
else
    _has_random_suffix=false
fi
assert_eq "$_has_random_suffix" "true" "header dump file has 10-char random suffix from mktemp (not PID)"

# Verify the temp file is cleaned up after the request completes
assert_eq "$(test -f "$_dump_path" && echo exists || echo gone)" "gone" \
    "header temp file is cleaned up after request"

# ── Version ──────────────────────────────────────────────────────

describe "SDK version"

assert_eq "$SUPERPOS_SDK_VERSION" "0.1.0" "SDK version is 0.1.0"

# ── Summary ──────────────────────────────────────────────────────

test_summary
