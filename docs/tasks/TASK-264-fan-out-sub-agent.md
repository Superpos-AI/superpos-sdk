# TASK-264: Fan-out sub-agent support

**Status:** pending
**Branch:** `task/264-fan-out-sub-agent`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/464
**Depends on:** TASK-263
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §10

## Objective

Enable fan-out child tasks to each specify a different `sub_agent_definition_slug`, resolved to a concrete `sub_agent_definition_id` at creation time. This allows multi-sub-agent pipelines where a parent task fans out work to children, each using a specialized sub-agent persona.

## Background

Fan-out (TASK-096) creates multiple child tasks from a parent. Currently, children inherit the parent's hive context but have no way to specify per-child sub-agent definitions. With task sub-agent binding (TASK-263), tasks can reference sub-agent definitions. This task extends fan-out to support per-child sub-agent specification.

Example use case:
```json
{
  "children": [
    {
      "payload": { "prompt": "Research the topic" },
      "target_capability": "research",
      "sub_agent_definition_slug": "researcher"
    },
    {
      "payload": { "prompt": "Write the code" },
      "target_capability": "engineering",
      "sub_agent_definition_slug": "coder"
    },
    {
      "payload": { "prompt": "Review the output" },
      "target_capability": "qa",
      "sub_agent_definition_slug": "reviewer"
    }
  ]
}
```

## Requirements

### Functional

- [ ] FR-1: Fan-out child task definitions accept an optional `sub_agent_definition_slug` field (string, alpha_dash, max:100)
- [ ] FR-2: When creating fan-out children, resolve each child's `sub_agent_definition_slug` to the currently active `sub_agent_definition_id` in the parent task's hive:
  ```php
  if ($slug = $childDef['sub_agent_definition_slug'] ?? null) {
      $subAgent = SubAgentDefinition::where('slug', $slug)
          ->where('hive_id', $parentTask->hive_id)
          ->where('is_active', true)
          ->first();
      $child->sub_agent_definition_id = $subAgent?->id;
  }
  ```
- [ ] FR-3: Fail-open per child: if a child's slug doesn't resolve (deleted, deactivated, typo), that child is still created without a sub-agent definition. Other children with valid slugs are unaffected. No error thrown — log a warning via ActivityLogger.

### Non-Functional

- [ ] NFR-1: Backward compatible — existing fan-out requests without `sub_agent_definition_slug` continue to work unchanged
- [ ] NFR-2: PSR-12 compliant
- [ ] NFR-3: Slug resolution should be batched where possible (collect unique slugs, resolve once, map to children) to minimize queries

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Services/FanOutService.php` | Add slug resolution in child creation |
| Modify | `app/Http/Requests/CreateTaskRequest.php` | Validate `sub_agent_definition_slug` in children array |
| Create | `tests/Feature/FanOutSubAgentTest.php` | Fan-out sub-agent tests |

### Key Design Decisions

- **Per-child resolution** — each child can have a different sub-agent slug, resolved independently. This is the core value: a single fan-out can dispatch work to different specialized sub-agents.
- **Fail-open per child** — a missing slug on one child doesn't block creation of other children. This matches the overall fail-open philosophy from TASK-263.
- **Batched resolution** — to avoid N queries for N children with different slugs, collect unique slugs first, resolve them all in one query, then map IDs back to children.

## Implementation Plan

1. Update `CreateTaskRequest` to accept `sub_agent_definition_slug` in children array:
   ```php
   'children.*.sub_agent_definition_slug' => ['nullable', 'string', 'alpha_dash', 'max:100'],
   ```

2. Update `FanOutService` child creation logic:
   - Before the child creation loop, collect all unique slugs from children
   - Batch-resolve slugs to IDs:
     ```php
     $slugs = collect($children)
         ->pluck('sub_agent_definition_slug')
         ->filter()
         ->unique()
         ->values();

     $slugToId = SubAgentDefinition::where('hive_id', $parentTask->hive_id)
         ->where('is_active', true)
         ->whereIn('slug', $slugs)
         ->pluck('id', 'slug');
     ```
   - In the child creation loop, set `sub_agent_definition_id` from the resolved map:
     ```php
     if ($slug = $childDef['sub_agent_definition_slug'] ?? null) {
         $child->sub_agent_definition_id = $slugToId[$slug] ?? null;
         if (!isset($slugToId[$slug])) {
             // Log warning: slug did not resolve
         }
     }
     ```

3. Write tests

## Test Plan

### Feature Tests

- [ ] Fan-out child with valid `sub_agent_definition_slug` gets correct `sub_agent_definition_id`
- [ ] Fan-out child without `sub_agent_definition_slug` has null `sub_agent_definition_id`
- [ ] Fan-out child with invalid slug is created without sub-agent (fail-open)
- [ ] Multiple children with different valid slugs each get correct IDs
- [ ] Mix of valid and invalid slugs: valid ones resolve, invalid ones are null
- [ ] Slug resolution is scoped to parent's hive (slug from other hive doesn't resolve)
- [ ] Existing fan-out without any sub_agent_definition_slug works unchanged
- [ ] Warning logged when slug resolution fails for a child
- [ ] Validation accepts `sub_agent_definition_slug` in children array
- [ ] Validation rejects invalid slug format in children array

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on slug resolution failures
- [ ] Backward compatible with existing fan-out behavior
- [ ] Form Request validation on children inputs
- [ ] Batch query for slug resolution (no N+1)
