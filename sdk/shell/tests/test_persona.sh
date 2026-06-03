#!/usr/bin/env bash
# test_persona.sh — Persona endpoint tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

# ── Get persona ──────────────────────────────────────────────────

describe "superpos_get_persona"

mock_reset
mock_response GET "/api/v1/persona" 200 \
    '{"data":{"version":1,"is_active":true,"documents":{"SOUL":{"content":"You are helpful.","locked":true},"AGENT":{"content":"Process tasks.","locked":false}},"config":{"llm":{"model":"claude-sonnet-4-5-20250514","temperature":0.3}},"lock_policy":{},"message":"Initial persona","created_by_type":"human","created_at":"2025-01-01T00:00:00+00:00"},"meta":{},"errors":null}'

result=$(superpos_get_persona)
assert_eq "$(echo "$result" | jq -r '.version')" "1" "get_persona returns version"
assert_eq "$(echo "$result" | jq -r '.is_active')" "true" "get_persona returns is_active"

method=$(mock_last_method)
assert_eq "$method" "GET" "get_persona uses GET method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona" "get_persona URL is correct"

# ── Get persona config ───────────────────────────────────────────

describe "superpos_get_persona_config"

mock_reset
mock_response GET "/api/v1/persona/config" 200 \
    '{"data":{"version":1,"config":{"llm":{"model":"claude-sonnet-4-5-20250514","temperature":0.3}}},"meta":{},"errors":null}'

result=$(superpos_get_persona_config)
assert_eq "$(echo "$result" | jq -r '.version')" "1" "get_persona_config returns version"
assert_eq "$(echo "$result" | jq -r '.config.llm.model')" "claude-sonnet-4-5-20250514" "get_persona_config returns nested config.llm.model"

method=$(mock_last_method)
assert_eq "$method" "GET" "get_persona_config uses GET method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/config" "get_persona_config URL is correct"

# ── Get persona document ─────────────────────────────────────────

describe "superpos_get_persona_document"

mock_reset
mock_response GET "/api/v1/persona/documents/SOUL" 200 \
    '{"data":{"version":1,"document":"SOUL","content":"You are a helpful agent."},"meta":{},"errors":null}'

result=$(superpos_get_persona_document SOUL)
assert_eq "$(echo "$result" | jq -r '.document')" "SOUL" "get_persona_document returns document name via .document key"
assert_eq "$(echo "$result" | jq -r '.content')" "You are a helpful agent." "get_persona_document returns content"

method=$(mock_last_method)
assert_eq "$method" "GET" "get_persona_document uses GET method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/documents/SOUL" "get_persona_document URL contains document name"

# ── Get persona assembled ────────────────────────────────────────

describe "superpos_get_persona_assembled"

mock_reset
mock_response GET "/api/v1/persona/assembled" 200 \
    '{"data":{"version":1,"prompt":"You are a helpful agent.\n\nRules:\n- Be concise.","document_count":2},"meta":{},"errors":null}'

result=$(superpos_get_persona_assembled)
assert_eq "$(echo "$result" | jq '.document_count')" "2" "get_persona_assembled returns document_count"

method=$(mock_last_method)
assert_eq "$method" "GET" "get_persona_assembled uses GET method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/assembled" "get_persona_assembled URL is correct"

# ── Update persona document — with message ───────────────────────

describe "superpos_update_persona_document (with message)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":2,"document":"MEMORY","content":"New content"},"meta":{},"errors":null}'

result=$(superpos_update_persona_document MEMORY -c "New content" -m "update msg")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "update_persona_document returns document name via .document key"
assert_eq "$(echo "$result" | jq '.version')" "2" "update_persona_document returns new version"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "update_persona_document uses PATCH method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/documents/MEMORY" "update_persona_document URL contains document name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "New content" "update_persona_document sends content"
assert_eq "$(echo "$body" | jq -r '.message')" "update msg" "update_persona_document sends message"

# ── Update persona document — without message ────────────────────

describe "superpos_update_persona_document (no message)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":3,"document":"MEMORY","content":"New content"},"meta":{},"errors":null}'

