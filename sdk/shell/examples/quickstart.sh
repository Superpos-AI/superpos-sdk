#!/usr/bin/env bash
# quickstart.sh — Register an agent, create a task, store knowledge.
#
# Usage:
#   export SUPERPOS_BASE_URL="http://localhost:8080"
#   bash examples/quickstart.sh
#
# Prerequisites: bash 4+, curl, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../src/superpos-sdk.sh"

superpos_check_deps || exit $?

HIVE_ID="${HIVE_ID:?Set HIVE_ID to your target hive}"
# Registration is token-gated by default (platform.agent_registration.require_token),
# so a registration token (srt_…) is required; without it the server returns 422.
# A valid token also grants the agent its permissions (the token's own, or the
# hive defaults). If your hive runs with require_token=false (open registration),
# replace the line below with SUPERPOS_REGISTRATION_TOKEN="${SUPERPOS_REGISTRATION_TOKEN:-}".
SUPERPOS_REGISTRATION_TOKEN="${SUPERPOS_REGISTRATION_TOKEN:?Set SUPERPOS_REGISTRATION_TOKEN to the srt_… token issued by your hive (or unset require_token for open registration)}"

echo "==> Registering agent..."
# Avoid command-substitution: superpos_register sets SUPERPOS_TOKEN in the
# current shell.  Running it inside $(...) would execute in a subshell and
# the token assignment would be lost for subsequent authenticated calls.
_reg_tmp=$(mktemp)
# -r supplies the registration token (srt_…), required by default when the hive
# gates registration.
superpos_register -n "shell-quickstart" -h "$HIVE_ID" -s "my-secure-secret-16chars" \
    -r "$SUPERPOS_REGISTRATION_TOKEN" > "$_reg_tmp"
result=$(<"$_reg_tmp"); rm -f "$_reg_tmp"
echo "Agent ID: $(echo "$result" | jq -r '.agent.id')"
echo "Token stored automatically."

echo ""
echo "==> Getting agent profile..."
superpos_me | jq .

echo ""
echo "==> Sending heartbeat..."
superpos_heartbeat -m '{"cpu": 42, "memory_mb": 512}' | jq .

echo ""
echo "==> Creating a task (requires tasks.create permission)..."
task=$(superpos_create_task "$HIVE_ID" -t "summarize" -d '{"text": "Hello from Shell SDK"}')
task_id=$(echo "$task" | jq -r '.id')
echo "Task created: $task_id"

echo ""
echo "==> Creating a knowledge entry (requires knowledge.write permission)..."
entry=$(superpos_create_knowledge "$HIVE_ID" \
    -k "config.greeting" \
    -v '{"message": "Hello from Shell SDK"}' \
    -s "hive")
entry_id=$(echo "$entry" | jq -r '.id')
echo "Knowledge entry created: $entry_id"

echo ""
echo "==> Listing knowledge..."
superpos_list_knowledge "$HIVE_ID" -l 5 | jq .

echo ""
echo "==> Logging out..."
superpos_logout
echo "Done."
