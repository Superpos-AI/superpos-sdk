#!/usr/bin/env bash
# service_worker_example.sh — Minimal shell service worker.
#
# Demonstrates the service worker pattern: register with a data:* capability,
# poll for data_request tasks, dispatch to operation handlers, and complete/fail.
#
# Usage:
#   export SUPERPOS_BASE_URL="http://localhost:8080"
#   export HIVE_ID="01HXYZ..."
#   export AGENT_SECRET="your-secret"        # used for registration
#   # or:
#   export SUPERPOS_TOKEN="your-token"         # skip registration
#   bash examples/service_worker_example.sh
#
# To send a data request (from any other agent):
#   superpos_data_request "$HIVE_ID" \
#       -c data:example \
#       -o fetch_items \
#       -p '{"filter":"active","limit":10}'
#
# Prerequisites: bash 4+, curl, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

superpos_check_deps || exit $?

HIVE_ID="${HIVE_ID:?Set HIVE_ID}"
CAPABILITY="${CAPABILITY:-data:example}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

# ── Authentication ────────────────────────────────────────────────────

if [[ -z "${SUPERPOS_TOKEN:-}" ]]; then
    AGENT_ID="${AGENT_ID:-}"
    AGENT_SECRET="${AGENT_SECRET:?Set AGENT_SECRET or SUPERPOS_TOKEN}"

    if [[ -n "$AGENT_ID" ]]; then
        echo "==> Logging in as agent $AGENT_ID..."
        superpos_login -i "$AGENT_ID" -s "$AGENT_SECRET" >/dev/null
    else
        WORKER_NAME="${WORKER_NAME:-example-worker}"
        echo "==> Registering as '$WORKER_NAME' with capability $CAPABILITY..."
        superpos_register \
            -n "$WORKER_NAME" \
            -h "$HIVE_ID" \
            -s "$AGENT_SECRET" \
            -T "service_worker" \
            -c "$CAPABILITY" >/dev/null
    fi
    echo "Authenticated."
fi

# ── Graceful shutdown ─────────────────────────────────────────────────

cleanup() {
    echo ""
    echo "==> Shutting down..."
    superpos_update_status "offline" >/dev/null 2>&1 || true
    superpos_logout 2>/dev/null || true
    echo "Goodbye."
}
trap cleanup EXIT INT TERM

# ── Operation handlers ────────────────────────────────────────────────
#
# Add a handler function for each operation your worker supports.
# Handler receives the "params" JSON object from the task payload as $1.
# It must write a JSON result to stdout, or exit non-zero on failure.

handle_fetch_items() {
    local params="$1"
    local filter
    filter=$(echo "$params" | jq -r '.filter // "all"')
    local limit
    limit=$(echo "$params" | jq -r '.limit // 50')

    # Replace with real data-source calls.
    local items='[{"id":"item-1","name":"Widget A"},{"id":"item-2","name":"Widget B"}]'

    if [[ "$filter" != "all" ]]; then
        # Example filtering — replace with actual logic.
        items=$(echo "$items" | jq --arg f "$filter" '[.[] | select(.name | ascii_downcase | contains($f))]')
    fi

    local count
    count=$(echo "$items" | jq 'length')
    jq -n --argjson data "$items" --argjson count "$count" \
        '{data: $data, metadata: {count: $count}}'
}

handle_search_items() {
    local params="$1"
    local query
    query=$(echo "$params" | jq -r '.query // ""')
    jq -n --arg q "$query" '{data: [], metadata: {query: $q, count: 0}}'
}

# ── Operation router ──────────────────────────────────────────────────

dispatch_operation() {
    local operation="$1"
    local params="$2"

    case "$operation" in
        fetch_items|fetch-items)
            handle_fetch_items "$params"
            ;;
        search_items|search-items)
            handle_search_items "$params"
            ;;
        *)
            echo "Unknown operation: $operation" >&2
            return 1
            ;;
    esac
}