superpos_update_persona_document MEMORY -c "New content" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "New content" "update_persona_document (no msg) sends content"
assert_eq "$(echo "$body" | jq 'has("message")')" "false" "update_persona_document omits message when not provided"

# ── Update persona document — explicit empty message ─────────────

describe "superpos_update_persona_document (explicit empty message)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":4,"document":"MEMORY","content":"New content"},"meta":{},"errors":null}'

superpos_update_persona_document MEMORY -c "New content" -m "" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "New content" "update_persona_document (empty msg) sends content"
assert_eq "$(echo "$body" | jq 'has("message")')" "true" "update_persona_document includes message key when -m '' is passed"
assert_eq "$(echo "$body" | jq -r '.message')" "" "update_persona_document sends empty string for -m ''"

# ── Update persona document — missing -c flag ────────────────────

describe "superpos_update_persona_document (missing -c)"

assert_exit 1 superpos_update_persona_document MEMORY "update_persona_document returns error when -c is missing"

# ── Update persona document — 403 locked document ────────────────

describe "superpos_update_persona_document (403 locked)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/SOUL" 403 \
    '{"data":null,"meta":{},"errors":[{"message":"Document is locked.","code":"forbidden"}]}'

set +e
superpos_update_persona_document SOUL -c "override" >/dev/null 2>/dev/null
rc=$?
set -e
assert_eq "$rc" "$SUPERPOS_ERR_PERMISSION" "update_persona_document returns 403 exit code for locked document"

# ── Update persona document — content starting with '[' ──────────

describe "superpos_update_persona_document (content starting with '[')"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":4,"document":"MEMORY","content":"[ ] task"},"meta":{},"errors":null}'

result=$(superpos_update_persona_document MEMORY -c "[ ] task" -m "checklist")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "bracket content: returns document name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "[ ] task" "bracket content: sent as string, not raw JSON"
assert_eq "$(echo "$body" | jq -r 'type')" "object" "bracket content: body is a valid JSON object"

# ── Update persona document — content starting with '{' ──────────

describe "superpos_update_persona_document (content starting with '{')"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":5,"document":"MEMORY","content":"{\"foo\":1}"},"meta":{},"errors":null}'

result=$(superpos_update_persona_document MEMORY -c '{"foo":1}' -m "json-like content")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "brace content: returns document name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" '{"foo":1}' "brace content: sent as string, not parsed as object"
assert_eq "$(echo "$body" | jq -r '.content | type')" "string" "brace content: content field is a JSON string"

# ── Update persona document — content is 'true' ──────────────────

describe "superpos_update_persona_document (content is 'true')"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":6,"document":"MEMORY","content":"true"},"meta":{},"errors":null}'

result=$(superpos_update_persona_document MEMORY -c "true")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "true content: returns document name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "true" "true content: sent as string, not boolean"
assert_eq "$(echo "$body" | jq -r '.content | type')" "string" "true content: content field is a JSON string"

# ── Update persona document — content is 'null' ──────────────────

describe "superpos_update_persona_document (content is 'null')"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":7,"document":"MEMORY","content":"null"},"meta":{},"errors":null}'

result=$(superpos_update_persona_document MEMORY -c "null")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "null content: returns document name"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "null" "null content: sent as string, not JSON null"
assert_eq "$(echo "$body" | jq -r '.content | type')" "string" "null content: content field is a JSON string"

# ── Update persona document — jq unavailable ─────────────────────
#
# When jq is absent, superpos_update_persona_document must fail BEFORE sending
# the PATCH. If the request were sent, the server would create a new persona
# version while the response parsing failed, misleading callers into retrying
# and silently creating duplicate versions.

describe "superpos_update_persona_document (jq unavailable)"

mock_reset

