# TASK-265: Webhook route sub-agent integration

**Status:** in_progress
**Branch:** `task/265-webhook-sub-agent`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/468
**Depends on:** TASK-263
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §8

## Objective

Enable webhook routes to specify a `sub_agent_definition_slug` in their `action_config`, which is resolved to an active `sub_agent_definition_id` when the webhook creates a task. Also add a sub-agent definition selector to the webhook route form in the dashboard.

## Background

Webhook routes (TASK-055, TASK-058) create tasks when external events arrive. Currently, the `action_config` supports `task_type`, `target_capability`, `target_agent_id`, and `invoke` fields. This task adds `sub_agent_definition_slug` so that webhook-created tasks can specify which sub-agent persona the handling agent should use.

Example `action_config`:
```json
{
  "action": "create_task",
  "task_type": "code_review",
  "target_capability": "code-review",
  "sub_agent_definition_slug": "coder",
  "invoke": {
    "instructions": "Review this PR and push fixes"
  }
}
```

## Requirements

### Functional

- [ ] FR-1: `WebhookRoute.action_config` gains optional `sub_agent_definition_slug` field (string). This is stored in the JSON `action_config` column — no schema migration needed.
- [ ] FR-2: `WebhookRouteEvaluator` resolves `sub_agent_definition_slug` → active `sub_agent_definition_id` at task creation time:
  ```php
  if ($slug = $actionConfig['sub_agent_definition_slug'] ?? null) {
      $subAgent = SubAgentDefinition::where('slug', $slug)
          ->where('hive_id', $webhookRoute->hive_id)
          ->where('is_active', true)
          ->first();
      $task->sub_agent_definition_id = $subAgent?->id;
  }
  ```
- [ ] FR-3: Fail-open: if the slug doesn't resolve (deleted, deactivated, renamed), the task is still created without a sub-agent definition. Log an activity entry noting the failed resolution with slug value and webhook route ID.
- [ ] FR-4: Webhook route form in dashboard (`WebhookRouteDashboardController` / route builder UI): add a sub-agent definition selector dropdown. The dropdown lists active sub-agent definitions in the current hive. The selected slug is stored in `action_config.sub_agent_definition_slug`.
- [ ] FR-5: Activity log on slug resolution — both success (resolved slug X to definition ID Y) and fail-open (slug X not found, task created without sub-agent).

### Non-Functional

- [ ] NFR-1: Backward compatible — existing webhook routes without `sub_agent_definition_slug` continue to work unchanged
- [ ] NFR-2: PSR-12 compliant
- [ ] NFR-3: No schema migration needed — `sub_agent_definition_slug` lives in the existing JSON `action_config` column

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Services/WebhookRouteEvaluator.php` | Add slug resolution in `executeCreateTask()` |
| Modify | `app/Http/Controllers/Dashboard/WebhookRouteDashboardController.php` | Pass sub-agent definitions to form |
| Modify | `resources/js/Pages/WebhookRoutes/*.jsx` (route builder) | Add sub-agent selector dropdown |
| Create | `tests/Feature/WebhookSubAgentTest.php` | Integration tests |

### Key Design Decisions

- **No migration** — the `sub_agent_definition_slug` lives inside the existing `action_config` JSON column on webhook_routes. This is consistent with how other action config fields (task_type, target_capability, etc.) are stored.
- **Resolution at task creation** — the slug is resolved to the currently active definition when the webhook fires, not when the route is configured. This means if the sub-agent definition is updated (new version activated), future webhook-created tasks will automatically use the latest version.
- **Fail-open with logging** — a missing slug should never prevent webhook task creation (webhooks are external events that must not be silently dropped). Activity logging ensures the failure is observable.

## Implementation Plan

1. Update `WebhookRouteEvaluator::executeCreateTask()`:
   - After building the task attributes from `action_config`, check for `sub_agent_definition_slug`
   - Resolve slug → active ID in the webhook route's hive
   - Set `sub_agent_definition_id` on the created task
   - Log activity for success or fail-open

2. Update `WebhookRouteDashboardController`:
   - In the `create()` and `edit()` methods, pass available sub-agent definitions to the view:
     ```php
     $subAgentDefinitions = SubAgentDefinition::where('hive_id', $hive->id)
         ->where('is_active', true)
         ->select('slug', 'name')
         ->orderBy('name')
         ->get();
     ```
   - Pass as Inertia prop

3. Update webhook route builder UI:
   - Add a dropdown select for sub-agent definition
   - Populated with active definitions (slug + name)
   - Optional — can be left empty
   - Stores selected slug in `action_config.sub_agent_definition_slug`

4. Write tests

## Test Plan

### Feature Tests

- [ ] Webhook task creation with valid `sub_agent_definition_slug` in action_config sets correct `sub_agent_definition_id` on task
- [ ] Webhook task creation with invalid slug creates task without sub-agent (fail-open)
- [ ] Webhook task creation without slug in action_config works as before
- [ ] Slug is resolved against the webhook route's hive (not cross-hive)
- [ ] Activity logged on successful slug resolution
- [ ] Activity logged on failed slug resolution (fail-open)
- [ ] Webhook route form shows sub-agent definition dropdown
- [ ] Webhook route form populates dropdown with active definitions from current hive
- [ ] Saving webhook route with sub-agent slug stores it in action_config

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on slug resolution (success + fail-open)
- [ ] Backward compatible with existing webhook routes
- [ ] No schema migration needed
- [ ] Fail-open behavior verified
- [ ] Dashboard form updated with sub-agent selector
