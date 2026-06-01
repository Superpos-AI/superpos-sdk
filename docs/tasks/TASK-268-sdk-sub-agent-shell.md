# TASK-268: Shell SDK sub-agent support

**Status:** pending
**Branch:** `task/268-sdk-sub-agent-shell`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/472
**Depends on:** TASK-261, TASK-263
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §11.2

## Objective

Update the Shell SDK to parse the `sub_agent` block from task claim responses and expose sub-agent information as environment variables. When an agent claims a task with a sub-agent definition attached (TASK-263), the shell SDK should make the sub-agent's slug, model, and assembled prompt available via `SUB_AGENT_SLUG`, `SUB_AGENT_MODEL`, and `SUB_AGENT_PROMPT` environment variables.

## Background

The Shell SDK (`sdk/shell/src/superpos-sdk.sh`) is a bash-based SDK that agents use to interact with the Superpos API. It parses task JSON responses and sets environment variables for the agent process. With task sub-agent binding (TASK-263), the task claim response now includes a `sub_agent` block containing the assembled prompt and metadata. The Shell SDK needs to parse this block and expose it as environment variables so shell-based agents can use the sub-agent instructions.

Task claim response `sub_agent` block:
```json
{
  "sub_agent": {
    "id": "01DEF...",
    "slug": "coder",
    "name": "Coding Agent",
    "model": "claude-opus-4-7",
    "version": 3,
    "prompt": "# SOUL\n\nYou are a focused coding agent...",
    "config": { "temperature": 0.2 },
    "allowed_tools": ["Bash", "Read", "Write", "Edit"]
  }
}
```

## Requirements

### Functional

- [ ] FR-1: Parse the `sub_agent` block from the task JSON response. Use `jq` (already a dependency of the shell SDK) to extract sub-agent fields from the claim response.
- [ ] FR-2: Expose the following environment variables when a sub-agent block is present:
  - `SUB_AGENT_SLUG` — the sub-agent definition slug (e.g., "coder")
  - `SUB_AGENT_MODEL` — the model override, if set (e.g., "claude-opus-4-7"), empty string if null
  - `SUB_AGENT_PROMPT` — the assembled system prompt (the full concatenated prompt text)
  - `SUB_AGENT_ID` — the sub-agent definition ULID (for version-stable re-fetch via API)
  - `SUB_AGENT_NAME` — the human-readable name (e.g., "Coding Agent")
  - `SUB_AGENT_VERSION` — the version number
- [ ] FR-3: When no sub-agent block is present (task has no sub-agent definition), all `SUB_AGENT_*` variables should be unset or empty. The agent process should not see stale values from a previous task.
- [ ] FR-4: Update the `superpos_create_task()` function in `superpos-sdk.sh` to accept an optional sub-agent definition slug parameter (e.g. via a `-S <slug>` flag). When provided, include `"sub_agent_definition_slug": "<slug>"` in the task-creation JSON payload sent to `POST /api/v1/hives/{hive_id}/tasks`. This aligns with the task-creation contract defined in TASK-263 and the existing hive-scoped endpoint used by `superpos_create_task()`.

### Non-Functional

- [ ] NFR-1: Backward compatible — existing shell agents that don't use `SUB_AGENT_*` variables continue to work unchanged
- [ ] NFR-2: Handle edge cases: null `model`, null `allowed_tools`, missing `sub_agent` key entirely
- [ ] NFR-3: The prompt may contain newlines, quotes, and special characters — ensure proper escaping when setting the environment variable

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `sdk/shell/src/superpos-sdk.sh` | Parse sub_agent block and export env vars |
| Create | `sdk/shell/tests/test_sub_agent.sh` | Shell SDK tests |

### Key Design Decisions

- **Environment variables** — the shell SDK's primary interface is environment variables (consistent with how it exposes task payload, invoke instructions, etc.). This is the simplest way for shell scripts to consume sub-agent information.
- **Full prompt in env var** — the assembled prompt is exposed as `SUB_AGENT_PROMPT`. While this can be large, shell agents need the full prompt to pass to their LLM invocation. For very large prompts, agents can alternatively use the `SUB_AGENT_ID` to re-fetch via the API.
- **Clean state between tasks** — sub-agent variables must be cleared/unset between tasks to prevent a task without a sub-agent from inheriting a previous task's sub-agent configuration.

