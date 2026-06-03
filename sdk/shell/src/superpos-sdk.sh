#!/usr/bin/env bash
# superpos-sdk.sh — Pure Bash client for the Superpos v1 API.
#
# Source this file in your script:
#   source superpos-sdk.sh
#
# Dependencies: bash 4+, curl, jq
# Env vars:
#   SUPERPOS_BASE_URL  — API base URL (required, no trailing slash)
#   SUPERPOS_TOKEN     — Bearer token (set automatically by auth helpers)
#   SUPERPOS_AGENT_REFRESH_TOKEN — Agent refresh token (set by register/login/refresh helpers)
#   SUPERPOS_TIMEOUT   — Request timeout in seconds (default: 30)
#   SUPERPOS_TOKEN_FILE — Path to persisted token file (default: ~/.config/superpos/token)
#   SUPERPOS_DEBUG     — Set to 1 for verbose curl output on stderr
#
# Legacy env vars (backward compat — APIARY_* are accepted as fallbacks):
#   APIARY_BASE_URL  → SUPERPOS_BASE_URL
#   APIARY_TOKEN / APIARY_API_TOKEN → SUPERPOS_TOKEN
#   APIARY_HIVE_ID   → SUPERPOS_HIVE_ID
#   APIARY_AGENT_ID  → SUPERPOS_AGENT_ID
#   APIARY_REFRESH_TOKEN → SUPERPOS_AGENT_REFRESH_TOKEN

# ── Version ──────────────────────────────────────────────────────
SUPERPOS_SDK_VERSION="0.1.0"

# ── Exit codes ───────────────────────────────────────────────────
readonly SUPERPOS_OK=0
readonly SUPERPOS_ERR=1
readonly SUPERPOS_ERR_VALIDATION=2   # 422
readonly SUPERPOS_ERR_AUTH=3         # 401
readonly SUPERPOS_ERR_PERMISSION=4   # 403
readonly SUPERPOS_ERR_NOT_FOUND=5    # 404
readonly SUPERPOS_ERR_CONFLICT=6     # 409
readonly SUPERPOS_ERR_DEPS=7         # missing dependencies
readonly SUPERPOS_ERR_RATE_LIMIT=8   # 429

# Rate-limit retry-after value (set by _superpos_request on 429 responses)
_SUPERPOS_RETRY_AFTER=""

# Backpressure signal from poll responses (set by superpos_poll_tasks).
# Contains the server-recommended milliseconds to wait before the next poll.
# 0 means "poll immediately"; >0 means "wait this long".
# Scripts that call superpos_poll_tasks can read this variable to sleep accordingly.
_SUPERPOS_NEXT_POLL_MS=0

# ── Legacy APIARY_* env var fallbacks ────────────────────────────
# Existing agents that still export APIARY_* variables will work
# seamlessly.  New SUPERPOS_* vars always take precedence.
: "${SUPERPOS_BASE_URL:=${APIARY_BASE_URL:-}}"
: "${SUPERPOS_TOKEN:=${APIARY_API_TOKEN:-${APIARY_TOKEN:-}}}"
: "${SUPERPOS_HIVE_ID:=${APIARY_HIVE_ID:-}}"
: "${SUPERPOS_AGENT_ID:=${APIARY_AGENT_ID:-}}"
: "${SUPERPOS_AGENT_REFRESH_TOKEN:=${APIARY_REFRESH_TOKEN:-}}"
: "${SUPERPOS_TIMEOUT:=${APIARY_TIMEOUT:-}}"
: "${SUPERPOS_DEBUG:=${APIARY_DEBUG:-}}"

# ── Dependency check ─────────────────────────────────────────────
superpos_check_deps() {
    local missing=()
    command -v curl >/dev/null 2>&1 || missing+=("curl")
    command -v jq   >/dev/null 2>&1 || missing+=("jq")
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "superpos-sdk: missing required dependencies: ${missing[*]}" >&2
        return $SUPERPOS_ERR_DEPS
    fi
    # Check bash version
    if [[ ${BASH_VERSINFO[0]} -lt 4 ]]; then
        echo "superpos-sdk: requires bash 4+, found ${BASH_VERSION}" >&2
        return $SUPERPOS_ERR_DEPS
    fi
    return $SUPERPOS_OK
}

# ── Internal helpers ─────────────────────────────────────────────

# _superpos_debug MSG — print to stderr when SUPERPOS_DEBUG=1
_superpos_debug() {
    [[ "${SUPERPOS_DEBUG:-0}" == "1" ]] && echo "[superpos-debug] $*" >&2
    return 0
}

# _superpos_err MSG — print error to stderr
_superpos_err() {
    echo "superpos-sdk: $*" >&2
}

# _superpos_exit_code HTTP_STATUS — map HTTP status to exit code
_superpos_exit_code() {
    local status="$1"
    case "$status" in
        2[0-9][0-9]) echo $SUPERPOS_OK ;;
        401)         echo $SUPERPOS_ERR_AUTH ;;
        403)         echo $SUPERPOS_ERR_PERMISSION ;;
        404)         echo $SUPERPOS_ERR_NOT_FOUND ;;
        409)         echo $SUPERPOS_ERR_CONFLICT ;;
        422)         echo $SUPERPOS_ERR_VALIDATION ;;
        429)         echo $SUPERPOS_ERR_RATE_LIMIT ;;
        *)           echo $SUPERPOS_ERR ;;
    esac
}

# _superpos_request METHOD PATH [JSON_BODY]
#   Sends HTTP request, unwraps envelope, prints data to stdout.
#   Returns mapped exit code. Errors go to stderr.
_superpos_request() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local url="${SUPERPOS_BASE_URL:?SUPERPOS_BASE_URL must be set}${path}"
    local timeout="${SUPERPOS_TIMEOUT:-30}"

    local _header_file
    _header_file=$(mktemp "${TMPDIR:-/tmp}/superpos-sdk-headers.XXXXXXXXXX") || {
        _superpos_err "failed to create temp file for response headers"
        return $SUPERPOS_ERR
    }

    local -a curl_args=(
        --silent
        --show-error
        --max-time "$timeout"
        --write-out '\n%{http_code}'
        -D "$_header_file"
        -H 'Accept: application/json'
    )

    if [[ -n "${SUPERPOS_TOKEN:-}" ]]; then
        curl_args+=(-H "Authorization: Bearer ${SUPERPOS_TOKEN}")
    fi

    if [[ -n "$body" ]]; then
        curl_args+=(-H 'Content-Type: application/json' -d "$body")
    fi

    [[ "${SUPERPOS_DEBUG:-0}" == "1" ]] && curl_args+=(--verbose) 2>/dev/null

    _superpos_debug "$method $url"
    [[ -n "$body" ]] && _superpos_debug "body: $body"

    # Execute request — capture both body and status code
    local raw_output
    raw_output=$(curl -X "$method" "${curl_args[@]}" "$url" 2>&${_superpos_debug_fd:-2}) || {
        _superpos_err "curl failed (network error or timeout)"
        rm -f "$_header_file" 2>/dev/null || true
        return $SUPERPOS_ERR
    }

    # Extract Retry-After header for rate-limit handling
    _SUPERPOS_RETRY_AFTER=""
    local _ra_line
    _ra_line=$(grep -i '^retry-after:' "$_header_file" 2>/dev/null | head -1) || true
    if [[ -n "${_ra_line:-}" ]]; then
        _SUPERPOS_RETRY_AFTER=$(echo "$_ra_line" | sed 's/^[^:]*:[[:space:]]*//' | tr -d '\r')
    fi
    rm -f "$_header_file" 2>/dev/null || true

    # Split response: last line is HTTP status code
    local http_status
    http_status=$(echo "$raw_output" | tail -n1)
    local response_body
    response_body=$(echo "$raw_output" | sed '$d')

    _superpos_debug "HTTP $http_status"

    # Handle 204 No Content
    if [[ "$http_status" == "204" ]]; then
        return $SUPERPOS_OK
    fi

    # Verify JSON response — always fail on non-JSON, even for 2xx
    if ! echo "$response_body" | jq empty 2>/dev/null; then
        _superpos_err "HTTP ${http_status}: non-JSON response"
        [[ -n "$response_body" ]] && _superpos_err "${response_body:0:200}"
        return $SUPERPOS_ERR
    fi

    local exit_code
    exit_code=$(_superpos_exit_code "$http_status")

    if [[ "$exit_code" -ne 0 ]]; then
        # Extract error message(s) from envelope
        local errors
        errors=$(echo "$response_body" | jq -r '.errors // empty')
        if [[ -n "$errors" && "$errors" != "null" ]]; then
            # Handle array of errors
            if echo "$response_body" | jq -e '.errors | type == "array"' >/dev/null 2>&1; then
                echo "$response_body" | jq -r '.errors[] | "[\(.code // "error")] \(.message // "Unknown error")\(if .field then " (field: \(.field))" else "" end)"' >&2
            # Handle object-style Laravel errors
            elif echo "$response_body" | jq -e '.errors | type == "object"' >/dev/null 2>&1; then
                echo "$response_body" | jq -r '.errors | to_entries[] | .key as $field | (.value | if type == "array" then .[] else . end) | "[validation_error] \(.) (field: \($field))"' >&2
            fi
        else
            _superpos_err "HTTP ${http_status}"
        fi
        # Still output the full response body for programmatic consumption
        echo "$response_body"
        return "$exit_code"
    fi

    # Success — unwrap envelope: output .data
    local data
    data=$(echo "$response_body" | jq '.data // empty')
    if [[ -n "$data" && "$data" != "null" ]]; then
        echo "$data"
    fi

    return $SUPERPOS_OK
}

# _superpos_urlencode VALUE — percent-encode a value for use in query strings.
#   Uses jq's @uri filter (RFC 3986).
_superpos_urlencode() {
    jq -rn --arg v "$1" '$v | @uri'
}

