#!/usr/bin/env bash
# test_webhook_wake.sh — Tests for webhook-wake bridge.
#
# Validates:
#   - PR comment payload parsing (GitHub formats)
#   - Severity hint extraction
#   - Idempotency / deduplication
#   - Wake invocation conditions (enabled/disabled, session set/unset)
#   - Fail-soft on malformed payloads
#   - CLI-direct transport (openclaw agent / openclaw message send)
#   - Gateway transport (opt-in fallback)
#   - Fail-fast diagnostics when CLI is unavailable
#   - Transport selection via SUPERPOS_WAKE_TRANSPORT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the Shell SDK test harness
source "${SCRIPT_DIR}/../../shell/tests/test_harness.sh"

# We need the SDK loaded (provides SUPERPOS_OK, etc.)
source "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
_SUPERPOS_SDK_LOADED=1

# ── helpers ──────────────────────────────────────────────────────

_tmp_dir=$(mktemp -d)
trap 'rm -rf "$_tmp_dir"' EXIT

_setup() {
    export SUPERPOS_CONFIG_DIR="$_tmp_dir"
    export SUPERPOS_WAKE_ENABLED="true"
    export SUPERPOS_WAKE_SESSION="test-session-123"
    export SUPERPOS_WAKE_LOG="${_tmp_dir}/wake.log"
    export SUPERPOS_WAKE_DEBOUNCE_SECS="5"
    export SUPERPOS_WAKE_TRANSPORT="cli"
    rm -f "${_tmp_dir}/wake_seen.json"
    rm -f "${_tmp_dir}/wake.log"
    _WAKE_INVOCATIONS=0
    _WAKE_LAST_MESSAGE=""
    _WAKE_LAST_SESSION=""

    # Clear any mock functions from prior tests so re-source sees the real binaries
    unset -f openclaw timeout curl 2>/dev/null || true

    # Re-source to pick up env changes
    source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

    # Override _wake_send with a tracking mock.
    # We mock at this level (not the CLI binary) because openclaw calls
    # run in subshells — variable updates would be lost.
    _wake_send() {
        local session_id="$1"
        local message="$2"
        _WAKE_LAST_SESSION="$session_id"
        _WAKE_LAST_MESSAGE="$message"
        _WAKE_INVOCATIONS=$((_WAKE_INVOCATIONS + 1))
        return 0
    }
}

# Build a realistic GitHub PR comment webhook task payload.
# Matches the real shape produced by GitHubConnector::parseWebhook() →
# WebhookRouteEvaluator::executeCreateTask():
#   task.payload.event_payload = { action, repository, sender, body: { <raw github json> } }
_make_pr_comment_task() {
    local task_id="${1:-task-001}"
    local comment_id="${2:-42}"
    local repo="${3:-octocat/hello-world}"
    local pr_num="${4:-7}"
    local comment_body="${5:-Please fix the tests}"
    local action="${6:-created}"

    jq -n \
        --arg tid "$task_id" \
        --arg action "$action" \
        --argjson cid "$comment_id" \
        --arg repo "$repo" \
        --argjson pr "$pr_num" \
        --arg cbody "$comment_body" \
        --arg curl "https://github.com/${repo}/pull/${pr_num}#issuecomment-${comment_id}" \
        --arg purl "https://github.com/${repo}/pull/${pr_num}" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                webhook_route_id: "route-001",
                service_id: "svc-001",
                event_payload: {
                    action: $action,
                    repository: { full_name: $repo },
                    sender: { login: "test-user" },
                    body: {
                        action: $action,
                        comment: {
                            id: $cid,
                            html_url: $curl,
                            body: $cbody
                        },
                        issue: {
                            number: $pr,
                            pull_request: {
                                html_url: $purl
                            }
                        },
                        repository: {
                            full_name: $repo
                        }
                    }
                }
            }
        }'
}

# Build a legacy/flat payload (no .body wrapper) for backwards-compat testing
_make_pr_comment_task_flat() {
    local task_id="${1:-task-flat-001}"
    local comment_id="${2:-42}"
    local repo="${3:-octocat/hello-world}"
    local pr_num="${4:-7}"
    local comment_body="${5:-Please fix the tests}"
    local action="${6:-created}"

    jq -n \
        --arg tid "$task_id" \
        --arg action "$action" \
        --argjson cid "$comment_id" \
        --arg repo "$repo" \
        --argjson pr "$pr_num" \
        --arg cbody "$comment_body" \
        --arg curl "https://github.com/${repo}/pull/${pr_num}#issuecomment-${comment_id}" \
        --arg purl "https://github.com/${repo}/pull/${pr_num}" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                webhook_route_id: "route-001",
                service_id: "svc-001",
                event_payload: {
                    action: $action,
                    comment: {
                        id: $cid,
                        html_url: $curl,
                        body: $cbody
                    },
                    issue: {
                        number: $pr,
                        pull_request: {
                            html_url: $purl
                        }
                    },
                    repository: {
                        full_name: $repo
                    }
                }
            }
        }'
}

_make_pr_comment_task_with_invoke() {
    local task_id="${1:-task-invoke-001}"
    local comment_id="${2:-142}"

    _make_pr_comment_task "$task_id" "$comment_id" "octocat/hello-world" "7" "Please fix" | \
        jq '.payload.invoke = {
            instructions: "Apply fix and report back",
            context: {"source":"router","attempt":1}
        }'
}

_make_pr_comment_task_with_mixed_invoke() {
    local task_id="${1:-task-invoke-mixed-001}"
    local comment_id="${2:-143}"

    _make_pr_comment_task_with_invoke "$task_id" "$comment_id" | \
        jq '.invoke = {
            instructions: "Top-level instructions",
            context: {"source":"top-level","attempt":2}
        }'
}

# Build a PR review comment payload (pull_request_review_comment event)
# Real shape: event_payload.body contains the raw GitHub JSON
_make_pr_review_comment_task() {
    local task_id="${1:-task-002}"
    local comment_id="${2:-99}"

    jq -n \
        --arg tid "$task_id" \
        --argjson cid "$comment_id" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                webhook_route_id: "route-002",
                service_id: "svc-002",
                event_payload: {
                    action: "created",
                    repository: { full_name: "acme/repo" },
                    sender: { login: "reviewer" },
                    body: {
                        action: "created",
                        comment: {
                            id: $cid,
                            html_url: "https://github.com/acme/repo/pull/5#discussion_r99",
                            body: "Looks good to me"
                        },
                        pull_request: {
                            number: 5,
                            html_url: "https://github.com/acme/repo/pull/5"
                        },
                        repository: {
                            full_name: "acme/repo"
                        }
                    }
                }
            }
        }'
}

