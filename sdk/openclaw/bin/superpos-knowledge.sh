#!/usr/bin/env bash
# superpos-knowledge.sh — Knowledge operations for OpenClaw skill.
#
# Thin wrappers around Shell SDK knowledge functions with
# human-readable output for OpenClaw's LLM.
#
# Functions:
#   superpos_oc_knowledge_list     — List knowledge entries
#   superpos_oc_knowledge_search   — Search knowledge entries
#   superpos_oc_knowledge_get      — Get a single entry
#   superpos_oc_knowledge_set      — Create or update an entry
#   superpos_oc_knowledge_delete   — Delete an entry

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

# ── List ────────────────────────────────────────────────────────
# superpos_oc_knowledge_list [KEY_PATTERN] — List knowledge entries.
superpos_oc_knowledge_list() {
    local key_pattern="${1:-}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local -a args=("$hive_id")
    [[ -n "$key_pattern" ]] && args+=(-k "$key_pattern")

    local result
    result=$(superpos_list_knowledge "${args[@]}") || return $?

    local count
    count=$(echo "$result" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    if [[ "$count" -eq 0 ]]; then
        echo "No knowledge entries found."
        return $SUPERPOS_OK
    fi

    echo "Knowledge entries ($count):"
    echo ""
    echo "$result" | jq -r '.[] | "  [\(.id)] key=\(.key) scope=\(.scope // "hive") updated=\(.updated_at // "unknown")"'

    return $SUPERPOS_OK
}

# ── Search ──────────────────────────────────────────────────────
# superpos_oc_knowledge_search QUERY — Full-text search knowledge entries.
superpos_oc_knowledge_search() {
    local query="${1:?usage: superpos_oc_knowledge_search QUERY}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local result
    result=$(superpos_search_knowledge "$hive_id" -q "$query") || return $?

    local count
    count=$(echo "$result" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)

    if [[ "$count" -eq 0 ]]; then
        echo "No results for: $query"
        return $SUPERPOS_OK
    fi

    echo "Search results for \"$query\" ($count):"
    echo ""
    echo "$result" | jq -r '.[] | "  [\(.id)] key=\(.key) scope=\(.scope // "hive")"'

    return $SUPERPOS_OK
}

# ── Get ─────────────────────────────────────────────────────────
# superpos_oc_knowledge_get ENTRY_ID — Get a single knowledge entry.
superpos_oc_knowledge_get() {
    local entry_id="${1:?usage: superpos_oc_knowledge_get ENTRY_ID}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local result
    result=$(superpos_get_knowledge "$hive_id" "$entry_id") || return $?
    echo "$result" | jq '.'
    return $SUPERPOS_OK
}

# ── Set (create or update) ──────────────────────────────────────
# superpos_oc_knowledge_set KEY VALUE_JSON [SCOPE] [VISIBILITY]
#   Creates a new knowledge entry, or updates the existing entry if the
#   key already exists (idempotent "set" semantics).
superpos_oc_knowledge_set() {
    local key="${1:?usage: superpos_oc_knowledge_set KEY VALUE_JSON [SCOPE] [VISIBILITY]}"
    local value="${2:?usage: superpos_oc_knowledge_set KEY VALUE_JSON [SCOPE] [VISIBILITY]}"
    local scope="${3:-}"
    local visibility="${4:-}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    local -a create_args=(-k "$key" -v "$value")
    [[ -n "$scope" ]] && create_args+=(-s "$scope")
    [[ -n "$visibility" ]] && create_args+=(-V "$visibility")

    # Try create first
    local result rc=0
    result=$(superpos_create_knowledge "$hive_id" "${create_args[@]}" 2>&1) || rc=$?

    if [[ $rc -eq "${SUPERPOS_ERR_CONFLICT}" ]]; then
        # Key exists — look up entry by exact key+scope, then update
        local entries entry_id effective_scope
        effective_scope="${scope:-hive}"
        local -a list_args=(-k "$key")
        [[ -n "$scope" ]] && list_args+=(-s "$scope")
        entries=$(superpos_list_knowledge "$hive_id" "${list_args[@]}") || return $?
        # Filter for exact key AND exact scope (API key filter is pattern-based)
        entry_id=$(echo "$entries" | jq -r \
            --arg k "$key" --arg s "$effective_scope" \
            '[.[] | select(.key == $k and ((.scope // "hive") == $s))] | .[0].id // empty' 2>/dev/null)

        if [[ -z "$entry_id" ]]; then
            echo "Knowledge key '$key' conflict but no exact match found (key='$key', scope='$effective_scope')." >&2
            return "$SUPERPOS_ERR"
        fi

        local -a update_args=(-v "$value")
        [[ -n "$visibility" ]] && update_args+=(-V "$visibility")

        result=$(superpos_update_knowledge "$hive_id" "$entry_id" "${update_args[@]}") || return $?
        entry_id=$(echo "$result" | jq -r '.id // "'"$entry_id"'"' 2>/dev/null)
        echo "Knowledge entry updated: $entry_id (key: $key)"
        return $SUPERPOS_OK
    elif [[ $rc -ne 0 ]]; then
        echo "$result" >&2
        return $rc
    fi

    local entry_id
    entry_id=$(echo "$result" | jq -r '.id // "unknown"' 2>/dev/null)
    echo "Knowledge entry created: $entry_id (key: $key)"
    return $SUPERPOS_OK
}

# ── Delete ──────────────────────────────────────────────────────
# superpos_oc_knowledge_delete ENTRY_ID — Delete a knowledge entry.
superpos_oc_knowledge_delete() {
    local entry_id="${1:?usage: superpos_oc_knowledge_delete ENTRY_ID}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"

    superpos_delete_knowledge "$hive_id" "$entry_id" || return $?
    echo "Knowledge entry $entry_id deleted."
    return $SUPERPOS_OK
}