# _superpos_build_json KEY1 VAL1 KEY2 VAL2 ...
#   Build JSON object from key-value pairs, skipping empty values.
#   Values starting with '{' or '[' and booleans/null are treated as raw JSON.
#   Digit-only strings are treated as strings by default (safe for secrets/IDs).
#   Append ':n' to a key name to force numeric treatment, e.g. "priority:n" "3".
_superpos_build_json() {
    local json="{}"
    while [[ $# -ge 2 ]]; do
        local key="$1" val="$2"
        shift 2
        [[ -z "$val" ]] && continue
        # Explicit numeric hint: key ends with ':n'
        local force_raw=false
        if [[ "$key" == *":n" ]]; then
            key="${key%:n}"
            force_raw=true
        fi
        # Validate forced-numeric values — only allow numbers (reject arrays, objects, booleans, null)
        if $force_raw && ! [[ "$val" =~ ^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$ ]]; then
            _superpos_err "build_json: invalid numeric value for '$key': $val"
            return $SUPERPOS_ERR
        fi
        # Detect raw JSON values (objects, arrays, booleans, null, or forced numeric)
        if $force_raw || [[ "$val" =~ ^[\{\[] ]] || [[ "$val" == "true" || "$val" == "false" || "$val" == "null" ]]; then
            json=$(echo "$json" | jq --arg k "$key" --argjson v "$val" '. + {($k): $v}') || {
                _superpos_err "build_json: invalid JSON value for '$key': $val"
                return $SUPERPOS_ERR
            }
        else
            json=$(echo "$json" | jq --arg k "$key" --arg v "$val" '. + {($k): $v}')
        fi
    done
    echo "$json"
}

# ── Agent Auth ───────────────────────────────────────────────────

# superpos_register — register a new agent and store the token.
#   -n NAME  -h HIVE_ID  -s SECRET  [-a ORGANIZATION_ID] [-t TYPE] [-c CAPABILITIES_JSON] [-m METADATA_JSON]
#   Outputs full data envelope (agent + token) to stdout.
superpos_register() {
    local name="" hive_id="" secret="" organization_id="" agent_type="" capabilities="" metadata=""
    local OPTIND OPTARG opt
    while getopts "n:h:s:a:t:c:m:" opt; do
        case "$opt" in
            n) name="$OPTARG" ;;
            h) hive_id="$OPTARG" ;;
            s) secret="$OPTARG" ;;
            a) organization_id="$OPTARG" ;;
            t) agent_type="$OPTARG" ;;
            c) capabilities="$OPTARG" ;;
            m) metadata="$OPTARG" ;;
            *) _superpos_err "register: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$name" || -z "$hive_id" || -z "$secret" ]]; then
        _superpos_err "register: -n NAME, -h HIVE_ID, and -s SECRET are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "name" "$name" \
        "hive_id" "$hive_id" \
        "secret" "$secret" \
        "organization_id" "$organization_id" \
        "type" "$agent_type" \
        "capabilities" "$capabilities" \
        "metadata" "$metadata"
    ) || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/agents/register" "$body") || return $?

    # Auto-store auth credentials
    SUPERPOS_TOKEN=$(echo "$result" | jq -r '.token // empty')
    SUPERPOS_AGENT_REFRESH_TOKEN=$(echo "$result" | jq -r '.refresh_token // empty')
    echo "$result"
    return $SUPERPOS_OK
}

# superpos_login — authenticate an existing agent.
#   -i AGENT_ID  -s SECRET
superpos_login() {
    local agent_id="" secret=""
    local OPTIND OPTARG opt
    while getopts "i:s:" opt; do
        case "$opt" in
            i) agent_id="$OPTARG" ;;
            s) secret="$OPTARG" ;;
            *) _superpos_err "login: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$agent_id" || -z "$secret" ]]; then
        _superpos_err "login: -i AGENT_ID and -s SECRET are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json "agent_id" "$agent_id" "secret" "$secret") || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/agents/login" "$body") || return $?

    SUPERPOS_TOKEN=$(echo "$result" | jq -r '.token // empty')
    SUPERPOS_AGENT_REFRESH_TOKEN=$(echo "$result" | jq -r '.refresh_token // empty')
    echo "$result"
    return $SUPERPOS_OK
}

# superpos_refresh_agent_token — refresh an expired/expiring token without the agent secret.
#   -i AGENT_ID  -r REFRESH_TOKEN
superpos_refresh_agent_token() {
    local agent_id="" refresh_token=""
    local OPTIND OPTARG opt
    while getopts "i:r:" opt; do
        case "$opt" in
            i) agent_id="$OPTARG" ;;
            r) refresh_token="$OPTARG" ;;
            *) _superpos_err "refresh_agent_token: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$agent_id" || -z "$refresh_token" ]]; then
        _superpos_err "refresh_agent_token: -i AGENT_ID and -r REFRESH_TOKEN are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json "agent_id" "$agent_id" "refresh_token" "$refresh_token") || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/agents/token/refresh" "$body") || return $?

    SUPERPOS_TOKEN=$(echo "$result" | jq -r '.token // empty')
    SUPERPOS_AGENT_REFRESH_TOKEN=$(echo "$result" | jq -r '.refresh_token // empty')
    echo "$result"
    return $SUPERPOS_OK
}

# superpos_logout — revoke the current token.
#   Always clears SUPERPOS_TOKEN regardless of HTTP/network outcome.
superpos_logout() {
    local rc=0
    _superpos_request POST "/api/v1/agents/logout" || rc=$?
    SUPERPOS_TOKEN=""
    return $rc
}

# ── Token file persistence ────────────────────────────────────────
# Optional file-based token storage for multi-command CLI workflows.
# Override the file location with SUPERPOS_TOKEN_FILE env var.

_superpos_token_file() {
    echo "${SUPERPOS_TOKEN_FILE:-${HOME}/.config/superpos/token}"
}

# superpos_save_token — persist SUPERPOS_TOKEN to a file (mode 600).
superpos_save_token() {
    local tf
    tf=$(_superpos_token_file)
    if [[ -n "${SUPERPOS_TOKEN:-}" ]]; then
        mkdir -p "$(dirname "$tf")"
        printf '%s\n' "$SUPERPOS_TOKEN" > "$tf"
        chmod 600 "$tf"
    fi
}

# superpos_load_token — load token from file if SUPERPOS_TOKEN is unset.
superpos_load_token() {
    if [[ -n "${SUPERPOS_TOKEN:-}" ]]; then
        return 0
    fi
    local tf
    tf=$(_superpos_token_file)
    if [[ -f "$tf" ]]; then
        SUPERPOS_TOKEN=$(<"$tf")
        export SUPERPOS_TOKEN
    fi
}

# superpos_clear_token_file — remove the persisted token file.
superpos_clear_token_file() {
    rm -f "$(_superpos_token_file)"
}

# superpos_me — get the authenticated agent's profile.
superpos_me() {
    _superpos_request GET "/api/v1/agents/me"
}

# ── Agent Lifecycle ──────────────────────────────────────────────

# superpos_heartbeat — send a heartbeat signal.
#   [-m METADATA_JSON]
superpos_heartbeat() {
    local metadata=""
    local OPTIND OPTARG opt
    while getopts "m:" opt; do
        case "$opt" in
            m) metadata="$OPTARG" ;;
            *) _superpos_err "heartbeat: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body="{}"
    if [[ -n "$metadata" ]]; then
        body=$(_superpos_build_json "metadata" "$metadata") || return $SUPERPOS_ERR
    fi

    _superpos_request POST "/api/v1/agents/heartbeat" "$body"
}

# superpos_update_status — update the agent's status.
#   STATUS (online|busy|idle|offline|error)
superpos_update_status() {
    local status="${1:?usage: superpos_update_status STATUS}"
    local body
    body=$(_superpos_build_json "status" "$status") || return $SUPERPOS_ERR
    _superpos_request PATCH "/api/v1/agents/status" "$body"
}

# ── Drain Mode ───────────────────────────────────────────────────

# superpos_enter_drain — enter drain mode (stop accepting new tasks).
#   [-r REASON] [-d DEADLINE_MINUTES]
superpos_enter_drain() {
    local reason="" deadline_minutes=""
    local OPTIND OPTARG opt
    while getopts "r:d:" opt; do
        case "$opt" in
            r) reason="$OPTARG" ;;
            d) deadline_minutes="$OPTARG" ;;
            *) _superpos_err "enter_drain: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "reason" "$reason" "deadline_minutes:n" "$deadline_minutes") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/agents/drain" "$body"
}

# superpos_exit_drain — exit drain mode.
superpos_exit_drain() {
    _superpos_request POST "/api/v1/agents/undrain"
}

# superpos_drain_status — get current drain status.
superpos_drain_status() {
    _superpos_request GET "/api/v1/agents/drain"
}

# ── Key Rotation ─────────────────────────────────────────────────

# superpos_rotate_key — rotate the agent's API key.
#   -s NEW_SECRET  [-g GRACE_PERIOD_MINUTES]
#   Returns new token; auto-stores in SUPERPOS_TOKEN.
superpos_rotate_key() {
    local new_secret="" grace_period_minutes=""
    local OPTIND OPTARG opt
    while getopts "s:g:" opt; do
        case "$opt" in
            s) new_secret="$OPTARG" ;;
            g) grace_period_minutes="$OPTARG" ;;
            *) _superpos_err "rotate_key: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$new_secret" ]]; then
        _superpos_err "rotate_key: -s NEW_SECRET is required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "new_secret" "$new_secret" \
        "grace_period_minutes:n" "$grace_period_minutes"
    ) || return $SUPERPOS_ERR

    local result
    result=$(_superpos_request POST "/api/v1/agents/key/rotate" "$body") || return $?

    SUPERPOS_TOKEN=$(echo "$result" | jq -r '.token // empty')
    SUPERPOS_AGENT_REFRESH_TOKEN=$(echo "$result" | jq -r '.refresh_token // empty')
    export SUPERPOS_TOKEN SUPERPOS_AGENT_REFRESH_TOKEN

    echo "$result"
    return $SUPERPOS_OK
}

# superpos_revoke_previous_key — immediately revoke the grace-period key.
superpos_revoke_previous_key() {
    _superpos_request POST "/api/v1/agents/key/revoke"
}

# superpos_key_status — get current key rotation status.
superpos_key_status() {
    _superpos_request GET "/api/v1/agents/key/status"
}

# ── Pool Health ───────────────────────────────────────────────────

# superpos_get_pool_health — get pool health metrics for a hive.
#   HIVE_ID  [-w WINDOW_MINUTES]
superpos_get_pool_health() {
    local hive_id="${1:?usage: superpos_get_pool_health HIVE_ID [-w WINDOW_MINUTES]}"
    shift
    local window=""
    local OPTIND OPTARG opt
    while getopts "w:" opt; do
        case "$opt" in
            w) window="$OPTARG" ;;
            *) _superpos_err "get_pool_health: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$window" ]] && params+=("window=$(_superpos_urlencode "$window")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/pool/health${qs}"
}

