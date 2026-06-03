# TASK-262: Dashboard: sub-agent CRUD + pages

**Status:** pending
**Branch:** `task/262-sub-agent-dashboard`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/462
**Depends on:** TASK-259, TASK-260
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §7

## Objective

Create dashboard controller and Inertia/React pages for managing sub-agent definitions: listing, creating, editing (document editor with tabs), version history, and rollback. Follows existing dashboard patterns (reference: `PersonaDashboardController`).

## Requirements

### Functional

- [ ] FR-1: `GET /dashboard/sub-agents` — index page listing all sub-agent definitions in the current hive (both active and inactive). Displays as a card grid showing slug, name, description, model, version, active status, and document count. UI provides a toggle/filter to show or hide inactive definitions.
- [ ] FR-2: `POST /dashboard/sub-agents` — create a new sub-agent definition. Validates input via `StoreSubAgentDefinitionRequest`. Delegates to `SubAgentDefinitionService::create()`. Redirects to show page on success.
- [ ] FR-3: `GET /dashboard/sub-agents/{slug}` — show/edit page for a specific sub-agent definition. Displays document editor with tabs for each document type (SOUL, AGENT, RULES, STYLE, EXAMPLES, NOTES). Shows config, model, allowed_tools editors.
- [ ] FR-4: `PUT /dashboard/sub-agents/{slug}` — update a sub-agent definition (creates a new version). Validates via `UpdateSubAgentDefinitionRequest`. Delegates to `SubAgentDefinitionService::update()`.
- [ ] FR-5: `DELETE /dashboard/sub-agents/{slug}` — deactivate the sub-agent definition. Delegates to `SubAgentDefinitionService::deactivate()`. Redirects to index.
- [ ] FR-6: `GET /dashboard/sub-agents/{slug}/versions` — version history page showing all versions of a slug with version number, created_by, created_at, and active status.
- [ ] FR-7: `POST /dashboard/sub-agents/{slug}/rollback` — rollback to a prior version. Accepts `{ version: int }` in request body. Delegates to `SubAgentDefinitionService::rollback()`.
- [ ] FR-8: Inertia pages:
  - `SubAgents/Index.jsx` — card grid listing all definitions with create button
  - `SubAgents/Show.jsx` — document editor with tab-based navigation for each document type, JSON editors for config and allowed_tools, model selector
  - `SubAgents/Versions.jsx` — version history table with rollback action buttons
- [ ] FR-9: Form request validation per feature spec §7.3:
  - `StoreSubAgentDefinitionRequest`: slug (required, alpha_dash, max:100, unique per hive among active), name (required, string, max:255), description (nullable, string), model (nullable, string, max:100), documents (required, array, keys validated against allowed document names), config (nullable, array), allowed_tools (nullable, array of strings)
  - `UpdateSubAgentDefinitionRequest`: same as store but slug is not editable (excluded from validation)
- [ ] FR-10: Add "Sub-Agents" navigation item to the dashboard sidebar/navigation in `AppLayout.jsx`. Place it near "Personas" in the navigation order.

### Non-Functional