# Hide jq by placing a temporary stub directory at the front of PATH that
# contains a fake `jq` script which exits 127. This makes `command -v jq`
# succeed (finding the stub) but any invocation immediately fail, reliably
# exercising the preflight check regardless of where the real jq is installed
# on the host (e.g. even if it lives in /usr/bin or /bin).
_jq_stub_dir=$(mktemp -d)
printf '#!/bin/sh\nexit 127\n' > "$_jq_stub_dir/jq"
chmod +x "$_jq_stub_dir/jq"
_saved_PATH="$PATH"
PATH="$_jq_stub_dir:$PATH"

rc=0
err_output=$(superpos_update_persona_document MEMORY -c "some content" 2>&1) || rc=$?

PATH="$_saved_PATH"
rm -rf "$_jq_stub_dir"

assert_eq "$rc" "$SUPERPOS_ERR_DEPS" "returns SUPERPOS_ERR_DEPS when jq is unavailable"
assert_contains "$err_output" "jq is required" "prints descriptive error when jq is unavailable"
assert_eq "$(mock_was_called)" "false" \
    "does not send PATCH request when jq is unavailable"

# ── Update persona document — append mode ────────────────────────

describe "superpos_update_persona_document (append mode)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":5,"document":"MEMORY","content":"old\nnew fact"},"meta":{},"errors":null}'

superpos_update_persona_document MEMORY -c "new fact" -M append >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.mode')" "append" "update_persona_document sends mode=append"
assert_eq "$(echo "$body" | jq -r '.content')" "new fact" "update_persona_document sends content with append mode"

# ── Update persona document — prepend mode ───────────────────────

describe "superpos_update_persona_document (prepend mode)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":6,"document":"MEMORY","content":"preamble\nold"},"meta":{},"errors":null}'

superpos_update_persona_document MEMORY -c "preamble" -M prepend >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.mode')" "prepend" "update_persona_document sends mode=prepend"

# ── Update persona document — default mode is replace ────────────

describe "superpos_update_persona_document (default mode is replace)"

mock_reset
mock_response PATCH "/api/v1/persona/documents/MEMORY" 200 \
    '{"data":{"version":7,"document":"MEMORY","content":"fresh"},"meta":{},"errors":null}'

superpos_update_persona_document MEMORY -c "fresh" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.mode')" "replace" "update_persona_document defaults to mode=replace"

# ── Update persona document — invalid mode ───────────────────────

describe "superpos_update_persona_document (invalid mode)"

set +e
err_output=$(superpos_update_persona_document MEMORY -c "x" -M overwrite 2>&1)
rc=$?
set -e
assert_ne "$rc" "0" "update_persona_document exits non-zero for invalid mode"
assert_contains "$err_output" "replace, append, or prepend" "update_persona_document prints allowed modes on invalid -M"

# ── superpos_update_memory — default mode is append ────────────────

describe "superpos_update_memory (default mode is append)"

mock_reset
mock_response PATCH "/api/v1/persona/memory" 200 \
    '{"data":{"version":2,"document":"MEMORY","content":"old\nnew fact"},"meta":{},"errors":null}'

result=$(superpos_update_memory -c "new fact")
assert_eq "$(echo "$result" | jq -r '.document')" "MEMORY" "update_memory returns document=MEMORY"
assert_eq "$(echo "$result" | jq '.version')" "2" "update_memory returns new version"

method=$(mock_last_method)
assert_eq "$method" "PATCH" "update_memory uses PATCH method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/memory" "update_memory hits /api/v1/persona/memory"

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.content')" "new fact" "update_memory sends content"
assert_eq "$(echo "$body" | jq -r '.mode')" "append" "update_memory defaults to mode=append"
assert_eq "$(echo "$body" | jq 'has("message")')" "false" "update_memory omits message when not provided"

# ── superpos_update_memory — with message ──────────────────────────

describe "superpos_update_memory (with message)"

mock_reset
mock_response PATCH "/api/v1/persona/memory" 200 \
    '{"data":{"version":3,"document":"MEMORY","content":"old\nnew fact"},"meta":{},"errors":null}'

superpos_update_memory -c "new fact" -m "schema discovery" >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.message')" "schema discovery" "update_memory sends message"

# ── superpos_update_memory — replace mode ──────────────────────────

describe "superpos_update_memory (replace mode)"