# ── Tasks ────────────────────────────────────────────────────────

# superpos_create_task — create a task in a hive.
#   HIVE_ID  -t TYPE  [-p PRIORITY] [-a TARGET_AGENT_ID] [-c TARGET_CAPABILITY]
#   [-d PAYLOAD_JSON] [-T TIMEOUT_SECONDS] [-r MAX_RETRIES] [-P PARENT_TASK_ID]
#   [-x CONTEXT_REFS_JSON] [-g GUARANTEE] [-e EXPIRES_AT]
#   [-I INVOKE_INSTRUCTIONS] [-X INVOKE_CONTEXT_JSON]
#   [-S SUB_AGENT_DEFINITION_SLUG]
superpos_create_task() {
    local hive_id="${1:?usage: superpos_create_task HIVE_ID -t TYPE ...}"
    shift
    local task_type="" priority="" target_agent_id="" target_capability=""
    local payload="" timeout_seconds="" max_retries="" parent_task_id="" context_refs=""
    local guarantee="" expires_at="" invoke_instructions="" invoke_context=""
    local sub_agent_slug=""
    local OPTIND OPTARG opt
    while getopts "t:p:a:c:d:T:r:P:x:g:e:I:X:S:" opt; do
        case "$opt" in
            t) task_type="$OPTARG" ;;
            p) priority="$OPTARG" ;;
            a) target_agent_id="$OPTARG" ;;
            c) target_capability="$OPTARG" ;;
            d) payload="$OPTARG" ;;
            T) timeout_seconds="$OPTARG" ;;
            r) max_retries="$OPTARG" ;;
            P) parent_task_id="$OPTARG" ;;
            x) context_refs="$OPTARG" ;;
            g) guarantee="$OPTARG" ;;
            e) expires_at="$OPTARG" ;;
            I) invoke_instructions="$OPTARG" ;;
            X) invoke_context="$OPTARG" ;;
            S) sub_agent_slug="$OPTARG" ;;
            *) _superpos_err "create_task: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$task_type" ]]; then
        _superpos_err "create_task: -t TYPE is required"
        return $SUPERPOS_ERR
    fi

    local invoke_json=""
    if [[ -n "$invoke_instructions" || -n "$invoke_context" ]]; then
        invoke_json=$(_superpos_build_json \
            "instructions" "$invoke_instructions" \
            "context" "$invoke_context"
        ) || return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "type" "$task_type" \
        "priority:n" "$priority" \
        "target_agent_id" "$target_agent_id" \
        "target_capability" "$target_capability" \
        "payload" "$payload" \
        "timeout_seconds:n" "$timeout_seconds" \
        "max_retries:n" "$max_retries" \
        "parent_task_id" "$parent_task_id" \
        "context_refs" "$context_refs" \
        "guarantee" "$guarantee" \
        "expires_at" "$expires_at" \
        "invoke" "$invoke_json" \
        "sub_agent_definition_slug" "$sub_agent_slug"
    ) || return $SUPERPOS_ERR

    _superpos_request POST "/api/v1/hives/${hive_id}/tasks" "$body"
}

# superpos_poll_tasks — poll for available tasks.
#   HIVE_ID  [-c CAPABILITY] [-l LIMIT]
#
#   Sets _SUPERPOS_NEXT_POLL_MS to the server-recommended backoff (ms) before the
#   next poll.  Scripts may read this value to sleep accordingly:
#
#       superpos_poll_tasks "$HIVE_ID"
#       [[ "$_SUPERPOS_NEXT_POLL_MS" -gt 0 ]] && sleep "$(( (_SUPERPOS_NEXT_POLL_MS + 999) / 1000 ))"
superpos_poll_tasks() {
    local hive_id="${1:?usage: superpos_poll_tasks HIVE_ID [-c CAPABILITY] [-l LIMIT]}"
    shift
    local capability="" limit=""
    local OPTIND OPTARG opt
    while getopts "c:l:" opt; do
        case "$opt" in
            c) capability="$OPTARG" ;;
            l) limit="$OPTARG" ;;
            *) _superpos_err "poll_tasks: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$capability" ]] && params+=("capability=$(_superpos_urlencode "$capability")")
    [[ -n "$limit" ]]      && params+=("limit=$(_superpos_urlencode "$limit")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    # Capture the raw response body to extract both .data and meta.next_poll_ms.
    local url="${SUPERPOS_BASE_URL:?SUPERPOS_BASE_URL must be set}/api/v1/hives/${hive_id}/tasks/poll${qs}"
    local timeout="${SUPERPOS_TIMEOUT:-30}"

    local _poll_header_file
    _poll_header_file=$(mktemp "${TMPDIR:-/tmp}/superpos-sdk-poll-headers.XXXXXXXXXX") || {
        _superpos_err "poll_tasks: failed to create temp file for response headers"
        return $SUPERPOS_ERR
    }

    local -a curl_args=(
        --silent --show-error --max-time "$timeout"
        --write-out '\n%{http_code}'
        -D "$_poll_header_file"
        -H 'Accept: application/json'
    )
    [[ -n "${SUPERPOS_TOKEN:-}" ]] && curl_args+=(-H "Authorization: Bearer ${SUPERPOS_TOKEN}")
    [[ "${SUPERPOS_DEBUG:-0}" == "1" ]] && curl_args+=(--verbose)

    local raw_output
    raw_output=$(curl -X GET "${curl_args[@]}" "$url" 2>&${_superpos_debug_fd:-2}) || {
        _superpos_err "poll_tasks: curl failed (network error or timeout)"
        rm -f "$_poll_header_file" 2>/dev/null || true
        return $SUPERPOS_ERR
    }

    # Extract Retry-After header for rate-limit handling (mirrors _superpos_request behaviour).
    _SUPERPOS_RETRY_AFTER=""
    local _ra_line
    _ra_line=$(grep -i '^retry-after:' "$_poll_header_file" 2>/dev/null | head -1) || true
    if [[ -n "${_ra_line:-}" ]]; then
        _SUPERPOS_RETRY_AFTER=$(echo "$_ra_line" | sed 's/^[^:]*:[[:space:]]*//' | tr -d '\r')
    fi
    rm -f "$_poll_header_file" 2>/dev/null || true

    local http_status response_body
    http_status=$(echo "$raw_output" | tail -n1)
    response_body=$(echo "$raw_output" | sed '$d')

    if [[ "$http_status" == "204" ]]; then
        _SUPERPOS_NEXT_POLL_MS=0
        return $SUPERPOS_OK
    fi

    if ! echo "$response_body" | jq empty 2>/dev/null; then
        _superpos_err "poll_tasks: HTTP ${http_status}: non-JSON response"
        return $SUPERPOS_ERR
    fi

    local exit_code
    exit_code=$(_superpos_exit_code "$http_status")
    if [[ "$exit_code" -ne 0 ]]; then
        _superpos_err "poll_tasks: HTTP ${http_status}"
        echo "$response_body"
        return "$exit_code"
    fi

    # Extract backpressure signal from meta.
    _SUPERPOS_NEXT_POLL_MS=$(echo "$response_body" | jq -r '.meta.next_poll_ms // 0')
    _SUPERPOS_NEXT_POLL_MS="${_SUPERPOS_NEXT_POLL_MS:-0}"

    # Output the full envelope (preserving {data, meta, errors} shape for callers).
    echo "$response_body"

    return $SUPERPOS_OK
}

# _superpos_clear_sub_agent_env — unset all SUB_AGENT_* env vars.
#   Called before parsing a new claim response to prevent stale values from
#   leaking between tasks (FR-3 / NFR-1).
_superpos_clear_sub_agent_env() {
    unset SUB_AGENT_SLUG SUB_AGENT_MODEL SUB_AGENT_PROMPT
    unset SUB_AGENT_ID SUB_AGENT_NAME SUB_AGENT_VERSION
}

# superpos_claim_task — atomically claim a pending task.
#   HIVE_ID  TASK_ID
#
#   On success, parses the `sub_agent` block from the claim response and
#   exports the following environment variables for the caller:
#     SUB_AGENT_SLUG, SUB_AGENT_MODEL, SUB_AGENT_PROMPT,
#     SUB_AGENT_ID, SUB_AGENT_NAME, SUB_AGENT_VERSION
#
#   If the task has no sub-agent bound, all SUB_AGENT_* variables are unset
#   (i.e. no stale values from a prior task leak into the current one).
#
#   NOTE: env var exports are only visible in the caller's shell when
#   superpos_claim_task is invoked directly (not via command substitution).
#   The common pattern — mirroring superpos_register — is to redirect stdout
#   to a temp file so SUB_AGENT_* are set in the current shell:
#       superpos_claim_task "$HIVE" "$TASK" > /tmp/claim.json
#       echo "$SUB_AGENT_PROMPT"
superpos_claim_task() {
    local hive_id="${1:?usage: superpos_claim_task HIVE_ID TASK_ID}"
    local task_id="${2:?usage: superpos_claim_task HIVE_ID TASK_ID}"

    # Clear any stale sub-agent env vars from a previous task before we start.
    _superpos_clear_sub_agent_env

    local task_json
    task_json=$(_superpos_request PATCH "/api/v1/hives/${hive_id}/tasks/${task_id}/claim") || {
        local _rc=$?
        # Re-emit the body the request printed (error envelope) for the caller.
        [[ -n "$task_json" ]] && echo "$task_json"
        return "$_rc"
    }

    # Emit the claim response body (unwrapped `.data`) to stdout, preserving
    # the prior return-value contract.
    [[ -n "$task_json" ]] && echo "$task_json"

    # Parse and export the sub_agent block, if present. `jq -r` handles raw
    # strings (newlines, quotes, backslashes) correctly (NFR-3).
    if [[ -n "$task_json" ]] && echo "$task_json" | jq -e 'has("sub_agent") and (.sub_agent != null)' >/dev/null 2>&1; then
        SUB_AGENT_SLUG=$(echo "$task_json" | jq -r '.sub_agent.slug // ""')
        SUB_AGENT_MODEL=$(echo "$task_json" | jq -r '.sub_agent.model // ""')
        SUB_AGENT_PROMPT=$(echo "$task_json" | jq -r '.sub_agent.prompt // ""')
        SUB_AGENT_ID=$(echo "$task_json" | jq -r '.sub_agent.id // ""')
        SUB_AGENT_NAME=$(echo "$task_json" | jq -r '.sub_agent.name // ""')
        SUB_AGENT_VERSION=$(echo "$task_json" | jq -r '.sub_agent.version // ""')
        export SUB_AGENT_SLUG SUB_AGENT_MODEL SUB_AGENT_PROMPT
        export SUB_AGENT_ID SUB_AGENT_NAME SUB_AGENT_VERSION
    fi

    return $SUPERPOS_OK
}