## Implementation Plan

1. Locate the task claim response parsing logic in `superpos-sdk.sh` (where other task fields like payload, invoke, etc. are extracted).

2. Add sub-agent block parsing after the existing task field extraction:
   ```bash
   # Parse sub-agent block from task response
   SUB_AGENT_SLUG=$(echo "$TASK_JSON" | jq -r '.sub_agent.slug // empty')
   SUB_AGENT_MODEL=$(echo "$TASK_JSON" | jq -r '.sub_agent.model // empty')
   SUB_AGENT_PROMPT=$(echo "$TASK_JSON" | jq -r '.sub_agent.prompt // empty')
   SUB_AGENT_ID=$(echo "$TASK_JSON" | jq -r '.sub_agent.id // empty')
   SUB_AGENT_NAME=$(echo "$TASK_JSON" | jq -r '.sub_agent.name // empty')
   SUB_AGENT_VERSION=$(echo "$TASK_JSON" | jq -r '.sub_agent.version // empty')

   export SUB_AGENT_SLUG SUB_AGENT_MODEL SUB_AGENT_PROMPT
   export SUB_AGENT_ID SUB_AGENT_NAME SUB_AGENT_VERSION
   ```

3. Ensure clean state between tasks:
   - Before parsing a new task, unset all `SUB_AGENT_*` variables:
     ```bash
     unset SUB_AGENT_SLUG SUB_AGENT_MODEL SUB_AGENT_PROMPT
     unset SUB_AGENT_ID SUB_AGENT_NAME SUB_AGENT_VERSION
     ```

4. Update `superpos_create_task()` to support the `-S <slug>` flag:
   ```bash
   superpos_create_task() {
       local sub_agent_slug=""
       # ... existing option parsing ...
       while getopts "p:t:S:" opt; do
           case $opt in
               S) sub_agent_slug="$OPTARG" ;;
               # ... existing flags ...
           esac
       done

       local body='{... existing fields ...}'
       if [ -n "$sub_agent_slug" ]; then
           body=$(echo "$body" | jq --arg s "$sub_agent_slug" '. + {sub_agent_definition_slug: $s}')
       fi
       # ... POST to /api/v1/hives/${hive_id}/tasks ...
   }
   ```

5. Handle special characters in the prompt:
   - `jq -r` outputs raw strings, which should handle most cases
   - Test with prompts containing quotes, newlines, backslashes

6. Write tests

## Test Plan

### Unit Tests

- [ ] Task with sub-agent block sets `SUB_AGENT_SLUG` correctly
- [ ] Task with sub-agent block sets `SUB_AGENT_MODEL` correctly
- [ ] Task with sub-agent block sets `SUB_AGENT_PROMPT` correctly
- [ ] Task with sub-agent block sets `SUB_AGENT_ID` correctly
- [ ] Task with sub-agent block sets `SUB_AGENT_NAME` correctly
- [ ] Task with sub-agent block sets `SUB_AGENT_VERSION` correctly
- [ ] Task without sub-agent block has empty `SUB_AGENT_*` variables
- [ ] Task with null model results in empty `SUB_AGENT_MODEL`
- [ ] Prompt with newlines is handled correctly
- [ ] Prompt with quotes is handled correctly
- [ ] Variables are cleared between tasks (no stale values)
- [ ] Existing task fields (payload, invoke, etc.) still work correctly
- [ ] `superpos_create_task` without `-S` flag does not include `sub_agent_definition_slug` in payload (backward compatible)
- [ ] `superpos_create_task -S "coder"` includes `"sub_agent_definition_slug": "coder"` in the JSON payload
- [ ] `-S` flag with special characters in slug is handled correctly

## Validation Checklist

- [ ] All tests pass
- [ ] Backward compatible — existing shell agents unaffected
- [ ] Proper escaping for prompts with special characters
- [ ] Clean state between tasks (no stale SUB_AGENT_* values)
- [ ] All SUB_AGENT_* variables exported correctly
- [ ] Edge cases handled: null model, missing sub_agent block
