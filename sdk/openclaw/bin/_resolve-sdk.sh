#!/usr/bin/env bash
# _resolve-sdk.sh — Locate the Superpos Shell SDK.
#
# Sourced by CLI entry points and modules. No external dependencies.
#
# Searches (in order):
#   1. $SUPERPOS_SHELL_SDK                          — explicit override
#   2. $SCRIPT_DIR/../../shell/src/superpos-sdk.sh  — repo layout
#   3. $SCRIPT_DIR/../lib/superpos-sdk.sh           — bundled copy install
#
# Sets _SUPERPOS_SHELL_SDK_PATH on success, returns 1 on failure.
# Requires SCRIPT_DIR to be set before calling.

_superpos_find_shell_sdk() {
    local _candidates=(
        "${SUPERPOS_SHELL_SDK:-}"
        "${SCRIPT_DIR}/../../shell/src/superpos-sdk.sh"
        "${SCRIPT_DIR}/../lib/superpos-sdk.sh"
        "${APIARY_SHELL_SDK:-}"
        "${SCRIPT_DIR}/../../shell/src/apiary-sdk.sh"
        "${SCRIPT_DIR}/../lib/apiary-sdk.sh"
    )
    for _c in "${_candidates[@]}"; do
        [[ -z "$_c" ]] && continue
        if [[ -f "$_c" ]]; then
            _SUPERPOS_SHELL_SDK_PATH="$_c"
            return 0
        fi
    done
    echo "Fatal: Superpos Shell SDK not found." >&2
    echo "Searched:" >&2
    for _c in "${_candidates[@]}"; do
        [[ -n "$_c" ]] && echo "  - $_c" >&2
    done
    echo "" >&2
    echo "Fix: set SUPERPOS_SHELL_SDK=/path/to/superpos-sdk.sh (or legacy APIARY_SHELL_SDK)" >&2
    echo "  or copy sdk/shell/src/superpos-sdk.sh into $(cd "${SCRIPT_DIR}/.." 2>/dev/null && pwd)/lib/" >&2
    return 1
}