# superpos_update_progress — report progress on a claimed task.
#   HIVE_ID  TASK_ID  -p PROGRESS  [-m STATUS_MESSAGE]
superpos_update_progress() {
    local hive_id="${1:?usage: superpos_update_progress HIVE_ID TASK_ID -p PROGRESS}"
    local task_id="${2:?usage: superpos_update_progress HIVE_ID TASK_ID -p PROGRESS}"
    shift 2
    local progress="" status_message=""
    local OPTIND OPTARG opt
    while getopts "p:m:" opt; do
        case "$opt" in
            p) progress="$OPTARG" ;;
            m) status_message="$OPTARG" ;;
            *) _superpos_err "update_progress: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$progress" ]]; then
        _superpos_err "update_progress: -p PROGRESS is required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json "progress:n" "$progress" "status_message" "$status_message") || return $SUPERPOS_ERR
    _superpos_request PATCH "/api/v1/hives/${hive_id}/tasks/${task_id}/progress" "$body"
}

# superpos_complete_task — mark a claimed task as completed.
#   HIVE_ID  TASK_ID  [-r RESULT_JSON] [-m STATUS_MESSAGE]
superpos_complete_task() {
    local hive_id="${1:?usage: superpos_complete_task HIVE_ID TASK_ID}"
    local task_id="${2:?usage: superpos_complete_task HIVE_ID TASK_ID}"
    shift 2
    local result="" status_message=""
    local OPTIND OPTARG opt
    while getopts "r:m:" opt; do
        case "$opt" in
            r) result="$OPTARG" ;;
            m) status_message="$OPTARG" ;;
            *) _superpos_err "complete_task: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "result" "$result" "status_message" "$status_message") || return $SUPERPOS_ERR
    _superpos_request PATCH "/api/v1/hives/${hive_id}/tasks/${task_id}/complete" "$body"
}

# superpos_deliver_response — deliver a response to a pending data_request response task.
#   HIVE_ID  RESPONSE_TASK_ID  [-r RESULT_JSON] [-m STATUS_MESSAGE]
#
# Uses POST /deliver-response which bypasses the normal in_progress/ownership
# checks.  The server verifies the calling agent has an in_progress task whose
# payload.response_task_id matches the target task ID.
superpos_deliver_response() {
    local hive_id="${1:?usage: superpos_deliver_response HIVE_ID RESPONSE_TASK_ID}"
    local response_task_id="${2:?usage: superpos_deliver_response HIVE_ID RESPONSE_TASK_ID}"
    shift 2
    local result="" status_message=""
    local OPTIND OPTARG opt
    while getopts "r:m:" opt; do
        case "$opt" in
            r) result="$OPTARG" ;;
            m) status_message="$OPTARG" ;;
            *) _superpos_err "deliver_response: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "result" "$result" "status_message" "$status_message") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/tasks/${response_task_id}/deliver-response" "$body"
}

# superpos_fail_task — mark a claimed task as failed.
#   HIVE_ID  TASK_ID  [-e ERROR_JSON] [-m STATUS_MESSAGE]
superpos_fail_task() {
    local hive_id="${1:?usage: superpos_fail_task HIVE_ID TASK_ID}"
    local task_id="${2:?usage: superpos_fail_task HIVE_ID TASK_ID}"
    shift 2
    local error="" status_message=""
    local OPTIND OPTARG opt
    while getopts "e:m:" opt; do
        case "$opt" in
            e) error="$OPTARG" ;;
            m) status_message="$OPTARG" ;;
            *) _superpos_err "fail_task: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "error" "$error" "status_message" "$status_message") || return $SUPERPOS_ERR
    _superpos_request PATCH "/api/v1/hives/${hive_id}/tasks/${task_id}/fail" "$body"
}

# ── Task Replay / Time Travel ─────────────────────────────────────

# superpos_get_task_trace — get the full execution trace for a task.
#   HIVE_ID  TASK_ID
superpos_get_task_trace() {
    local hive_id="${1:?usage: superpos_get_task_trace HIVE_ID TASK_ID}"
    local task_id="${2:?usage: superpos_get_task_trace HIVE_ID TASK_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/tasks/${task_id}/trace"
}

# superpos_replay_task — create a replay of a completed/failed/dead_letter/expired task.
#   HIVE_ID  TASK_ID  [-d OVERRIDE_PAYLOAD_JSON]
superpos_replay_task() {
    local hive_id="${1:?usage: superpos_replay_task HIVE_ID TASK_ID}"
    local task_id="${2:?usage: superpos_replay_task HIVE_ID TASK_ID}"
    shift 2
    local override_payload=""
    local OPTIND OPTARG opt
    while getopts "d:" opt; do
        case "$opt" in
            d) override_payload="$OPTARG" ;;
            *) _superpos_err "replay_task: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "override_payload" "$override_payload") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/tasks/${task_id}/replay" "$body"
}

# superpos_compare_tasks — compare two tasks by payload, result, and trace.
#   HIVE_ID  TASK_A_ID  TASK_B_ID
superpos_compare_tasks() {
    local hive_id="${1:?usage: superpos_compare_tasks HIVE_ID TASK_A_ID TASK_B_ID}"
    local task_a="${2:?usage: superpos_compare_tasks HIVE_ID TASK_A_ID TASK_B_ID}"
    local task_b="${3:?usage: superpos_compare_tasks HIVE_ID TASK_A_ID TASK_B_ID}"

    local qs="?task_a=$(_superpos_urlencode "$task_a")&task_b=$(_superpos_urlencode "$task_b")"
    _superpos_request GET "/api/v1/hives/${hive_id}/tasks/compare${qs}"
}

# ── Schedules ────────────────────────────────────────────────────

# superpos_list_schedules — list task schedules in a hive.
#   HIVE_ID  [-s STATUS]
superpos_list_schedules() {
    local hive_id="${1:?usage: superpos_list_schedules HIVE_ID [-s STATUS]}"
    shift
    local status=""
    local OPTIND OPTARG opt
    while getopts "s:" opt; do
        case "$opt" in
            s) status="$OPTARG" ;;
            *) _superpos_err "list_schedules: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$status" ]] && params+=("status=$(_superpos_urlencode "$status")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/schedules${qs}"
}

# superpos_get_schedule — get a single task schedule.
#   HIVE_ID  SCHEDULE_ID
superpos_get_schedule() {
    local hive_id="${1:?usage: superpos_get_schedule HIVE_ID SCHEDULE_ID}"
    local schedule_id="${2:?usage: superpos_get_schedule HIVE_ID SCHEDULE_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/schedules/${schedule_id}"
}

# superpos_create_schedule — create a task schedule.
#   HIVE_ID  -n NAME  -g TRIGGER_TYPE  -t TASK_TYPE
#   [-c CRON_EXPRESSION] [-i INTERVAL_SECONDS] [-R RUN_AT]
#   [-d TASK_PAYLOAD_JSON] [-p TASK_PRIORITY] [-a TASK_TARGET_AGENT_ID]
#   [-C TASK_TARGET_CAPABILITY] [-T TASK_TIMEOUT_SECONDS]
#   [-r TASK_MAX_RETRIES] [-o OVERLAP_POLICY] [-e EXPIRES_AT]
superpos_create_schedule() {
    local hive_id="${1:?usage: superpos_create_schedule HIVE_ID -n NAME -g TRIGGER_TYPE -t TASK_TYPE ...}"
    shift
    local name="" trigger_type="" task_type="" cron_expression="" interval_seconds=""
    local run_at="" task_payload="" task_priority="" task_target_agent_id=""
    local task_target_capability="" task_timeout_seconds="" task_max_retries=""
    local overlap_policy="" expires_at=""
    local OPTIND OPTARG opt
    while getopts "n:g:t:c:i:R:d:p:a:C:T:r:o:e:" opt; do
        case "$opt" in
            n) name="$OPTARG" ;;
            g) trigger_type="$OPTARG" ;;
            t) task_type="$OPTARG" ;;
            c) cron_expression="$OPTARG" ;;
            i) interval_seconds="$OPTARG" ;;
            R) run_at="$OPTARG" ;;
            d) task_payload="$OPTARG" ;;
            p) task_priority="$OPTARG" ;;
            a) task_target_agent_id="$OPTARG" ;;
            C) task_target_capability="$OPTARG" ;;
            T) task_timeout_seconds="$OPTARG" ;;
            r) task_max_retries="$OPTARG" ;;
            o) overlap_policy="$OPTARG" ;;
            e) expires_at="$OPTARG" ;;
            *) _superpos_err "create_schedule: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$name" || -z "$trigger_type" || -z "$task_type" ]]; then
        _superpos_err "create_schedule: -n NAME, -g TRIGGER_TYPE, and -t TASK_TYPE are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "name" "$name" \
        "trigger_type" "$trigger_type" \
        "task_type" "$task_type" \
        "cron_expression" "$cron_expression" \
        "interval_seconds:n" "$interval_seconds" \
        "run_at" "$run_at" \
        "task_payload" "$task_payload" \
        "task_priority:n" "$task_priority" \
        "task_target_agent_id" "$task_target_agent_id" \
        "task_target_capability" "$task_target_capability" \
        "task_timeout_seconds:n" "$task_timeout_seconds" \
        "task_max_retries:n" "$task_max_retries" \
        "overlap_policy" "$overlap_policy" \
        "expires_at" "$expires_at"
    ) || return $SUPERPOS_ERR

    _superpos_request POST "/api/v1/hives/${hive_id}/schedules" "$body"
}