mock_reset
mock_response PATCH "/api/v1/persona/memory" 200 \
    '{"data":{"version":4,"document":"MEMORY","content":"fresh slate"},"meta":{},"errors":null}'

superpos_update_memory -c "fresh slate" -M replace >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.mode')" "replace" "update_memory sends mode=replace"

# ── superpos_update_memory — prepend mode ──────────────────────────

describe "superpos_update_memory (prepend mode)"

mock_reset
mock_response PATCH "/api/v1/persona/memory" 200 \
    '{"data":{"version":5,"document":"MEMORY","content":"preamble\nold"},"meta":{},"errors":null}'

superpos_update_memory -c "preamble" -M prepend >/dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.mode')" "prepend" "update_memory sends mode=prepend"

# ── superpos_update_memory — missing -c ────────────────────────────

describe "superpos_update_memory (missing -c)"

assert_exit 1 superpos_update_memory "update_memory returns error when -c is missing"

# ── superpos_update_memory — invalid mode ──────────────────────────

describe "superpos_update_memory (invalid mode)"

set +e
err_output=$(superpos_update_memory -c "x" -M overwrite 2>&1)
rc=$?
set -e
assert_ne "$rc" "0" "update_memory exits non-zero for invalid mode"
assert_contains "$err_output" "replace, append, or prepend" "update_memory prints allowed modes on invalid -M"

# ── superpos_update_memory — jq unavailable ────────────────────────

describe "superpos_update_memory (jq unavailable)"

mock_reset

_jq_stub_dir=$(mktemp -d)
printf '#!/bin/sh\nexit 127\n' > "$_jq_stub_dir/jq"
chmod +x "$_jq_stub_dir/jq"
_saved_PATH="$PATH"
PATH="$_jq_stub_dir:$PATH"

rc=0
err_output=$(superpos_update_memory -c "some content" 2>&1) || rc=$?

PATH="$_saved_PATH"
rm -rf "$_jq_stub_dir"

assert_eq "$rc" "$SUPERPOS_ERR_DEPS" "update_memory returns SUPERPOS_ERR_DEPS when jq is unavailable"
assert_contains "$err_output" "jq is required" "update_memory prints descriptive error when jq is unavailable"
assert_eq "$(mock_was_called)" "false" \
    "update_memory does not send PATCH request when jq is unavailable"

# ── CLI dispatch — help text ─────────────────────────────────────

describe "superpos-cli persona commands in help text"

CLI="${SCRIPT_DIR}/../bin/superpos-cli"
export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"

help_output=$(bash "$CLI" --help 2>&1 || true)

assert_contains "$help_output" "persona-get" \
    "help text includes persona-get command"
assert_contains "$help_output" "persona-get-config" \
    "help text includes persona-get-config command"
assert_contains "$help_output" "persona-get-document" \
    "help text includes persona-get-document command"
assert_contains "$help_output" "persona-get-assembled" \
    "help text includes persona-get-assembled command"
assert_contains "$help_output" "persona-update-document" \
    "help text includes persona-update-document command"
assert_contains "$help_output" "persona-update-memory" \
    "help text includes persona-update-memory command"

# ── CLI dispatch — argument validation ───────────────────────────

describe "superpos-cli persona-get-document (missing NAME)"