# ═══════════════════════════════════════════════════════════════
# Parser tests
# ═══════════════════════════════════════════════════════════════

describe "Parser — GitHub issue comment on PR"

_setup
task_json=$(_make_pr_comment_task "t1" 42 "octocat/hello" 7 "Fix the bug")

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "parses issue_comment payload successfully"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "42" "extracts comment_id"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "octocat/hello" "extracts repo"
assert_eq "$(echo "$parsed" | jq -r '.pr_number')" "7" "extracts pr_number"
assert_contains "$(echo "$parsed" | jq -r '.comment_url')" "issuecomment-42" "extracts comment URL"
assert_eq "$(echo "$parsed" | jq -r '.severity')" "normal" "default severity is normal"

# ── Parser: invoke passthrough fields ──────────────────────────

describe "Parser — invoke passthrough fields"

_setup
task_json=$(_make_pr_comment_task_with_invoke "t-invoke" 142)
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)

assert_eq "$(echo "$parsed" | jq -r '.invoke.instructions // empty')" "Apply fix and report back" \
    "parser extracts invoke.instructions"
assert_eq "$(echo "$parsed" | jq -r '.invoke.context.source // empty')" "router" \
    "parser extracts invoke.context"

# ── Parser: mixed-mode invoke precedence ───────────────────────

describe "Parser — mixed invoke prefers top-level"

_setup
task_json=$(_make_pr_comment_task_with_mixed_invoke "t-invoke-mixed" 143)
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)

assert_eq "$(echo "$parsed" | jq -r '.invoke.instructions // empty')" "Top-level instructions" \
    "parser prefers top-level invoke.instructions"
assert_eq "$(echo "$parsed" | jq -r '.invoke.context.source // empty')" "top-level" \
    "parser prefers top-level invoke.context"

# ── Parser: PR review comment ──────────────────────────────────

describe "Parser — GitHub PR review comment"

_setup
task_json=$(_make_pr_review_comment_task "t2" 99)

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "parses pull_request_review_comment payload"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "99" "extracts comment_id from review comment"
assert_eq "$(echo "$parsed" | jq -r '.pr_number')" "5" "extracts pr_number from pull_request object"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "acme/repo" "extracts repo from review comment"

# ── Parser: severity hints ─────────────────────────────────────

describe "Parser — severity hints"

_setup
task_json=$(_make_pr_comment_task "t3" 50 "org/repo" 1 "[URGENT] Deploy is broken")
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
assert_eq "$(echo "$parsed" | jq -r '.severity')" "urgent" "detects [urgent] severity"

task_json=$(_make_pr_comment_task "t4" 51 "org/repo" 1 "[Critical] Production down")
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
assert_eq "$(echo "$parsed" | jq -r '.severity')" "urgent" "detects [critical] severity"

task_json=$(_make_pr_comment_task "t5" 52 "org/repo" 1 "[HIGH] needs attention")
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
assert_eq "$(echo "$parsed" | jq -r '.severity')" "high" "detects [high] severity"

task_json=$(_make_pr_comment_task "t6" 53 "org/repo" 1 "[low] minor nit")
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
assert_eq "$(echo "$parsed" | jq -r '.severity')" "low" "detects [low] severity"

task_json=$(_make_pr_comment_task "t7" 54 "org/repo" 1 "Just a regular comment")
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
assert_eq "$(echo "$parsed" | jq -r '.severity')" "normal" "no severity hint defaults to normal"

# ── Parser: non-comment payloads return failure ────────────────

describe "Parser — non-comment payloads"

_setup

# Push event (no comment object)
push_task=$(jq -n '{
    id: "t-push",
    type: "webhook_handler",
    payload: {
        event_payload: {
            action: "push",
            ref: "refs/heads/main",
            repository: { full_name: "org/repo" }
        }
    }
}')

set +e
parsed=$(_wake_parse_pr_comment "$push_task" 2>/dev/null)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero for push event (no comment)"

# Empty payload
empty_task='{"id":"t-empty","type":"webhook_handler","payload":{}}'
set +e
parsed=$(_wake_parse_pr_comment "$empty_task" 2>/dev/null)
rc=$?
set -e

assert_ne "$rc" "0" "returns non-zero for empty payload"

# Regular issue comment (NOT on a PR — no .issue.pull_request key)
issue_comment_task=$(jq -n '{
    id: "t-issue",
    type: "webhook_handler",
    payload: {
        event_payload: {
            action: "created",
            repository: { full_name: "org/repo" },
            sender: { login: "commenter" },
            body: {
                action: "created",
                comment: {
                    id: 999,
                    html_url: "https://github.com/org/repo/issues/3#issuecomment-999",
                    body: "This is a regular issue comment"
                },
                issue: {
                    number: 3,
                    title: "Bug report"
                },
                repository: { full_name: "org/repo" }
            }
        }
    }
}')

set +e
parsed=$(_wake_parse_pr_comment "$issue_comment_task" 2>/dev/null)
rc=$?
set -e

assert_ne "$rc" "0" "rejects issue_comment on regular issue (no pull_request marker)"

# Also test flat format (no .body wrapper) for regular issue comment
issue_comment_flat=$(jq -n '{
    id: "t-issue-flat",
    type: "webhook_handler",
    payload: {
        event_payload: {
            action: "created",
            comment: {
                id: 998,
                html_url: "https://github.com/org/repo/issues/3#issuecomment-998",
                body: "Flat issue comment"
            },
            issue: {
                number: 3,
                title: "Bug report"
            },
            repository: { full_name: "org/repo" }
        }
    }
}')

set +e
parsed=$(_wake_parse_pr_comment "$issue_comment_flat" 2>/dev/null)
rc=$?
set -e

assert_ne "$rc" "0" "rejects flat issue_comment on regular issue (no pull_request marker)"

# ── Parser: backwards-compat flat payload (no .body wrapper) ──

describe "Parser — backwards-compat flat payload (no body wrapper)"