# superpos_update_schedule — update a task schedule (partial update).
#   HIVE_ID  SCHEDULE_ID
#   [-n NAME] [-g TRIGGER_TYPE] [-t TASK_TYPE]
#   [-c CRON_EXPRESSION] [-i INTERVAL_SECONDS] [-R RUN_AT]
#   [-d TASK_PAYLOAD_JSON] [-p TASK_PRIORITY] [-a TASK_TARGET_AGENT_ID]
#   [-C TASK_TARGET_CAPABILITY] [-T TASK_TIMEOUT_SECONDS]
#   [-r TASK_MAX_RETRIES] [-o OVERLAP_POLICY] [-e EXPIRES_AT]
superpos_update_schedule() {
    local hive_id="${1:?usage: superpos_update_schedule HIVE_ID SCHEDULE_ID [-n NAME] ...}"
    local schedule_id="${2:?usage: superpos_update_schedule HIVE_ID SCHEDULE_ID [-n NAME] ...}"
    shift 2
    local name="" trigger_type="" task_type="" cron_expression="" interval_seconds=""
    local run_at="" task_payload="" task_priority="" task_target_agent_id=""
    local task_target_capability="" task_timeout_seconds="" task_max_retries=""
    local overlap_policy="" expires_at=""
    local OPTIND OPTARG opt
    while getopts "n:g:t:c:i:R:d:p:a:C:T:r:o:e:" opt; do
        case "$opt" in
            n) name="$OPTARG" ;;
            g) trigger_type="$OPTARG" ;;
            t) task_type="$OPTARG" ;;
            c) cron_expression="$OPTARG" ;;
            i) interval_seconds="$OPTARG" ;;
            R) run_at="$OPTARG" ;;
            d) task_payload="$OPTARG" ;;
            p) task_priority="$OPTARG" ;;
            a) task_target_agent_id="$OPTARG" ;;
            C) task_target_capability="$OPTARG" ;;
            T) task_timeout_seconds="$OPTARG" ;;
            r) task_max_retries="$OPTARG" ;;
            o) overlap_policy="$OPTARG" ;;
            e) expires_at="$OPTARG" ;;
            *) _superpos_err "update_schedule: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json \
        "name" "$name" \
        "trigger_type" "$trigger_type" \
        "task_type" "$task_type" \
        "cron_expression" "$cron_expression" \
        "interval_seconds:n" "$interval_seconds" \
        "run_at" "$run_at" \
        "task_payload" "$task_payload" \
        "task_priority:n" "$task_priority" \
        "task_target_agent_id" "$task_target_agent_id" \
        "task_target_capability" "$task_target_capability" \
        "task_timeout_seconds:n" "$task_timeout_seconds" \
        "task_max_retries:n" "$task_max_retries" \
        "overlap_policy" "$overlap_policy" \
        "expires_at" "$expires_at"
    ) || return $SUPERPOS_ERR

    _superpos_request PUT "/api/v1/hives/${hive_id}/schedules/${schedule_id}" "$body"
}

# superpos_delete_schedule — delete a task schedule.
#   HIVE_ID  SCHEDULE_ID
superpos_delete_schedule() {
    local hive_id="${1:?usage: superpos_delete_schedule HIVE_ID SCHEDULE_ID}"
    local schedule_id="${2:?usage: superpos_delete_schedule HIVE_ID SCHEDULE_ID}"
    _superpos_request DELETE "/api/v1/hives/${hive_id}/schedules/${schedule_id}"
}

# superpos_pause_schedule — pause an active schedule.
#   HIVE_ID  SCHEDULE_ID
superpos_pause_schedule() {
    local hive_id="${1:?usage: superpos_pause_schedule HIVE_ID SCHEDULE_ID}"
    local schedule_id="${2:?usage: superpos_pause_schedule HIVE_ID SCHEDULE_ID}"
    _superpos_request PATCH "/api/v1/hives/${hive_id}/schedules/${schedule_id}/pause"
}

# superpos_resume_schedule — resume a paused schedule.
#   HIVE_ID  SCHEDULE_ID
superpos_resume_schedule() {
    local hive_id="${1:?usage: superpos_resume_schedule HIVE_ID SCHEDULE_ID}"
    local schedule_id="${2:?usage: superpos_resume_schedule HIVE_ID SCHEDULE_ID}"
    _superpos_request PATCH "/api/v1/hives/${hive_id}/schedules/${schedule_id}/resume"
}

# ── Knowledge ────────────────────────────────────────────────────

# superpos_list_knowledge — list knowledge entries.
#   HIVE_ID  [-k KEY_PATTERN] [-s SCOPE] [-l LIMIT]
superpos_list_knowledge() {
    local hive_id="${1:?usage: superpos_list_knowledge HIVE_ID}"
    shift
    local key="" scope="" limit=""
    local OPTIND OPTARG opt
    while getopts "k:s:l:" opt; do
        case "$opt" in
            k) key="$OPTARG" ;;
            s) scope="$OPTARG" ;;
            l) limit="$OPTARG" ;;
            *) _superpos_err "list_knowledge: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$key" ]]   && params+=("key=$(_superpos_urlencode "$key")")
    [[ -n "$scope" ]] && params+=("scope=$(_superpos_urlencode "$scope")")
    [[ -n "$limit" ]] && params+=("limit=$(_superpos_urlencode "$limit")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/knowledge${qs}"
}

# superpos_search_knowledge — search knowledge entries.
#   HIVE_ID  [-q QUERY] [-s SCOPE] [-m MODE] [-e] [-l LIMIT]
# MODE is one of fts|semantic|hybrid; when omitted the server picks its
# default (currently hybrid). -e enables explain mode (score_breakdown).
superpos_search_knowledge() {
    local hive_id="${1:?usage: superpos_search_knowledge HIVE_ID}"
    shift
    local query="" scope="" mode="" explain="" limit=""
    local OPTIND OPTARG opt
    while getopts "q:s:m:el:" opt; do
        case "$opt" in
            q) query="$OPTARG" ;;
            s) scope="$OPTARG" ;;
            m) mode="$OPTARG" ;;
            e) explain="true" ;;
            l) limit="$OPTARG" ;;
            *) _superpos_err "search_knowledge: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$query" ]] && params+=("q=$(_superpos_urlencode "$query")")
    [[ -n "$scope" ]] && params+=("scope=$(_superpos_urlencode "$scope")")
    [[ -n "$mode" ]] && params+=("mode=$(_superpos_urlencode "$mode")")
    [[ -n "$explain" ]] && params+=("explain=true")
    [[ -n "$limit" ]] && params+=("limit=$(_superpos_urlencode "$limit")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/knowledge/search${qs}"
}

# superpos_get_knowledge — get a single knowledge entry.
#   HIVE_ID  ENTRY_ID
superpos_get_knowledge() {
    local hive_id="${1:?usage: superpos_get_knowledge HIVE_ID ENTRY_ID}"
    local entry_id="${2:?usage: superpos_get_knowledge HIVE_ID ENTRY_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/knowledge/${entry_id}"
}

# superpos_create_knowledge — create a knowledge entry.
#   HIVE_ID  -k KEY  -v VALUE_JSON  [-s SCOPE] [-V VISIBILITY] [-t TTL]
superpos_create_knowledge() {
    local hive_id="${1:?usage: superpos_create_knowledge HIVE_ID -k KEY -v VALUE_JSON}"
    shift
    local key="" value="" scope="" visibility="" ttl=""
    local OPTIND OPTARG opt
    while getopts "k:v:s:V:t:" opt; do
        case "$opt" in
            k) key="$OPTARG" ;;
            v) value="$OPTARG" ;;
            s) scope="$OPTARG" ;;
            V) visibility="$OPTARG" ;;
            t) ttl="$OPTARG" ;;
            *) _superpos_err "create_knowledge: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$key" || -z "$value" ]]; then
        _superpos_err "create_knowledge: -k KEY and -v VALUE_JSON are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "key" "$key" \
        "value" "$value" \
        "scope" "$scope" \
        "visibility" "$visibility" \
        "ttl" "$ttl"
    ) || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/knowledge" "$body"
}

# superpos_update_knowledge — update an existing knowledge entry.
#   HIVE_ID  ENTRY_ID  -v VALUE_JSON  [-V VISIBILITY] [-t TTL]
superpos_update_knowledge() {
    local hive_id="${1:?usage: superpos_update_knowledge HIVE_ID ENTRY_ID -v VALUE_JSON}"
    local entry_id="${2:?usage: superpos_update_knowledge HIVE_ID ENTRY_ID -v VALUE_JSON}"
    shift 2
    local value="" visibility="" ttl=""
    local OPTIND OPTARG opt
    while getopts "v:V:t:" opt; do
        case "$opt" in
            v) value="$OPTARG" ;;
            V) visibility="$OPTARG" ;;
            t) ttl="$OPTARG" ;;
            *) _superpos_err "update_knowledge: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$value" ]]; then
        _superpos_err "update_knowledge: -v VALUE_JSON is required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json "value" "$value" "visibility" "$visibility" "ttl" "$ttl") || return $SUPERPOS_ERR
    _superpos_request PUT "/api/v1/hives/${hive_id}/knowledge/${entry_id}" "$body"
}

# superpos_delete_knowledge — delete a knowledge entry.
#   HIVE_ID  ENTRY_ID
superpos_delete_knowledge() {
    local hive_id="${1:?usage: superpos_delete_knowledge HIVE_ID ENTRY_ID}"
    local entry_id="${2:?usage: superpos_delete_knowledge HIVE_ID ENTRY_ID}"
    _superpos_request DELETE "/api/v1/hives/${hive_id}/knowledge/${entry_id}"
}

# ======================================================================
# Context Threads
# ======================================================================

# superpos_list_threads — list context threads in a hive.
#   HIVE_ID  [-l LIMIT]
superpos_list_threads() {
    local hive_id="${1:?usage: superpos_list_threads HIVE_ID}"
    shift
    local limit=""
    local OPTIND OPTARG opt
    while getopts "l:" opt; do
        case "$opt" in
            l) limit="$OPTARG" ;;
            *) _superpos_err "list_threads: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done
    local qs=""
    [[ -n "$limit" ]] && qs="${qs:+$qs&}limit=${limit}"
    [[ -n "$qs" ]] && qs="?${qs}"
    _superpos_request GET "/api/v1/hives/${hive_id}/threads${qs}"
}

# superpos_create_thread — create a new context thread.
#   HIVE_ID  [-t TITLE]  [-m MESSAGE]
superpos_create_thread() {
    local hive_id="${1:?usage: superpos_create_thread HIVE_ID [-t TITLE] [-m MESSAGE]}"
    shift
    local title="" message=""
    local OPTIND OPTARG opt
    while getopts "t:m:" opt; do
        case "$opt" in
            t) title="$OPTARG" ;;
            m) message="$OPTARG" ;;
            *) _superpos_err "create_thread: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done
    local body
    body=$(_superpos_build_json "title" "$title" "message" "$message") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/threads" "$body"
}

