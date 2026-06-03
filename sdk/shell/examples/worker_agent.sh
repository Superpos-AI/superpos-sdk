#!/usr/bin/env bash
# worker_agent.sh — Poll/claim/complete loop with error handling.
#
# Usage:
#   export SUPERPOS_BASE_URL="http://localhost:8080"
#   export SUPERPOS_TOKEN="your-bearer-token"   # or use login below
#   export HIVE_ID="01HXYZ..."
#   bash examples/worker_agent.sh
#
# Prerequisites: bash 4+, curl, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

superpos_check_deps || exit $?

HIVE_ID="${HIVE_ID:?Set HIVE_ID to your target hive}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

# Login if no token set
if [[ -z "${SUPERPOS_TOKEN:-}" ]]; then
    AGENT_ID="${AGENT_ID:?Set AGENT_ID or SUPERPOS_TOKEN}"
    AGENT_SECRET="${AGENT_SECRET:?Set AGENT_SECRET or SUPERPOS_TOKEN}"
    echo "==> Logging in..."
    superpos_login -i "$AGENT_ID" -s "$AGENT_SECRET" >/dev/null
    echo "Authenticated."
fi

# Set status to online
superpos_update_status "online" >/dev/null
echo "==> Agent online, polling every ${POLL_INTERVAL}s..."

cleanup() {
    echo ""
    echo "==> Shutting down..."
    superpos_update_status "offline" >/dev/null 2>&1 || true
    superpos_logout 2>/dev/null || true
    echo "Goodbye."
}
trap cleanup EXIT INT TERM

while true; do
    # Send heartbeat
    superpos_heartbeat >/dev/null 2>&1 || true

    # Poll for tasks
    tasks=$(superpos_poll_tasks "$HIVE_ID" -l 1 2>/dev/null) || {
        echo "  Poll failed, retrying..." >&2
        sleep "$POLL_INTERVAL"
        continue
    }

    # Check if we got any tasks (array may be empty or null)
    count=$(echo "$tasks" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    if [[ "$count" -eq 0 ]]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    task_id=$(echo "$tasks" | jq -r '.[0].id')
    task_type=$(echo "$tasks" | jq -r '.[0].type')
    echo "==> Found task: $task_id (type: $task_type)"

    # Try to claim
    if ! claimed=$(superpos_claim_task "$HIVE_ID" "$task_id" 2>/dev/null); then
        echo "  Claim failed (likely already claimed), skipping." >&2
        continue
    fi
    echo "  Claimed."

    # Report progress
    superpos_update_progress "$HIVE_ID" "$task_id" -p 50 -m "Processing..." >/dev/null 2>&1 || true

    # Simulate work
    echo "  Working..."
    sleep 1

    # Complete the task
    if superpos_complete_task "$HIVE_ID" "$task_id" \
        -r '{"output": "done", "processor": "shell-worker"}' \
        -m "Completed by shell worker" >/dev/null 2>&1; then
        echo "  Completed."
    else
        echo "  Failed to mark complete." >&2
    fi
done
