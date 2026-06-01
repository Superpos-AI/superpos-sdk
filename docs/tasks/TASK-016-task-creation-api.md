# TASK-016: Task Creation API

**Status:** done
**Branch:** `task/016-task-creation-api`
**PR:** [#18](https://github.com/Superpos-AI/superpos-app/pull/18)
**Depends On:** TASK-003, TASK-008, TASK-011, TASK-012, TASK-013

## Objective

Implement the task creation API endpoint (`POST /api/v1/tasks`) allowing agents to create tasks within their hive. Includes Form Request validation, activity logging, permission checking, and the standard API response envelope.

## Requirements

- `POST /api/v1/tasks` endpoint with Form Request validation
- Required fields: `type`, `payload`
- Optional fields: `target_agent_id`, `target_capability`, `priority`, `timeout_seconds`, `max_retries`, `parent_task_id`, `context_refs`
- Activity logging on task creation
- Permission check: `tasks:create`
- Response: standard `{ data, meta, errors }` envelope
- ULIDs for task IDs

## Status

Completed and merged via PR #18.