_setup
task_json=$(_make_pr_comment_task_flat "t-flat" 77 "flat/repo" 10 "Flat payload comment")

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "parses flat (legacy) payload successfully"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "77" "extracts comment_id from flat payload"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "flat/repo" "extracts repo from flat payload"
assert_eq "$(echo "$parsed" | jq -r '.pr_number')" "10" "extracts pr_number from flat payload"

# ── Parser: real GitHubConnector payload (event_payload.body) ─

describe "Parser — real GitHubConnector nested payload (event_payload.body)"

_setup
task_json=$(_make_pr_comment_task "t-real" 88 "real/repo" 15 "Real nested comment")

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "parses real nested payload successfully"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "88" "extracts comment_id from body-nested payload"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "real/repo" "extracts repo from body-nested payload"
assert_eq "$(echo "$parsed" | jq -r '.pr_number')" "15" "extracts pr_number from body-nested payload"
assert_eq "$(echo "$parsed" | jq -r '.comment_body')" "Real nested comment" "extracts comment body from body-nested payload"

# ── Wake: full round-trip with real nested payload ────────────

describe "Wake — full round-trip with real GitHubConnector payload"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task "wake-real" 500 "org/real-project" 42 "[urgent] Production broken")

superpos_webhook_wake "$task_json" "wake-real"

assert_eq "$_WAKE_INVOCATIONS" "1" "sends wake for real nested payload"
assert_contains "$_WAKE_LAST_MESSAGE" "org/real-project" "wake message includes repo from nested payload"
assert_contains "$_WAKE_LAST_MESSAGE" "#42" "wake message includes PR number from nested payload"
assert_contains "$_WAKE_LAST_MESSAGE" "urgent" "wake message includes severity from nested payload"

# ═══════════════════════════════════════════════════════════════
# Deduplication tests
# ═══════════════════════════════════════════════════════════════

describe "Deduplication — prevents duplicate wakes"

_setup

# First call should not be seen
set +e
_wake_is_seen "task1:comment1"
seen1=$?
set -e
assert_ne "$seen1" "0" "first check returns not-seen"

# Mark it
_wake_mark_seen "task1:comment1"

# Now it should be seen
set +e
_wake_is_seen "task1:comment1"
seen2=$?
set -e
assert_eq "$seen2" "0" "second check returns seen (within debounce)"

# Different key should not be seen
set +e
_wake_is_seen "task2:comment2"
seen3=$?
set -e
assert_ne "$seen3" "0" "different key is not seen"

# ── Deduplication: expired entries are not seen ────────────────

describe "Deduplication — expired debounce"

_setup
export SUPERPOS_WAKE_DEBOUNCE_SECS=0
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

_wake_mark_seen "task-old:comment-old"
sleep 1

set +e
_wake_is_seen "task-old:comment-old"
seen=$?
set -e

assert_ne "$seen" "0" "expired entry is not seen (debounce=0)"

# ═══════════════════════════════════════════════════════════════
# Wake invocation tests
# ═══════════════════════════════════════════════════════════════

describe "Wake — sends via CLI transport (openclaw agent)"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task "wake-t1" 100 "org/repo" 3 "Please review")

superpos_webhook_wake "$task_json" "wake-t1"

assert_eq "$_WAKE_INVOCATIONS" "1" "sends exactly one wake via CLI"
assert_eq "$_WAKE_LAST_SESSION" "test-session-123" "targets correct session"
assert_contains "$_WAKE_LAST_MESSAGE" "wake-t1" "message includes task ID"
assert_contains "$_WAKE_LAST_MESSAGE" "org/repo" "message includes repo"
assert_contains "$_WAKE_LAST_MESSAGE" "#3" "message includes PR number"

# ── Wake: invoke passthrough included in wake message ──────────

describe "Wake — includes invoke instructions/context in message"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task_with_invoke "wake-invoke" 143)

superpos_webhook_wake "$task_json" "wake-invoke"

assert_eq "$_WAKE_INVOCATIONS" "1" "invoke wake: sends one wake"
assert_contains "$_WAKE_LAST_MESSAGE" "Invoke instructions: Apply fix and report back" \
    "invoke wake: message includes invoke instructions"
assert_contains "$_WAKE_LAST_MESSAGE" "Invoke context: {\"source\":\"router\",\"attempt\":1}" \
    "invoke wake: message includes invoke context"

# ── Wake: mixed-mode invoke precedence in message ──────────────

describe "Wake — mixed invoke prefers top-level values"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task_with_mixed_invoke "wake-invoke-mixed" 144)

superpos_webhook_wake "$task_json" "wake-invoke-mixed"

assert_eq "$_WAKE_INVOCATIONS" "1" "invoke mixed wake: sends one wake"
assert_contains "$_WAKE_LAST_MESSAGE" "Invoke instructions: Top-level instructions" \
    "invoke mixed wake: message uses top-level instructions"
assert_contains "$_WAKE_LAST_MESSAGE" "Invoke context: {\"source\":\"top-level\",\"attempt\":2}" \
    "invoke mixed wake: message uses top-level context"

# ── Wake: disabled does not invoke ─────────────────────────────

describe "Wake — disabled skips invocation"

_setup
export SUPERPOS_WAKE_ENABLED="false"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_INVOCATIONS=0

task_json=$(_make_pr_comment_task "wake-t2" 101)
superpos_webhook_wake "$task_json" "wake-t2"

assert_eq "$_WAKE_INVOCATIONS" "0" "does not invoke when disabled"

# ── Wake: missing session skips invocation ─────────────────────

describe "Wake — missing session skips invocation"

_setup
export SUPERPOS_WAKE_SESSION=""
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_INVOCATIONS=0

task_json=$(_make_pr_comment_task "wake-t3" 102)
superpos_webhook_wake "$task_json" "wake-t3"

assert_eq "$_WAKE_INVOCATIONS" "0" "does not invoke without session"

# ── Wake: dedup prevents second invocation ─────────────────────

describe "Wake — dedup prevents duplicate wake"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task "wake-t4" 200 "org/repo" 5 "Review please")

superpos_webhook_wake "$task_json" "wake-t4"
assert_eq "$_WAKE_INVOCATIONS" "1" "first wake succeeds"

# Second call with same task+comment should be deduped
superpos_webhook_wake "$task_json" "wake-t4"
assert_eq "$_WAKE_INVOCATIONS" "1" "second wake is deduped"

