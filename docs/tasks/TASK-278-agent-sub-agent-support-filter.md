---
name: TASK-278 agent sub-agent support filter
description: Let agents declare which sub-agent definitions they can run, and filter task polling so attached-sub-agent tasks only land on supporting agents.
type: project
---

# TASK-278: Agent sub-agent support filter

**Status:** pending
**Branch:** `task/278-agent-sub-agent-support-filter`
**PR:** —
**Depends on:** TASK-259 (sub_agent_definitions table), TASK-265 (webhook routes set `sub_agent_definition_id` on tasks), TASK-267/268/277 (other producers of attached tasks)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md)

## Objective

Tasks can now carry a `sub_agent_definition_id` (webhook routes, dashboard create, SDK paths). Today, **any** agent in the hive whose `capabilities[]` matches `target_capability` can claim such a task — including agents that have no runtime support for that sub-agent (e.g. a Claude Code agent claiming a task explicitly attached to a Codex sub-agent definition). Add an agent-side declaration of which sub-agent slugs an agent supports, and filter the poll query so attached-sub-agent tasks only flow to supporting agents.

## Background

- `tasks.sub_agent_definition_id` is nullable (TASK-259 migration). The producer side (TASK-265 webhook routes, TASK-267/268 SDK, TASK-277 dashboard) is shipped.
- The consumer side — `TaskController::poll()` (`app/Http/Controllers/Api/TaskController.php:239-348`) — does not consult `sub_agent_definition_id` when ranking eligibility. It only filters by `target_agent_id`, `target_capability`, hive, and availability windows.
- `Agent.capabilities` is a JSON string array. There is no `supported_sub_agent_*` field.
- Sub-agent definitions are immutable per version, but their **slug** is stable per hive (active version is unique on `(hive_id, slug)`). Agents should declare support by **slug**, not id, so they don't need re-config every time a definition gets a new version.

## Requirements

### Functional

- [ ] FR-1: New nullable JSONB column `agents.supported_sub_agent_slugs` (string array). `NULL` means "supports all sub-agents" (backward-compatible default — existing agents keep claiming everything). `[]` means "supports none — refuse all attached-sub-agent tasks". `["slug-a","slug-b"]` means "supports exactly these slugs".
- [ ] FR-2: `TaskController::poll()` adds a clause to the eligibility query:
  - If the task has `sub_agent_definition_id` set, the corresponding `SubAgentDefinition.slug` must be in the polling agent's `supported_sub_agent_slugs` (or the column is `NULL`).
  - If the task has `sub_agent_definition_id = NULL`, behavior is unchanged.
  - The check is implemented as a SQL filter, not in PHP after the fact, so the existing FOR UPDATE SKIP LOCKED claim semantics still hold.
