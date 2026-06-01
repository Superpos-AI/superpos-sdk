#!/usr/bin/env bash
# test_sub_agent.sh — Tests for sub-agent block parsing and -S flag on create_task.
#
# Covers TASK-268 Functional Requirements:
#   FR-1  Parse the sub_agent block from the claim response.
#   FR-2  Expose SUB_AGENT_{SLUG,MODEL,PROMPT,ID,NAME,VERSION}.
#   FR-3  Clean state — no stale SUB_AGENT_* values between tasks.
#   FR-4  `-S <slug>` flag on superpos_create_task injects
#         `sub_agent_definition_slug` into the request body.
#   NFR-2 Handle edge cases (null model, missing sub_agent key).
#   NFR-3 Proper escaping for prompts with newlines, quotes, specials.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test_harness.sh"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

export SUPERPOS_BASE_URL="http://localhost:9999"
export SUPERPOS_TOKEN="test-token"
export SUPERPOS_DEBUG=0

HIVE="HHHHHHHHHHHHHHHHHHHHHHHHHH"
TASK_WITH_SUB="T0000000000000000000000001"
TASK_NO_SUB="T0000000000000000000000002"
TASK_NULL_MODEL="T0000000000000000000000003"
TASK_MISSING_KEY="T0000000000000000000000004"
TASK_SPECIAL="T0000000000000000000000005"
TASK_STALE="T0000000000000000000000006"

# Full claim response with sub_agent block (assembled prompt has newlines).
PROMPT_WITH_NEWLINES=$'# SOUL\n\nYou are a focused coding agent.\n\n# RULES\n\nNever commit directly to main.'

SUB_AGENT_RESPONSE=$(jq -n \
    --arg prompt "$PROMPT_WITH_NEWLINES" \
    --arg task "$TASK_WITH_SUB" \
    --arg hive "$HIVE" \
    '{
      data: {
        id: $task,
        hive_id: $hive,
        status: "in_progress",
        claimed_by: "agent-1",
        claimed_at: "2026-04-22T12:00:00Z",
        sub_agent: {
          id: "01DEFXXXXXXXXXXXXXXXXXXXXX",
          slug: "coder",
          name: "Coding Agent",
          model: "claude-opus-4-7",
          version: 3,
          prompt: $prompt,
          config: { temperature: 0.2 },
          allowed_tools: ["Bash","Read","Write","Edit"]
        }
      },
      meta: {},
      errors: null
    }')

NO_SUB_RESPONSE=$(jq -n \
    --arg task "$TASK_NO_SUB" \
    --arg hive "$HIVE" \
    '{ data: { id: $task, hive_id: $hive, status: "in_progress", sub_agent: null }, meta: {}, errors: null }')

NULL_MODEL_RESPONSE=$(jq -n \
    --arg task "$TASK_NULL_MODEL" \
    --arg hive "$HIVE" \
    '{
      data: {
        id: $task,
        hive_id: $hive,
        status: "in_progress",
        sub_agent: {
          id: "01ABCXXXXXXXXXXXXXXXXXXXXX",
          slug: "planner",
          name: "Planner",
          model: null,
          version: 1,
          prompt: "Be a planner."
        }
      },
      meta: {}, errors: null
    }')

# Task response that omits the sub_agent key entirely (not merely null).
MISSING_KEY_RESPONSE=$(jq -n \
    --arg task "$TASK_MISSING_KEY" \
    --arg hive "$HIVE" \
    '{ data: { id: $task, hive_id: $hive, status: "in_progress" }, meta: {}, errors: null }')

# Prompt containing double-quotes, backslashes, and a newline — exercises
# jq raw-output robustness.
PROMPT_SPECIAL=$'Line with "quotes" and a backslash \\ and \nnewline.'
SPECIAL_RESPONSE=$(jq -n \
    --arg prompt "$PROMPT_SPECIAL" \
    --arg task "$TASK_SPECIAL" \
    --arg hive "$HIVE" \
    '{
      data: {
        id: $task,
        hive_id: $hive,
        status: "in_progress",
        sub_agent: {
          id: "01SPECIALXXXXXXXXXXXXXXX",
          slug: "critic",
          name: "Critic",
          model: "claude-opus-4-7",
          version: 2,
          prompt: $prompt
        }
      },
      meta: {}, errors: null
    }')

# ── Claim with sub_agent present ────────────────────────────────

describe "superpos_claim_task parses sub_agent block"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_WITH_SUB}/claim" 200 "$SUB_AGENT_RESPONSE"

# Call directly so env vars propagate into this shell; capture stdout to a file.
_claim_out=$(mktemp)
superpos_claim_task "$HIVE" "$TASK_WITH_SUB" > "$_claim_out"

