# Registry Cutover (b2): Stop Dual-Write

Status: Plan for sign-off
Owner: nelson-bighetti (claude-agent) on behalf of the registry track
Scope: Implementation plan for PR (b2) — the irreversible half of the
dual-write → registry cutover. Phases (b1) [#782, #783] made the
registry path independent of the legacy `sub_agent_definitions` table.
**(b2) flips the default and removes every rollback path so the registry
is the only source of truth.**

---

## 1. What (b2) does

1. **Remove every gated `else`-branch legacy read** — the env-rollback
   paths that read from `sub_agent_definitions` when the registry path
   is off. These are the routes that make
   `PLATFORM_REGISTRY_REGISTRY_PRIMARY=false` a safe rollback today.
2. **Strip every dual-write writer** — the code that mirrors writes
   from `RegistryItem` → `SubAgentDefinition` (and the reverse
   back-sync inside `registryPrimary*` writers). Because the back-sync
   is what currently leaves an active legacy row behind for every
   registry-primary write, removing it means the **public authoring
   contract must move off the `SubAgentDefinition` model** in the same
   PR — otherwise dashboard update / deactivate / rollback 404 for any
   sub-agent created post-(b2). See §5 "Public authoring contract."
3. **Flip the default** of `config('platform.registry.subagent_dual_write')`
   from `true` → `false`. The `subagent_dual_write` gate becomes a
   no-op (it controls code that no longer exists).

## 2. What (b2) does **not** do (belongs to (c))

- Drop the `SubAgentDefinition` model.
- Drop the `sub_agent_definitions` table (and the FK on it).
- Drop `tasks.sub_agent_definition_id` (and audit its remaining
  readers; we'll re-evaluate in (c) after a bake period).
- Remove the `PLATFORM_REGISTRY_REGISTRY_PRIMARY` env var (the
  registry-primary path itself stays; the var is unused once (c)
  drops the dual-write).
- Delete the `*RegistryPrimaryTest.php` files. The registry-primary
  (ON) cases in them survive (b2) and guard the back-pointer column,
  so they are kept and updated, not dropped. Only the
  *registry-primary-off* legacy-mode cases must go — they assert the
  legacy `sub_agent_definition_id` fallback that (b2) removes (§6/§8
  make the flag a no-op), so they are deleted or rewritten as
  registry-only assertions (see §7). (c) drops the whole files.

## 3. The irreversible part — what's given up

After (b2) merges and deploys, `sub_agent_definitions` stops being
written. `PLATFORM_REGISTRY_REGISTRY_PRIMARY=false` is **no longer a
safe rollback** — the legacy table would be stale. The registry is the
only source of truth from this point on.

This is why (b1) and (b2) are split: (b1) was reversible, (b2) is not.
Bake runs (see §10) before PR (c) drops the model + table.

## 4. Back-pointer strategy: option (a)

The two back-pointer readers — `SubAgentApiController::currentRevision`
(L359-363) and `SubAgentDashboardController::resolveCurrentRevisionId`
(L748-752) — currently resolve the *active* revision via
`sub_agent_definitions.is_active=true`. Their existing fallback is
"match by payload equality," which breaks when two revisions share a
payload (metadata-only updates, where payload is unchanged but a new
revision row exists).

We add a nullable `latest_revision_id` column to `registry_items` and
populate it with the revision the item *currently points at* on every
write. Readers switch from "latest active SubAgentDefinition → match
payload → newest" to "RegistryItem.latest_revision_id, period."

**Column type:** `registry_item_revisions.id` is a 26-char ULID string
(see `2026_06_01_100001_create_registry_item_revisions_table.php`,
`$table->string('id', 26)->primary()`), and the FK from a revision back
to its item is `item_id` (not `registry_item_id`). The pointer column
must therefore be a nullable `string(26)` with a string FK, declared
the same way the existing ULID FKs are in this codebase (a bare
`string(..., 26)` column plus a separate `foreign(...)` clause — see
`create_registry_item_revisions_table.php` L13/L20), **not**
`foreignId()` (which would emit an unsigned bigint).

### 4.1 Migration

```php
// database/migrations/2026_xx_xx_add_latest_revision_id_to_registry_items.php
Schema::table('registry_items', function (Blueprint $table) {
    $table->string('latest_revision_id', 26)
        ->nullable()
        ->after('payload');

    $table->foreign('latest_revision_id')
        ->references('id')
        ->on('registry_item_revisions')
        ->nullOnDelete();
});

// Backfill: derive the pointer from the revision the item currently
// points at, NOT the newest revision. A "newest revision per item"
// backfill is WRONG for already-rolled-back items: rollback repoints
// RegistryItem.payload at an OLDER target revision WITHOUT creating a
// new revision (see registryPrimaryRollback, §4.2), so the newest
// revision is not the live one. Resolve in the same order the readers
// do (SubAgentApiController::currentRevision): (1) the active legacy
// SubAgentDefinition's id, (2) a current-payload match, (3) newest
// revision only as a last-resort fallback.
DB::statement("
    UPDATE registry_items ri
    SET latest_revision_id = COALESCE(
        -- (1) active legacy definition id (the explicit live pointer)
        (
            SELECT sad.id FROM sub_agent_definitions sad
            WHERE sad.hive_id = ri.hive_id
              AND sad.slug = ri.slug
              AND sad.is_active = true
              AND EXISTS (
                  SELECT 1 FROM registry_item_revisions r
                  WHERE r.item_id = ri.id AND r.id = sad.id
              )
            LIMIT 1
        ),
        -- (2) revision whose payload matches the item's current payload
        (
            SELECT r.id FROM registry_item_revisions r
            WHERE r.item_id = ri.id
              AND r.payload = ri.payload
            ORDER BY r.version DESC
            LIMIT 1
        ),
        -- (3) fallback: newest revision (only when no match above)
        (
            SELECT r.id FROM registry_item_revisions r
            WHERE r.item_id = ri.id
            ORDER BY r.version DESC, r.id DESC
            LIMIT 1
        )
    )
");
```

### 4.2 Write-side update

The pointer must follow the revision each writer actually makes the
item point at — which is **not** the same as "whoever creates a
revision." Confirmed against the current code:

- `registryPrimaryCreate` — creates the first `RegistryItemRevision`
  (`RegistryItemRevision::forceCreate([...])` at ~L1263). Set
  `$registryItem->latest_revision_id = $newRevision->id` before save.
- `registryPrimaryUpdate` — **creates a new `RegistryItemRevision`**
  (`forceCreate` at L1380, version = max+1) and repoints
  `RegistryItem.payload` at it. Set
  `$registryItem->latest_revision_id = $newRevision->id` before save.
- `registryPrimaryRollback` — **does NOT create a revision**; it looks
  up the existing `$targetRevision` for `$targetVersion` and repoints
  `RegistryItem.payload = $targetRevision->payload` (L1438-1449). Set
  `$registryItem->latest_revision_id = $targetRevision->id` before
  save. (The API contract is that a rollback reports the rolled-back
  *target* version — see
  `SubAgentApiControllerTest::test_registry_backed_reflects_rollback_version`,
  which asserts version `1` after rolling back to v1, not the newest
  revision.)
- `registryPrimaryDeactivate` — does NOT create a revision and does
  NOT change which revision is current; it only flips
  `RegistryItem.is_active = false` (L1561-1563). Leave
  `latest_revision_id` **unchanged** — unless (b2) explicitly adopts
  null-on-deactivate semantics (i.e. `active_revision_id` rather than
  `latest_revision_id`; see open question 1 in §"Open questions"), in
  which case set it to `null`. Default: leave unchanged.

**Second write path — `RegistryService` (do not miss this).** The four
`registryPrimary*` methods above are **not** the only writers that
create `RegistryItemRevision` rows. There is a second, independent
subagent-revision write path that also creates revisions directly and
must populate `latest_revision_id`:

- `RegistryService::createItem()`
  (`app/Services/RegistryService.php:100-118`) — creates the
  `RegistryItem` and its first `RegistryItemRevision` directly. Set
  `$registryItem->latest_revision_id = $newRevision->id` before save.
- `RegistryService::updateItem()`
  (`app/Services/RegistryService.php:182-199`) — creates a new
  `RegistryItemRevision` **whenever the request includes a `payload`
  key** (`isset($data['payload'])`). There is **no payload-equality /
  no-op check**: a payload-present update always creates a revision and
  advances the pointer, even if the new payload is byte-identical to the
  current one. A metadata-only update (one that omits `payload`
  entirely) is the only path that does NOT create a revision. Set
  `$registryItem->latest_revision_id = $newRevision->id` **only on the
  payload-present branch that creates a new revision** — never on a
  metadata-only update, which must leave the pointer untouched.

Both are reachable for sub-agents via `RegistryApiController`
(`app/Http/Controllers/Api/RegistryApiController.php`): `store()` (L85)
delegates to `createItem()` and `update()` (L176) delegates to
`updateItem()`. The controller validates `kind` against
`RegistryItem::KINDS = ['subagent','skill','module']`, so `kind=subagent`
requests flow straight through these methods. A registry-only sub-agent
created or payload-updated this way must have its `latest_revision_id`
set, or the §4.3 readers (task producers, workflow snapshots) would
resolve a **null** pointer after (b2) and fail to bind the revision.
There is no model boot/`saving` hook that auto-populates the pointer, so
every revision-creating writer — the four `registryPrimary*` methods and
both `RegistryService` methods — must set it explicitly.

### 4.3 Reader updates

Two classes of reader resolve "which revision is current" today and
must switch to the back-pointer. The first reads the *active legacy
`SubAgentDefinition`*; the second resolves a slug via
`RegistryItem::latestRevision` (highest `version`). **Both are wrong
after a rollback** — rollback repoints `RegistryItem.payload` at an
older revision *without creating a new revision* (see
`registryPrimaryRollback`, §4.2), so the active legacy row is stale and
`latestRevision` still points at the highest version, not the live one.
After (b2) stops writing active `SubAgentDefinition` rows, a
rolled-back sub-agent is effectively registry-only for the slug-resolving
paths, so `latestRevision` pins v2 even when `registryPrimaryRollback`
repointed the item to v1.

**Active-legacy readers** (switch to the column directly):
- `SubAgentApiController::currentRevision` (L359-363) →
  `$item->latest_revision_id`.
- `SubAgentDashboardController::resolveCurrentRevisionId` (L748-752) →
  `$item->latest_revision_id`.

**Slug-resolving readers** that bind a task/snapshot to the "current
revision" via `RegistryItem::latestRevision` (highest `version`).
`RegistryItem::latestRevision` is
`hasOne(RegistryItemRevision, 'item_id')->orderByDesc('version')`
(`app/Models/RegistryItem.php:63-67`) — it returns the highest-version
revision, which is **not** the live revision for a rolled-back item.
These must resolve via the back-pointer instead (read
`$item->latest_revision_id`, or change the `latestRevision` relation /
add a `currentRevision` relation that joins on
`registry_items.latest_revision_id`):
- `DualWritesTaskExecutorAttachment::resolveSlugViaRegistry()`
  (`app/Traits/DualWritesTaskExecutorAttachment.php:112`,
  `$revision = $item->latestRevision;`) — single-slug task producer.
- `DualWritesTaskExecutorAttachment::batchResolveSubAgentSlugsViaRegistry()`
  (`app/Traits/DualWritesTaskExecutorAttachment.php:142,150-151`,
  `->with('latestRevision')` then `$item->latestRevision`) — batch
  task producer (fan-out).
- `Workflow::snapshotVersion()` registry-only slug binding
  (`app/Models/Workflow.php:324,328`, `->with('latestRevision')` then
  `$item->latestRevision?->id`) — pins the snapshot's
  `sub_agent_revision_id` for registry-only slugs. After (b2),
  rolled-back slugs are registry-only here, so this must bind the
  back-pointer revision, not the highest version. (The trait rename to
  `TaskExecutorAttachment` in §5 carries the first two methods; the
  reader fix applies under the new name.)

The 1:1 mirror of `payload` in `SubAgentDefinition` is no longer
the source of truth; we only read the active row's id for
back-pointer, and now we read the id directly from the column.

## 5. Per-file changes

### `app/Services/SubAgentDefinitionService.php` (1598 → ~700 lines)

**Remove:**
- L442-445 `isDualWriteEnabled()` config gate
- L487-624 `dualWriteCreate()`
- L655-803 `backfillRegistryItem()` (137 lines, only used by
  `dualWrite*` paths — verify no other callers before deleting)
- L827-864 `assertRegistryHistoryFaithful()`
- L892-929 `assertRegistryPrimaryHistoryFaithful()` (registry-primary
  validator that asserts legacy mirror is faithful; obsolete)
- L934-989 `dualWriteUpdate()`
- L997-1042 `dualWriteRollback()`
- L1053-1080 `dualWriteDeactivate()`
- The four `dualWrite*` calls inside `create/update/rollback/deactivate`
  (L98-100, L207-209, L292-294, L378-380)
- The back-sync blocks inside `registryPrimaryCreate/Update/Rollback/Deactivate`
  (L1245-1259, L1357-1377, L1458-1486 + L1494-1509 forceCreate, L1566-1570)
- The `isRegistryPrimary()` config gate at L455-458 (or keep as a
  no-op marker for one release — see §6)

**Keep and update:**
- The four `registryPrimary*` methods, with the back-sync blocks
  removed. They become the sole writers *within this service* (note:
  `RegistryService::createItem/updateItem` is a separate
  revision-writing path outside this service — see §4.2 and the
  `RegistryService.php` entry below; both paths must set
  `latest_revision_id`).

**Net:** ~640 lines of dual-write code removed; service becomes
straightforward "create/update/rollback/deactivate" against the
registry.

**Public authoring contract — migrate the write paths off the legacy
model (do not miss this).** Removing the back-sync (the `registryPrimary*`
blocks above, and §1.2) means a sub-agent created after (b2) has **no
active legacy `SubAgentDefinition` row**. But the service's public write
API still speaks `SubAgentDefinition`:
- `SubAgentDefinitionService::create()` (L26), `update()` (L121),
  `rollback()` (L231) and `deactivate()` (L316) all **accept and/or
  return** a `SubAgentDefinition` model.
- The dashboard write paths find a legacy model *before* calling the
  service: `SubAgentDashboardController::update()` resolves
  `findActiveDefinitionModel()` (L181), `destroy()` the same (L218), and
  `rollback()` resolves `findAnyDefinitionModel()` (L271). Both helpers
  ultimately `return SubAgentDefinition::...->first()` (L639-643,
  L678-681) — i.e. they hand the service a legacy row.

After the back-sync is gone, a registry-only sub-agent has no such row, so
`findActiveDefinitionModel()`/`findAnyDefinitionModel()` return `null` and
the controller short-circuits to "Sub-agent definition not found"
(L183-185, L220-222, L273-275) — update / deactivate / rollback become
unreachable for any sub-agent created post-(b2). **(b2) must make these
write paths registry-native:**
- Change the service's `update`/`rollback`/`deactivate` to **resolve their
  subject by `RegistryItem` (slug) / revision** rather than requiring a
  `SubAgentDefinition` instance, and return a canonical record / registry
  revision instead of a legacy model. `create()` likewise returns a
  canonical record. (Signatures change; update all call sites.)
- Rework `findActiveDefinitionModel()` / `findAnyDefinitionModel()` to
  resolve the `RegistryItem` (and, for rollback, its revision history)
  directly — they already gate on `RegistryItem` existence under
  registry-primary (L610-618, L654-661); the legacy `->first()` tail
  (L639-643, L678-681) is what must go.
- **Alternative (smaller blast radius):** keep a single compatibility
  legacy *write* (an active-row mirror used solely as the service's write
  handle) until the above call sites are migrated, and schedule its
  removal in (c). This contradicts the "stop writing legacy rows" goal, so
  it is the fallback, not the default — but it must be a conscious choice,
  not an oversight. Pick one explicitly at sign-off.

### `app/Traits/DualWritesTaskExecutorAttachment.php`

**Remove:**
- The `dualWriteTaskExecutorAttachment` method (L39-74)
- The `isTaskProducerRegistryPrimary` gate (L76-79)
- The `if(config('platform.registry.subagent_dual_write', false))`
  branch in any callers (the trait's own gate is redundant with the
  callers' gates — remove both layers)

**Keep:**
- `resolveSlugViaRegistry()` / `batchResolveSubAgentSlugsViaRegistry()`
- `actorMayAccessRegistryItem()`
- `createTaskExecutorAttachment()`

**Update:** `resolveSlugViaRegistry()` (L112) and
`batchResolveSubAgentSlugsViaRegistry()` (L150-151) currently bind the
task attachment to `$item->latestRevision` (highest `version`). Switch
both to resolve via `registry_items.latest_revision_id` per §4.3 so a
rolled-back slug binds the live revision, not v2.

**Rename** the trait from `DualWritesTaskExecutorAttachment` to
`TaskExecutorAttachment` to reflect the new shape.

**Caller updates** (5 sites, all currently 3-way conditionals):
- `app/Http/Controllers/Api/TaskController.php:1449, 1507, 1656`
- `app/Http/Controllers/Dashboard/TaskDashboardController.php:647`
- `app/Services/WebhookRouteEvaluator.php:290`
- `app/Services/FanOutService.php:228`

Each caller becomes a single call to the registry-only
`createTaskExecutorAttachment()` (no gating).

### `app/Services/TaskReplayService.php`

**Remove:**
- `dualWriteReplayAttachment()` (L362-602, ~240 lines)
- The `if(config('platform.registry.subagent_dual_write', false))`
  call at L367
- The legacy `sub_agent_definition_id` preservation in `replay()`
  (L179-181) — readers will get the new column or `null`

**Keep:** the registry-only replay path.

### `app/Models/Workflow.php`

**Update:** `snapshotVersion()` (L324, L328) resolves registry-only
slugs via `->with('latestRevision')` → `$item->latestRevision?->id`
to set each step's pinned `sub_agent_revision_id`. Switch to the
back-pointer (`registry_items.latest_revision_id`) per §4.3 — after
(b2) a rolled-back slug is registry-only here and `latestRevision`
would pin the highest version instead of the live (rolled-back)
revision.

### `app/Services/WorkflowExecutionService.php`

**Remove:**
- The inline dual-write block at L1836-1878 (creates
  `RegistryAttachment` directly; redundant once the trait
  `createTaskExecutorAttachment` is the only writer)
- The gated `else` in `createStepTask` (L1797-1821, reads
  `SubAgentDefinition::where('id', $pinnedId)`)
- The 3-way conditional caller of `dualWriteTaskExecutorAttachment`
  at L1872 (becomes a direct call)

**Keep:** the registry-only path.

### `app/Http/Controllers/Api/SubAgentApiController.php`

**Remove:** gated `else` branches in:
- `listSubAgents()` (L189-204)
- `findSubAgentBySlug()` (L214-233)
- `findSubAgentById()` (L249-276)

**Update:** `currentRevision()` (L359-363) → read
`$item->latest_revision_id` instead of resolving via
`sub_agent_definitions.is_active`.

**Update:** `isRegistryPrimary()` gate at L171-174 (or keep as a
no-op marker per §6).

### `app/Http/Controllers/Dashboard/SubAgentDashboardController.php`

**Remove:** gated `else` branches in:
- `listDefinitionRecords()` (L478-511)
- `findDefinitionRecordForDisplay()` (L520-557)
- `listVersionRecords()` (L565-595)
- `findActiveDefinitionModel()` (L610-644) — registry check +
  legacy-active fallback
- `findAnyDefinitionModel()` (L654-682) — registry check +
  legacy-exists fallback

**Make the write paths registry-native (see the "Public authoring
contract" note under `SubAgentDefinitionService` above).** The read paths
above can simply drop their legacy `else`, but the **write** paths
(`update()` L172-204, `destroy()` L209-229, `rollback()` L258-286) feed a
`SubAgentDefinition` model into the service via `findActiveDefinitionModel`
/ `findAnyDefinitionModel`. After the back-sync is removed there is no
legacy row for a registry-only sub-agent, so these helpers' legacy
`->first()` tail (L639-643, L678-681) returns `null` and the controller
404s / cannot call the service. Rework the helpers to resolve and return
the `RegistryItem` (and revision history, for rollback) directly, and have
`update`/`destroy`/`rollback` call the registry-native service API. If the
compatibility-write fallback (above) is chosen instead, document that the
helpers keep returning the mirrored active legacy row until (c).

**Update:** `recordsForItem()` (L711-715) and
`resolveCurrentRevisionId()` (L748-752) → use
`registry_items.latest_revision_id`.

**Update:** the `isRegistryPrimary()` gate at L465-468 per §6.

### `app/Http/Controllers/Api/TaskController.php`

**Remove:** gated `else` branches in:
- `storeFanOut()` (L1338-1369)
- `store()` (L1578-1609)

**Update:** 3 callers of `dualWriteTaskExecutorAttachment` (L1449,
L1507, L1656) → direct call to `createTaskExecutorAttachment`.

### `app/Http/Controllers/Dashboard/TaskDashboardController.php`

**Remove:** gated `else` in `store()` (L437-473).

**Update:** caller of `dualWriteTaskExecutorAttachment` at L647.

### `app/Services/WebhookRouteEvaluator.php`

**Remove:** gated `else` in `evaluateRoute()` (L198-223).

**Update:** caller of `dualWriteTaskExecutorAttachment` at L290.

### `app/Services/FanOutService.php`

**Remove:**
- Gated `else` branches in `createWithChildren()` (L109-120,
  L166-210)
- `resolveSubAgentSlugs()` helper (L267-285) — only used by the
  `else` branch
- The `if(isTaskProducerRegistryPrimary)` check in caller at L228

### `app/Services/RegistryService.php`

**Update:** this is the second subagent-revision write path (§4.2).
- `createItem()` (L100-118) — set
  `$registryItem->latest_revision_id = $newRevision->id` on the new
  `RegistryItemRevision` it creates, before saving the item.
- `updateItem()` (L182-199) — set
  `$registryItem->latest_revision_id = $newRevision->id` **only on the
  payload-present branch that creates a new revision**
  (`isset($data['payload'])`). The metadata-only path (request omits
  `payload`, so no revision is created) must leave `latest_revision_id`
  untouched — no phantom advance. Note there is no payload-equality
  check: any payload-present update creates a revision and advances the
  pointer, even for a byte-identical payload.

### `app/Http/Controllers/Api/RegistryApiController.php`

**No change.** `store()` (L85) and `update()` (L176) only delegate to
`RegistryService::createItem()` / `updateItem()`; the pointer is set in
the service, so the controller needs no edit. Listed here explicitly to
avoid ambiguity — it is reachable for `kind=subagent` (it validates
against `RegistryItem::KINDS`) but is not itself a writer of the column.

### `app/Models/RegistryItem.php`

**Update:** add `latest_revision_id` to `$fillable` (and to `$casts`
only if a cast is warranted — it is a plain `string(26)` ULID FK, so no
cast is required) so the writers in §4.2 can assign it. Optionally add a
`currentRevision()` relation that joins on
`registry_items.latest_revision_id` if §4.3 readers prefer a relation
over reading the raw column.

### `app/Services/Marketplace/WorkflowDependencyResolver.php`

**Remove:** gated `else` branches in:
- `activeSlugsInScope()` (L144-176)
- `presentPersonas()` (L201-249)
- `availablePersonas()` (L266-307)
- The `registryPrimary()` gate at L353-356

### `app/Services/Marketplace/MarketplaceBundleInstaller.php`

**Replace:** the ungated `SubAgentDefinition` dup-check at L177-181
with a registry-backed check. The comment at L287 already flags this
as a write-path dependency that becomes a hard legacy-table
dependency once dual-write flips off. Use the registry's
"exists in this scope?" query.

### `app/Cloud/Services/HiveTemplateEligibility.php`

**Remove:** the legacy `else` branch in `countSubAgents()` (L187-191).

### `config/platform.php`

**Flip:** line 905
```php
'subagent_dual_write' => (bool) env('PLATFORM_REGISTRY_SUBAGENT_DUAL_WRITE', true),
```
→
```php
'subagent_dual_write' => (bool) env('PLATFORM_REGISTRY_SUBAGENT_DUAL_WRITE', false),
```

**Keep reading the env var** so old `.env` files don't crash on
`env()`. The var is unused (gate is gone) but reading it is
harmless and avoids a one-line migration surprise.

## 6. `isRegistryPrimary()` — to keep or to delete

The `isRegistryPrimary()` config gate is still consulted in a few
places (SubAgentApiController:171, SubAgentDashboardController:465).
After (b2), the gate has no `else` branches left to control. Two
options:

**(a) Keep as a no-op marker** for one release, deleted in (c). Lets
us roll out (b2) and have a kill switch that doesn't do anything yet.

**(b) Delete now.** Cleaner, but loses the kill switch.

**Recommendation: (a)** — keep for one release. The flag itself is
cheap; the roll-back safety it implies is now fictional, but a comment
on the config call site ("no longer gates anything post-b2; deleted
in (c)") is enough.

## 7. Test strategy

**Delete entire files** (54 tests, ~4000 lines):
- `tests/Feature/TaskProducerDualWriteTest.php` (28 tests) — full file
- `tests/Feature/TaskReplayDualWriteTest.php` (26 tests) — full file

**Do NOT delete `SubAgentDualWriteTest.php` wholesale.** Despite the
`DualWrite` name, the file is not purely dual-write: from
`tests/Feature/SubAgentDualWriteTest.php:1557` onward it contains a full
block of **registry-primary** create / update / rollback / deactivate
coverage that survives (b2) and must be preserved. The dual-write-only
tests at the top of the file (the `test_*_dual_write_*` cases and the
legacy/back-sync flag-gated cases) are deleted; the registry-primary
tests are **moved**, not deleted. Before removing the dual-write
portion, **move** the registry-primary cases into a new
`tests/Feature/SubAgentRegistryPrimaryTest.php` (named to match the
existing `WorkflowStepRegistryPrimaryTest.php` /
`TaskProducerRegistryPrimaryTest.php` /
`TaskReplayRegistryPrimaryTest.php` convention). Tests to move
(registry-primary, all from L1557 onward):
- `test_registry_primary_create_writes_registry_item_and_revision`
- `test_registry_primary_create_back_syncs_legacy_row`
- `test_registry_primary_create_revision_payload_matches_item_payload`
- `test_registry_primary_create_uses_shared_id_between_legacy_and_revision`
- `test_registry_primary_create_rejects_duplicate_active_slug`
- `test_registry_primary_update_creates_new_revision`
- `test_registry_primary_update_back_syncs_legacy_row`
- `test_registry_primary_update_version_is_monotonic`
- `test_registry_primary_update_shares_id_between_revision_and_legacy`
- `test_registry_primary_rollback_repoints_item_payload`
- `test_registry_primary_rollback_does_not_create_new_revision`
- `test_registry_primary_rollback_back_syncs_legacy`
- `test_registry_primary_rollback_fails_for_nonexistent_version`
- `test_registry_primary_deactivate_sets_registry_item_inactive`
- `test_registry_primary_deactivate_back_syncs_legacy`
- `test_registry_primary_deactivate_preserves_revisions`
- `test_registry_primary_deactivate_returns_false_when_already_inactive`
- `test_registry_primary_create_rejects_active_legacy_only_slug`
- `test_registry_primary_rollback_synthesized_legacy_row_has_revision_id`
- `test_registry_primary_rollback_backfills_registry_when_legacy_only_definition_exists`
- `test_registry_primary_deactivate_backfills_registry_when_legacy_only_definition_exists`
- `test_registry_primary_full_lifecycle`
- `test_registry_primary_config_defaults_to_true`
- `test_registry_primary_can_be_disabled_via_rollback_override`
- `test_registry_primary_create_after_legacy_deactivate_backfills_full_history`
- `test_update_registry_primary_fails_when_existing_registry_item_was_authored_via_registry_service`
- `test_rollback_registry_primary_fails_when_existing_registry_item_was_authored_via_registry_service`
- `test_deactivate_registry_primary_fails_when_existing_registry_item_was_authored_via_registry_service`
- `test_create_registry_primary_fails_when_existing_registry_item_was_authored_via_registry_service`

When moving, **adapt the back-sync-specific assertions**: cases such as
`test_registry_primary_*_back_syncs_legacy*` and the
`backfills_registry_when_legacy_only_definition_exists` cases assert on
the legacy `sub_agent_definitions` mirror. Keep the registry-primary
behavioral assertions (revision creation, `latest_revision_id` advance,
version monotonicity, rollback no-new-revision, deactivate
preserves-revisions) and rework or drop the assertions that only exist
to verify the now-removed dual-write back-sync mirror, so the moved
tests reflect the registry-primary-only world after (b2). Move the
supporting private helpers these tests depend on as well. Once the
registry-primary block is moved, the remaining dual-write-only tests in
`SubAgentDualWriteTest.php` are deleted with the file.

**Do NOT delete `WorkflowSnapshotDualWriteTest.php` wholesale.** Despite
the `DualWrite` name, it contains registry-only coverage that is still
valid — and load-bearing — after (b2), because it exercises the
registry-primary snapshot path that survives dual-write removal. Before
deleting the dual-write-specific tests, **move** the registry-only tests
into a new `tests/Feature/WorkflowSnapshotRegistryPrimaryTest.php`
(named to match the existing `WorkflowStepRegistryPrimaryTest.php` /
`TaskProducerRegistryPrimaryTest.php` /
`TaskReplayRegistryPrimaryTest.php` convention). Tests to move:
- `test_snapshot_registry_only_slug_binds_current_revision`
- `test_snapshot_registry_only_evaluator_slug_binds_current_revision`
- `test_snapshot_registry_only_binds_revision_even_when_dual_write_off`
  (rename to drop the now-meaningless `_even_when_dual_write_off`
  suffix, since dual-write no longer exists)
- `test_snapshot_does_not_bind_another_agents_private_registry_only_slug`
- `test_snapshot_binds_own_private_registry_only_slug`
- `test_snapshot_does_not_bind_private_registry_slug_for_dashboard_workflow`
- `test_step_task_registry_only_creates_attachment_registry_primary`

Move the supporting private helpers they depend on as well
(`createRegistryOnlySubAgent`, `createPrivateRegistryOnlySubAgent`,
and any shared setup). Once those are moved, the remaining
dual-write-only tests in `WorkflowSnapshotDualWriteTest.php` are deleted
with the file.

**Update in place:**
- `tests/Feature/SubAgentDualWriteTest.php:91
  test_dual_write_enabled_by_default` — part of the dual-write portion
  that is deleted once the registry-primary block is moved out (see the
  "move, don't delete wholesale" note above); removed with the rest of
  the dual-write-only cases.
- `tests/Feature/WorkflowStepRegistryPrimaryTest.php:262
  test_registry_primary_old_snapshot_does_not_read_legacy_mirror` —
  this test should still pass after (b2). Verify it does.
- `tests/Feature/WorkflowStepRegistryPrimaryTest.php:324
  test_registry_primary_off_preserves_current_behaviour` — once
  registry_primary is a no-op, the test's premise is gone. Replace
  with `test_registry_primary_no_op_after_b2`.

**Delete or rewrite the registry-primary-off cases.**
`WorkflowStepRegistryPrimaryTest.php:324` is **not** the only test
that disables `PLATFORM_REGISTRY_REGISTRY_PRIMARY` and asserts the
legacy `sub_agent_definition_id` fallback. §6/§8 make the flag a
no-op (registry is always primary), so every registry-primary-off
case that asserts the legacy path either fails the suite after (b2)
or forces the implementation to keep stale `sub_agent_definition_id`
/ legacy-fallback behaviour just to satisfy an obsolete test. Each
must be **deleted, or rewritten as a no-op / registry-only
assertion** — i.e. assert the registry-primary behaviour
unconditionally (revision-backed attachment, no legacy id), never the
legacy fallback. The `*RegistryPrimaryTest.php` cases (verified against
the current head):
- `tests/Feature/TaskProducerRegistryPrimaryTest.php:449
  test_api_task_create_legacy_mode_uses_sub_agent_definition` —
  `disableRegistryPrimary()` then asserts `sub_agent_definition_id`
  is set. Delete, or rewrite to assert registry-primary behaviour
  (null legacy id + executor attachment).
- `tests/Feature/TaskProducerRegistryPrimaryTest.php:757
  test_dashboard_task_create_legacy_mode_uses_sub_agent_definition` —
  dashboard equivalent of the above; same treatment.
- `tests/Feature/TaskProducerRegistryPrimaryTest.php:908
  test_legacy_mode_api_task_with_dual_write_still_works` —
  `disableRegistryPrimary()` + `enableDualWrite()`, asserts legacy id
  + dual-write attachment. Delete (dual-write is gone after (b2)).
- `tests/Feature/TaskProducerRegistryPrimaryTest.php:944
  test_legacy_mode_fanout_with_dual_write_still_works` — fan-out
  variant of the above; delete with it.
- `tests/Feature/TaskReplayRegistryPrimaryTest.php:242
  test_registry_primary_off_preserves_current_behaviour` —
  `disableRegistryPrimary()` + `enableDualWrite()`, asserts the
  replayed child copies `sub_agent_definition_id`. Delete, or rewrite
  as the registry-only replay assertion (null legacy id, single
  executor attachment).
- `tests/Feature/TaskReplayRegistryPrimaryTest.php:348
  test_registry_primary_off_with_dual_write_off_copies_legacy_id_only`
  — `disableRegistryPrimary()` + dual-write off, asserts the legacy id
  is copied and no attachment is created (pre-dual-write era). Delete:
  that era no longer exists after (b2).

**Registry-primary-off cases also live OUTSIDE `*RegistryPrimaryTest.php`
(do not miss these).** The list above is not exhaustive: other suites set
`platform.registry.registry_primary=false` and assert the legacy
`sub_agent_definition_id` binding / legacy rollback-flag behaviour. They
fail (or force (b2) to keep the obsolete legacy path) for the same reason
and need the same treatment — delete or rewrite as registry-only
assertions. The cases (verified against the current head):
- `tests/Feature/FanOutSubAgentTest.php` — the **whole class** forces the
  flag off in `setUp()` (L36), and many cases assert
  `sub_agent_definition_id` is populated from legacy rows, e.g.
  `test_fanout_children_get_correct_sub_agent_binding` (L126, asserts at
  L174-178), `test_fanout_resolves_slug_to_active_definition` (L230,
  asserts at L279), and `test_fanout_parent_sub_agent_slug_is_propagated`
  (L706, asserts at L732/L737). The `assertNull(...sub_agent_definition_id)`
  cases (invalid/cross-hive/deactivated slug, L319/L385/L432) are also
  legacy-binding assertions. After (b2), fan-out binds the registry
  executor attachment, not `sub_agent_definition_id`. Rewrite the class to
  drop the `registry_primary=false` `setUp()` and assert the registry
  attachment / revision binding (no legacy id), or split the legacy-binding
  cases out and delete them.
- `tests/Unit/Cloud/HiveTemplateEligibilityTest.php:604
  test_rollback_flag_still_counts_legacy_only_subagent` — sets
  `registry_primary=false` (L612) and asserts a legacy-only sub-agent
  still makes the hive non-empty ("1 sub agent definitions", L627-628).
  This is the env-rollback counterpart of
  `test_registry_primary_ignores_legacy_only_subagent` (L573). §5 removes
  the legacy `else` in `HiveTemplateEligibility::countSubAgents()`, so the
  rollback-flag path no longer counts legacy-only rows. Delete this case
  (or rewrite to assert the registry-only count behaviour
  unconditionally).
- `tests/Feature/TaskSubAgentBindingTest.php` — the **whole class** forces
  the flag off in `setUp()` (`config()->set('platform.registry.registry_primary',
  false)`, L33), and the cases assert task/fan-out binding via the legacy
  `sub_agent_definition_id` column, e.g. the single-binding case asserting
  `$child->sub_agent_definition_id` (L638) and the fan-out case asserting
  per-child legacy ids (L718/L721). After (b2) the flag is a no-op and
  binding flows through the registry executor attachment, not
  `sub_agent_definition_id`. Rewrite the class to drop the
  `registry_primary=false` `setUp()` and assert the registry attachment /
  revision binding (no legacy id), or split the legacy-binding cases out and
  delete them — same treatment as `FanOutSubAgentTest` above.
- `tests/Feature/TaskReplayApiTest.php` — the **whole class** forces the flag
  off in `setUp()` (L46). `replay_carries_over_sub_agent_definition_id` (L2662)
  replays a completed task carrying `sub_agent_definition_id` and asserts the
  replayed task copies the legacy id (`assertSame($definition->id,
  $replayTask->sub_agent_definition_id)`, L2691). This **directly contradicts
  §5's `TaskReplayService::replay()` change**, which removes the legacy
  `sub_agent_definition_id` preservation (L179-181) so replayed tasks get the
  new column or `null`. Delete this case, or rewrite as the registry-only
  replay assertion (replayed task carries the registry executor
  attachment / revision, no legacy id). Reconcile the class-level
  `registry_primary=false` `setUp()` with the rest of the suite at the same
  time (drop it, or scope it to the cases that genuinely still need it).

**Registry-primary-ON cases that assert a retained compatibility fallback —
KEEP these (do NOT delete), and (b2) must preserve the fallback they cover.**
Not every legacy-id assertion is obsolete: several registry-primary-**ON**
cases assert a legacy fallback that lives *inside* the `registryPrimary()`
branch (not the removed `else`), and (b2) must keep that fallback or these
break and real behaviour regresses. (verified against the current head):
- `tests/Feature/TaskProducerRegistryPrimaryTest.php:1100
  test_dashboard_unpinned_capability_task_uses_legacy_binding`, `:1143
  test_dashboard_open_task_uses_legacy_binding`, and `:1185
  test_dashboard_unpinned_registry_primary_poll_and_claim_return_sub_agent` —
  all call `enableRegistryPrimary()` and assert an **unpinned** task (no
  `target_agent_id`) falls back to the legacy `sub_agent_definition_id`
  (asserts at L1127, L1170, and within the third case). This is the
  **unpinned fallback** at `TaskDashboardController::store()` L446-463 (and the
  API equivalent in `TaskController::store()`): with no `target_agent_id` the
  task-scoped executor attachment cannot be created (`pinned_by` is required;
  the dual-write trait skips when null), so the producer writes
  `sub_agent_definition_id` so workers still see the prompt/config/allowed_tools
  at claim time. §5's "Remove gated `else` in `store()`" targets the
  registry-primary-**off** `else` (L464-473), NOT this unpinned fallback inside
  the registry-primary path. **(b2) must keep the unpinned fallback** — do not
  drop it, and keep these tests (they guard it).
- `tests/Feature/Dashboard/MarketplaceWorkflowControllerTest.php:1860
  test_preflight_registry_primary_falls_back_to_legacy_only_subagent` (asserts
  at L1889) and `:1936
  test_bundle_install_registry_primary_keeps_legacy_only_slug_via_fallback`
  (asserts at L1976) — both set `registry_primary=true` and assert that a
  **pre-dual-write legacy-only** sub-agent (legacy row, no registry mirror) is
  still surfaced in marketplace preflight `present` / kept by the bundle-install
  strip. This is the **legacy union-fallback inside the registry-primary
  branch** of `WorkflowDependencyResolver` (`activeSlugsInScope()` L150-168,
  `presentPersonas()` / `availablePersonas()` similarly) — the `$remaining`
  legacy-slug merge, NOT the registry-primary-off `else` (L171-176). §5's
  "Remove gated `else` branches" must be read narrowly here: it removes the
  flag-off `else`, but **(b2) must keep the in-branch legacy union-fallback** for
  pre-dual-write rows, or these legacy-only sub-agents vanish from the
  marketplace preflight/install. Keep these two tests; they guard that
  fallback. (If (b2) deliberately drops the pre-dual-write union-fallback,
  delete these and document the dropped fallback in §5's
  `WorkflowDependencyResolver` entry instead.)
- `tests/Feature/SubAgentDashboardControllerTest.php:840
  test_index_registry_primary_lists_legacy_only_definition`, `:877
  test_show_registry_primary_returns_legacy_only_definition`, and `:916
  test_versions_registry_primary_returns_legacy_only_history` — these set
  `registry_primary=true` (via `enableRegistryPrimary()`) but assert the
  dashboard **read** paths still surface a legacy-only definition with no
  registry mirror. Unlike the two fallbacks above, §5's
  `SubAgentDashboardController` entry **removes** the gated `else` legacy
  fallbacks in `listDefinitionRecords()` (L478-511),
  `findDefinitionRecordForDisplay()` (L520-557), and `listVersionRecords()`
  (L565-595) — so after (b2) these read paths no longer fall back to legacy-only
  rows. Delete these three cases, or rewrite them to seed a registry-backed
  definition and assert the registry-only read behaviour (no legacy-only
  fallback).

**Keep load-bearing back-pointer tests** (will pass after the
`latest_revision_id` migration):
- `tests/Feature/SubAgentApiControllerTest.php:1122
  test_registry_backed_reflects_rollback_version`
- `tests/Feature/SubAgentApiControllerTest.php:1151
  test_registry_backed_reflects_rollback_when_revisions_share_payload`
  — this is the test that specifically validates option (a). Must
  still pass.

**Add new test:**
- `tests/Feature/RegistryItemLatestRevisionTest.php` — covers the
  new column via the four `registryPrimary*` writers: write creates new
  revision → `latest_revision_id` updates; rollback →
  `latest_revision_id` reverts; deactivation doesn't change
  `latest_revision_id`.
- **Same file — also cover the second write path (`RegistryService`,
  §4.2).** Keep these alongside (not replacing) the `registryPrimary*`
  pointer cases above:
  - Creating a `kind=subagent` item via `RegistryService::createItem()`
    (or a `POST` through `RegistryApiController::store`) sets
    `latest_revision_id` to the first revision's id.
  - A payload-present `RegistryService::updateItem()` (request includes a
    `payload` key, via `PUT`/`PATCH` through
    `RegistryApiController::update`) creates a new revision and advances
    `latest_revision_id` to it — on **any** payload-present revision,
    including one whose payload is byte-identical to the current one
    (there is no payload-equality no-op in the code).
  - A **metadata-only** `updateItem()` (request omits `payload`
    entirely) does NOT create a revision and does NOT advance
    `latest_revision_id` — the pointer stays on the prior revision.

**Add rollback-binding coverage for the slug-resolving readers (§4.3).**
The back-pointer is only correct if the *task-producing* and
*workflow-snapshot* paths bind it rather than `latestRevision`
(highest version). Without these, a rolled-back sub-agent (item
repointed v2 → v1, no new revision created) would still bind v2.
Add cases that create a sub-agent at v2, roll it back to v1 via
`registryPrimaryRollback()`, and assert the bound revision is v1
(the `latest_revision_id` target), not v2:
- **Task creation (single slug)** — in
  `tests/Feature/TaskProducerRegistryPrimaryTest.php`: a task
  targeting a rolled-back registry-only slug attaches the v1 revision
  (`resolveSlugViaRegistry()` binds `registry_items.latest_revision_id`).
- **Task creation (fan-out / batch)** — same file: a fan-out across
  multiple slugs, one of them rolled back, binds the rolled-back
  slug's v1 revision via `batchResolveSubAgentSlugsViaRegistry()`.
- **Workflow snapshot** — in the new
  `WorkflowSnapshotRegistryPrimaryTest.php` (see above): snapshotting
  a workflow that references a rolled-back registry-only slug pins the
  step's `sub_agent_revision_id` to v1, not the highest-version v2
  (`Workflow::snapshotVersion()` binds the back-pointer).

These three assert the property the reviewer flagged: after
`registryPrimaryRollback()`, task creation and workflow snapshotting
resolve `registry_items.latest_revision_id` (v1), not the
highest-version `latestRevision` (v2). The test code itself ships in
the (b2) implementation PR — this doc is the sign-off artifact and
carries no PHP per its stated "no code" scope (§"What (b2) does").

**Add registry-native authoring-lifecycle coverage (Public authoring
contract, §5).** Once the back-sync is removed, a freshly-created
sub-agent has no active legacy `SubAgentDefinition` row, so the dashboard
write paths (`update`/`destroy`/`rollback`) must still work against the
registry alone. The existing dual-write/registry-primary suites all
**seed** their subjects (or rely on the back-sync producing a legacy row),
so none exercise "author via the create path, then mutate" with the
back-sync gone. Add cases — in
`tests/Feature/SubAgentDashboardControllerTest.php` (the dashboard
write-path suite) and/or the new `SubAgentRegistryPrimaryTest.php` — that
run **after** legacy back-sync removal:
- **create → update**: create a sub-agent via the service/dashboard create
  path (no legacy row written), then update it; assert a new revision is
  created, `latest_revision_id` advances, and the controller does not 404.
- **create → rollback**: create, update to v2, then roll back to v1;
  assert the rollback succeeds (no legacy `findAnyDefinitionModel` row
  required) and `latest_revision_id` repoints to v1.
- **create → deactivate**: create, then deactivate; assert the
  `RegistryItem` goes inactive and the controller does not 404 for lack of
  an active legacy row.
These guard the §5 contract migration: each must pass with **no** legacy
`sub_agent_definitions` row backing the slug.

**Run the full suite** after the implementation. Expected: ~124 fewer
tests than today (the three fully-deleted dual-write files plus the
dual-write-only tests dropped from `WorkflowSnapshotDualWriteTest.php`),
the 7 registry-only snapshot tests preserved in the new
`WorkflowSnapshotRegistryPrimaryTest.php`, plus 1 new back-pointer
test file and the registry-native authoring-lifecycle cases above. The
net count also shifts by the registry-primary-off cases rewritten in
`FanOutSubAgentTest` and `HiveTemplateEligibilityTest` (rewritten
in-place as registry-only assertions, not deleted), so treat ~124 as an
estimate to reconcile against the real run.
The registry-primary (ON) cases in `*RegistryPrimaryTest.php` stay —
they guard the back-pointer column and the registry-only path, and
we'll re-evaluate the files wholesale in (c). The
*registry-primary-off* cases do **not** stay — **and they are not
confined to `*RegistryPrimaryTest.php`** (see the `FanOutSubAgentTest` /
`HiveTemplateEligibilityTest` entries above): §6/§8 make
`PLATFORM_REGISTRY_REGISTRY_PRIMARY` a no-op (registry always
primary), so any test that disables it and asserts the legacy
`sub_agent_definition_id` binding / legacy rollback-flag behaviour can
no longer pass and must be deleted or rewritten (see the "Delete or
rewrite the registry-primary-off cases" list below).

## 8. Config & env-var summary

| Var | Before (b2) | After (b2) | After (c) |
|---|---|---|---|
| `PLATFORM_REGISTRY_SUBAGENT_DUAL_WRITE` | gates dual-write paths, default `true` | unused, default `false` | removed |
| `PLATFORM_REGISTRY_REGISTRY_PRIMARY` | gates registry-primary path, default `true` | no-op, registry always primary (gate's `else` branches removed) | removed |

`PLATFORM_REGISTRY_REGISTRY_PRIMARY` is the env-var that makes
`subagent_dual_write=false` *safe* today. After (b2) it does nothing
useful (registry is always primary). We leave it for one release and
remove in (c).

## 9. Risk callouts

1. **Back-pointer readers** (§4) — the load-bearing tests at
   `SubAgentApiControllerTest.php:1122` and `:1151` must pass after
   the migration. If they don't, the column is not the 1:1 substitute
   we thought it was and we need to fall back to option (b)
   (accept the regression) before merging. **The reader inventory must
   be complete:** besides the two active-legacy readers, the
   slug-resolving readers
   (`resolveSlugViaRegistry`/`batchResolveSubAgentSlugsViaRegistry`,
   `Workflow::snapshotVersion`) also resolve "current revision" via
   `latestRevision` (highest version) and must move to the back-pointer
   (§4.3). Miss one and rolled-back sub-agents silently bind the wrong
   (newest) revision for task creation / workflow snapshots, with no
   active legacy row left to correct it after (b2). The new
   rollback-binding tests (§7) guard exactly this.
   **The writer inventory must be complete too:** the pointer is only
   correct if *every* revision-creating writer sets it. Besides the four
   `registryPrimary*` methods, `RegistryService::createItem/updateItem`
   (reachable via `RegistryApiController` for `kind=subagent`, §4.2) is
   a second write path — miss it and a registry-only sub-agent
   created/updated through the registry API has a null
   `latest_revision_id` and fails to bind in §4.3 readers. The
   `RegistryService` pointer tests (§7) guard this; `updateItem()` must
   advance the pointer whenever the request includes a payload key
   (`isset($data['payload'])`, i.e. whenever it creates a revision),
   never on a metadata-only update. There is **no payload-equality /
   no-op check**: do not add one in (b2). A payload-present update must
   still create a revision and advance `latest_revision_id` even if the
   new payload is byte-identical to the current one.
2. **`MarketplaceBundleInstaller:177-181`** — replacing the
   ungated legacy dup-check with a registry check is the most
   error-prone single change in this PR. Add a feature test that
   specifically exercises the dup-check under both scenarios
   (existing scope slug → reject; new slug → accept) before
   implementing.
3. **`tasks.sub_agent_definition_id`** — readers in
   `MarketplaceBundleInstaller`, `TaskReplayService::replay`,
   dashboard metadata reads, workflow step validation. (b2) doesn't
   touch the column or its readers; (c) does. Audit list in the
   follow-up issue.
4. **No migration in scope** for dropping the column — that's (c).
   After (b2) the column will be unpopulated but present. Any
   consumer that reads it post-(b2) without checking for null will
   behave incorrectly. Audited during (b2)'s code review.

## 10. Bake plan (post-merge)

1. Merge (b2) → deploy.
2. Run `php artisan registry:check-primary-health` for one full task
   cycle. Expected: clean. The check is the only monitoring signal
   we have.
3. If anything looks off, the `subagent_dual_write` env var is still
   readable (it just controls nothing) — actual rollback requires a
   revert of the deploy. Plan for this: tag the release so the
   revert is one command.
4. Once the bake is clean, PR (c) drops:
   - `SubAgentDefinition` model
   - `sub_agent_definitions` table + FK
   - `tasks.sub_agent_definition_id` column (after auditing readers)
   - The remaining `*RegistryPrimaryTest.php` files wholesale (the
     registry-primary-off legacy-mode cases are already gone in (b2)
     per §7; (c) retires the registry-primary ON coverage too, since
     the gate itself is removed)
   - The `isRegistryPrimary()` config gate (and the env var)

## 11. Estimated size

- ~700 lines removed (640 in `SubAgentDefinitionService` + 60 across
  other files).
- 1 new migration (~25 lines).
- 1 new back-pointer test file (~80 lines).
- 1 new `WorkflowSnapshotRegistryPrimaryTest.php` (registry-only
  tests moved out of `WorkflowSnapshotDualWriteTest.php`).
- 3 dual-write test files deleted (~5500 lines); a fourth
  (`WorkflowSnapshotDualWriteTest.php`) has its dual-write-only tests
  removed and is deleted once its registry-only tests are moved out.
- Registry-native authoring write paths (§5 "Public authoring
  contract"): signature changes to `SubAgentDefinitionService::{create,
  update,rollback,deactivate}` + reworked
  `SubAgentDashboardController::{findActiveDefinitionModel,
  findAnyDefinitionModel}` and their write callers; plus the
  create→update / create→rollback / create→deactivate cases (§7).
- 8+ files modified, 4+ files deleted. (Modified set includes
  `RegistryService.php` and the `RegistryItem` model for the second
  pointer write path — §4.2/§5 — and the authoring write-path files
  above. `FanOutSubAgentTest` and `HiveTemplateEligibilityTest` are
  rewritten in place for their registry-primary-off cases — §7.)

Net: the service becomes markedly smaller; the test suite loses
~124 tests but preserves the registry-only snapshot coverage and
gains back-pointer coverage that's currently absent.

## 12. Out of scope

- (c) — drop model + table + column.
- Per-agent back-pointer caching or invalidation.
- Removing `isRegistryPrimary()` config — see §6.

---

## Open questions for sign-off

1. **Back-pointer column name**: `registry_items.latest_revision_id`
   — or do you prefer a name like `current_revision_id` /
   `active_revision_id`? `latest_revision_id` matches the
   data shape (it's the *most recent* revision, even if no
   "active" boolean exists), but `active_revision_id` is more
   semantically honest if deactivation is implemented as "set to
   null." TBD.
2. **Migration timing**: the migration that adds
   `latest_revision_id` and backfills it ships in the same PR as
   the code that reads it, OR do you want the migration in a
   separate one-PR-prep PR so the (b2) PR is "code only" and the
   prep PR is "data only"? Two PRs is safer (easier revert) but
   stretches the cutover.
3. **`isRegistryPrimary()` kill switch**: keep for one release
   (§6 option a) or delete now? My read: keep.

Once signed off, the implementation is straightforward — most of
the work is mechanical removal gated by the per-file inventory
above. No surprises expected beyond the back-pointer test passing
on the first run.