# ── Poll loop ─────────────────────────────────────────────────────────

superpos_update_status "online" >/dev/null
echo "==> Worker online. Polling every ${POLL_INTERVAL}s for capability=$CAPABILITY..."

while true; do
    # Heartbeat
    superpos_heartbeat >/dev/null 2>&1 || true

    # Poll for data_request tasks matching our capability
    envelope=$(superpos_poll_tasks "$HIVE_ID" -c "$CAPABILITY" -l 1 2>/dev/null) || {
        echo "  Poll failed, retrying..." >&2
        sleep "$POLL_INTERVAL"
        continue
    }

    count=$(echo "$envelope" | jq '.data | if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    # Capture backpressure hint before branching — the server may return
    # next_poll_ms > 0 even when tasks are present (rate-limit / high-load).
    _next_poll_ms="${_SUPERPOS_NEXT_POLL_MS:-0}"

    if [[ "$count" -eq 0 ]]; then
        if [[ "$_next_poll_ms" -gt 0 ]]; then
            sleep "$(( (_next_poll_ms + 999) / 1000 ))"
        else
            sleep "$POLL_INTERVAL"
        fi
        continue
    fi

    task_id=$(echo "$envelope" | jq -r '.data[0].id')
    task_type=$(echo "$envelope" | jq -r '.data[0].type')
    echo "==> Found task: $task_id (type: $task_type)"

    # Claim
    if ! claimed=$(superpos_claim_task "$HIVE_ID" "$task_id" 2>/dev/null); then
        echo "  Claim failed (likely already claimed), skipping." >&2
        continue
    fi
    echo "  Claimed."

    # Extract operation, params, and optional response_task_id from payload
    payload=$(echo "$claimed" | jq -c '.payload // {}')
    operation=$(echo "$payload" | jq -r '.operation // ""')
    params=$(echo "$payload" | jq -c '.params // {}')
    response_task_id=$(echo "$payload" | jq -r '.response_task_id // ""')

    echo "  Operation: $operation"

    # Report progress
    superpos_update_progress "$HIVE_ID" "$task_id" -p 10 -m "Starting $operation..." >/dev/null 2>&1 || true

    # Dispatch
    if result=$(dispatch_operation "$operation" "$params" 2>/tmp/superpos_worker_err); then
        # Wrap in envelope if result is not already a JSON object
        if ! echo "$result" | jq -e 'type == "object"' >/dev/null 2>&1; then
            result=$(jq -n --argjson v "$result" '{value: $v}')
        fi

        # If a response_task_id was provided, push the result there via the
        # dedicated deliver-response endpoint (bypasses ownership/status checks).
        if [[ -n "$response_task_id" ]]; then
            superpos_deliver_response "$HIVE_ID" "$response_task_id" \
                -r "$result" \
                -m "Delivered response for operation '$operation'" >/dev/null 2>&1 || true
            echo "  Response delivered to task $response_task_id."
        fi

        if superpos_complete_task "$HIVE_ID" "$task_id" \
            -r "$result" \
            -m "Completed operation '$operation'" >/dev/null 2>&1; then
            echo "  Completed."
        else
            echo "  Warning: could not mark task complete." >&2
        fi
    else
        err_msg=$(cat /tmp/superpos_worker_err 2>/dev/null || echo "Worker error")
        err_payload=$(jq -n --arg t "WorkerError" --arg m "$err_msg" --arg o "$operation" \
            '{type: $t, message: $m, operation: $o}')
        superpos_fail_task "$HIVE_ID" "$task_id" \
            -e "$err_payload" \
            -m "Worker error on operation '$operation'" >/dev/null 2>&1 || true
        echo "  Failed: $err_msg" >&2
    fi

    # Honour server backpressure even when tasks were returned (rate-limit / high-load).
    if [[ "$_next_poll_ms" -gt 0 ]]; then
        sleep "$(( (_next_poll_ms + 999) / 1000 ))"
    fi
done
