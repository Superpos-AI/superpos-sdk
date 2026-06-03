# TASK-266: Workflow sub-agent integration + version pinning

**Status:** pending
**Branch:** `task/266-workflow-sub-agent`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/471
**Depends on:** TASK-263
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §9

## Objective

Enable workflow steps to specify sub-agent definitions with version pinning at snapshot time. When a workflow version is snapshotted (published), each step's `sub_agent_definition_slug` is resolved to a concrete `sub_agent_definition_id`. At execution time, the pinned ID is used directly — no live slug resolution. This ensures deterministic execution across workflow runs.

## Background

Workflows (Phase 7B) orchestrate multi-step pipelines. Each step creates a task when ready. With sub-agent definitions (TASK-259), steps can now specify which sub-agent persona should be used for the task. The key design choice is **version pinning at snapshot time** — the sub-agent version is locked when the workflow version is published, not when the step executes. This ensures that the same workflow version always runs against the same sub-agent definitions, even if newer versions are activated later.

Multi-sub-agent pipeline example:
```
[webhook: github.pull_request_review]
    │
    ▼
┌─────────────┐   ┌──────────────┐   ┌─────────────────┐
│ Step: triage │──▶│ Step: fix    │──▶│ Step: verify    │
│ sub: analyst │   │ sub: coder   │   │ sub: reviewer   │
│ cap: triage  │   │ cap: dev     │   │ cap: qa         │
└─────────────┘   └──────────────┘   └─────────────────┘
```

## Requirements

### Functional

- [ ] FR-1: Workflow step definition schema gains optional `sub_agent_definition_slug` field (string). This is stored in the step definition JSON within the workflow version's `steps` column. No schema migration needed.
  ```json
  {
    "key": "implement",
    "type": "prompt",
    "prompt": "Implement the fix described in: {{steps.analyze.result}}",
    "target_capability": "engineering",
    "sub_agent_definition_slug": "coder",
    "depends_on_steps": ["analyze"]
  }
  ```

- [ ] FR-2: Version pinning at snapshot time — when a workflow version is snapshotted/published, resolve each step's `sub_agent_definition_slug` to the **currently active** `sub_agent_definition_id` and store the concrete ID in the step configuration snapshot:
  ```php
  // In workflow version snapshot logic:
  foreach ($steps as &$stepDef) {
      if ($slug = $stepDef['sub_agent_definition_slug'] ?? null) {
          $subAgent = SubAgentDefinition::where('slug', $slug)
              ->where('hive_id', $workflow->hive_id)
              ->where('is_active', true)
              ->first();
          // Pin the concrete version ID into the snapshot
          $stepDef['sub_agent_definition_id'] = $subAgent?->id;
      }
  }
  ```
  The snapshotted step contains both the human-readable `sub_agent_definition_slug` (for display) and the pinned `sub_agent_definition_id` (for execution).

- [ ] FR-3: Execution uses pinned ID — `WorkflowExecutionService::createStepTask()` uses the **pinned** `sub_agent_definition_id` from the snapshotted step configuration. It does **not** re-resolve the slug at execution time:
  ```php
  if ($pinnedId = $stepDef['sub_agent_definition_id'] ?? null) {
      $task->sub_agent_definition_id = $pinnedId;
  }
  ```

- [ ] FR-4: Workflow builder UI — add a sub-agent selector dropdown per step in the visual workflow builder (`resources/js/Pages/Workflows/` or similar). The dropdown lists active sub-agent definitions in the current hive. The selected slug is stored in the step definition as `sub_agent_definition_slug`.

- [ ] FR-5: `WorkflowValidationService` (if it exists) or validation logic — validate that `sub_agent_definition_slug` values in step definitions reference existing active definitions in the workflow's hive. Emit a warning (not a hard error) if a slug doesn't resolve, since it will be resolved at snapshot time.

- [ ] FR-6: Fail-open at execution: if the pinned `sub_agent_definition_id` references a definition that has been deleted since snapshot time, the step's task is created without a sub-agent definition. No error — the task proceeds without sub-agent context.

### Non-Functional