- [ ] NFR-1: Follow existing dashboard patterns — reference `PersonaDashboardController` for controller structure, `resources/js/Pages/Agents/` for page component patterns
- [ ] NFR-2: PSR-12 compliant for PHP files
- [ ] NFR-3: Use Inertia::render() for page responses with proper props
- [ ] NFR-4: Flash messages for success/error feedback on mutations

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Http/Controllers/Dashboard/SubAgentDashboardController.php` | Dashboard controller |
| Create | `app/Http/Requests/StoreSubAgentDefinitionRequest.php` | Create validation |
| Create | `app/Http/Requests/UpdateSubAgentDefinitionRequest.php` | Update validation |
| Create | `resources/js/Pages/SubAgents/Index.jsx` | Card grid listing page |
| Create | `resources/js/Pages/SubAgents/Show.jsx` | Document editor page |
| Create | `resources/js/Pages/SubAgents/Versions.jsx` | Version history page |
| Modify | `resources/js/Layouts/AppLayout.jsx` | Add Sub-Agents nav item |
| Modify | `routes/web.php` | Register dashboard routes |
| Create | `tests/Feature/SubAgentDashboardControllerTest.php` | Controller tests |

### Key Design Decisions

- **Card grid for index** — sub-agent definitions are conceptual units (like agents or personas), so a card grid is more appropriate than a table for the index page.
- **Tab-based document editor** — each document type (SOUL, AGENT, RULES, etc.) gets its own tab, matching the persona editor pattern. This keeps the editor clean even with many documents.
- **Slug-based routes** — dashboard routes use slug for human-friendly URLs (`/dashboard/sub-agents/coder`), same pattern as other dashboard pages.
- **Version as new row** — the update action creates a new version (new row), not an in-place edit. The UI should communicate this to the user (e.g., "Save will create version N+1").

## Implementation Plan

1. Create `StoreSubAgentDefinitionRequest`:
   ```php
   public function rules(): array
   {
       return [
           'slug' => ['required', 'string', 'alpha_dash', 'max:100'],
           'name' => ['required', 'string', 'max:255'],
           'description' => ['nullable', 'string'],
           'model' => ['nullable', 'string', 'max:100'],
           'documents' => ['required', 'array'],
           'documents.*' => ['string'],
           'config' => ['nullable', 'array'],
           'allowed_tools' => ['nullable', 'array'],
           'allowed_tools.*' => ['string'],
       ];
   }
   ```
   Add custom validation to ensure document keys are valid (SOUL, AGENT, RULES, STYLE, EXAMPLES, NOTES only).

2. Create `UpdateSubAgentDefinitionRequest` (same rules minus slug).

3. Create `SubAgentDashboardController`:
   - `index()` — fetch all definitions for current hive, render `SubAgents/Index` (UI filters by active/inactive status)
   - `store(StoreSubAgentDefinitionRequest)` — create via service, redirect to show
   - `show(string $slug)` — find active definition, render `SubAgents/Show`
   - `update(UpdateSubAgentDefinitionRequest, string $slug)` — update via service, redirect back
   - `destroy(string $slug)` — deactivate via service, redirect to index
   - `versions(string $slug)` — fetch all versions for slug, render `SubAgents/Versions`
   - `rollback(Request $request, string $slug)` — validate version, rollback via service, redirect back

4. Create React pages:
   - `SubAgents/Index.jsx`: Card grid with create button, each card shows slug, name, description, model, version badge, document count, edit/delete actions
   - `SubAgents/Show.jsx`: Tab navigation for document types, textarea for each document, JSON editors for config/allowed_tools, model input field, save button with version increment notice
   - `SubAgents/Versions.jsx`: Table of all versions with columns: version, created_by, created_at, is_active badge, rollback button (disabled for currently active)

5. Add "Sub-Agents" to `AppLayout.jsx` navigation, placed near Personas.

6. Register routes in `routes/web.php`:
   ```php
   Route::prefix('sub-agents')->group(function () {
       Route::get('/', [SubAgentDashboardController::class, 'index'])->name('sub-agents.index');
       Route::post('/', [SubAgentDashboardController::class, 'store'])->name('sub-agents.store');
       Route::get('/{slug}', [SubAgentDashboardController::class, 'show'])->name('sub-agents.show');
       Route::put('/{slug}', [SubAgentDashboardController::class, 'update'])->name('sub-agents.update');
       Route::delete('/{slug}', [SubAgentDashboardController::class, 'destroy'])->name('sub-agents.destroy');
       Route::get('/{slug}/versions', [SubAgentDashboardController::class, 'versions'])->name('sub-agents.versions');
       Route::post('/{slug}/rollback', [SubAgentDashboardController::class, 'rollback'])->name('sub-agents.rollback');
   });
   ```

7. Write controller tests

## Test Plan

### Feature Tests

- [ ] `GET /dashboard/sub-agents` renders index page with definitions
- [ ] `GET /dashboard/sub-agents` shows only definitions from current hive
- [ ] `POST /dashboard/sub-agents` creates new definition and redirects
- [ ] `POST /dashboard/sub-agents` validates required fields (slug, name, documents)
- [ ] `POST /dashboard/sub-agents` rejects invalid slug format
- [ ] `POST /dashboard/sub-agents` rejects duplicate active slug in same hive
- [ ] `POST /dashboard/sub-agents` rejects invalid document keys
- [ ] `GET /dashboard/sub-agents/{slug}` renders show page with definition data
- [ ] `GET /dashboard/sub-agents/{slug}` returns 404 for non-existent slug
- [ ] `PUT /dashboard/sub-agents/{slug}` creates new version
- [ ] `PUT /dashboard/sub-agents/{slug}` validates input
- [ ] `DELETE /dashboard/sub-agents/{slug}` deactivates definition
- [ ] `GET /dashboard/sub-agents/{slug}/versions` shows version history
- [ ] `POST /dashboard/sub-agents/{slug}/rollback` activates target version
- [ ] `POST /dashboard/sub-agents/{slug}/rollback` validates version exists
- [ ] Navigation includes "Sub-Agents" link

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Form Request validation on all inputs
- [ ] Activity logging on state changes (via service)
- [ ] Inertia pages render correctly
- [ ] Navigation updated in AppLayout.jsx
- [ ] Flash messages on success/error
- [ ] Follows PersonaDashboardController patterns