# superpos_get_thread — get a context thread with full message history.
#   HIVE_ID  THREAD_ID
superpos_get_thread() {
    local hive_id="${1:?usage: superpos_get_thread HIVE_ID THREAD_ID}"
    local thread_id="${2:?usage: superpos_get_thread HIVE_ID THREAD_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/threads/${thread_id}"
}

# superpos_append_thread_message — append a message to a context thread.
#   HIVE_ID  THREAD_ID  -m MESSAGE  [-T TASK_ID]
superpos_append_thread_message() {
    local hive_id="${1:?usage: superpos_append_thread_message HIVE_ID THREAD_ID -m MESSAGE}"
    local thread_id="${2:?usage: superpos_append_thread_message HIVE_ID THREAD_ID -m MESSAGE}"
    shift 2
    local message="" task_id=""
    local OPTIND OPTARG opt
    while getopts "m:T:" opt; do
        case "$opt" in
            m) message="$OPTARG" ;;
            T) task_id="$OPTARG" ;;
            *) _superpos_err "append_thread_message: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done
    if [[ -z "$message" ]]; then
        _superpos_err "append_thread_message: -m MESSAGE is required"
        return $SUPERPOS_ERR
    fi
    local body
    body=$(_superpos_build_json "message" "$message" "task_id" "$task_id") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/threads/${thread_id}/messages" "$body"
}

# superpos_clear_thread_messages — clear all messages from a context thread.
#   HIVE_ID  THREAD_ID
superpos_clear_thread_messages() {
    local hive_id="${1:?usage: superpos_clear_thread_messages HIVE_ID THREAD_ID}"
    local thread_id="${2:?usage: superpos_clear_thread_messages HIVE_ID THREAD_ID}"
    _superpos_request DELETE "/api/v1/hives/${hive_id}/threads/${thread_id}/messages"
}

# superpos_delete_thread — delete a context thread and all its messages.
#   HIVE_ID  THREAD_ID
superpos_delete_thread() {
    local hive_id="${1:?usage: superpos_delete_thread HIVE_ID THREAD_ID}"
    local thread_id="${2:?usage: superpos_delete_thread HIVE_ID THREAD_ID}"
    _superpos_request DELETE "/api/v1/hives/${hive_id}/threads/${thread_id}"
}

# ======================================================================
# Rate Limiting
# ======================================================================

# superpos_rate_limit_status — get current rate limit config & usage.
superpos_rate_limit_status() {
    _superpos_request GET "/api/v1/agents/rate-limit"
}

# superpos_update_rate_limit — update the per-agent rate limit.
#   -l LIMIT  (integer or "null" to reset to default)
superpos_update_rate_limit() {
    local limit=""
    local OPTIND OPTARG opt
    while getopts "l:" opt; do
        case "$opt" in
            l) limit="$OPTARG" ;;
            *) _superpos_err "update_rate_limit: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$limit" ]]; then
        _superpos_err "update_rate_limit: -l LIMIT is required (integer or 'null')"
        return $SUPERPOS_ERR
    fi

    local body
    if [[ "$limit" == "null" ]]; then
        body='{"rate_limit_per_minute":null}'
    else
        body=$(_superpos_build_json "rate_limit_per_minute:n" "$limit") || return $SUPERPOS_ERR
    fi

    _superpos_request PUT "/api/v1/agents/rate-limit" "$body"
}

# ── Persona ──────────────────────────────────────────────────────

# superpos_get_persona_version — lightweight version check for hot-reload polling.
#   [-k KNOWN_VERSION]  (optional) — if set, response includes a 'changed' bool
#   [-p KNOWN_PLATFORM_VERSION]  (optional) — if set, platform context changes
#       are also factored into the 'changed' flag
#   [-e KNOWN_ENVIRONMENT_VERSION]  (optional) — hex content-hash; if set, hive
#       environment changes (sibling agents, service connections, webhook
#       routes) are also factored into the 'changed' flag
#
# Returns the server-assigned persona version for this agent without fetching full
# documents. When -k KNOWN_VERSION is provided, the response also includes
# 'changed' (true/false) comparing the server version to the provided value.
# When -p KNOWN_PLATFORM_VERSION is also provided, platform context version
# changes will additionally trigger 'changed'. When -e KNOWN_ENVIRONMENT_VERSION
# is also provided, hive environment changes will additionally trigger 'changed'.
superpos_get_persona_version() {
    local known_version="" known_platform_version="" known_environment_version="" query_string=""
    local OPTIND OPTARG opt
    while getopts "k:p:e:" opt; do
        case "$opt" in
            k) known_version="$OPTARG" ;;
            p) known_platform_version="$OPTARG" ;;
            e) known_environment_version="$OPTARG" ;;
            *) _superpos_err "get_persona_version: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    if [[ -n "$known_version" ]]; then
        params+=("known_version=${known_version}")
    fi
    if [[ -n "$known_platform_version" ]]; then
        params+=("known_platform_version=${known_platform_version}")
    fi
    if [[ -n "$known_environment_version" ]]; then
        params+=("known_environment_version=${known_environment_version}")
    fi

    if [[ ${#params[@]} -gt 0 ]]; then
        local IFS='&'
        query_string="?${params[*]}"
    fi

    _superpos_request GET "/api/v1/persona/version${query_string}"
}

# superpos_check_persona_version — returns 0 (true) if persona version has changed.
#   -k KNOWN_VERSION  (required) — the version the agent currently holds locally
#   [-p KNOWN_PLATFORM_VERSION]  (optional) — the platform context version the
#       agent currently holds locally. When provided, platform context changes
#       will also trigger a refresh.
#   [-e KNOWN_ENVIRONMENT_VERSION]  (optional) — the hive environment version
#       (hex content-hash) the agent currently holds locally. When provided,
#       environment changes (sibling agents, service connections, webhook
#       routes) will also trigger a refresh.
#
# Returns exit code 0 if the server persona version differs from KNOWN_VERSION
# (i.e., the agent should refresh its persona), or 1 if unchanged.
# Exits with SUPERPOS_ERR on request failure.
superpos_check_persona_version() {
    local known_version="" known_platform_version="" known_environment_version=""
    local OPTIND OPTARG opt
    while getopts "k:p:e:" opt; do
        case "$opt" in
            k) known_version="$OPTARG" ;;
            p) known_platform_version="$OPTARG" ;;
            e) known_environment_version="$OPTARG" ;;
            *) _superpos_err "check_persona_version: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$known_version" ]]; then
        _superpos_err "check_persona_version: -k KNOWN_VERSION is required"
        return $SUPERPOS_ERR
    fi

    if ! jq --version >/dev/null 2>&1; then
        _superpos_err "check_persona_version: jq is required (install jq and retry)"
        return $SUPERPOS_ERR_DEPS
    fi

    local version_args=(-k "$known_version")
    if [[ -n "$known_platform_version" ]]; then
        version_args+=(-p "$known_platform_version")
    fi
    if [[ -n "$known_environment_version" ]]; then
        version_args+=(-e "$known_environment_version")
    fi

    local result
    result=$(superpos_get_persona_version "${version_args[@]}") || return $?

    local changed
    changed=$(echo "$result" | jq -r '.changed // "false"')

    if [[ "$changed" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# superpos_get_persona — get the agent's active persona (policy-selected version).
superpos_get_persona() {
    _superpos_request GET "/api/v1/persona"
}

# superpos_get_persona_config — get persona config only (model, temperature, etc.).
superpos_get_persona_config() {
    _superpos_request GET "/api/v1/persona/config"
}

# superpos_get_persona_document — get a single persona document by name.
#   NAME  (e.g. SOUL, AGENT, RULES, STYLE, EXAMPLES, MEMORY)
superpos_get_persona_document() {
    local name="${1:?usage: superpos_get_persona_document NAME}"
    _superpos_request GET "/api/v1/persona/documents/${name}"
}

# superpos_get_persona_assembled — get pre-assembled system prompt in canonical order.
superpos_get_persona_assembled() {
    _superpos_request GET "/api/v1/persona/assembled"
}

# superpos_update_persona_document — agent self-update of an unlocked document.
#   NAME  -c CONTENT  [-m MESSAGE]  [-M MODE]
#   MODE: replace (default), append, prepend
#   Returns 403 if the document is locked by policy.
superpos_update_persona_document() {
    local name="${1:?usage: superpos_update_persona_document NAME -c CONTENT [-m MESSAGE] [-M MODE]}"
    shift
    local content="" message="" mode="replace"
    local message_set=0
    local OPTIND OPTARG opt
    while getopts "c:m:M:" opt; do
        case "$opt" in
            c) content="$OPTARG" ;;
            m) message="$OPTARG"; message_set=1 ;;
            M) mode="$OPTARG" ;;
            *) _superpos_err "update_persona_document: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$content" ]]; then
        _superpos_err "update_persona_document: -c CONTENT is required"
        return $SUPERPOS_ERR
    fi

    if [[ "$mode" != "replace" && "$mode" != "append" && "$mode" != "prepend" ]]; then
        _superpos_err "update_persona_document: -M MODE must be replace, append, or prepend"
        return $SUPERPOS_ERR
    fi

    # jq is required to build the request body with guaranteed string encoding
    # AND to parse the response in _superpos_request. Without jq, we must not send
    # the PATCH at all — the server-side update would succeed (creating a new
    # persona version) while the response parsing would fail, misleading callers
    # into retrying and silently creating duplicate versions.
    if ! jq --version >/dev/null 2>&1; then
        _superpos_err "update_persona_document: jq is required (install jq and retry)"
        return $SUPERPOS_ERR_DEPS
    fi

    # Build JSON body with guaranteed string encoding for content and message.
    # _superpos_build_json coerces values starting with {, [, true, false, null as
    # raw JSON, making it unsafe for free-form persona text. Use jq --arg instead,
    # which always emits values as JSON strings regardless of their content.
    #
    # Use message_set flag (not [[ -n "$message" ]]) so that -m '' (explicit
    # empty string) is included in the body rather than silently dropped.
    local body
    if [[ "$message_set" -eq 1 ]]; then
        body=$(jq -n --arg content "$content" --arg message "$message" --arg mode "$mode" \
            '{content: $content, message: $message, mode: $mode}') || {
            _superpos_err "update_persona_document: failed to build JSON body"
            return $SUPERPOS_ERR
        }
    else
        body=$(jq -n --arg content "$content" --arg mode "$mode" \
            '{content: $content, mode: $mode}') || {
            _superpos_err "update_persona_document: failed to build JSON body"
            return $SUPERPOS_ERR
        }
    fi
    _superpos_request PATCH "/api/v1/persona/documents/${name}" "$body"
}

