---
name: TASK-193 built-in workflow templates
description: Seed 4 starter workflow templates and add a "Start from template" picker to the workflow builder.
type: project
---

# TASK-193: Built-in workflow templates

**Status:** pending
**Branch:** `task/193-built-in-workflow-templates`
**PR:** —
**Depends on:** TASK-177 (workflow engine), TASK-191 (loop step type), TASK-194 (qa-evaluator persona — Plan-Build-QA references it)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_WORKFLOWS.md](../features/list-1/FEATURE_WORKFLOWS.md)

## Objective

The workflow engine + builder UI ship empty. New users see a blank canvas and have to design every workflow from scratch. Seed 4 first-class **starter templates** and add a "Start from template" picker on the workflow builder so users can fork a template into an editable workflow with one click.

## Background

- Workflow engine (TASK-177) and loop step type (TASK-191) are shipped.
- `MarketplacePersona` already has the established "library of templates the user forks into a working object" pattern — see `MarketplacePersonaTemplateSeeder`, `PersonaDashboardController`, and the `SubAgents/Create.jsx` marketplace prefill picker (TASK-276). **Apply that pattern to workflows**, do not invent a new one.
- TASK-194 (this batch) adds the rich `qa-evaluator` persona that the Plan-Build-QA template references as its evaluator.

## Templates to seed

Each template is a complete workflow definition (steps, settings, trigger_config) plus marketplace metadata (slug, name, description, category, visibility). Edit-fork semantics: the user picks a template, the controller deep-copies it into a new `workflows` row with the user's chosen name/slug; no FK back to the template.

1. **`plan-build-qa`** — 3 agent steps + 1 loop wrapper:
   - Step `plan` (capability `planning`) → outputs plan
   - Step `build` (capability `coding`) → consumes plan, outputs work product
   - Step `qa` (loop body — uses persona `qa-evaluator`, max iterations 3, threshold pass) → returns `{score, pass, feedback}`; on `pass: false`, retry `build` with feedback appended; on `pass: true` or max iterations, exit
2. **`research-summarize`** — 2 agent steps:
   - Step `research` (capability `research`) → gathers sources
   - Step `summarize` (capability `summarization`) → produces structured summary
3. **`bug-triage`** — 1 agent step + branching:
   - Step `triage` (capability `code-review`) → outputs `{severity, owner, repro_steps}`; based on `severity`, branch to one of three notify steps (`page-oncall` / `file-issue` / `comment-only`)
4. **`pr-review`** — 2 agent steps:
   - Step `review` (capability `code-review`) → walks the diff, emits comments
   - Step `approve_or_reject` — uses the same `qa-evaluator` persona for a final pass/reject decision

All templates use placeholder `target_capability` / `sub_agent_definition_slug` values so users can wire them to their own agents post-fork.

## Requirements

### Functional

- [ ] FR-1: New table `workflow_templates` (or, if simpler, a `is_template` boolean + `template_slug` column on `workflows`). **Pick the cleaner option** during architecture and document the choice in the PR body. Recommendation: separate table — keeps `workflows` queries clean and mirrors `marketplace_personas` ↔ `agent_personas` separation.
- [ ] FR-2: Seeder `database/seeders/WorkflowTemplateSeeder.php` populates the 4 templates with `updateOrCreate(['slug' => …])` semantics (idempotent re-runs).
- [ ] FR-3: Dashboard endpoints (Inertia or JSON, match the persona-template precedent):
  - `GET /dashboard/workflow-templates` → list (id, slug, name, description, category, step_count)
  - `GET /dashboard/workflow-templates/{slug}` → full definition (for preview / for the picker to read before forking)
  - `POST /dashboard/workflows/from-template` body `{template_slug, name, slug}` → forks the template into a new `workflows` row in the current hive; returns the new workflow id; redirects to its builder