- [ ] NFR-1: Version determinism — the same workflow version must always run against the same sub-agent definitions, regardless of whether newer versions have been activated for those slugs
- [ ] NFR-2: Backward compatible — existing workflows without sub-agent slugs continue to work unchanged
- [ ] NFR-3: No schema migration needed — sub-agent fields live in the existing JSON step definitions
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Models/Workflow.php` | Add sub-agent slug→ID resolution inside `snapshotVersion()` — this is the **central** snapshot method called from all write paths |
| Modify | `app/Services/WorkflowExecutionService.php` | Use pinned ID in `createStepTask()` |
| Modify | `app/Http/Controllers/Dashboard/WorkflowDashboardController.php` | Pass sub-agent definitions to builder |
| Modify | `resources/js/Pages/Workflows/*.jsx` (builder) | Add sub-agent selector per step |
| Create | `tests/Feature/WorkflowSubAgentTest.php` | Integration tests |

> **Note:** Workflow version snapshots are produced centrally by `Workflow::snapshotVersion()` (`app/Models/Workflow.php`), **not** by individual controllers. This method is invoked from multiple write paths: `WorkflowController::update()`, `WorkflowDashboardController::update()`, and `WorkflowStepKnowledgeController::store()`/`destroy()`. Sub-agent pinning **must** be wired into `snapshotVersion()` itself to ensure all workflow versions record the pinned IDs regardless of which controller triggers the snapshot.

### Key Design Decisions

- **Snapshot-time pinning** — the sub-agent definition is resolved and pinned when the workflow version is published, not when a run starts or when a step executes. This is the same pattern used for other workflow config — the version snapshot is a complete, deterministic configuration.
- **Both slug and ID in snapshot** — the snapshot stores both `sub_agent_definition_slug` (for human display in version history) and `sub_agent_definition_id` (for execution). This avoids losing the human-readable reference while maintaining version determinism.
- **Fail-open at execution** — if the pinned definition is deleted, the task is still created. This matches the fail-open philosophy from TASK-263 and TASK-265. Workflows should be resilient to external changes.
- **No migration** — sub-agent fields are stored in the existing JSON `steps` column on `workflow_versions`. This keeps the change additive and backward compatible.

## Implementation Plan

1. Update `Workflow::snapshotVersion()` in `app/Models/Workflow.php` to resolve sub-agent slugs:
   - This is the **single, central** snapshot method — it is called from `WorkflowController::update()`, `WorkflowDashboardController::update()`, and `WorkflowStepKnowledgeController::store()`/`destroy()`. Pinning here ensures every snapshot path records `sub_agent_definition_id`, not just one controller.
   - Inside the existing transaction, after reading `$this->steps`, resolve slugs to IDs:
     ```php
     $steps = $this->steps;

     $slugs = collect($steps)
         ->pluck('sub_agent_definition_slug')
         ->filter()
         ->unique();

     if ($slugs->isNotEmpty()) {
         $slugToId = SubAgentDefinition::where('hive_id', $this->hive_id)
             ->where('is_active', true)
             ->whereIn('slug', $slugs)
             ->pluck('id', 'slug');

         foreach ($steps as $key => &$step) {
             if ($slug = $step['sub_agent_definition_slug'] ?? null) {
                 $step['sub_agent_definition_id'] = $slugToId[$slug] ?? null;
             }
         }
         unset($step);
     }
     ```
   - Pass the resolved `$steps` (with pinned IDs) to `$this->versions()->create(...)` instead of `$this->steps`

2. Update `WorkflowExecutionService::createStepTask()`:
   - When creating the task for a step, check for pinned ID:
     ```php
     if ($pinnedId = $stepDef['sub_agent_definition_id'] ?? null) {
         // Verify the definition still exists (fail-open if not)
         $exists = SubAgentDefinition::where('id', $pinnedId)->exists();
         $task->sub_agent_definition_id = $exists ? $pinnedId : null;
     }
     ```

3. Update workflow builder UI:
   - Add sub-agent selector dropdown to step configuration panel
   - Fetch active sub-agent definitions for the hive
   - Store selected slug in step definition

4. Add validation warnings for unresolvable slugs (if WorkflowValidationService exists)

5. Write tests

## Test Plan

### Feature Tests

- [ ] Workflow version snapshot resolves `sub_agent_definition_slug` to correct `sub_agent_definition_id`
- [ ] Snapshot stores both slug (display) and ID (execution) in step definition
- [ ] Snapshot handles step without sub-agent slug (backward compatible)
- [ ] Snapshot handles unresolvable slug (sets ID to null, doesn't fail)
- [ ] Step task creation uses pinned `sub_agent_definition_id` from snapshot
- [ ] Step task creation does NOT re-resolve slug at execution time
- [ ] Step task creation with null pinned ID creates task without sub-agent
- [ ] Step task creation with deleted pinned definition creates task without sub-agent (fail-open)
- [ ] Different steps in same workflow can have different sub-agent definitions
- [ ] Workflow builder UI shows sub-agent selector per step
- [ ] Workflow builder UI populates dropdown with active definitions
- [ ] Existing workflows without sub-agent slugs continue to work

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Version determinism verified (pinned at snapshot, not re-resolved at execution)
- [ ] Fail-open behavior at execution
- [ ] Backward compatible with existing workflows
- [ ] No schema migration needed
- [ ] Builder UI updated with sub-agent selector
- [ ] Both slug and ID stored in snapshot for display + execution