# Existing contract — claim returns the unwrapped `.data` JSON.
_claim_json=$(cat "$_claim_out")
assert_eq "$(echo "$_claim_json" | jq -r '.id')" "$TASK_WITH_SUB" "claim_task still returns task id (backward compatible)"
assert_eq "$(echo "$_claim_json" | jq -r '.status')" "in_progress" "claim_task still returns status (backward compatible)"

# FR-2 — each field set from the sub_agent block.
assert_eq "${SUB_AGENT_SLUG:-}"    "coder"                          "SUB_AGENT_SLUG set"
assert_eq "${SUB_AGENT_MODEL:-}"   "claude-opus-4-7"                "SUB_AGENT_MODEL set"
assert_eq "${SUB_AGENT_ID:-}"      "01DEFXXXXXXXXXXXXXXXXXXXXX"     "SUB_AGENT_ID set"
assert_eq "${SUB_AGENT_NAME:-}"    "Coding Agent"                   "SUB_AGENT_NAME set"
assert_eq "${SUB_AGENT_VERSION:-}" "3"                              "SUB_AGENT_VERSION set"

# FR-1 / NFR-3 — multi-line prompt survives intact, incl. newlines.
assert_eq "${SUB_AGENT_PROMPT:-}" "$PROMPT_WITH_NEWLINES" "SUB_AGENT_PROMPT preserves newlines and exact content"

rm -f "$_claim_out"

# ── Claim without sub_agent block (null) ────────────────────────

describe "superpos_claim_task leaves SUB_AGENT_* unset when sub_agent is null"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_NO_SUB}/claim" 200 "$NO_SUB_RESPONSE"

# Seed stale values — we expect them to be cleared.
export SUB_AGENT_SLUG="stale-slug"
export SUB_AGENT_MODEL="stale-model"
export SUB_AGENT_PROMPT="stale-prompt"
export SUB_AGENT_ID="stale-id"
export SUB_AGENT_NAME="stale-name"
export SUB_AGENT_VERSION="99"

superpos_claim_task "$HIVE" "$TASK_NO_SUB" > /dev/null

assert_eq "${SUB_AGENT_SLUG:-UNSET}"    "UNSET" "SUB_AGENT_SLUG cleared when sub_agent is null"
assert_eq "${SUB_AGENT_MODEL:-UNSET}"   "UNSET" "SUB_AGENT_MODEL cleared when sub_agent is null"
assert_eq "${SUB_AGENT_PROMPT:-UNSET}"  "UNSET" "SUB_AGENT_PROMPT cleared when sub_agent is null"
assert_eq "${SUB_AGENT_ID:-UNSET}"      "UNSET" "SUB_AGENT_ID cleared when sub_agent is null"
assert_eq "${SUB_AGENT_NAME:-UNSET}"    "UNSET" "SUB_AGENT_NAME cleared when sub_agent is null"
assert_eq "${SUB_AGENT_VERSION:-UNSET}" "UNSET" "SUB_AGENT_VERSION cleared when sub_agent is null"

# ── Claim with sub_agent key entirely missing ───────────────────

describe "superpos_claim_task handles missing sub_agent key (NFR-2)"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_MISSING_KEY}/claim" 200 "$MISSING_KEY_RESPONSE"

# Seed a stale slug.
export SUB_AGENT_SLUG="should-be-cleared"

superpos_claim_task "$HIVE" "$TASK_MISSING_KEY" > /dev/null

assert_eq "${SUB_AGENT_SLUG:-UNSET}" "UNSET" "SUB_AGENT_SLUG cleared when sub_agent key absent"
assert_eq "${SUB_AGENT_ID:-UNSET}"   "UNSET" "SUB_AGENT_ID cleared when sub_agent key absent"

# ── Null model → empty SUB_AGENT_MODEL ───────────────────────────

describe "superpos_claim_task handles null model (NFR-2)"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_NULL_MODEL}/claim" 200 "$NULL_MODEL_RESPONSE"

superpos_claim_task "$HIVE" "$TASK_NULL_MODEL" > /dev/null

assert_eq "${SUB_AGENT_SLUG:-}"  "planner"     "SUB_AGENT_SLUG set when model is null"
assert_eq "${SUB_AGENT_MODEL:-}" ""            "SUB_AGENT_MODEL is empty string when model is null"
assert_eq "${SUB_AGENT_NAME:-}"  "Planner"     "SUB_AGENT_NAME still set when model is null"

# ── Prompt with quotes / backslashes (NFR-3) ────────────────────

describe "superpos_claim_task handles prompts with quotes and special chars"

mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_SPECIAL}/claim" 200 "$SPECIAL_RESPONSE"

superpos_claim_task "$HIVE" "$TASK_SPECIAL" > /dev/null

assert_eq "${SUB_AGENT_PROMPT:-}" "$PROMPT_SPECIAL" "SUB_AGENT_PROMPT preserves quotes, backslashes, and newlines"
assert_eq "${SUB_AGENT_SLUG:-}"   "critic"          "SUB_AGENT_SLUG set for special-char prompt"

# ── Stale values cleared between successive claims (FR-3) ────────

describe "superpos_claim_task clears stale SUB_AGENT_* between tasks"

# 1) Claim a task with sub_agent — variables populated.
mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_WITH_SUB}/claim" 200 "$SUB_AGENT_RESPONSE"
superpos_claim_task "$HIVE" "$TASK_WITH_SUB" > /dev/null
assert_eq "${SUB_AGENT_SLUG:-UNSET}" "coder" "first claim populates SUB_AGENT_SLUG"

# 2) Claim a second task WITHOUT a sub_agent — all SUB_AGENT_* must be gone.
mock_reset
mock_response PATCH "/api/v1/hives/${HIVE}/tasks/${TASK_STALE}/claim" 200 \
    "$(jq -n --arg t "$TASK_STALE" --arg h "$HIVE" \
        '{data:{id:$t,hive_id:$h,status:"in_progress",sub_agent:null},meta:{},errors:null}')"
superpos_claim_task "$HIVE" "$TASK_STALE" > /dev/null

assert_eq "${SUB_AGENT_SLUG:-UNSET}"    "UNSET" "SUB_AGENT_SLUG cleared before second claim with no sub_agent"
assert_eq "${SUB_AGENT_MODEL:-UNSET}"   "UNSET" "SUB_AGENT_MODEL cleared before second claim"
assert_eq "${SUB_AGENT_PROMPT:-UNSET}"  "UNSET" "SUB_AGENT_PROMPT cleared before second claim"
assert_eq "${SUB_AGENT_ID:-UNSET}"      "UNSET" "SUB_AGENT_ID cleared before second claim"
assert_eq "${SUB_AGENT_NAME:-UNSET}"    "UNSET" "SUB_AGENT_NAME cleared before second claim"
assert_eq "${SUB_AGENT_VERSION:-UNSET}" "UNSET" "SUB_AGENT_VERSION cleared before second claim"

# ── create_task: -S flag injects sub_agent_definition_slug (FR-4) ──

describe "superpos_create_task -S injects sub_agent_definition_slug"

mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"NEW-TASK-ID","type":"summarize","status":"pending","sub_agent":null},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "summarize" -S "coder" > /dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.sub_agent_definition_slug')" "coder" \
    "create_task -S includes sub_agent_definition_slug in body"
assert_eq "$(echo "$body" | jq -r '.type')" "summarize" \
    "create_task -S preserves other body fields (type)"

# Without -S — field is NOT present (backward compatible).
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"NEW-TASK-ID","type":"summarize","status":"pending"},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "summarize" > /dev/null

body=$(mock_last_body)
assert_eq "$(echo "$body" | jq 'has("sub_agent_definition_slug")')" "false" \
    "create_task without -S omits sub_agent_definition_slug (backward compatible)"

# -S with a hyphenated / underscored slug — common valid slug characters.
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"NEW-TASK-ID","type":"summarize"},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "summarize" -S "code_reviewer-v2" > /dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.sub_agent_definition_slug')" "code_reviewer-v2" \
    "create_task -S handles hyphen/underscore in slug"

# -S combined with existing flags — payload, invoke, priority still work.
mock_reset
mock_response POST "/api/v1/hives/${HIVE}/tasks" 200 \
    '{"data":{"id":"NEW-TASK-ID","type":"process"},"meta":{},"errors":null}'

superpos_create_task "$HIVE" -t "process" -p 1 -d '{"k":"v"}' -I "do it" -S "coder" > /dev/null
body=$(mock_last_body)
assert_eq "$(echo "$body" | jq -r '.sub_agent_definition_slug')" "coder" \
    "create_task -S coexists with other flags (slug)"
assert_eq "$(echo "$body" | jq -r '.type')" "process" "create_task -S coexists with -t"
assert_eq "$(echo "$body" | jq '.priority')" "1" "create_task -S coexists with -p"
assert_eq "$(echo "$body" | jq -r '.payload.k')" "v" "create_task -S coexists with -d"
assert_eq "$(echo "$body" | jq -r '.invoke.instructions')" "do it" \
    "create_task -S coexists with -I"

# ── Summary ──────────────────────────────────────────────────────

test_summary