set +e
output=$(bash "$CLI" persona-get-document 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "persona-get-document without NAME exits non-zero"
assert_contains "$output" "persona-get-document NAME" \
    "persona-get-document without NAME prints usage hint"

describe "superpos-cli persona-update-document (missing NAME)"

set +e
output=$(bash "$CLI" persona-update-document 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "persona-update-document without NAME exits non-zero"
assert_contains "$output" "persona-update-document NAME" \
    "persona-update-document without NAME prints usage hint"

describe "superpos-cli persona-update-memory (missing -c)"

set +e
output=$(bash "$CLI" persona-update-memory 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "persona-update-memory without args exits non-zero"
assert_contains "$output" "persona-update-memory" \
    "persona-update-memory without args prints usage hint"

# ── Get persona version (TASK-132) ──────────────────────────────

describe "superpos_get_persona_version (no known_version)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3},"meta":{},"errors":null}'

result=$(superpos_get_persona_version)
assert_eq "$(echo "$result" | jq '.version')" "3" "get_persona_version returns version"
assert_eq "$(echo "$result" | jq 'has("changed")')" "false" \
    "get_persona_version response has no changed key without -k"

method=$(mock_last_method)
assert_eq "$method" "GET" "get_persona_version uses GET method"

url=$(mock_last_url)
assert_contains "$url" "/api/v1/persona/version" "get_persona_version URL is correct"

# ── Get persona version — with known_version ─────────────────────

describe "superpos_get_persona_version (with -k KNOWN_VERSION)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"changed":false},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3)
assert_eq "$(echo "$result" | jq '.version')" "3" "get_persona_version -k returns version"
assert_eq "$(echo "$result" | jq '.changed')" "false" "get_persona_version -k returns changed=false when same"

url=$(mock_last_url)
assert_contains "$url" "known_version=3" "get_persona_version -k passes known_version in query string"

# ── Get persona version — version changed ────────────────────────

describe "superpos_get_persona_version (version changed)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":4,"changed":true},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 2)
assert_eq "$(echo "$result" | jq '.version')" "4" "get_persona_version -k returns new version"
assert_eq "$(echo "$result" | jq '.changed')" "true" "get_persona_version -k returns changed=true when different"

# ── Check persona version — unchanged ────────────────────────────

describe "superpos_check_persona_version (unchanged, exit 1)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"changed":false},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 3
rc=$?
set -e
assert_eq "$rc" "1" "check_persona_version exits 1 when persona unchanged"

# ── Check persona version — changed ──────────────────────────────

describe "superpos_check_persona_version (changed, exit 0)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":5,"changed":true},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 2
rc=$?
set -e
assert_eq "$rc" "0" "check_persona_version exits 0 when persona changed"

# ── Check persona version — missing -k ───────────────────────────

describe "superpos_check_persona_version (missing -k)"

assert_exit 1 superpos_check_persona_version "check_persona_version exits error without -k"

# ── CLI: persona-get-version ─────────────────────────────────────
# Source the real superpos-cli so _cli_dispatch is available in-process.
# This keeps the mock curl function override active while exercising the
# actual dispatch block (superpos-cli lines 326-343) rather than a local copy.

# shellcheck source=../bin/superpos-cli
source "${SCRIPT_DIR}/../bin/superpos-cli"

describe "superpos-cli persona-get-version"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":7},"meta":{},"errors":null}'

result=$(_cli_dispatch persona-get-version)
assert_eq "$(echo "$result" | jq '.version')" "7" "persona-get-version CLI returns version"

# ── CLI: persona-check-version — changed ─────────────────────────

describe "superpos-cli persona-check-version (changed)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":7,"changed":true},"meta":{},"errors":null}'

result=$(_cli_dispatch persona-check-version -k 3)
assert_eq "$result" "changed" "persona-check-version CLI prints 'changed' when version differs"

# ── CLI: persona-check-version — unchanged ───────────────────────

describe "superpos-cli persona-check-version (unchanged)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":7,"changed":false},"meta":{},"errors":null}'

set +e
result=$(_cli_dispatch persona-check-version -k 7)
rc=$?
set -e
assert_eq "$result" "unchanged" "persona-check-version CLI prints 'unchanged' when version same"

# ── CLI: persona-check-version — missing -k ──────────────────────

describe "superpos-cli persona-check-version (missing -k)"

