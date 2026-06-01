# TASK-276: Sub-agent marketplace persona prefill

**Status:** in_progress
**Branch:** `task/276-sub-agent-marketplace-prefill`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/469
**Depends on:** TASK-262 (sub-agent dashboard — merged in PR #462)
**Blocks:** —
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §10 (new "Marketplace prefill" addendum)

## Objective

Let users bootstrap a new `SubAgentDefinition` from an existing `MarketplacePersona` via a "Start from Marketplace Persona" selector on the sub-agent create form. The selector prefills the six documents (SOUL / AGENT / RULES / STYLE / EXAMPLES / NOTES), the config JSON, model, description, and allowed_tools (mapped from persona `capabilities` where sensible). The result is a **fork** — a snapshot copy — not a live link. After prefill the user can freely edit every field and submit. `name` and `slug` are never prefilled (user picks their own identifier).

## Background

The dashboard already contains two asymmetric surfaces that share the same `documents + config` shape:

1. **Persona Marketplace** (`App\Models\MarketplacePersona`, `resources/js/Pages/PersonaMarketplace/*`) — a catalog of curated personas, public org-wide or private to the owning apiary, with install / apply flows for full managed agents.
2. **Sub-Agent Definitions** (`App\Models\SubAgentDefinition`, `resources/js/Pages/SubAgents/*`, TASK-260/261/262) — reusable templates scoped to a hive that can be bound to tasks, webhooks, workflows, and fan-out.

Right now every new sub-agent definition starts from a blank form, even when the user wants "the coding persona from the marketplace, but as a sub-agent". This task closes that gap with a forking prefill: the user picks a marketplace persona, we fetch its documents/config/description/capabilities and seed the create form, and the user tweaks and saves. The resulting sub-agent has no persistent FK back to the persona — editing the marketplace persona later does not reach forks.

## Requirements

### Functional

- [ ] FR-1: `resources/js/Pages/SubAgents/Create.jsx` gains a "Start from Marketplace Persona" dropdown at the top of the form. It lists personas visible to the current apiary (public + private-owned), ordered by name. Visibility label is shown after the name so users can distinguish public vs private. Placeholder: `-- Start from scratch --`.
- [ ] FR-2: On pick, the client calls `GET /dashboard/persona-marketplace/{slug}` with `Accept: application/json` (existing endpoint — see §Architecture) to fetch the full persona. It then populates:
  - `documents` — each doc's content string, normalized from the persona's `{NAME: {content, ...meta}}` or `{NAME: "string"}` shape;
  - `config` — stringified as JSON (pretty-printed) for the editor;
  - `model` — copied from `config.model` or `config.llm.model` if present, otherwise left blank;
  - `description` — copied from persona if present;
  - `allowed_tools` — stringified from persona's `capabilities` array as a JSON array.
- [ ] FR-3: Fork semantics. No FK from `sub_agent_definitions` to `marketplace_personas`. No `install_count` increment. No activity log entry on the persona. Selection is a UI-side bootstrap only.
- [ ] FR-4: User can clear the selection (choose `-- Start from scratch --`) to wipe all prefilled fields back to empty defaults, or simply edit any single field after prefilling. No lock, no diff tracking.
- [ ] FR-5: `name` and `slug` are **never** prefilled from the persona. The user picks their own identifier; slug auto-derives from name as it does today.
- [ ] FR-6: Reuse the existing `/dashboard/persona-marketplace/{slug}` JSON endpoint. It already returns `documents`, `config`, `capabilities`, `description`, `name`, `slug`, `visibility`, `category` with no side effects — no new endpoint required. The `SubAgentDashboardController::create()` passes a pre-filtered summary list as an Inertia prop to populate the dropdown (no client-side list call).

### Non-Functional

- [ ] NFR-1: No schema migration, no new database columns.
- [ ] NFR-2: Backward compatible — submitting the create form without picking a persona works exactly as before.
- [ ] NFR-3: PSR-12 and existing frontend style (tailwind, shadcn Select not used elsewhere — follow native `<select>` usage that matches current Create.jsx conventions).
- [ ] NFR-4: Covered by one frontend test (Create.jsx with prefill, mocked fetch) and one feature test asserting `create()` passes `marketplacePersonas` with correct visibility filtering.
- [ ] NFR-5: No `install_count` mutation on prefill — verified by a feature test that fetches the marketplace persona JSON and asserts the count is unchanged.

## Architecture & Design

### Files to Modify

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `app/Http/Controllers/Dashboard/SubAgentDashboardController.php` | `create()` resolves visible marketplace personas for current org and passes `marketplacePersonas` Inertia prop |
| Modify | `resources/js/Pages/SubAgents/Create.jsx` | Add "Start from Marketplace Persona" dropdown + prefill logic |
| Modify | `tests/Feature/SubAgentDashboardControllerTest.php` | Assert `marketplacePersonas` prop on create, visibility filter |
| Create | `resources/js/Pages/SubAgents/__tests__/CreatePrefill.test.jsx` | JSX test for the prefill flow (mocked fetch) |
| Modify | `docs/features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md` | Append §10.5 "Marketplace prefill" describing the fork model |

### Key Design Decisions

- **Fork, not link.** A persistent FK (`source_marketplace_persona_id` on `sub_agent_definitions`) was rejected: sub-agents evolve independently after creation (new versions via `SubAgentDefinitionService::update()`), and any "propagate upstream changes" story would collide with the existing immutable-versioning model. Keeping this UI-side means zero schema change and no semantic commitment.
- **Reuse the dashboard JSON endpoint, not a new `/template` endpoint.** `PersonaMarketplaceDashboardController::show()` already returns the required shape on `wantsJson()` requests and already enforces the correct visibility gate (`isVisibleTo`). Adding a narrow `/template` alias would duplicate that logic without benefit — the existing `show` is side-effect-free (no install_count mutation, no activity log).
- **Pass the dropdown list as an Inertia prop, not an AJAX call.** For a single form load we already pay the controller round-trip; pushing the summary list through `create()` keeps the dropdown ready on first render without an extra fetch or spinner.
- **`allowed_tools` from `capabilities` is best-effort.** Marketplace personas track `capabilities` as arbitrary string tags (e.g. `["coding", "research"]`), not Claude tool names. We copy them verbatim into `allowed_tools` so the user can see what the persona declared — they are free to replace with actual tool names (`Bash`, `Read`, ...). This is documented in the helper text.

### Endpoint Contract

`GET /dashboard/persona-marketplace/{slug}` with `Accept: application/json` (unchanged; see `PersonaMarketplaceDashboardController::show`):

```json
{
  "data": {
    "id": "01HB...",
    "slug": "coding-agent",
    "name": "Coding Agent",
    "description": "A focused coding agent.",
    "category": "coding",
    "tags": [],
    "visibility": "public",
    "is_featured": false,
    "install_count": 42,
    "documents": { "SOUL": { "content": "You are a..." } },
    "config": { "model": "claude-sonnet-4-20250514", "temperature": 0.2 },
    "lock_policy": {},
    "claim_type": null,
    "capabilities": ["coding"],
    "organization_id": "01HA...",
    "created_at": "...",
    "updated_at": "..."
  }
}
```

### Create() Prop Shape

```php
'marketplacePersonas' => [
  ['slug' => 'coding-agent', 'name' => 'Coding Agent', 'description' => '...', 'category' => 'coding', 'visibility' => 'public'],
  ...
]
```

Filtered via `MarketplacePersona::visibleTo($organizationId)` (public + private-for-this-org), ordered by name. Empty array when there is no org context.

## Implementation Plan

1. Update `SubAgentDashboardController::create()` to resolve the current org, query `MarketplacePersona::visibleTo($orgId)`, map to summary fields, and pass as `marketplacePersonas` Inertia prop.
2. Update `Create.jsx`:
   - Accept `marketplacePersonas` prop (default `[]`).
   - Add a labeled dropdown above Basic Information.
   - On change: if slug selected, `fetch('/dashboard/persona-marketplace/' + slug, {headers: {Accept: 'application/json'}})`, normalize documents from `{NAME: {content}}` shape to `{NAME: string}`, stringify config and capabilities as JSON, populate `setData`. If cleared, reset documents/config/model/description/allowed_tools to initial empties.
   - Never touch `name` or `slug`.
3. Add feature test: assert `create()` page has `marketplacePersonas` prop containing the expected public + private-owned persona and excluding private-other-org.
4. Add JSX test: render Create with a mocked `marketplacePersonas` list, mock `global.fetch` returning a persona detail, select the option, assert `setData` called for `documents`, `config`, `model`, `description`, `allowed_tools` and NOT called for `name`/`slug`.
5. Append §10.5 "Marketplace prefill" to FEATURE_SUB_AGENT_DEFINITIONS.md describing the fork model.

## Test Plan

### Feature tests

- [ ] `test_create_passes_marketplace_personas_prop` — public persona and private-owned-by-current-org persona appear; private-owned-by-other-org does not.
- [ ] `test_create_marketplace_personas_empty_when_no_org_context` — no context → empty array.
- [ ] `test_marketplace_persona_show_does_not_mutate_install_count` — hit the JSON endpoint, assert `install_count` unchanged. (Guards against future regression where preview is mistakenly wired to `applyToAgent`.)

### Frontend test

- [ ] `CreatePrefill.test.jsx` — renders dropdown populated from prop, selecting a persona invokes fetch, populates documents/config/model/description/allowed_tools, leaves name/slug untouched, clearing selection resets populated fields to empty defaults.

### Manual smoke

- [ ] Open `/dashboard/sub-agents/create` with at least one public marketplace persona in the catalog. Confirm dropdown shows it. Pick it. Confirm SOUL tab shows persona content, config textarea has the persona's config as pretty JSON, allowed_tools shows persona capabilities. Edit SOUL. Give it a new name/slug. Submit. Confirm the new sub-agent saved with the edited SOUL. Open the source marketplace persona — confirm `install_count` unchanged.

## Validation Checklist

- [ ] `./vendor/bin/pint --test` clean
- [ ] `php artisan test --filter=SubAgentDefinition` green
- [ ] `php artisan test --filter=SubAgentDashboard` green
- [ ] `php artisan test --filter=MarketplacePersona` green
- [ ] `npx vitest run SubAgents/Create` green
- [ ] No schema migration
- [ ] `name` and `slug` never prefilled
- [ ] `install_count` not mutated on preview/prefill
- [ ] Feature doc §10.5 appended
