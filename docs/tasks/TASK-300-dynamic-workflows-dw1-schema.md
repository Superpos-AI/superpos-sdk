# TASK-300 — Phase DW-1: schema + payload discriminator

**Status:** ⬜ pending
**Owner:** workflow track
**Track:** Dynamic Workflows
**Blocked by:** —
**Blocks:** DW-2, DW-3, DW-4
**Proposal:** [`docs/proposals/dynamic-workflows.md`](../proposals/dynamic-workflows.md) §15

## Goal

Make the registry recognise `dynamic_workflow` as a 4th `kind`
value, validate its payload shape on write, and let task-scoped
executor attachments target a DW. **No API surface, no runs
table, no SDK, no events yet** — those are DW-2+.

## Scope (in)

1. **Kind discriminator** — extend the `KINDS` constant and the
   form-request validation rules.
2. **CHECK constraint** — at the DB level (not a Postgres ENUM
   extension; `registry_items.kind` is `string(20)`, see
   `database/migrations/2026_06_01_100000_create_registry_items_table.php:16`).
3. **Payload validator** — a `DynamicWorkflowPayloadValidator`
   that runs on `createItem` and `updateItem` when
   `kind = 'dynamic_workflow'`. Validates the §6.2 shape
   (`entry`, `inputs`, `outputs`, `capabilities.declared[]`,
   `capabilities.limits{}`).
4. **Executor role reservation** — extend
   `RegistryService::attach` so `role = 'executor'` is allowed
   for `kind ∈ {'subagent', 'dynamic_workflow'}` at
   `scope = 'task'`. Today the code only allows `subagent`
   (`RegistryService.php:355-362`). Skills and modules remain
   excluded.
5. **Hard-gate tests** — covering kind acceptance, payload
   validation (positive + negative), executor reservation
   update, and the CHECK constraint.

## Out of scope (deferred)

- `dynamic_workflow_runs` table and run lifecycle — **DW-2**
- `POST /registry/dynamic-workflow/...` API routes — **DW-2**
- Agent claim endpoint — **DW-2**
- `superpos.workflows.dynamic` SDK — **DW-3**
- `platform.dynamic_workflow.*` event topics — **DW-3**
- Permissions (`registry.dynamic_workflow.*`) — **DW-3**
- `ScriptRuntime` interface + V8/sidecar — **DW-3**
- `config/dynamic_workflow.php` ceilings — **DW-3**
- Dashboard code-editor view — **DW-4**
- Static-DAG step of `type = 'dynamic_workflow'` — **DW-4**
- `WorkflowTemplate.kind` discriminator — **DW-4**

## Spec correction (rolls into this PR)

The proposal §6.1 says:

> ```sql
> ALTER TYPE registry_item_kind ADD VALUE 'dynamic_workflow';
> ```

This is **wrong**: `registry_items.kind` is a
`string(20)` column, not a Postgres ENUM. The actual schema
change is:

- Add `'dynamic_workflow'` to `RegistryItem::KINDS`
  (`app/Models/RegistryItem.php:17`).
- Add a CHECK constraint in a new migration.

Fix the proposal text in the same PR (one-line doc edit).

## Files touched

### New
- `database/migrations/2026_06_XX_XXXXXX_add_dynamic_workflow_kind_to_registry_items.php` — CHECK constraint
- `app/Registry/PayloadValidators/DynamicWorkflowPayloadValidator.php` — kind-specific payload shape
- `app/Registry/PayloadValidators/Contracts/PayloadValidator.php` — interface (so subagent/skill/module can adopt it later)
- `app/Exceptions/DynamicWorkflowPayloadInvalid.php` — payload validation failure (carries field path)
- `tests/Feature/Registry/DynamicWorkflowKindDiscriminatorTest.php` — kind acceptance + CHECK constraint
- `tests/Feature/Registry/DynamicWorkflowPayloadValidatorTest.php` — payload shape (positive + negative)
- `tests/Feature/Registry/DynamicWorkflowExecutorAttachmentTest.php` — `role='executor'` for DW

### Modified
- `app/Models/RegistryItem.php` — add `'dynamic_workflow'` to `KINDS`
- `app/Http/Requests/StoreRegistryItemRequest.php` — add `'kind'` to the rules + accept the new value
- `app/Http/Requests/UpdateRegistryItemRequest.php` — same
- `app/Services/RegistryService.php` — wire `PayloadValidator` by kind in `createItem` + `updateItem`; extend executor role reservation (line 355-362) to allow `kind = 'dynamic_workflow'`
- `docs/proposals/dynamic-workflows.md` — fix §6.1 enum-extension claim (string column, CHECK constraint instead)

## Contract (locked, mirrors proposal §6.2 + §8.6)