- [ ] FR-3: An agent that targets a task explicitly via `target_agent_id` overrides the sub-agent filter — the assumption is that the task creator knows what they're doing. (Document this in code; it matches how `target_agent_id` already overrides `target_capability`.)
- [ ] FR-4: Agent registration / heartbeat endpoint (whatever the SDK calls — likely `POST /agents/register` or the heartbeat) accepts `supported_sub_agent_slugs` in the payload. Validation: `nullable|array`, `*.string`. Persisted on the Agent row.
- [ ] FR-5: Dashboard agent edit page (`resources/js/Pages/Agents/Edit.jsx` or equivalent) gets a multi-select of slugs from the hive's `sub_agent_definitions` so operators can manage support list without hitting the API.
- [ ] FR-6: Activity log entry `dashboard.agent.sub_agent_support_updated` with `{agent_id, before, after}` on changes through the dashboard.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Migration is reversible.
- [ ] NFR-3: Backward-compat — existing agents (column `NULL`) keep claiming all tasks. No behavior change unless the operator opts in.
- [ ] NFR-4: Hive isolation — the slug list is interpreted in the agent's hive context. If a slug exists in two hives, the agent's hive scope already covers it (poll is hive-scoped).
- [ ] NFR-5: One additional join (or sub-select) in the poll query at most. Verify no N+1.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/YYYY_MM_DD_HHMMSS_add_supported_sub_agent_slugs_to_agents_table.php` | Nullable JSONB column |
| Modify | `app/Models/Agent.php` | Add to `$fillable` + cast to array |
| Modify | `app/Http/Controllers/Api/TaskController.php` | Extend `poll()` query with sub-agent filter |
| Modify | `app/Http/Requests/RegisterAgentRequest.php` (or wherever `supported_*` fields live today — find by grepping for `capabilities` validation) | Accept `supported_sub_agent_slugs` |
| Modify | `app/Http/Controllers/Dashboard/AgentDashboardController.php` | Update endpoint accepts the new field |
| Modify | `resources/js/Pages/Agents/Edit.jsx` | Multi-select UI |
| Create | `tests/Feature/Api/TaskPollSubAgentFilterTest.php` | Poll filter behaviour: NULL = all, [] = none, list = match-only, target_agent_id override |
| Create | `tests/Feature/Dashboard/AgentSupportedSubAgentsTest.php` | Dashboard update + activity log |

### Key Design Decisions

- **Slug, not id** — sub-agent definitions are versioned; the slug is the stable handle. Agents declare slug support so they don't need re-config on every version bump.
- **NULL = supports all** — preserves existing behavior for every currently-running agent. Operators opt in to filtering by setting a list (or `[]` for "none").
- **`target_agent_id` overrides** — keeps the explicit-targeting escape hatch consistent with `target_capability`. Useful for ops pushing one-off tasks to a specific agent regardless of declared support.
- **No FK to `sub_agent_definitions`** — the slug list is a soft reference. If a slug is removed from the hive, the agent's list still has the string but no task will match it. That's fine and avoids cascading-delete complexity.
- **Filter in SQL, not PHP** — preserves the existing FOR UPDATE SKIP LOCKED claim semantics. Implementing as: `WHERE (tasks.sub_agent_definition_id IS NULL OR EXISTS (SELECT 1 FROM sub_agent_definitions sad WHERE sad.id = tasks.sub_agent_definition_id AND (agents.supported_sub_agent_slugs IS NULL OR agents.supported_sub_agent_slugs @> to_jsonb(sad.slug))))` — Postgres specifics (`@>` checks whether the JSONB array contains the slug value); SQLite path uses `JSON_CONTAINS` or whatever the existing capability filter does (mirror that style — look at how `target_capability` matching is written cross-DB).

## Implementation Plan

1. Migration + Agent model field + cast.
2. SDK / heartbeat / register payload accepts the new field; validation; persist.
3. Extend `TaskController::poll()` with the SQL filter. Mirror the cross-DB pattern used by the existing `target_capability` matching (look there first; do not invent a new JSON-array predicate).
4. Dashboard edit UI + controller method + activity log.
5. Tests:
   - `null` agent column claims a task with `sub_agent_definition_id` set
   - `[]` agent column does NOT claim a task with `sub_agent_definition_id` set
   - `["foo"]` agent column claims a task whose def slug = `foo` but not one with slug = `bar`
   - `target_agent_id` matching this agent overrides — agent claims regardless of slug list
   - Tasks without `sub_agent_definition_id` are unaffected

## Test Plan

### Feature Tests
- [ ] Agent with `supported_sub_agent_slugs = NULL` claims attached-sub-agent task (back-compat)
- [ ] Agent with `[]` does not claim any attached-sub-agent task
- [ ] Agent with `["a"]` claims tasks attached to slug `a`, skips tasks attached to slug `b`
- [ ] `target_agent_id = this agent` overrides the slug filter
- [ ] Tasks without sub-agent attachment are claimable by any capability-matching agent (unchanged)
- [ ] Heartbeat / register endpoint accepts and persists `supported_sub_agent_slugs`
- [ ] Dashboard PATCH on agent updates the field and writes activity log

### JSX Tests
- [ ] Agent edit page renders multi-select pre-populated from hive's sub-agent definitions
- [ ] Empty selection saves as `[]` (not `null`); operator must explicitly pick "supports all" toggle to set `null`

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] Migration reversible
- [ ] Existing agents (column `NULL`) still claim everything they used to
- [ ] No N+1 — poll query EXPLAIN looks like one extra subselect, not a per-row lookup
- [ ] Dashboard UI lists slugs from current hive only

## Notes for Implementer

- The existing `target_capability` matching SQL is the reference for how to write JSON-array containment cross-DB. Do not invent a new pattern.
- When the dashboard surfaces "supports all" vs "supports specific", be explicit — `null` and `[]` mean very different things and the UI must make that obvious. Suggest a toggle: "Accept tasks for any sub-agent" (`null`) vs "Restrict to selected sub-agents" (array).