# superpos_update_memory — agent self-update of the MEMORY document.
#   -c CONTENT  (required) — content to write
#   -m MESSAGE  (optional) — commit message
#   -M MODE     (optional) — replace | append (default) | prepend
#
# Convenience wrapper for superpos_update_persona_document MEMORY.
# Agents call this to persist learned facts, project context, and runtime
# observations across executions. Defaults to append mode so that individual
# calls accumulate knowledge rather than overwriting earlier entries.
superpos_update_memory() {
    local content="" message="" mode="append"
    local message_set=0
    local OPTIND OPTARG opt
    while getopts "c:m:M:" opt; do
        case "$opt" in
            c) content="$OPTARG" ;;
            m) message="$OPTARG"; message_set=1 ;;
            M) mode="$OPTARG" ;;
            *) _superpos_err "update_memory: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$content" ]]; then
        _superpos_err "update_memory: -c CONTENT is required"
        return $SUPERPOS_ERR
    fi

    if [[ "$mode" != "replace" && "$mode" != "append" && "$mode" != "prepend" ]]; then
        _superpos_err "update_memory: -M MODE must be replace, append, or prepend"
        return $SUPERPOS_ERR
    fi

    if ! jq --version >/dev/null 2>&1; then
        _superpos_err "update_memory: jq is required (install jq and retry)"
        return $SUPERPOS_ERR_DEPS
    fi

    local body
    if [[ "$message_set" -eq 1 ]]; then
        body=$(jq -n --arg content "$content" --arg message "$message" --arg mode "$mode" \
            '{content: $content, message: $message, mode: $mode}') || {
            _superpos_err "update_memory: failed to build JSON body"
            return $SUPERPOS_ERR
        }
    else
        body=$(jq -n --arg content "$content" --arg mode "$mode" \
            '{content: $content, mode: $mode}') || {
            _superpos_err "update_memory: failed to build JSON body"
            return $SUPERPOS_ERR
        }
    fi
    _superpos_request PATCH "/api/v1/persona/memory" "$body"
}

# ── Service worker helpers ────────────────────────────────────────────
#
# These helpers implement the service worker pattern from
# docs/features/list-1/FEATURE_SERVICE_WORKERS.md.
#
# A service worker is a regular agent with a "data:<service>" capability
# that polls for "data_request" tasks and executes named operations.

# superpos_data_request HIVE_ID — create a data_request task.
#   Required:
#     -c CAPABILITY   target service worker capability (e.g. "data:gmail")
#     -o OPERATION    operation name (e.g. "fetch_emails")
#   Optional:
#     -p PARAMS_JSON  operation parameters as a JSON object (default: {})
#     -d DELIVERY     delivery mode: task_result (default) | knowledge
#     -f FORMAT       result_format hint passed to the worker
#     -C TASK_ID      continuation_of — resume from a previous request
#     -r TASK_ID      response_task_id — push result to this task (push-style delivery)
#     -t TIMEOUT      task timeout in seconds
#     -k IDEMPOTENCY  idempotency key
#
# Prints the created task JSON (data envelope unwrapped) to stdout.
#
# Example:
#   superpos_data_request "$HIVE_ID" \
#       -c data:gmail \
#       -o fetch_emails \
#       -p '{"query":"from:boss@acme.com","max_results":20}'
superpos_data_request() {
    local hive_id="$1"
    shift || { _superpos_err "data_request: HIVE_ID is required"; return $SUPERPOS_ERR; }

    local capability="" operation="" params="" delivery="task_result"
    local result_format="" continuation_of="" response_task_id="" timeout_seconds="" idempotency_key=""
    local OPTIND OPTARG opt
    while getopts "c:o:p:d:f:C:r:t:k:" opt; do
        case "$opt" in
            c) capability="$OPTARG" ;;
            o) operation="$OPTARG" ;;
            p) params="$OPTARG" ;;
            d) delivery="$OPTARG" ;;
            f) result_format="$OPTARG" ;;
            C) continuation_of="$OPTARG" ;;
            r) response_task_id="$OPTARG" ;;
            t) timeout_seconds="$OPTARG" ;;
            k) idempotency_key="$OPTARG" ;;
            *) _superpos_err "data_request: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$capability" ]]; then
        _superpos_err "data_request: -c CAPABILITY is required"
        return $SUPERPOS_ERR
    fi
    if [[ -z "$operation" ]]; then
        _superpos_err "data_request: -o OPERATION is required"
        return $SUPERPOS_ERR
    fi

    # Build payload JSON
    local payload
    if [[ -n "$params" ]]; then
        payload=$(jq -n \
            --arg op "$operation" \
            --arg del "$delivery" \
            --argjson p "$params" \
            '{operation: $op, delivery: $del, params: $p}') || {
            _superpos_err "data_request: invalid params JSON"
            return $SUPERPOS_ERR
        }
    else
        payload=$(jq -n \
            --arg op "$operation" \
            --arg del "$delivery" \
            '{operation: $op, delivery: $del}') || {
            _superpos_err "data_request: failed to build payload"
            return $SUPERPOS_ERR
        }
    fi

    if [[ -n "$result_format" ]]; then
        payload=$(echo "$payload" | jq --arg f "$result_format" '. + {result_format: $f}')
    fi
    if [[ -n "$continuation_of" ]]; then
        payload=$(echo "$payload" | jq --arg c "$continuation_of" '. + {continuation_of: $c}')
    fi
    if [[ -n "$response_task_id" ]]; then
        payload=$(echo "$payload" | jq --arg r "$response_task_id" '. + {response_task_id: $r}')
    fi

    # Build task body
    local body
    body=$(jq -n \
        --arg type "data_request" \
        --arg cap "$capability" \
        --argjson payload "$payload" \
        '{type: $type, target_capability: $cap, payload: $payload}') || {
        _superpos_err "data_request: failed to build request body"
        return $SUPERPOS_ERR
    }

    if [[ -n "$timeout_seconds" ]]; then
        body=$(echo "$body" | jq --argjson t "$timeout_seconds" '. + {timeout_seconds: $t}')
    fi
    if [[ -n "$idempotency_key" ]]; then
        body=$(echo "$body" | jq --arg k "$idempotency_key" '. + {idempotency_key: $k}')
    fi

    _superpos_request POST "/api/v1/hives/${hive_id}/tasks" "$body"
}

# superpos_data_request_dispatch HIVE_ID — dispatch a data_request from inside a service worker.
#
# This is the service-worker-side companion to superpos_data_request.
# Use it when one service worker needs data from another worker.
#
#   Required:
#     -o OPERATION    operation name to request
#   Optional:
#     -c CAPABILITY   target capability (default: value of $SUPERPOS_CAPABILITY)
#     -p PARAMS_JSON  operation parameters as a JSON object (default: {})
#     -d DELIVERY     delivery mode: task_result (default) | knowledge
#     -r TASK_ID      response_task_id — push result to this task (push-style delivery)
#     -t TIMEOUT      task timeout in seconds
#     -k IDEMPOTENCY  idempotency key
#
# Prints the created task JSON to stdout.
#
# Example (inside a worker script):
#   superpos_data_request_dispatch "$HIVE_ID" \
#       -c data:github \
#       -o fetch_issues \
#       -p '{"repo":"acme/backend","state":"open"}'
superpos_data_request_dispatch() {
    local hive_id="$1"
    shift || { _superpos_err "data_request_dispatch: HIVE_ID is required"; return $SUPERPOS_ERR; }

    local capability="${SUPERPOS_CAPABILITY:-}" operation="" params="" delivery="task_result"
    local response_task_id="" timeout_seconds="" idempotency_key=""
    local OPTIND OPTARG opt
    while getopts "c:o:p:d:r:t:k:" opt; do
        case "$opt" in
            c) capability="$OPTARG" ;;
            o) operation="$OPTARG" ;;
            p) params="$OPTARG" ;;
            d) delivery="$OPTARG" ;;
            r) response_task_id="$OPTARG" ;;
            t) timeout_seconds="$OPTARG" ;;
            k) idempotency_key="$OPTARG" ;;
            *) _superpos_err "data_request_dispatch: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$capability" ]]; then
        _superpos_err "data_request_dispatch: -c CAPABILITY is required (or set \$SUPERPOS_CAPABILITY)"
        return $SUPERPOS_ERR
    fi
    if [[ -z "$operation" ]]; then
        _superpos_err "data_request_dispatch: -o OPERATION is required"
        return $SUPERPOS_ERR
    fi

    # Delegate to superpos_data_request with the same args
    local extra_args=()
    [[ -n "$params" ]]           && extra_args+=(-p "$params")
    [[ -n "$delivery" ]]         && extra_args+=(-d "$delivery")
    [[ -n "$response_task_id" ]] && extra_args+=(-r "$response_task_id")
    [[ -n "$timeout_seconds" ]]  && extra_args+=(-t "$timeout_seconds")
    [[ -n "$idempotency_key" ]]  && extra_args+=(-k "$idempotency_key")

    superpos_data_request "$hive_id" -c "$capability" -o "$operation" "${extra_args[@]}"
}

# superpos_discover_services HIVE_ID — list service workers in a hive.
#   Optional:
#     -p PREFIX  capability prefix to filter on (default: "data:")
#
# Queries GET /api/v1/hives/{hive_id}/agents?capability=<PREFIX> and
# prints the matching agent JSON array to stdout.
#
# Example:
#   superpos_discover_services "$HIVE_ID"
#   superpos_discover_services "$HIVE_ID" -p custom:
superpos_discover_services() {
    local hive_id="$1"
    shift || { _superpos_err "discover_services: HIVE_ID is required"; return $SUPERPOS_ERR; }

    local prefix="data:"
    local OPTIND OPTARG opt
    while getopts "p:" opt; do
        case "$opt" in
            p) prefix="$OPTARG" ;;
            *) _superpos_err "discover_services: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    params+=("capability=$(_superpos_urlencode "$prefix")")
    local qs="?$(IFS='&'; echo "${params[*]}")"

    _superpos_request GET "/api/v1/hives/${hive_id}/agents${qs}"
}

# ── Workflows ──────────────────────────────────────────────────────