# ── Wake: non-PR-comment task does not invoke ──────────────────

describe "Wake — non-PR-comment task is skipped gracefully"

_setup
_WAKE_INVOCATIONS=0

push_task=$(jq -n '{
    id: "wake-push",
    type: "webhook_handler",
    payload: {
        event_payload: {
            action: "push",
            ref: "refs/heads/main",
            repository: { full_name: "org/repo" }
        }
    }
}')

superpos_webhook_wake "$push_task" "wake-push"

assert_eq "$_WAKE_INVOCATIONS" "0" "does not wake for non-comment webhook"

# ── Wake: empty/null task JSON does not crash ──────────────────

describe "Wake — fail-soft on empty input"

_setup
_WAKE_INVOCATIONS=0

set +e
superpos_webhook_wake "" "wake-empty"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on empty task JSON"
assert_eq "$_WAKE_INVOCATIONS" "0" "does not invoke on empty input"

set +e
superpos_webhook_wake '{"invalid' "wake-bad"
rc=$?
set -e

assert_eq "$rc" "0" "returns 0 on malformed JSON"
assert_eq "$_WAKE_INVOCATIONS" "0" "does not invoke on malformed JSON"

# ── Wake: log file is written ──────────────────────────────────

describe "Wake — log file records activity"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_pr_comment_task "wake-log1" 300)

superpos_webhook_wake "$task_json" "wake-log1" 2>/dev/null

if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_contains "$log_content" "wake-log1" "log contains task ID"
    assert_contains "$log_content" "INFO" "log contains INFO level"
else
    _fail "log file exists after wake" "wake.log was not created"
fi

# ═══════════════════════════════════════════════════════════════
# CLI transport tests
# ═══════════════════════════════════════════════════════════════

describe "CLI transport — _wake_send_cli invokes openclaw agent"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

# Mock openclaw binary to capture args
_cli_capture_dir="${_tmp_dir}/cli_capture"
mkdir -p "$_cli_capture_dir"

openclaw() {
    echo "$@" > "${_cli_capture_dir}/args"
    return 0
}
# Mock timeout to passthrough (since it wraps openclaw)
timeout() {
    shift  # skip timeout value
    "$@"
}
_WAKE_CLI_AVAILABLE=1

set +e
_wake_send_cli "test-sess-1" "Hello from CLI"
rc=$?
set -e

assert_eq "$rc" "0" "cli-wake: returns 0 on success"
_captured_args=$(cat "${_cli_capture_dir}/args" 2>/dev/null || echo "")
assert_contains "$_captured_args" "agent" "cli-wake: invokes 'agent' subcommand"
assert_contains "$_captured_args" "--session-id test-sess-1" "cli-wake: passes session-id"
assert_contains "$_captured_args" "--message Hello from CLI" "cli-wake: passes message"

# ── CLI transport: alert invokes openclaw message send ─────────

describe "CLI transport — _wake_send_alert_cli invokes openclaw message send"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

_cli_capture_dir="${_tmp_dir}/cli_capture_alert"
mkdir -p "$_cli_capture_dir"

openclaw() {
    echo "$@" > "${_cli_capture_dir}/args"
    return 0
}
timeout() {
    shift
    "$@"
}
_WAKE_CLI_AVAILABLE=1

set +e
_wake_send_alert_cli "@testuser" "telegram" "Test alert"
rc=$?
set -e

assert_eq "$rc" "0" "cli-alert: returns 0 on success"
_captured_args=$(cat "${_cli_capture_dir}/args" 2>/dev/null || echo "")
assert_contains "$_captured_args" "message send" "cli-alert: invokes 'message send'"
assert_contains "$_captured_args" "--channel telegram" "cli-alert: passes channel"
assert_contains "$_captured_args" "--target @testuser" "cli-alert: passes target"
assert_contains "$_captured_args" "--message Test alert" "cli-alert: passes message"

# ── CLI transport: openclaw failure propagates error ───────────

describe "CLI transport — openclaw failure returns error"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_CLI_AVAILABLE=1

openclaw() {
    echo "error: connection refused" >&2
    return 1
}
timeout() {
    shift
    "$@"
}

set +e
_wake_send_cli "fail-sess" "will fail" 2>/dev/null
rc=$?
set -e

assert_ne "$rc" "0" "cli-fail: returns non-zero on openclaw error"

# ── CLI transport: unavailable CLI returns error with diagnostics ──

describe "CLI transport — unavailable CLI produces fail-fast error"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_CLI_AVAILABLE=0
rm -f "${_tmp_dir}/wake.log"

# Force lazy validation path to fail by mocking missing binary.
command() {
    if [[ "$1" == "-v" ]] && [[ "$2" == "openclaw" ]]; then
        return 1
    fi

    builtin command "$@"
}

set +e
_wake_send_cli "no-cli-sess" "no cli" 2>/dev/null
rc=$?
set -e

assert_ne "$rc" "0" "cli-unavail: returns non-zero"

if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_contains "$log_content" "CLI transport requested but openclaw CLI is not available" \
        "cli-unavail: log contains diagnostic message"
fi

# ── CLI validation: command discovery is hermetic ─────────────

describe "CLI validation — detects openclaw via mocked command discovery"

_setup

_cmd_mock_state="present"
command() {
    if [[ "$1" == "-v" ]] && [[ "$2" == "openclaw" ]]; then
        if [[ "${_cmd_mock_state:-}" == "present" ]]; then
            echo "/mock/bin/openclaw"
            return 0
        fi

        return 1
    fi

    builtin command "$@"
}

set +e
_wake_validate_cli 2>/dev/null
rc=$?
set -e

assert_eq "$rc" "0" "validate-cli: succeeds when mocked binary is present"
assert_eq "$_WAKE_CLI_AVAILABLE" "1" "validate-cli: sets _WAKE_CLI_AVAILABLE=1"

# ── CLI validation: missing binary fails fast with diagnostics ─

describe "CLI validation — mocked missing binary fails with diagnostics"

_setup
rm -f "${_tmp_dir}/wake.log"

_cmd_mock_state="missing"
command() {
    if [[ "$1" == "-v" ]] && [[ "$2" == "openclaw" ]]; then
        return 1
    fi

    builtin command "$@"
}

set +e
_wake_validate_cli 2>/dev/null
rc=$?
set -e

