#!/usr/bin/env bash
# superpos-events.sh — Event operations for OpenClaw skill.
#
# Wrappers for Superpos event subscription and publishing.
# Uses _superpos_request directly for event endpoints not yet in the Shell SDK.
#
# Functions:
#   superpos_oc_events_subscribe     — Subscribe to an event type
#   superpos_oc_events_unsubscribe   — Unsubscribe from an event type
#   superpos_oc_events_poll_raw      — Poll for new events (raw JSON array)
#   superpos_oc_events_commit_cursor — Persist event cursor after successful handling
#   superpos_oc_events_poll          — Poll for new events (human-readable)
#   superpos_oc_events_publish       — Publish an event
#   superpos_oc_events_list          — List current subscriptions

# ── Source Shell SDK (guard against re-sourcing) ────────────────
if [[ -z "${_SUPERPOS_SDK_LOADED:-}" ]]; then
    _src="${BASH_SOURCE[0]}"
    while [[ -L "$_src" ]]; do
        _dir="$(cd "$(dirname "$_src")" && pwd)"
        _src="$(readlink "$_src")"
        [[ "$_src" != /* ]] && _src="$_dir/$_src"
    done
    SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
    unset _src _dir
    # shellcheck source=_resolve-sdk.sh
    source "${SCRIPT_DIR}/_resolve-sdk.sh"
    _superpos_find_shell_sdk || return 1
    # shellcheck source=../../shell/src/superpos-sdk.sh
    source "$_SUPERPOS_SHELL_SDK_PATH"
    _SUPERPOS_SDK_LOADED=1
fi

# ── Source auth module (for _superpos_oc_config_dir) ───────────
if ! declare -f _superpos_oc_config_dir >/dev/null 2>&1; then
    # shellcheck source=superpos-auth.sh
    source "${SCRIPT_DIR}/superpos-auth.sh"
fi

# ── Cursor persistence ─────────────────────────────────────────
_superpos_oc_cursor_file() {
    echo "$(_superpos_oc_config_dir)/cursor.json"
}

_superpos_oc_load_cursor() {
    local cursor_file
    cursor_file=$(_superpos_oc_cursor_file)
    if [[ -f "$cursor_file" ]]; then
        local cursor
        if cursor=$(jq -r '.last_event_id // empty' "$cursor_file" 2>/dev/null); then
            echo "$cursor"
        else
            echo "[superpos-events] warning: malformed cursor.json, skipping cursor" >&2
        fi
    fi
}

_superpos_oc_save_cursor() {
    local last_event_id="$1"
    local cursor_file
    cursor_file=$(_superpos_oc_cursor_file)
    mkdir -p "$(dirname "$cursor_file")"
    jq -n --arg id "$last_event_id" '{last_event_id: $id}' > "$cursor_file"
}

# ── Subscribe ───────────────────────────────────────────────────
# superpos_oc_events_subscribe EVENT_TYPE [SCOPE] — Subscribe to an event type.
#   SCOPE: "hive" (default) or "apiary"
superpos_oc_events_subscribe() {
    local event_type="${1:?usage: superpos_oc_events_subscribe EVENT_TYPE [SCOPE]}"
    local scope="${2:-hive}"

    local body
    body=$(_superpos_build_json "event_type" "$event_type" "scope" "$scope") || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/agents/subscriptions" "$body") || return $?
    echo "Subscribed to: $event_type (scope: $scope)"
    return $SUPERPOS_OK
}

# ── Unsubscribe ─────────────────────────────────────────────────
# superpos_oc_events_unsubscribe EVENT_TYPE — Unsubscribe from an event type.
superpos_oc_events_unsubscribe() {
    local event_type="${1:?usage: superpos_oc_events_unsubscribe EVENT_TYPE}"

    local encoded_type
    encoded_type=$(_superpos_urlencode "$event_type")

    _superpos_request DELETE "/api/v1/agents/subscriptions/${encoded_type}" || return $?
    echo "Unsubscribed from: $event_type"
    return $SUPERPOS_OK
}

# ── List subscriptions ──────────────────────────────────────────
# superpos_oc_events_list — List current event subscriptions.
superpos_oc_events_list() {
    local result
    result=$(_superpos_request GET "/api/v1/agents/subscriptions") || return $?

    local count
    count=$(echo "$result" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    if [[ "$count" -eq 0 ]]; then
        echo "No active subscriptions."
        return $SUPERPOS_OK
    fi

    echo "Active subscriptions ($count):"
    echo ""
    echo "$result" | jq -r '.[] | "  \(.event_type) (scope: \(.scope // "hive"))"'

    return $SUPERPOS_OK
}

# ── Poll events ─────────────────────────────────────────────────
# superpos_oc_events_poll_raw — Poll for new events since last cursor.
# Outputs raw JSON array. Cursor is NOT advanced here; caller must commit
# only after events are successfully handled.
superpos_oc_events_poll_raw() {
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local params=()
    local last_event_id
    last_event_id=$(_superpos_oc_load_cursor) || last_event_id=""
    [[ -n "$last_event_id" ]] && params+=("last_event_id=$(_superpos_urlencode "$last_event_id")")

    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    local result
    result=$(_superpos_request GET "/api/v1/hives/${hive_id}/events/poll${qs}") || return $?

    echo "$result"
    return $SUPERPOS_OK
}

# superpos_oc_events_commit_cursor EVENT_ID — Persist cursor after successful handling.
superpos_oc_events_commit_cursor() {
    local event_id="${1:-}"
    [[ -n "$event_id" ]] || return $SUPERPOS_OK
    _superpos_oc_save_cursor "$event_id"
    return $SUPERPOS_OK
}

# superpos_oc_events_poll — Human-readable wrapper around raw event polling.
superpos_oc_events_poll() {
    local result
    result=$(superpos_oc_events_poll_raw) || return $?

    local count
    count=$(echo "$result" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    if [[ "$count" -eq 0 ]]; then
        echo "No new events."
        return $SUPERPOS_OK
    fi

    echo "New events ($count):"
    echo ""
    echo "$result" | jq -r '.[] | "  [\(.id)] type=\(.type) from=\(.source_agent_id // "system") at=\(.created_at // "unknown")"'

    # Human wrapper treats display as handling complete.
    local new_cursor
    new_cursor=$(echo "$result" | jq -r '.[-1].id // empty' 2>/dev/null)
    [[ -n "$new_cursor" ]] && superpos_oc_events_commit_cursor "$new_cursor"

    return $SUPERPOS_OK
}

# ── Publish ─────────────────────────────────────────────────────
# superpos_oc_events_publish EVENT_TYPE PAYLOAD_JSON — Publish an event.
superpos_oc_events_publish() {
    local event_type="${1:?usage: superpos_oc_events_publish EVENT_TYPE PAYLOAD_JSON}"
    local payload="${2:-"{}"}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local body
    body=$(_superpos_build_json "type" "$event_type" "payload" "$payload") || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/hives/${hive_id}/events" "$body") || return $?
    local event_id
    event_id=$(echo "$result" | jq -r '.id // "unknown"' 2>/dev/null)
    echo "Event published: $event_id (type: $event_type)"
    return $SUPERPOS_OK
}