- [ ] FR-4: `WorkflowBuilder.jsx` (or the workflow create page) gains a "Start from template" picker:
  - Dropdown or modal listing the 4 templates with name + description + step count
  - "Use this template" button → POSTs to `from-template`, navigates to the new workflow's builder
  - The picker is only visible on the **create** page, not the **edit** page (don't let the user blow away an existing workflow by picking a template)
- [ ] FR-5: Forking deep-copies steps + settings + trigger_config; sets `is_active = false`, `version = 1`, `created_by_user_id = current user`; **does not** copy any `template_id` FK (fork semantics, mirrors TASK-276 marketplace prefill).
- [ ] FR-6: Activity log entry `dashboard.workflow.created_from_template` with `{workflow_id, template_slug}`.

### Non-Functional

- [ ] NFR-1: PSR-12 / Pint clean.
- [ ] NFR-2: Migration is reversible (`down()` drops the table or column cleanly).
- [ ] NFR-3: Seeder is idempotent — running twice produces no duplicates and updates content in place.
- [ ] NFR-4: Templates are visible in CE and Cloud identically — no `app/Cloud` import. (If Cloud later wants to hide certain templates per-tenant, that's a future task.)
- [ ] NFR-5: Hive isolation on the fork endpoint — the new workflow lands in the requesting user's current hive.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/YYYY_MM_DD_HHMMSS_create_workflow_templates_table.php` | Table for built-in workflow templates |
| Create | `app/Models/WorkflowTemplate.php` | Model — fillable: slug, name, description, category, steps (JSON), settings (JSON), trigger_config (JSON), step_count (cached) |
| Create | `database/seeders/WorkflowTemplateSeeder.php` | 4 starter templates |
| Create | `app/Http/Controllers/Dashboard/WorkflowTemplateDashboardController.php` | `index`, `show`, `apply` |
| Modify | `app/Http/Controllers/Dashboard/WorkflowDashboardController.php` | Add `fromTemplate(Request)` (or co-locate on the template controller — pick one and document) |
| Modify | `routes/web.php` | 3 new routes |
| Modify | `resources/js/Pages/WorkflowBuilder.jsx` | Add template picker (create-mode only) |
| Modify | `database/seeders/DatabaseSeeder.php` | Call `WorkflowTemplateSeeder` |
| Create | `tests/Feature/Dashboard/WorkflowTemplateTest.php` | Controller + fork semantics + idempotency tests |
| Create | `resources/js/Pages/__tests__/WorkflowTemplatePicker.test.jsx` | Picker render + fork action |

### Key Design Decisions

- **Separate `workflow_templates` table** (recommended) — keeps `workflows` queries unaffected, mirrors `marketplace_personas` ↔ `agent_personas`. Confirm during architecture before committing migration.
- **Fork, not link** — the new workflow has no FK back to the template (mirrors TASK-276 marketplace prefill). Editing the template later does not change forked workflows.
- **Templates are seed data, not user-editable** — there is no "create template" UI in this task. Templates ship via seeder; future tasks can add a marketplace publish flow.
- **The `qa-evaluator` persona dependency** is satisfied by TASK-194 (this batch). Plan-Build-QA's `qa` step references slug `qa-evaluator`; the seeded persona must exist or the workflow won't be runnable. Add a seeder ordering check (`DatabaseSeeder` runs `MarketplacePersonaTemplateSeeder` before `WorkflowTemplateSeeder`).

## Implementation Plan

1. **Migration + model** — `workflow_templates` table with `id (ulid pk)`, `slug (unique)`, `name`, `description (text)`, `category`, `steps (jsonb)`, `settings (jsonb)`, `trigger_config (jsonb)`, `step_count (int)`, `is_featured (bool)`, timestamps.
2. **Seeder** — author the 4 templates as PHP arrays. Validate JSON shapes against `WorkflowExecutionService` step schema (look at `WorkflowExecutionService::executeStep` switch statement to confirm step type names: `agent`, `loop`, `condition`/`branch`, etc.).
3. **Controller** — `index()` returns `Inertia::render('Workflows/Templates', ['templates' => …])` or JSON depending on whether you want a dedicated page or a modal-driven picker. Picker-in-builder is simpler — go JSON for `index` + `show`, no dedicated page needed.
4. **Fork endpoint** — validates `template_slug`, `name` (required, unique within hive), `slug` (required, unique within hive). Creates a new `Workflow` record with deep-copied JSON, returns the new id.
5. **Builder UI** — add a "Start from template" button at the top of the create page. Click → modal listing templates → preview pane on hover → "Use this template" submits the fork POST, navigates to the new workflow's builder.
6. **Tests** — see Test Plan.

## Test Plan

### Feature Tests

- [ ] Seeder creates 4 templates on a fresh DB
- [ ] Re-running the seeder is idempotent (no duplicates, content updated)
- [ ] `GET /dashboard/workflow-templates` returns the 4 templates
- [ ] `GET /dashboard/workflow-templates/plan-build-qa` returns full definition with steps
- [ ] `POST /dashboard/workflows/from-template` with valid `template_slug` creates a new workflow in the current hive with deep-copied steps
- [ ] Forked workflow has `is_active = false`, `version = 1`, no FK to template
- [ ] Forking is hive-scoped — new workflow lands in caller's current hive
- [ ] Fork endpoint validates `name` / `slug` uniqueness within hive
- [ ] `dashboard.workflow.created_from_template` activity event logged
- [ ] Plan-Build-QA template's `qa` step references slug `qa-evaluator`, and that persona exists post-seed (cross-seeder integration test)
- [ ] Seeder ordering — `DatabaseSeeder` runs persona seeder before workflow template seeder

### JSX Tests

- [ ] Picker renders all templates with name, description, step count
- [ ] Picker is hidden on the workflow edit page (only visible on create)
- [ ] Selecting a template enables the "Use this template" submit
- [ ] Submit POSTs to `/dashboard/workflows/from-template` with the right payload

## Validation Checklist

- [ ] All tests pass
- [ ] Pint clean
- [ ] Migration reversible
- [ ] Seeder idempotent
- [ ] Plan-Build-QA template references the seeded `qa-evaluator` persona (TASK-194 dep satisfied)
- [ ] Picker only on create page, not edit page
- [ ] Activity logging verified
- [ ] Hive isolation verified