assert_ne "$rc" "0" "validate-missing: returns non-zero"
assert_eq "$_WAKE_CLI_AVAILABLE" "0" "validate-missing: sets _WAKE_CLI_AVAILABLE=0"

if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_contains "$log_content" "openclaw binary not found" \
        "validate-missing: log contains diagnostic"
fi

# ── No invalid CLI attempts: source code is clean ─────────────

describe "Wake — source code does not invoke invalid openclaw CLI subcommands"

# Verify the implementation file contains no invalid openclaw CLI invocations
# (sessions_send, session send as two-word command, message.send with dot)
_wake_src="${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
set +e
_cli_hits=$(grep -cE 'openclaw (sessions_send|session send|message\.send)' "$_wake_src" 2>/dev/null)
set -e
assert_eq "${_cli_hits:-0}" "0" "no-invalid-cli: source contains no invalid openclaw CLI subcommand calls"

# Verify the source DOES contain the correct CLI commands
set +e
_cli_agent_hits=$(grep -c 'openclaw agent' "$_wake_src" 2>/dev/null)
_cli_msg_hits=$(grep -c 'openclaw message send' "$_wake_src" 2>/dev/null)
set -e
assert_ne "${_cli_agent_hits:-0}" "0" "correct-cli: source contains 'openclaw agent' invocation"
assert_ne "${_cli_msg_hits:-0}" "0" "correct-cli: source contains 'openclaw message send' invocation"

# ═══════════════════════════════════════════════════════════════
# Transport selection tests
# ═══════════════════════════════════════════════════════════════

describe "Transport — default transport is CLI"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
assert_eq "$_WAKE_TRANSPORT" "cli" "transport-default: defaults to cli"

# ── Transport: disabled wake does not pre-validate CLI at source ──

describe "Transport — disabled wake skips eager CLI validation"

_setup
export SUPERPOS_WAKE_ENABLED="false"
export SUPERPOS_WAKE_TRANSPORT="cli"
rm -f "${_tmp_dir}/wake.log"

# Simulate no openclaw on PATH; source should remain quiet when disabled.
command() {
    if [[ "$1" == "-v" ]] && [[ "$2" == "openclaw" ]]; then
        return 1
    fi

    builtin command "$@"
}

source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

assert_eq "${_WAKE_CLI_AVAILABLE:-0}" "0" "transport-disabled: CLI not eagerly validated"
if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_not_contains "$log_content" "openclaw binary not found" \
        "transport-disabled: no CLI-missing noise when wake disabled"
fi

# ── Transport: env override to gateway ─────────────────────────

describe "Transport — SUPERPOS_WAKE_TRANSPORT=gateway selects gateway"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
assert_eq "$_WAKE_TRANSPORT" "gateway" "transport-gw: env override works"

# ── Transport: value is normalized to lowercase ────────────────

describe "Transport — SUPERPOS_WAKE_TRANSPORT normalization handles uppercase"

_setup
export SUPERPOS_WAKE_TRANSPORT="CLI"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
assert_eq "$_WAKE_TRANSPORT" "cli" "transport-norm: uppercase normalized to cli"
assert_eq "${_WAKE_TRANSPORT_INVALID:-0}" "0" "transport-norm: normalized value remains valid"

# ── Transport: invalid value fails fast ────────────────────────

describe "Transport — invalid SUPERPOS_WAKE_TRANSPORT is rejected"

_setup
export SUPERPOS_WAKE_TRANSPORT="clii"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
assert_eq "${_WAKE_TRANSPORT_INVALID:-0}" "1" "transport-invalid: invalid flag set"

set +e
_wake_send "sess-invalid" "test"
rc=$?
set -e
assert_eq "$rc" "1" "transport-invalid: _wake_send fails fast"

# ── Transport: _wake_send dispatches to CLI by default ─────────

describe "Transport — _wake_send dispatches to CLI by default"

_setup
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_TRANSPORT="cli"
_CLI_DISPATCH_HIT=0
_GW_DISPATCH_HIT=0

_wake_send_cli() { _CLI_DISPATCH_HIT=1; return 0; }
_wake_send_gateway() { _GW_DISPATCH_HIT=1; return 0; }

_wake_send "sess-1" "test"
assert_eq "$_CLI_DISPATCH_HIT" "1" "dispatch-cli: _wake_send_cli called"
assert_eq "$_GW_DISPATCH_HIT" "0" "dispatch-cli: _wake_send_gateway NOT called"

# ── Transport: _wake_send dispatches to gateway when configured ──

describe "Transport — _wake_send dispatches to gateway when SUPERPOS_WAKE_TRANSPORT=gateway"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_CLI_DISPATCH_HIT=0
_GW_DISPATCH_HIT=0

_wake_send_cli() { _CLI_DISPATCH_HIT=1; return 0; }
_wake_send_gateway() { _GW_DISPATCH_HIT=1; return 0; }

_wake_send "sess-2" "test"
assert_eq "$_GW_DISPATCH_HIT" "1" "dispatch-gw: _wake_send_gateway called"
assert_eq "$_CLI_DISPATCH_HIT" "0" "dispatch-gw: _wake_send_cli NOT called"

# ═══════════════════════════════════════════════════════════════
# Gateway transport tests (opt-in fallback)
# ═══════════════════════════════════════════════════════════════

describe "Gateway transport — _wake_send_gateway constructs correct request"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

# Mock curl: writes captured args to files (survives command substitution subshell)
_curl_capture_dir="${_tmp_dir}/curl_capture"
mkdir -p "$_curl_capture_dir"

curl() {
    local url="" body="" auth=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -d) body="$2"; shift 2 ;;
            -H)
                if [[ "$2" == Authorization:* ]]; then
                    auth="$2"
                fi
                shift 2
                ;;
            -o|-w|--max-time|--connect-timeout|-X) shift 2 ;;
            -s|-S) shift ;;
            *) url="$1"; shift ;;
        esac
    done
    echo "$url" > "${_curl_capture_dir}/url"
    echo "$body" > "${_curl_capture_dir}/body"
    echo "$auth" > "${_curl_capture_dir}/auth"
    echo "200"
    return 0
}

export SUPERPOS_WAKE_GATEWAY_URL="http://test-gw:9999"
export SUPERPOS_WAKE_GATEWAY_TOKEN="test-token-abc"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

rm -f "${_curl_capture_dir}"/{url,body,auth}