set +e
output=$(_cli_dispatch persona-check-version 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "persona-check-version without -k exits non-zero"
assert_contains "$output" "persona-check-version" \
    "persona-check-version without -k prints usage hint"

# ── CLI: persona-check-version — failure propagation ─────────────

describe "superpos-cli persona-check-version (auth failure propagation)"

# Simulate an auth error (401) from the server. The helper returns
# SUPERPOS_ERR_AUTH (3). The CLI must exit non-zero and must NOT print
# "unchanged" (which would wrongly mask the real failure).
mock_reset
mock_response GET "/api/v1/persona/version" 401 \
    '{"data":null,"meta":{},"errors":[{"message":"Unauthorized","code":"unauthorized"}]}'

set +e
output=$(_cli_dispatch persona-check-version -k 3 2>&1)
rc=$?
set -e

assert_ne "$rc" "0" "persona-check-version exits non-zero on auth failure"
assert_ne "$output" "unchanged" "persona-check-version does not print 'unchanged' on auth failure"

# ── CLI: persona-check-version (unchanged) under set -e ──────────
# Regression test for the set -e bug: when superpos_check_persona_version
# returns 1 (unchanged), bash would exit early under errexit before the
# CLI could print "unchanged" and return the intended exit code.
# The fix uses "|| _rc=$?" to capture the exit code without triggering
# errexit.  We test this by calling _cli_dispatch inside a subshell that
# has set -e active — the call must NOT abort the subshell.

describe "superpos-cli persona-check-version (unchanged) survives set -e"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":7,"changed":false},"meta":{},"errors":null}'

# Run _cli_dispatch in a subshell with set -e active.  If the old bug is
# present the subshell exits with code 1 but never prints "unchanged".
# With the fix, the subshell exits 1 AND prints "unchanged".
set +e
result=$(
    set -e
    _cli_dispatch persona-check-version -k 7
    echo "SHOULD_NOT_REACH"
)
rc=$?
set -e

assert_eq "$rc" "1" "persona-check-version (unchanged) exits 1 under set -e"
assert_eq "$result" "unchanged" "persona-check-version (unchanged) prints 'unchanged' under set -e"

# ── CLI: inherited SUPERPOS_OK environment variable guard ──────────
# Regression: if SUPERPOS_OK=1 is present in the environment when superpos-cli
# is executed directly, the old variable-based guard would skip sourcing
# superpos-sdk.sh, leaving superpos_check_deps undefined and causing a
# "command not found" error.  The function-presence guard must source the
# SDK regardless of any inherited SUPERPOS_OK value.

describe "superpos-cli: SUPERPOS_OK in environment does not break execution"

set +e
output=$(env SUPERPOS_OK=1 bash "${SCRIPT_DIR}/../bin/superpos-cli" version 2>&1)
rc=$?
set -e

assert_ne "$rc" "127" "superpos-cli version with SUPERPOS_OK=1 does not exit 127 (command not found)"
assert_contains "$output" "superpos-sdk" "superpos-cli version with SUPERPOS_OK=1 prints SDK version"

# ── Get persona version — with known_platform_version ─────────────

describe "superpos_get_persona_version (with -k and -p)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"changed":false},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3 -p 2)
assert_eq "$(echo "$result" | jq '.version')" "3" "get_persona_version -k -p returns version"
assert_eq "$(echo "$result" | jq '.platform_context_version')" "2" "get_persona_version -k -p returns platform_context_version"
assert_eq "$(echo "$result" | jq '.changed')" "false" "get_persona_version -k -p returns changed=false when both match"

url=$(mock_last_url)
assert_contains "$url" "known_platform_version=2" "get_persona_version -p passes known_platform_version in query string"

# ── Get persona version — platform context changed ────────────────

describe "superpos_get_persona_version (platform context changed)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":5,"changed":true},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3 -p 2)
assert_eq "$(echo "$result" | jq '.changed')" "true" "get_persona_version returns changed=true when platform version differs"
assert_eq "$(echo "$result" | jq '.platform_context_version')" "5" "get_persona_version returns new platform_context_version"

# ── Get persona version — platform_context_version in response ────

describe "superpos_get_persona_version (response includes platform_context_version)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":1},"meta":{},"errors":null}'

result=$(superpos_get_persona_version)
assert_eq "$(echo "$result" | jq '.platform_context_version')" "1" "get_persona_version response includes platform_context_version"

# ── Check persona version — platform changed triggers exit 0 ──────

