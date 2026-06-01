#!/usr/bin/env bash
# Backward-compatibility wrapper — delegates to the renamed script
exec "$(dirname "$0")/superpos-knowledge.sh" "$@"