set +e
_wake_send_gateway "sess-42" "Hello gateway"
rc=$?
set -e

_captured_url=$(cat "${_curl_capture_dir}/url" 2>/dev/null || echo "")
_captured_body=$(cat "${_curl_capture_dir}/body" 2>/dev/null || echo "")
_captured_auth=$(cat "${_curl_capture_dir}/auth" 2>/dev/null || echo "")

assert_eq "$rc" "0" "gateway-unit: returns 0 on HTTP 200"
assert_contains "$_captured_url" "test-gw:9999" "gateway-unit: uses configured gateway host"
assert_contains "$_captured_url" "/tools/invoke" "gateway-unit: correct endpoint path"
assert_contains "$_captured_auth" "Bearer test-token-abc" "gateway-unit: sends bearer token"

# Validate exact payload shape: {"tool":"session_send","args":{"sessionKey":"...","message":"..."}}
_body_tool=$(echo "$_captured_body" | jq -r '.tool' 2>/dev/null)
_body_session_key=$(echo "$_captured_body" | jq -r '.args.sessionKey' 2>/dev/null)
_body_message=$(echo "$_captured_body" | jq -r '.args.message' 2>/dev/null)
assert_eq "$_body_tool" "session_send" "gateway-unit: payload tool is session_send"
assert_eq "$_body_session_key" "sess-42" "gateway-unit: payload sessionKey matches session id"
assert_contains "$_body_message" "Hello gateway" "gateway-unit: payload message contains text"

# ── Gateway unit: HTTP error code ─────────────────────────────

describe "Gateway transport — handles HTTP errors"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

curl() {
    echo "503"
    return 0
}

set +e
_wake_send_gateway "sess-err" "will fail" 2>/dev/null
rc=$?
set -e

assert_ne "$rc" "0" "gateway-error: returns non-zero on HTTP 503"

# ── Gateway unit: curl failure ────────────────────────────────

describe "Gateway transport — handles curl failure"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

curl() {
    return 7  # connection refused
}

set +e
_wake_send_gateway "sess-curl" "unreachable" 2>/dev/null
rc=$?
set -e

assert_ne "$rc" "0" "gateway-curl-fail: returns non-zero when curl errors"

# ── Alert gateway unit: _wake_send_alert_gateway payload contract ──

describe "Alert gateway — _wake_send_alert_gateway constructs correct request"

_setup
export SUPERPOS_WAKE_TRANSPORT="gateway"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

_curl_capture_dir="${_tmp_dir}/curl_capture_alert"
mkdir -p "$_curl_capture_dir"

curl() {
    local url="" body="" auth=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -d) body="$2"; shift 2 ;;
            -H)
                if [[ "$2" == Authorization:* ]]; then
                    auth="$2"
                fi
                shift 2
                ;;
            -o|-w|--max-time|--connect-timeout|-X) shift 2 ;;
            -s|-S) shift ;;
            *) url="$1"; shift ;;
        esac
    done
    echo "$url" > "${_curl_capture_dir}/url"
    echo "$body" > "${_curl_capture_dir}/body"
    echo "$auth" > "${_curl_capture_dir}/auth"
    echo "200"
    return 0
}

export SUPERPOS_WAKE_GATEWAY_URL="http://test-gw:9999"
export SUPERPOS_WAKE_GATEWAY_TOKEN="test-token-abc"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"

rm -f "${_curl_capture_dir}"/{url,body,auth}

set +e
_wake_send_alert_gateway "@myuser" "telegram" "Test alert message"
rc=$?
set -e

_captured_url=$(cat "${_curl_capture_dir}/url" 2>/dev/null || echo "")
_captured_body=$(cat "${_curl_capture_dir}/body" 2>/dev/null || echo "")

assert_eq "$rc" "0" "alert-gw-unit: returns 0 on HTTP 200"
assert_contains "$_captured_url" "/tools/invoke" "alert-gw-unit: correct endpoint path"

# Validate exact payload: {"tool":"message","args":{"action":"send","channel":"...","target":"...","message":"..."}}
_alert_tool=$(echo "$_captured_body" | jq -r '.tool' 2>/dev/null)
_alert_action=$(echo "$_captured_body" | jq -r '.args.action' 2>/dev/null)
_alert_channel=$(echo "$_captured_body" | jq -r '.args.channel' 2>/dev/null)
_alert_target=$(echo "$_captured_body" | jq -r '.args.target' 2>/dev/null)
_alert_message=$(echo "$_captured_body" | jq -r '.args.message' 2>/dev/null)

assert_eq "$_alert_tool" "message" "alert-gw-unit: tool is 'message' (not 'message.send')"
assert_eq "$_alert_action" "send" "alert-gw-unit: args.action is 'send'"
assert_eq "$_alert_channel" "telegram" "alert-gw-unit: args.channel matches"
assert_eq "$_alert_target" "@myuser" "alert-gw-unit: args.target matches"
assert_contains "$_alert_message" "Test alert message" "alert-gw-unit: args.message contains text"

# Ensure no legacy 'text' key in args
_alert_text=$(echo "$_captured_body" | jq -r '.args.text // "ABSENT"' 2>/dev/null)
assert_eq "$_alert_text" "ABSENT" "alert-gw-unit: no legacy 'text' key in args"

# ═══════════════════════════════════════════════════════════════
# Dual-delivery (visible alert) tests
# ═══════════════════════════════════════════════════════════════

# Mock both _wake_send and _wake_send_alert to track dual-delivery calls.
_setup_dual_mocks() {
    _WAKE_INVOCATIONS=0
    _WAKE_LAST_MESSAGE=""
    _WAKE_LAST_SESSION=""
    _ALERT_INVOCATIONS=0
    _ALERT_LAST_TARGET=""
    _ALERT_LAST_CHANNEL=""
    _ALERT_LAST_MESSAGE=""

    _wake_send() {
        local session_id="$1"
        local message="$2"
        _WAKE_LAST_SESSION="$session_id"
        _WAKE_LAST_MESSAGE="$message"
        _WAKE_INVOCATIONS=$((_WAKE_INVOCATIONS + 1))
        return 0
    }

    _wake_send_alert() {
        local target="$1"
        local channel="$2"
        local message="$3"
        _ALERT_LAST_TARGET="$target"
        _ALERT_LAST_CHANNEL="$channel"
        _ALERT_LAST_MESSAGE="$message"
        _ALERT_INVOCATIONS=$((_ALERT_INVOCATIONS + 1))
        return 0
    }
}