```php
// DynamicWorkflowPayloadValidator validates:
$payload = [
    'entry'         => 'string, required, regex /^[A-Za-z_][A-Za-z0-9_]*$/',
    'inputs'        => 'array, required; JSON-Schema-shaped object with type=object',
    'outputs'       => 'array, required; JSON-Schema-shaped object with type=object',
    'capabilities'  => 'array, required, shape:',
    'capabilities.declared'   => 'array of non-empty strings (shape-only; NOT checked against the ProxyCapability allowlist in DW-1)',
    'capabilities.limits'     => 'array, shape:',
    'capabilities.limits.max_wallclock_ms'          => 'integer, required, ≥ 1',
    'capabilities.limits.max_memory_mb'             => 'integer, required, ≥ 1',
    'capabilities.limits.max_await_run_concurrent'  => 'integer, required, ≥ 1',
    'capabilities.limits.max_checkpoint_bytes'      => 'integer, required, ≥ 1',
    'capabilities.limits.proxy_allowlist'           => 'array of strings; [] = all declared',
    'script_sha256'  => 'string, required, size:64, hex regex',
    'script'         => 'string, required, max:262144 (256 KB)',
];
```

DW-1 is intentionally **shape-only**. The validator only checks
the declared shape — it does **not** enforce:

- the platform ceiling for each limit (per §8.6), and
- an allowlist for `capabilities.declared` tokens (per §8.6); DW-1
  accepts any array of non-empty strings.

Both the `min(declared, ceiling)` ceiling enforcement and the
`capabilities.declared` allowlist hard-gate live in **DW-3**,
alongside the `ScriptRuntime` interface and
`config/dynamic_workflow.php` (consistent with the proposal §15
rollout).

## Migration

```php
// up
DB::statement(<<<'SQL'
    ALTER TABLE registry_items
        ADD CONSTRAINT registry_items_kind_check
        CHECK (kind IN ('subagent', 'skill', 'module', 'dynamic_workflow'))
SQL);

// down
DB::statement('ALTER TABLE registry_items DROP CONSTRAINT registry_items_kind_check');
```

The constraint name is fixed (`registry_items_kind_check`) so
DW-4 can add new kinds without re-deriving it.

## Tests (hard-gate)

### `DynamicWorkflowKindDiscriminatorTest`

- `test_kind_constant_includes_dynamic_workflow` — `RegistryItem::KINDS` contains the value
- `test_create_item_accepts_dynamic_workflow_kind` — happy path, no payload validation yet at this level
- `test_create_item_rejects_unknown_kind` — covers the existing `validateKind` path, no regression
- `test_check_constraint_rejects_unknown_kind_at_db_level` — direct `DB::table('registry_items')->insert(['kind' => 'bogus', ...])` must throw a `QueryException`
- `test_check_constraint_accepts_all_known_kinds` — subagent, skill, module, dynamic_workflow all insert cleanly

### `DynamicWorkflowPayloadValidatorTest`

Happy path (one canonical payload) and a matrix of negative cases:

| Test | What it pins |
|---|---|
| `test_validator_accepts_canonical_payload` | full §6.2 shape passes |
| `test_validator_rejects_missing_entry` | `entry` required |
| `test_validator_rejects_malformed_entry` | entry must match `^[A-Za-z_][A-Za-z0-9_]*$` |
| `test_validator_rejects_oversized_script` | script > 256 KB rejected |
| `test_validator_rejects_missing_capabilities` | capabilities required |
| `test_validator_rejects_capabilities_limits_missing_field` | each limit field required |
| `test_validator_rejects_negative_limit` | limits must be ≥ 1 |
| `test_validator_rejects_non_object_inputs` | inputs must be an array (rejects a scalar) |
| `test_validator_rejects_inputs_without_object_type` | inputs must be a JSON-Schema object shape (type=object) |
| `test_validator_rejects_non_hex_script_sha256` | `script_sha256` must be 64-char hex |
| `test_validator_does_not_run_for_other_kinds` | validator is no-op for kind=subagent (regression guard) |
| `test_create_item_runs_validator_for_dynamic_workflow` | integration: `RegistryService::createItem` with kind=dynamic_workflow + bad payload throws `DynamicWorkflowPayloadInvalid` |
| `test_update_item_runs_validator_for_dynamic_workflow` | same, for `updateItem` |

> **DW-1 is shape-only.** There is deliberately **no**
> `capabilities.declared` allowlist case (e.g. an
> `unknown_capability_token` reject) — declared tokens are only
> shape-checked as non-empty strings; the allowlist hard-gate is
> deferred to DW-3. `outputs` is shape-checked by the same
> `type=object` rule as `inputs` (see
> `validateJsonSchemaShape`), but the negative matrix above pins
> that rule via the `inputs` cases rather than a separate
> `outputs` case.

### `DynamicWorkflowExecutorAttachmentTest`

- `test_attach_executor_allowed_for_dynamic_workflow_at_task_scope` — happy path
- `test_attach_executor_rejected_for_dynamic_workflow_at_hive_scope` — scope must be `task`
- `test_attach_executor_rejected_for_dynamic_workflow_at_agent_scope` — scope must be `task`
- `test_at_most_one_executor_per_task_with_dynamic_workflow` — two `role=executor` attachments (one DW, one subagent) on the same task → second throws
- `test_existing_subagent_executor_attachment_unchanged` — regression: subagent still works

## Definition of done

- Code meets the contract above
- All hard-gate tests pass (`php artisan test --filter=DynamicWorkflow`)
- PSR-12 compliant (`vendor/bin/pint --test`)
- No regression in `RegistryServiceTest` or `RegistryApiControllerTest`
- Proposal §6.1 enum-extension text replaced with the string-column + CHECK story
- PR opened, reviewed, merged
- TASKS.md row for TASK-300 flipped to ✅