# superpos_list_workflows — list workflows in a hive.
#   HIVE_ID  [-p PAGE] [-l PER_PAGE] [-a IS_ACTIVE] [-q SEARCH]
superpos_list_workflows() {
    local hive_id="${1:?usage: superpos_list_workflows HIVE_ID}"
    shift
    local page="" per_page="" is_active="" search=""
    local OPTIND OPTARG opt
    while getopts "p:l:a:q:" opt; do
        case "$opt" in
            p) page="$OPTARG" ;;
            l) per_page="$OPTARG" ;;
            a) is_active="$OPTARG" ;;
            q) search="$OPTARG" ;;
            *) _superpos_err "list_workflows: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$page" ]]      && params+=("page=$(_superpos_urlencode "$page")")
    [[ -n "$per_page" ]]  && params+=("per_page=$(_superpos_urlencode "$per_page")")
    [[ -n "$is_active" ]] && params+=("is_active=$(_superpos_urlencode "$is_active")")
    [[ -n "$search" ]]    && params+=("search=$(_superpos_urlencode "$search")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/workflows${qs}"
}

# superpos_get_workflow — get a single workflow.
#   HIVE_ID  WORKFLOW_ID
superpos_get_workflow() {
    local hive_id="${1:?usage: superpos_get_workflow HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_get_workflow HIVE_ID WORKFLOW_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}"
}

# superpos_create_workflow — create a workflow.
#   HIVE_ID  -S SLUG  -n NAME  -s STEPS_JSON  [-c TRIGGER_CONFIG_JSON] [-d DESCRIPTION] [-a IS_ACTIVE] [-e SETTINGS_JSON]
superpos_create_workflow() {
    local hive_id="${1:?usage: superpos_create_workflow HIVE_ID -S SLUG -n NAME -s STEPS_JSON}"
    shift
    local slug="" name="" steps="" trigger_config="" description="" is_active="" settings=""
    local OPTIND OPTARG opt
    while getopts "S:n:s:c:d:a:e:" opt; do
        case "$opt" in
            S) slug="$OPTARG" ;;
            n) name="$OPTARG" ;;
            s) steps="$OPTARG" ;;
            c) trigger_config="$OPTARG" ;;
            d) description="$OPTARG" ;;
            a) is_active="$OPTARG" ;;
            e) settings="$OPTARG" ;;
            *) _superpos_err "create_workflow: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    if [[ -z "$slug" || -z "$name" || -z "$steps" ]]; then
        _superpos_err "create_workflow: -S SLUG, -n NAME and -s STEPS_JSON are required"
        return $SUPERPOS_ERR
    fi

    local body
    body=$(_superpos_build_json \
        "slug" "$slug" \
        "name" "$name" \
        "steps" "$steps" \
        "trigger_config" "$trigger_config" \
        "description" "$description" \
        "is_active" "$is_active" \
        "settings" "$settings"
    ) || return $SUPERPOS_ERR

    _superpos_request POST "/api/v1/hives/${hive_id}/workflows" "$body"
}

# superpos_update_workflow — update a workflow (partial update).
#   HIVE_ID  WORKFLOW_ID  [-S SLUG] [-n NAME] [-s STEPS_JSON] [-c TRIGGER_CONFIG_JSON] [-d DESCRIPTION] [-a IS_ACTIVE] [-e SETTINGS_JSON]
superpos_update_workflow() {
    local hive_id="${1:?usage: superpos_update_workflow HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_update_workflow HIVE_ID WORKFLOW_ID}"
    shift 2
    local slug="" name="" steps="" trigger_config="" description="" is_active="" settings=""
    local OPTIND OPTARG opt
    while getopts "S:n:s:c:d:a:e:" opt; do
        case "$opt" in
            S) slug="$OPTARG" ;;
            n) name="$OPTARG" ;;
            s) steps="$OPTARG" ;;
            c) trigger_config="$OPTARG" ;;
            d) description="$OPTARG" ;;
            a) is_active="$OPTARG" ;;
            e) settings="$OPTARG" ;;
            *) _superpos_err "update_workflow: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json \
        "slug" "$slug" \
        "name" "$name" \
        "steps" "$steps" \
        "trigger_config" "$trigger_config" \
        "description" "$description" \
        "is_active" "$is_active" \
        "settings" "$settings"
    ) || return $SUPERPOS_ERR

    _superpos_request PUT "/api/v1/hives/${hive_id}/workflows/${workflow_id}" "$body"
}

# superpos_delete_workflow — delete a workflow.
#   HIVE_ID  WORKFLOW_ID
superpos_delete_workflow() {
    local hive_id="${1:?usage: superpos_delete_workflow HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_delete_workflow HIVE_ID WORKFLOW_ID}"
    _superpos_request DELETE "/api/v1/hives/${hive_id}/workflows/${workflow_id}"
}

# superpos_run_workflow — start a workflow run.
#   HIVE_ID  WORKFLOW_ID  [-d PAYLOAD_JSON]
superpos_run_workflow() {
    local hive_id="${1:?usage: superpos_run_workflow HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_run_workflow HIVE_ID WORKFLOW_ID}"
    shift 2
    local payload=""
    local OPTIND OPTARG opt
    while getopts "d:" opt; do
        case "$opt" in
            d) payload="$OPTARG" ;;
            *) _superpos_err "run_workflow: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local body
    body=$(_superpos_build_json "payload" "$payload") || return $SUPERPOS_ERR
    _superpos_request POST "/api/v1/hives/${hive_id}/workflows/${workflow_id}/runs" "$body"
}

# superpos_list_workflow_runs — list runs for a workflow.
#   HIVE_ID  WORKFLOW_ID  [-p PAGE] [-l PER_PAGE] [-s STATUS]
superpos_list_workflow_runs() {
    local hive_id="${1:?usage: superpos_list_workflow_runs HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_list_workflow_runs HIVE_ID WORKFLOW_ID}"
    shift 2
    local page="" per_page="" status=""
    local OPTIND OPTARG opt
    while getopts "p:l:s:" opt; do
        case "$opt" in
            p) page="$OPTARG" ;;
            l) per_page="$OPTARG" ;;
            s) status="$OPTARG" ;;
            *) _superpos_err "list_workflow_runs: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$page" ]]     && params+=("page=$(_superpos_urlencode "$page")")
    [[ -n "$per_page" ]] && params+=("per_page=$(_superpos_urlencode "$per_page")")
    [[ -n "$status" ]]   && params+=("status=$(_superpos_urlencode "$status")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}/runs${qs}"
}

# superpos_get_workflow_run — get a single workflow run.
#   HIVE_ID  WORKFLOW_ID  RUN_ID
superpos_get_workflow_run() {
    local hive_id="${1:?usage: superpos_get_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local workflow_id="${2:?usage: superpos_get_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local run_id="${3:?usage: superpos_get_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}/runs/${run_id}"
}

# superpos_cancel_workflow_run — cancel a running workflow run.
#   HIVE_ID  WORKFLOW_ID  RUN_ID
superpos_cancel_workflow_run() {
    local hive_id="${1:?usage: superpos_cancel_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local workflow_id="${2:?usage: superpos_cancel_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local run_id="${3:?usage: superpos_cancel_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    _superpos_request POST "/api/v1/hives/${hive_id}/workflows/${workflow_id}/runs/${run_id}/cancel"
}

# superpos_retry_workflow_run — retry a failed workflow run.
#   HIVE_ID  WORKFLOW_ID  RUN_ID
superpos_retry_workflow_run() {
    local hive_id="${1:?usage: superpos_retry_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local workflow_id="${2:?usage: superpos_retry_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    local run_id="${3:?usage: superpos_retry_workflow_run HIVE_ID WORKFLOW_ID RUN_ID}"
    _superpos_request POST "/api/v1/hives/${hive_id}/workflows/${workflow_id}/runs/${run_id}/retry"
}

# superpos_list_workflow_versions — list versions of a workflow.
#   HIVE_ID  WORKFLOW_ID  [-p PAGE] [-l PER_PAGE]
superpos_list_workflow_versions() {
    local hive_id="${1:?usage: superpos_list_workflow_versions HIVE_ID WORKFLOW_ID}"
    local workflow_id="${2:?usage: superpos_list_workflow_versions HIVE_ID WORKFLOW_ID}"
    shift 2
    local page="" per_page=""
    local OPTIND OPTARG opt
    while getopts "p:l:" opt; do
        case "$opt" in
            p) page="$OPTARG" ;;
            l) per_page="$OPTARG" ;;
            *) _superpos_err "list_workflow_versions: unknown option -$opt"; return $SUPERPOS_ERR ;;
        esac
    done

    local params=()
    [[ -n "$page" ]]     && params+=("page=$(_superpos_urlencode "$page")")
    [[ -n "$per_page" ]] && params+=("per_page=$(_superpos_urlencode "$per_page")")
    local qs=""
    if [[ ${#params[@]} -gt 0 ]]; then
        qs="?$(IFS='&'; echo "${params[*]}")"
    fi

    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}/versions${qs}"
}

# superpos_get_workflow_version — get a specific workflow version.
#   HIVE_ID  WORKFLOW_ID  VERSION
superpos_get_workflow_version() {
    local hive_id="${1:?usage: superpos_get_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    local workflow_id="${2:?usage: superpos_get_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    local version="${3:?usage: superpos_get_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}/versions/${version}"
}

# superpos_diff_workflow_versions — diff two workflow versions.
#   HIVE_ID  WORKFLOW_ID  FROM_VERSION  TO_VERSION
superpos_diff_workflow_versions() {
    local hive_id="${1:?usage: superpos_diff_workflow_versions HIVE_ID WORKFLOW_ID FROM TO}"
    local workflow_id="${2:?usage: superpos_diff_workflow_versions HIVE_ID WORKFLOW_ID FROM TO}"
    local from_version="${3:?usage: superpos_diff_workflow_versions HIVE_ID WORKFLOW_ID FROM TO}"
    local to_version="${4:?usage: superpos_diff_workflow_versions HIVE_ID WORKFLOW_ID FROM TO}"
    _superpos_request GET "/api/v1/hives/${hive_id}/workflows/${workflow_id}/versions/${from_version}/diff/${to_version}"
}

# superpos_rollback_workflow_version — rollback a workflow to a specific version.
#   HIVE_ID  WORKFLOW_ID  VERSION
superpos_rollback_workflow_version() {
    local hive_id="${1:?usage: superpos_rollback_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    local workflow_id="${2:?usage: superpos_rollback_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    local version="${3:?usage: superpos_rollback_workflow_version HIVE_ID WORKFLOW_ID VERSION}"
    _superpos_request POST "/api/v1/hives/${hive_id}/workflows/${workflow_id}/versions/${version}/rollback"
}