# ── Dual-send: both wake + alert succeed ──────────────────────

describe "Dual-delivery — both wake and alert succeed"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@myuser"
export SUPERPOS_WAKE_ALERT_CHANNEL="telegram"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_setup_dual_mocks

task_json=$(_make_pr_comment_task "dual-t1" 600 "org/dual-repo" 20 "[urgent] Fix deploy")

superpos_webhook_wake "$task_json" "dual-t1"

assert_eq "$_WAKE_INVOCATIONS" "1" "dual: internal wake invoked"
assert_eq "$_ALERT_INVOCATIONS" "1" "dual: visible alert invoked"
assert_eq "$_ALERT_LAST_CHANNEL" "telegram" "dual: alert uses telegram channel"
assert_eq "$_ALERT_LAST_TARGET" "@myuser" "dual: alert targets configured user"
assert_contains "$_ALERT_LAST_MESSAGE" "org/dual-repo" "dual: alert includes repo"
assert_contains "$_ALERT_LAST_MESSAGE" "#20" "dual: alert includes PR number"
assert_contains "$_ALERT_LAST_MESSAGE" "urgent" "dual: alert includes severity"

# ── Dual-send: alert disabled, only wake fires ───────────────

describe "Dual-delivery — alert disabled, only wake fires"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="false"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@myuser"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_setup_dual_mocks

task_json=$(_make_pr_comment_task "dual-t2" 601 "org/no-alert" 21 "No alert expected")

superpos_webhook_wake "$task_json" "dual-t2"

assert_eq "$_WAKE_INVOCATIONS" "1" "alert-off: internal wake invoked"
assert_eq "$_ALERT_INVOCATIONS" "0" "alert-off: no visible alert sent"

# ── Dual-send: alert enabled but no telegram target, only wake fires ─

describe "Dual-delivery — alert enabled but no telegram target"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM=""
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_setup_dual_mocks

task_json=$(_make_pr_comment_task "dual-t3" 602 "org/no-tgt" 22 "Missing target")

superpos_webhook_wake "$task_json" "dual-t3"

assert_eq "$_WAKE_INVOCATIONS" "1" "no-target: internal wake invoked"
assert_eq "$_ALERT_INVOCATIONS" "0" "no-target: no visible alert sent"

# ── Dual-send: alert fails but wake still succeeds ──────────

describe "Dual-delivery — alert failure does not crash, wake still succeeds"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@failuser"
export SUPERPOS_WAKE_ALERT_CHANNEL="telegram"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_INVOCATIONS=0
_ALERT_INVOCATIONS=0

# Mock: wake succeeds, alert fails
_wake_send() {
    _WAKE_INVOCATIONS=$((_WAKE_INVOCATIONS + 1))
    return 0
}
_wake_send_alert() {
    _ALERT_INVOCATIONS=$((_ALERT_INVOCATIONS + 1))
    return 1
}

task_json=$(_make_pr_comment_task "dual-t4" 603 "org/alert-fail" 23 "Alert will fail")

set +e
superpos_webhook_wake "$task_json" "dual-t4"
rc=$?
set -e

assert_eq "$rc" "0" "alert-fail: returns 0 (fail-soft)"
assert_eq "$_WAKE_INVOCATIONS" "1" "alert-fail: internal wake still succeeded"

# Verify log records alert failure
if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_contains "$log_content" "Failed to send visible alert" "alert-fail: log records alert failure"
    assert_contains "$log_content" "Woke session" "alert-fail: log records wake success"
fi

# ── Dual-send: wake fails, alert succeeds → still marks seen (dedupe) ──

describe "Dual-delivery — wake fails, alert succeeds, event marked seen"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@wake-fail-user"
export SUPERPOS_WAKE_ALERT_CHANNEL="telegram"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_INVOCATIONS=0
_ALERT_INVOCATIONS=0

# Mock _wake_send to fail, _wake_send_alert to succeed
_wake_send() {
    _WAKE_INVOCATIONS=$((_WAKE_INVOCATIONS + 1))
    _wake_log "ERROR" "CLI transport failed for session_send"
    return 1
}

_wake_send_alert() {
    local target="$1"
    local channel="$2"
    local message="$3"
    _ALERT_LAST_TARGET="$target"
    _ALERT_LAST_CHANNEL="$channel"
    _ALERT_LAST_MESSAGE="$message"
    _ALERT_INVOCATIONS=$((_ALERT_INVOCATIONS + 1))
    return 0
}

task_json=$(_make_pr_comment_task "dual-wf1" 700 "org/wake-fail" 30 "Wake will fail, alert ok")

superpos_webhook_wake "$task_json" "dual-wf1"
assert_eq "$_ALERT_INVOCATIONS" "1" "wake-fail-alert-ok: alert was sent"

# Key assertion: event must be marked seen even though wake failed
# Second call should be deduped (alert succeeded → seen marker written)
_ALERT_INVOCATIONS=0
superpos_webhook_wake "$task_json" "dual-wf1"
assert_eq "$_ALERT_INVOCATIONS" "0" "wake-fail-alert-ok: second alert deduped (seen marker written on first alert success)"

# Verify log records wake failure and alert success
if [[ -f "${_tmp_dir}/wake.log" ]]; then
    log_content=$(cat "${_tmp_dir}/wake.log")
    assert_contains "$log_content" "Failed to wake" "wake-fail-alert-ok: log records wake failure"
    assert_contains "$log_content" "Sent visible alert" "wake-fail-alert-ok: log records alert success"
fi

# ── Dual-send: both fail → event NOT marked seen (retry on next poll) ──

describe "Dual-delivery — both fail, event not marked seen (allows retry)"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@both-fail-user"
export SUPERPOS_WAKE_ALERT_CHANNEL="telegram"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_WAKE_INVOCATIONS=0
_ALERT_INVOCATIONS=0

# Mock: both transports fail
_wake_send() {
    _WAKE_INVOCATIONS=$((_WAKE_INVOCATIONS + 1))
    return 1
}
_wake_send_alert() {
    _ALERT_INVOCATIONS=$((_ALERT_INVOCATIONS + 1))
    return 1
}

task_json=$(_make_pr_comment_task "dual-bf1" 701 "org/both-fail" 31 "Both will fail")