describe "superpos_check_persona_version (platform changed, exit 0)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":5,"changed":true},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 3 -p 2
rc=$?
set -e
assert_eq "$rc" "0" "check_persona_version exits 0 when platform context changed"

# ── Check persona version — both unchanged triggers exit 1 ────────

describe "superpos_check_persona_version (both unchanged, exit 1)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"changed":false},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 3 -p 2
rc=$?
set -e
assert_eq "$rc" "1" "check_persona_version exits 1 when persona and platform both unchanged"

# ── CLI: persona-check-version — with -p flag ─────────────────────

describe "superpos-cli persona-check-version (with -p, changed)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":5,"changed":true},"meta":{},"errors":null}'

result=$(_cli_dispatch persona-check-version -k 3 -p 2)
assert_eq "$result" "changed" "persona-check-version -p prints 'changed' when platform version differs"

describe "superpos-cli persona-check-version (with -p, unchanged)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"changed":false},"meta":{},"errors":null}'

set +e
result=$(_cli_dispatch persona-check-version -k 3 -p 2)
rc=$?
set -e
assert_eq "$result" "unchanged" "persona-check-version -p prints 'unchanged' when both versions match"

# ── Get persona version — with known_environment_version ──────────

describe "superpos_get_persona_version (with -k and -e)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"environment_version":"abc123","changed":false},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3 -e abc123)
assert_eq "$(echo "$result" | jq -r '.environment_version')" "abc123" "get_persona_version -k -e returns environment_version"
assert_eq "$(echo "$result" | jq '.changed')" "false" "get_persona_version -k -e returns changed=false when environment matches"

url=$(mock_last_url)
assert_contains "$url" "known_environment_version=abc123" "get_persona_version -e passes known_environment_version in query string"

# ── Get persona version — environment changed ────────────────────

describe "superpos_get_persona_version (environment changed)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"environment_version":"def456","changed":true},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3 -e abc123)
assert_eq "$(echo "$result" | jq '.changed')" "true" "get_persona_version returns changed=true when environment version differs"
assert_eq "$(echo "$result" | jq -r '.environment_version')" "def456" "get_persona_version returns new environment_version"

# ── Get persona version — environment_version in response ────────

describe "superpos_get_persona_version (response includes environment_version)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":1,"environment_version":"abc123"},"meta":{},"errors":null}'

result=$(superpos_get_persona_version)
assert_eq "$(echo "$result" | jq -r '.environment_version')" "abc123" "get_persona_version response includes environment_version"

# ── Get persona version — all three known flags together ─────────

describe "superpos_get_persona_version (with -k, -p and -e)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"environment_version":"abc123","changed":false},"meta":{},"errors":null}'

result=$(superpos_get_persona_version -k 3 -p 2 -e abc123)
assert_eq "$(echo "$result" | jq '.changed')" "false" "get_persona_version -k -p -e returns changed=false when all three match"

url=$(mock_last_url)
assert_contains "$url" "known_version=3" "get_persona_version -k -p -e passes known_version"
assert_contains "$url" "known_platform_version=2" "get_persona_version -k -p -e passes known_platform_version"
assert_contains "$url" "known_environment_version=abc123" "get_persona_version -k -p -e passes known_environment_version"

# ── Check persona version — environment changed triggers exit 0 ──

describe "superpos_check_persona_version (environment changed, exit 0)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"environment_version":"def456","changed":true},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 3 -e abc123
rc=$?
set -e
assert_eq "$rc" "0" "check_persona_version exits 0 when environment version changed"

# ── Check persona version — environment unchanged triggers exit 1 ─

describe "superpos_check_persona_version (environment unchanged, exit 1)"

mock_reset
mock_response GET "/api/v1/persona/version" 200 \
    '{"data":{"version":3,"platform_context_version":2,"environment_version":"abc123","changed":false},"meta":{},"errors":null}'

set +e
superpos_check_persona_version -k 3 -e abc123
rc=$?
set -e
assert_eq "$rc" "1" "check_persona_version exits 1 when environment unchanged"

# ── Summary ──────────────────────────────────────────────────────

test_summary
