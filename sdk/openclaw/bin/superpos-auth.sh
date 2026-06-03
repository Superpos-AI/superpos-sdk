#!/usr/bin/env bash
# superpos-auth.sh — OpenClaw-specific authentication for Superpos.
#
# Sources the Shell SDK and provides auto-register/login flow
# with token and agent metadata persistence.
#
# Functions:
#   superpos_oc_ensure_auth   — Validate or obtain authentication
#   superpos_oc_register      — Register a new OpenClaw agent
#   superpos_oc_login         — Login an existing agent
#
# Env vars:
#   SUPERPOS_AGENT_NAME     — Agent name for registration
#   SUPERPOS_AGENT_SECRET         — Shared secret for register/login fallback
#   SUPERPOS_AGENT_ID             — Agent ID for login/refresh (set after first registration)
#   SUPERPOS_AGENT_REFRESH_TOKEN  — Refresh token for token renewal without secret
#   SUPERPOS_HIVE_ID              — Target hive ID
#   SUPERPOS_CAPABILITIES         — Comma-separated capability list (default: "general")

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
if [[ -z "${SCRIPT_DIR:-}" ]]; then
    _src="${BASH_SOURCE[0]}"
    while [[ -L "$_src" ]]; do
        _dir="$(cd "$(dirname "$_src")" && pwd)"
        _src="$(readlink "$_src")"
        [[ "$_src" != /* ]] && _src="$_dir/$_src"
    done
    SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
    unset _src _dir
fi

# ── Config directory ────────────────────────────────────────────
_superpos_oc_config_dir() {
    if [[ -n "${SUPERPOS_CONFIG_DIR:-}" ]]; then
        echo "$SUPERPOS_CONFIG_DIR"
    elif [[ -n "${APIARY_CONFIG_DIR:-}" ]]; then
        echo "$APIARY_CONFIG_DIR"
    elif [[ -d "${HOME}/.config/superpos" ]]; then
        echo "${HOME}/.config/superpos"
    elif [[ -d "${HOME}/.config/apiary" ]]; then
        echo "${HOME}/.config/apiary"
    else
        echo "${HOME}/.config/superpos"
    fi
}

_superpos_oc_agent_file() {
    echo "$(_superpos_oc_config_dir)/agent.json"
}

_superpos_oc_refresh_token_file() {
    echo "$(_superpos_oc_config_dir)/refresh-token"
}

_superpos_oc_sync_token_file() {
    if [[ -z "${SUPERPOS_TOKEN_FILE:-}" ]]; then
        SUPERPOS_TOKEN_FILE="$(_superpos_oc_config_dir)/token"
        export SUPERPOS_TOKEN_FILE
    fi
}

# ── Load persisted agent metadata ───────────────────────────────
_superpos_oc_load_agent() {
    local agent_file
    agent_file=$(_superpos_oc_agent_file)
    if [[ -f "$agent_file" ]]; then
        # Validate JSON before parsing — malformed file must not abort
        # the script under set -e when env vars already provide auth.
        if ! jq empty "$agent_file" 2>/dev/null; then
            _superpos_debug "Warning: $agent_file contains invalid JSON, skipping metadata load"
            return 0
        fi
        if [[ -z "${SUPERPOS_AGENT_ID:-}" ]]; then
            SUPERPOS_AGENT_ID=$(jq -r '.id // empty' "$agent_file")
            export SUPERPOS_AGENT_ID
        fi
        if [[ -z "${SUPERPOS_HIVE_ID:-}" ]]; then
            SUPERPOS_HIVE_ID=$(jq -r '.hive_id // empty' "$agent_file")
            export SUPERPOS_HIVE_ID
        fi
        if [[ -z "${SUPERPOS_AGENT_NAME:-}" ]]; then
            SUPERPOS_AGENT_NAME=$(jq -r '.name // empty' "$agent_file")
            export SUPERPOS_AGENT_NAME
        fi
    fi
}

_superpos_oc_load_refresh_token() {
    if [[ -n "${SUPERPOS_AGENT_REFRESH_TOKEN:-}" ]]; then
        return 0
    fi

    local refresh_file
    refresh_file=$(_superpos_oc_refresh_token_file)
    if [[ -f "$refresh_file" ]]; then
        SUPERPOS_AGENT_REFRESH_TOKEN=$(<"$refresh_file")
        export SUPERPOS_AGENT_REFRESH_TOKEN
    fi
}

_superpos_oc_save_refresh_token() {
    local refresh_token="${1:-}"
    if [[ -z "$refresh_token" ]]; then
        return 0
    fi

    local config_dir refresh_file
    config_dir=$(_superpos_oc_config_dir)
    refresh_file=$(_superpos_oc_refresh_token_file)
    mkdir -p "$config_dir"
    printf '%s\n' "$refresh_token" > "$refresh_file"
    chmod 600 "$refresh_file"

    SUPERPOS_AGENT_REFRESH_TOKEN="$refresh_token"
    export SUPERPOS_AGENT_REFRESH_TOKEN
}

# ── Save agent metadata ────────────────────────────────────────
_superpos_oc_save_agent() {
    local id="$1" name="$2" hive_id="$3"
    local config_dir agent_file
    config_dir=$(_superpos_oc_config_dir)
    agent_file=$(_superpos_oc_agent_file)
    mkdir -p "$config_dir"
    jq -n --arg id "$id" --arg name "$name" --arg hive_id "$hive_id" \
        '{id: $id, name: $name, hive_id: $hive_id}' > "$agent_file"
    chmod 600 "$agent_file"
    SUPERPOS_AGENT_ID="$id"
    export SUPERPOS_AGENT_ID
}

# ── Register ────────────────────────────────────────────────────
# superpos_oc_register — Register a new OpenClaw agent.
#   Uses SUPERPOS_AGENT_NAME, SUPERPOS_HIVE_ID, SUPERPOS_AGENT_SECRET,
#   SUPERPOS_CAPABILITIES env vars.
superpos_oc_register() {
    local name="${SUPERPOS_AGENT_NAME:?SUPERPOS_AGENT_NAME must be set}"
    local hive_id="${SUPERPOS_HIVE_ID:?SUPERPOS_HIVE_ID must be set}"
    local secret="${SUPERPOS_AGENT_SECRET:?SUPERPOS_AGENT_SECRET must be set}"
    local caps="${SUPERPOS_CAPABILITIES:-general}"

    _superpos_oc_sync_token_file

    # Convert comma-separated capabilities to JSON array
    local caps_json
    caps_json=$(echo "$caps" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))')

    local result
    result=$(superpos_register \
        -n "$name" \
        -h "$hive_id" \
        -s "$secret" \
        -t "openclaw" \
        -c "$caps_json"
    ) || return $?

    # Persist token/refresh-token and agent metadata
    SUPERPOS_TOKEN="$(echo "$result" | jq -r '.token // empty')"
    export SUPERPOS_TOKEN
    superpos_save_token
    _superpos_oc_save_refresh_token "$(echo "$result" | jq -r '.refresh_token // empty')"

    local agent_id agent_name
    agent_id=$(echo "$result" | jq -r '.agent.id // empty')
    agent_name=$(echo "$result" | jq -r '.agent.name // empty')
    if [[ -n "$agent_id" ]]; then
        _superpos_oc_save_agent "$agent_id" "$agent_name" "$hive_id"
    fi

    echo "$result"
    return $SUPERPOS_OK
}

# ── Login ───────────────────────────────────────────────────────
# superpos_oc_login — Login an existing agent.
#   Uses SUPERPOS_AGENT_ID and SUPERPOS_AGENT_SECRET env vars.
superpos_oc_login() {
    local agent_id="${SUPERPOS_AGENT_ID:?SUPERPOS_AGENT_ID must be set}"
    local secret="${SUPERPOS_AGENT_SECRET:?SUPERPOS_AGENT_SECRET must be set}"

    _superpos_oc_sync_token_file

    local result
    result=$(superpos_login -i "$agent_id" -s "$secret") || return $?

    SUPERPOS_TOKEN="$(echo "$result" | jq -r '.token // empty')"
    export SUPERPOS_TOKEN
    superpos_save_token
    _superpos_oc_save_refresh_token "$(echo "$result" | jq -r '.refresh_token // empty')"

    # Persist agent metadata (consistent with register flow).
    # Preserve existing hive_id/name when the response omits them so a
    # login that returns only {id, token} doesn't blank out saved state.
    local agent_name hive_id
    agent_name=$(echo "$result" | jq -r '.agent.name // empty')
    hive_id=$(echo "$result" | jq -r '.agent.hive_id // empty')

    # Fall back to current env / previously loaded values
    if [[ -z "$hive_id" ]]; then
        hive_id="${SUPERPOS_HIVE_ID:-}"
    fi
    if [[ -z "$agent_name" ]]; then
        agent_name="${SUPERPOS_AGENT_NAME:-}"
    fi

    _superpos_oc_save_agent "$agent_id" "${agent_name:-}" "${hive_id:-}"
    if [[ -n "$hive_id" ]]; then
        SUPERPOS_HIVE_ID="$hive_id"
        export SUPERPOS_HIVE_ID
    fi
    if [[ -n "$agent_name" ]]; then
        SUPERPOS_AGENT_NAME="$agent_name"
        export SUPERPOS_AGENT_NAME
    fi

    echo "$result"
    return $SUPERPOS_OK
}

# ── Refresh token ───────────────────────────────────────────────
# superpos_oc_refresh — Refresh access token using agent refresh token.
#   Uses SUPERPOS_AGENT_ID and SUPERPOS_AGENT_REFRESH_TOKEN env vars.
superpos_oc_refresh() {
    local agent_id="${SUPERPOS_AGENT_ID:?SUPERPOS_AGENT_ID must be set}"
    local refresh_token="${SUPERPOS_AGENT_REFRESH_TOKEN:?SUPERPOS_AGENT_REFRESH_TOKEN must be set}"

    _superpos_oc_sync_token_file

    local result
    result=$(superpos_refresh_agent_token -i "$agent_id" -r "$refresh_token") || return $?

    SUPERPOS_TOKEN="$(echo "$result" | jq -r '.token // empty')"
    export SUPERPOS_TOKEN
    superpos_save_token
    _superpos_oc_save_refresh_token "$(echo "$result" | jq -r '.refresh_token // empty')"

    local agent_name hive_id
    agent_name=$(echo "$result" | jq -r '.agent.name // empty')
    hive_id=$(echo "$result" | jq -r '.agent.hive_id // empty')

    if [[ -z "$hive_id" ]]; then
        hive_id="${SUPERPOS_HIVE_ID:-}"
    fi
    if [[ -z "$agent_name" ]]; then
        agent_name="${SUPERPOS_AGENT_NAME:-}"
    fi

    _superpos_oc_save_agent "$agent_id" "${agent_name:-}" "${hive_id:-}"
    if [[ -n "$hive_id" ]]; then
        SUPERPOS_HIVE_ID="$hive_id"
        export SUPERPOS_HIVE_ID
    fi
    if [[ -n "$agent_name" ]]; then
        SUPERPOS_AGENT_NAME="$agent_name"
        export SUPERPOS_AGENT_NAME
    fi

    echo "$result"
    return $SUPERPOS_OK
}

# ── Ensure auth ─────────────────────────────────────────────────
# superpos_oc_ensure_auth — Check for valid token, re-login or register as needed.
#   Returns 0 on success, non-zero on failure.
superpos_oc_ensure_auth() {
    # Load persisted state
    _superpos_oc_sync_token_file
    superpos_load_token
    _superpos_oc_load_agent
    _superpos_oc_load_refresh_token

    # If we have a token, validate it
    if [[ -n "${SUPERPOS_TOKEN:-}" ]]; then
        superpos_me >/dev/null 2>&1
        local me_rc=$?

        if [[ "$me_rc" -eq "$SUPERPOS_OK" ]]; then
            _superpos_debug "Auth valid (existing token)"
            return $SUPERPOS_OK
        fi

        if [[ "$me_rc" -eq "$SUPERPOS_ERR_AUTH" ]]; then
            _superpos_debug "Token expired or invalid (401), attempting refresh/login"
            SUPERPOS_TOKEN=""
            superpos_clear_token_file
        else
            _superpos_debug "Token validation failed with non-auth error ($me_rc); preserving persisted token"
            return "$me_rc"
        fi
    fi

    # Preferred recovery path for UI-managed agents: refresh token
    if [[ -n "${SUPERPOS_AGENT_ID:-}" && -n "${SUPERPOS_AGENT_REFRESH_TOKEN:-}" ]]; then
        _superpos_debug "Attempting token refresh for agent ID ${SUPERPOS_AGENT_ID}"
        if superpos_oc_refresh >/dev/null 2>&1; then
            _superpos_debug "Token refresh successful"
            return $SUPERPOS_OK
        fi
        _superpos_debug "Token refresh failed, trying secret-based fallback if configured"
    fi

    # Secret-based fallback for bootstrap/manual flows
    if [[ -n "${SUPERPOS_AGENT_ID:-}" && -n "${SUPERPOS_AGENT_SECRET:-}" ]]; then
        _superpos_debug "Attempting login with agent ID ${SUPERPOS_AGENT_ID}"
        if superpos_oc_login >/dev/null 2>&1; then
            _superpos_debug "Login successful"
            return $SUPERPOS_OK
        fi
        _superpos_debug "Login failed, attempting registration..."
    fi

    # Fall back to registration
    if [[ -n "${SUPERPOS_AGENT_NAME:-}" && -n "${SUPERPOS_HIVE_ID:-}" && -n "${SUPERPOS_AGENT_SECRET:-}" ]]; then
        _superpos_debug "Attempting registration as ${SUPERPOS_AGENT_NAME}"
        if superpos_oc_register >/dev/null 2>&1; then
            _superpos_debug "Registration successful"
            return $SUPERPOS_OK
        fi
        _superpos_err "Registration failed"
        return $SUPERPOS_ERR_AUTH
    fi

    _superpos_err "Cannot authenticate: set SUPERPOS_TOKEN (or SUPERPOS_AGENT_ID+SUPERPOS_AGENT_REFRESH_TOKEN), or provide SUPERPOS_AGENT_SECRET for login/register fallback"
    return $SUPERPOS_ERR_AUTH
}