set +e
superpos_webhook_wake "$task_json" "dual-bf1"
rc=$?
set -e

assert_eq "$rc" "0" "both-fail: returns 0 (fail-soft)"

# Key assertion: event NOT marked seen → second attempt should NOT be deduped
_WAKE_INVOCATIONS=0
_ALERT_INVOCATIONS=0
superpos_webhook_wake "$task_json" "dual-bf1"
assert_eq "$_WAKE_INVOCATIONS" "1" "both-fail: second wake attempted (not deduped)"
assert_eq "$_ALERT_INVOCATIONS" "1" "both-fail: second alert attempted (not deduped)"

# ── Dual-send: dedupe prevents second alert ──────────────────

describe "Dual-delivery — dedupe prevents duplicate alert"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@dedup-user"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_setup_dual_mocks

task_json=$(_make_pr_comment_task "dual-t5" 604 "org/dedup" 24 "Dedup test")

superpos_webhook_wake "$task_json" "dual-t5"
assert_eq "$_WAKE_INVOCATIONS" "1" "dedup-dual: first wake sent"
assert_eq "$_ALERT_INVOCATIONS" "1" "dedup-dual: first alert sent"

# Second call with same task+comment should be deduped (both wake and alert)
superpos_webhook_wake "$task_json" "dual-t5"
assert_eq "$_WAKE_INVOCATIONS" "1" "dedup-dual: second wake deduped"
assert_eq "$_ALERT_INVOCATIONS" "1" "dedup-dual: second alert deduped"

# ── Dual-send: severity icon mapping ─────────────────────────

describe "Dual-delivery — severity icon in alert message"

_setup
export SUPERPOS_WAKE_ALERT_ENABLED="true"
export SUPERPOS_WAKE_ALERT_TELEGRAM="@icon-user"
source "${SCRIPT_DIR}/../bin/superpos-webhook-wake.sh"
_setup_dual_mocks

task_json=$(_make_pr_comment_task "dual-t6" 605 "org/icon" 25 "[high] Needs attention")
superpos_webhook_wake "$task_json" "dual-t6"
assert_contains "$_ALERT_LAST_MESSAGE" "high" "icon: high severity in alert"


# ═══════════════════════════════════════════════════════════════
# P2: whitespace .body falls back to event_payload
# ═══════════════════════════════════════════════════════════════

# Build a task where .body is whitespace but event_payload has valid PR comment data
_make_whitespace_body_task() {
    local task_id="${1:-task-ws}"
    local comment_id="${2:-42}"
    local repo="${3:-org/ws-repo}"
    local pr_num="${4:-7}"
    local comment_body="${5:-Whitespace body test}"

    jq -n \
        --arg tid "$task_id" \
        --argjson cid "$comment_id" \
        --arg repo "$repo" \
        --argjson pr "$pr_num" \
        --arg cbody "$comment_body" \
        --arg curl "https://github.com/${repo}/pull/${pr_num}#issuecomment-${comment_id}" \
        --arg purl "https://github.com/${repo}/pull/${pr_num}" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                event_payload: {
                    action: "created",
                    body: "   ",
                    comment: {
                        id: $cid,
                        html_url: $curl,
                        body: $cbody
                    },
                    issue: {
                        number: $pr,
                        pull_request: {
                            html_url: $purl
                        }
                    },
                    repository: {
                        full_name: $repo
                    }
                }
            }
        }'
}

_make_empty_string_body_task() {
    local task_id="${1:-task-es}"
    local comment_id="${2:-42}"
    local repo="${3:-org/es-repo}"
    local pr_num="${4:-7}"
    local comment_body="${5:-Empty string body test}"

    jq -n \
        --arg tid "$task_id" \
        --argjson cid "$comment_id" \
        --arg repo "$repo" \
        --argjson pr "$pr_num" \
        --arg cbody "$comment_body" \
        --arg curl "https://github.com/${repo}/pull/${pr_num}#issuecomment-${comment_id}" \
        --arg purl "https://github.com/${repo}/pull/${pr_num}" \
        '{
            id: $tid,
            type: "webhook_handler",
            payload: {
                event_payload: {
                    action: "created",
                    body: "",
                    comment: {
                        id: $cid,
                        html_url: $curl,
                        body: $cbody
                    },
                    issue: {
                        number: $pr,
                        pull_request: {
                            html_url: $purl
                        }
                    },
                    repository: {
                        full_name: $repo
                    }
                }
            }
        }'
}

describe "P2 Parser — whitespace .body falls back to event_payload"

_setup
task_json=$(_make_whitespace_body_task "p2-ws" 8001 "org/ws-test" 80 "Whitespace body comment")

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "p2-ws: parses successfully (falls back to event_payload)"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "8001" "p2-ws: extracts comment_id"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "org/ws-test" "p2-ws: extracts repo"
assert_eq "$(echo "$parsed" | jq -r '.pr_number')" "80" "p2-ws: extracts pr_number"
assert_eq "$(echo "$parsed" | jq -r '.comment_body')" "Whitespace body comment" "p2-ws: extracts comment body"


describe "P2 Parser — empty string .body falls back to event_payload"

_setup
task_json=$(_make_empty_string_body_task "p2-es" 8002 "org/es-test" 81 "Empty string body")

set +e
parsed=$(_wake_parse_pr_comment "$task_json" 2>/dev/null)
rc=$?
set -e

assert_eq "$rc" "0" "p2-es: parses successfully (falls back to event_payload)"
assert_eq "$(echo "$parsed" | jq -r '.comment_id')" "8002" "p2-es: extracts comment_id"
assert_eq "$(echo "$parsed" | jq -r '.repo')" "org/es-test" "p2-es: extracts repo"


describe "P2 Wake — whitespace .body still delivers wake correctly"

_setup
_WAKE_INVOCATIONS=0
task_json=$(_make_whitespace_body_task "p2-wake" 8003 "org/ws-wake" 82 "Wake with whitespace body")

superpos_webhook_wake "$task_json" "p2-wake"

assert_eq "$_WAKE_INVOCATIONS" "1" "p2-wake: wake sent despite whitespace .body"
assert_contains "$_WAKE_LAST_MESSAGE" "org/ws-wake" "p2-wake: message includes repo"
assert_contains "$_WAKE_LAST_MESSAGE" "#82" "p2-wake: message includes PR number"


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════

test_summary
