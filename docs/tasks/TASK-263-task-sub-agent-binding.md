# TASK-263: Task sub-agent binding

**Status:** pending
**Branch:** `task/263-task-sub-agent-binding`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/465
**Depends on:** TASK-259, TASK-260
**Blocks:** TASK-264, TASK-265, TASK-266, TASK-267, TASK-268
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §5.2, §6.5

## Objective

Add `sub_agent_definition_id` to the tasks table and update the task delivery flow to include sub-agent information at two detail levels: a lightweight reference in poll/list responses and a full assembled prompt in claim responses. Also update task creation to accept an optional `sub_agent_definition_slug` which is resolved to an ID.

## Requirements

### Functional

- [ ] FR-1: Migration: add `sub_agent_definition_id` column to `tasks` table — string(26), nullable, FK → sub_agent_definitions (nullOnDelete), with index `idx_tasks_sub_agent`
- [ ] FR-2: Update `formatTask()` in `TaskController` to include a lightweight `sub_agent` reference when `sub_agent_definition_id` is set. The reference includes only: `id`, `slug`, `version`. This keeps poll responses small since `formatTask()` is called on every poll cycle.
  ```json
  {
    "sub_agent": {
      "id": "01DEF...",
      "slug": "coder",
      "version": 3
    }
  }
  ```
- [ ] FR-3: Update `claim()` response in `TaskController` to include the **full** `sub_agent` block when `sub_agent_definition_id` is set. The full block includes: id, slug, name, model, version, prompt (assembled via `SubAgentDefinitionService::assemble()`), config, allowed_tools. This is the only time the full prompt is sent.
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
- [ ] FR-4: Update `CreateTaskRequest` to accept optional `sub_agent_definition_slug` field (string, nullable, max:100, alpha_dash)
- [ ] FR-5: In the task creation flow (TaskController::store or task creation service), resolve `sub_agent_definition_slug` → active `sub_agent_definition_id`. **Important:** resolve against the **target hive** (`$targetHive->id`), not the calling agent's home hive (`$agent->hive_id`). `TaskController::store()` supports cross-hive task creation where the agent belongs to a different hive, so the definition must be looked up in the hive where the task is being created:
  ```php
  if ($slug = $request->input('sub_agent_definition_slug')) {
      $subAgent = SubAgentDefinition::where('slug', $slug)
          ->where('hive_id', $targetHive->id)
          ->where('is_active', true)
          ->first();
      $task->sub_agent_definition_id = $subAgent?->id;
  }
  ```
- [ ] FR-6: Fail-open behavior: if the slug doesn't resolve to an active definition (deleted, deactivated, typo), the task is still created without a sub-agent definition. No error is thrown — the task just doesn't have a sub-agent. Log a warning via `ActivityLogger` when resolution fails.

### Non-Functional

- [ ] NFR-1: Lightweight reference in polls, full prompt only at claim time — this design prevents bloating poll responses with large assembled prompts. Agents that need the full prompt outside the claim flow should use the id-based API endpoint (`GET /api/v1/sub-agents/by-id/{id}/assembled`).
- [ ] NFR-2: Eager-load the `subAgentDefinition` relationship on poll/list queries (e.g., `$query->with('subAgentDefinition')`) to avoid N+1 queries — `formatTask()` is called for every task in the response, so lazy-loading the relationship inside `formatTask()` would trigger a separate query per task. Claim is a single-row operation and does not need eager-loading.
- [ ] NFR-3: The `sub_agent` field should be `null` (omitted or null) when `sub_agent_definition_id` is not set — no empty object
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/xxxx_add_sub_agent_definition_id_to_tasks.php` | Add FK column to tasks |
| Modify | `app/Models/Task.php` | Add `subAgentDefinition()` relationship, add to fillable |
| Modify | `app/Http/Controllers/Api/TaskController.php` | Update `formatTask()` and `claim()` |
| Modify | `app/Http/Requests/CreateTaskRequest.php` | Add `sub_agent_definition_slug` validation |
| Create | `tests/Feature/TaskSubAgentBindingTest.php` | Integration tests |

### Key Design Decisions

- **Two-tier delivery** — lightweight ref on polls (3 fields) vs full prompt on claim (8+ fields). This is critical for performance: the assembled prompt can be large (many KB), and it should not be sent on every 5-second poll cycle. The agent only needs the full prompt when it actually claims and starts working on the task.
- **Slug resolution at creation time** — the slug is resolved to a concrete `sub_agent_definition_id` when the task is created, not when it's claimed. This pins the version at task creation time.
- **Fail-open** — a missing or invalid slug should never prevent task creation. The sub-agent is an enhancement, not a requirement.
- **nullOnDelete FK** — if a sub-agent definition is somehow deleted (shouldn't happen with soft-delete pattern, but safety), the task's reference becomes null rather than cascading a delete.

## Database Changes

```sql
ALTER TABLE tasks
    ADD COLUMN sub_agent_definition_id VARCHAR(26),
    ADD CONSTRAINT fk_tasks_sub_agent_definition
        FOREIGN KEY (sub_agent_definition_id)
        REFERENCES sub_agent_definitions(id)
        ON DELETE SET NULL;

CREATE INDEX idx_tasks_sub_agent ON tasks (sub_agent_definition_id);
```

## Implementation Plan

1. Create migration to add `sub_agent_definition_id` to tasks:
   ```php
   Schema::table('tasks', function (Blueprint $table) {
       $table->string('sub_agent_definition_id', 26)->nullable();
       $table->foreign('sub_agent_definition_id')
           ->references('id')
           ->on('sub_agent_definitions')
           ->nullOnDelete();
       $table->index('sub_agent_definition_id', 'idx_tasks_sub_agent');
   });
   ```

2. Update `Task` model:
   - Add `sub_agent_definition_id` to `$fillable`
   - Add relationship:
     ```php
     public function subAgentDefinition(): BelongsTo
     {
         return $this->belongsTo(SubAgentDefinition::class);
     }
     ```

3. Update poll/list queries to eager-load the relationship:
   - In `poll()`, add `->with('subAgentDefinition')` to the query builder so the relationship is pre-loaded before `formatTask()` is called in the `$tasks->map()` loop. This prevents N+1 queries — without eager-loading, each `$task->subAgentDefinition` access inside `formatTask()` would fire a separate SQL query, one per task in the poll response.
   - Apply the same eager-load to any other list/index queries that use `formatTask()`.

4. Update `formatTask()` in `TaskController`:
   - After building the task array, check if `sub_agent_definition_id` is set
   - Access the already-loaded relationship (eager-loaded by the poll/list query) and add lightweight ref:
     ```php
     if ($task->sub_agent_definition_id) {
         $subAgent = $task->subAgentDefinition;
         if ($subAgent) {
             $formatted['sub_agent'] = [
                 'id' => $subAgent->id,
                 'slug' => $subAgent->slug,
                 'version' => $subAgent->version,
             ];
         }
     }
     ```

5. Update `claim()` in `TaskController`:
   - After claiming the task, if `sub_agent_definition_id` is set:
     - Load the sub-agent definition (single-row load; no eager-loading needed since claim operates on one task)
     - Assemble the prompt via `SubAgentDefinitionService::assemble()`
     - Add full sub_agent block to the response:
       ```php
       if ($task->sub_agent_definition_id) {
           $subAgent = $task->subAgentDefinition;
           if ($subAgent) {
               $response['sub_agent'] = [
                   'id' => $subAgent->id,
                   'slug' => $subAgent->slug,
                   'name' => $subAgent->name,
                   'model' => $subAgent->model,
                   'version' => $subAgent->version,
                   'prompt' => $this->subAgentService->assemble($subAgent),
                   'config' => $subAgent->config,
                   'allowed_tools' => $subAgent->allowed_tools,
               ];
           }
       }
       ```

6. Update `CreateTaskRequest` rules:
   ```php
   'sub_agent_definition_slug' => ['nullable', 'string', 'alpha_dash', 'max:100'],
   ```

7. Update task creation flow to resolve slug → id:
   - After validation, before creating the task
   - Resolve slug against active definitions in the **target hive** (`$targetHive->id` from the route), not the calling agent's home hive — `TaskController::store()` supports cross-hive task creation where these differ
   - Set `sub_agent_definition_id` on the task
   - If resolution fails, log warning and continue without sub-agent

8. Write tests

## Test Plan

### Feature Tests

- [ ] Migration adds `sub_agent_definition_id` column to tasks
- [ ] Task model has `subAgentDefinition()` relationship
- [ ] `formatTask()` includes lightweight `sub_agent` ref when definition is set
- [ ] `formatTask()` omits `sub_agent` when definition is not set
- [ ] `formatTask()` omits `sub_agent` when definition was deleted (nullOnDelete)
- [ ] `claim()` includes full `sub_agent` block with assembled prompt
- [ ] `claim()` includes correct assembled prompt content
- [ ] `claim()` omits `sub_agent` when definition is not set
- [ ] Task creation with valid `sub_agent_definition_slug` resolves to correct ID
- [ ] Task creation with invalid slug creates task without sub-agent (fail-open)
- [ ] Task creation with slug from different hive does not resolve (hive scoping)
- [ ] Cross-hive task creation resolves slug against target hive, not caller's home hive
- [ ] Task creation without slug works as before (backward compatible)
- [ ] `CreateTaskRequest` accepts `sub_agent_definition_slug`
- [ ] `CreateTaskRequest` validates `sub_agent_definition_slug` format
- [ ] Poll response does not include assembled prompt (only lightweight ref)
- [ ] Claim response includes assembled prompt (full block)

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on slug resolution failure
- [ ] API responses use `{ data, meta, errors }` envelope
- [ ] Form Request validation on task creation input
- [ ] Backward compatible — existing tasks without sub-agent continue to work
- [ ] No N+1 queries on poll/list paths — `subAgentDefinition` eager-loaded before `formatTask()` loop
- [ ] ULIDs for primary keys
