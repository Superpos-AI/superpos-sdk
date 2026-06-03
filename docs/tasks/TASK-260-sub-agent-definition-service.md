# TASK-260: SubAgentDefinitionService

**Status:** pending
**Branch:** `task/260-sub-agent-definition-service`
**PR:** https://github.com/Superpos-AI/superpos-app/pull/461
**Depends on:** TASK-259
**Blocks:** TASK-261, TASK-262, TASK-263
**Edition:** shared
**Feature doc:** [FEATURE_SUB_AGENT_DEFINITIONS.md](../features/list-1/FEATURE_SUB_AGENT_DEFINITIONS.md) §4, §7

## Objective

Create a service class for managing sub-agent definition lifecycle: create, update (new version), activate, deactivate, rollback, list, and assemble documents into a system prompt. Follows the thin-controller → service pattern used throughout Superpos (mirrors `PersonaService` architecture).

## Requirements

### Functional

- [ ] FR-1: `create(Hive $hive, array $data): SubAgentDefinition` — creates a new sub-agent definition with a monotonically allocated version number (`max(version) + 1` across all rows for the slug+hive, falling back to 1 when no prior rows exist), is_active=true. Wrapped in a `DB::transaction()` that locks the hive row (`Hive::withoutGlobalScopes()->lockForUpdate()->find($hive->id)`) before checking slug uniqueness or computing the version, preventing concurrent-create races on MySQL/MariaDB (which lacks a partial unique index). Validates that the slug is unique among **active** definitions in the hive (a previously deactivated slug may be recreated — it receives the next version, not version 1, avoiding collision with `uq_sub_agent_slug_version`). Sets `superpos_id` from `$hive->superpos_id`.
- [ ] FR-2: `update(SubAgentDefinition $current, array $data): SubAgentDefinition` — creates a **new row** with a monotonically allocated version number (`max(version) + 1` across all rows for the slug+hive, under a row lock). This prevents unique-constraint collisions after rollback (e.g., rolling back from v3 to v1 and then updating would collide on v2 if using `$current->version + 1`). Follows the same pattern as `PersonaService::createPersona()`. Deactivates the previous active version and activates the new one. Both operations wrapped in a database transaction.
- [ ] FR-3: `rollback(SubAgentDefinition $definition, int $targetVersion): SubAgentDefinition` — activates a prior version of the same slug+hive, deactivating the currently active version. Wrapped in a transaction that locks the hive row and all candidate versions (matching the `PersonaService::activateVersion()` pattern) to prevent concurrent rollback/update races. On MySQL/MariaDB there is no filtered unique-index backstop, so this owner-row lock is the sole concurrency guard. Throws exception if target version doesn't exist.
- [ ] FR-4: `deactivate(SubAgentDefinition $definition): bool` — sets `is_active=false` on the currently active version of the slug. Wrapped in a transaction that locks the hive row **and re-reads the live active candidate set** inside the lock (mirroring the `rollback()` pattern) to prevent stale-read races where a concurrent `update()` or `rollback()` may have changed the active version between the caller's read and the lock acquisition. Effectively "soft deletes" the sub-agent definition (no hard delete).
- [ ] FR-5: `assemble(SubAgentDefinition $definition): string` — concatenates documents in the defined assembly order: SOUL → AGENT → RULES → STYLE → EXAMPLES → NOTES. Each document is prefixed with `# {DOCUMENT_NAME}` and separated by `\n\n`. Skips documents that are null/empty.
- [ ] FR-6: Activity logging on all mutations (create, update/new-version, rollback, deactivate) using `ActivityLogger`. Log entries should include:
  - `subject_type`: 'sub_agent_definition'
  - `subject_id`: the definition ID
  - `action`: 'created', 'version_created', 'rolled_back', 'deactivated'
  - `properties`: relevant metadata (slug, version, etc.)
- [ ] FR-7: `list(string $hiveId, ?bool $activeOnly = true): Collection` — returns sub-agent definitions for a hive. When `$activeOnly` is true (default), returns only active definitions.

### Non-Functional

- [ ] NFR-1: Thin controller → service pattern — all business logic in service, controllers delegate
- [ ] NFR-2: Database transactions for version switches (deactivate old + activate new must be atomic)
- [ ] NFR-3: Slug uniqueness validation at application level with hive-row locking in `create()` (covers MySQL/MariaDB which lacks partial unique index — the `lockForUpdate()` on the hive row serializes concurrent creates, matching the pattern used by `update()`, `rollback()`, and `deactivate()`)
- [ ] NFR-4: PSR-12 compliant

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/Services/SubAgentDefinitionService.php` | Main service class |
| Create | `tests/Feature/SubAgentDefinitionServiceTest.php` | Service tests |

### Key Design Decisions

- **Immutable versioning** — updates create new rows rather than modifying existing ones. This is the same pattern used by `PersonaService` for agent personas. Each version is a complete snapshot.
- **Assembly order** — documents are concatenated in a fixed order (SOUL → AGENT → RULES → STYLE → EXAMPLES → NOTES) matching the persona assembly pattern. No MEMORY document (sub-agents are stateless templates).
- **Fail-safe deactivation** — deactivating a sub-agent definition only sets `is_active=false`. The records remain for rollback and audit purposes.
- **Transaction scope** — version switches (deactivate old + activate new) must be atomic to prevent states where zero or two versions are active for the same slug.

## Implementation Plan

1. Create `SubAgentDefinitionService` class in `app/Services/`:
   ```php
   class SubAgentDefinitionService
   {
       public function __construct(
           private ActivityLogger $activityLogger
       ) {}
   }
   ```

2. Implement `create()`:
   - Wrap in `DB::transaction()`:
     - Lock the **hive row** (`Hive::withoutGlobalScopes()->lockForUpdate()->find($hive->id)`) to serialize concurrent creates. Without this lock, two concurrent `create()` calls for the same slug could both observe no active row and both insert, violating the one-active-per-slug invariant. On MySQL/MariaDB there is no partial unique index, so this hive-row lock is the sole concurrency guard. This mirrors the pattern used by `update()`, `rollback()`, and `deactivate()`.
     - Validate slug uniqueness among active definitions (inside the lock):
       ```php
       $exists = SubAgentDefinition::where('hive_id', $hive->id)
           ->where('slug', $data['slug'])
           ->where('is_active', true)
           ->exists();
       ```
       Throw `ValidationException` if an active definition with this slug already exists.
     - Compute version monotonically (inside the lock): `max(version) + 1` across **all** rows (active and inactive) for the same slug+hive, falling back to 1 when no prior rows exist. This ensures recreating a previously deactivated slug does not collide with the `uq_sub_agent_slug_version` constraint:
       ```php
       $maxVersion = SubAgentDefinition::where('hive_id', $hive->id)
           ->where('slug', $data['slug'])
           ->max('version');
       $version = $maxVersion !== null ? $maxVersion + 1 : 1;
       ```
     - Create the model with version=`$version`, is_active=true, superpos_id from hive
   - Log activity: action='created'

3. Implement `update()`:
   - Wrap in `DB::transaction()`:
     - Lock the **hive row** (`Hive::withoutGlobalScopes()->lockForUpdate()->find($current->hive_id)`) to serialize concurrent version creation. This mirrors the PersonaService pattern which locks the **owner row** (Agent), not the current active version.
     - Find whatever version is currently active inside the transaction (after acquiring the lock):
       ```php
       $currentActive = SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $current->hive_id)
           ->where('slug', $current->slug)
           ->where('is_active', true)
           ->first();
       ```
     - Compute next version monotonically: `max(version) + 1` across **all** rows for the same slug+hive (not `$current->version + 1`). This mirrors the pattern in `PersonaService::createPersona()` and prevents unique-constraint collisions after a rollback (e.g., rollback from v3→v1, then update would try to create v2 if using `$current->version + 1`)
       ```php
       $nextVersion = SubAgentDefinition::where('hive_id', $current->hive_id)
           ->where('slug', $current->slug)
           ->max('version');
       $nextVersion = $nextVersion !== null ? $nextVersion + 1 : 1;
       ```
     - Deactivate **all** active versions for this slug+hive (not just the passed `$current` — handles races where another request activated a different version):
       ```php
       SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $current->hive_id)
           ->where('slug', $current->slug)
           ->where('is_active', true)
           ->update(['is_active' => false]);
       ```
     - Create new row with version=`$nextVersion`, is_active=true, all new data fields, same slug/hive_id/superpos_id
   - Log activity: action='version_created' with old_version and new_version in properties

4. Implement `rollback()`:
   - Wrap in `DB::transaction()`:
     - Lock the **hive row** (`Hive::withoutGlobalScopes()->lockForUpdate()->find($definition->hive_id)`) to serialize concurrent rollback/update operations. This mirrors the `PersonaService::activateVersion()` pattern which locks the owner row (Agent) before switching active state.
     - Lock all versions for this slug+hive to prevent concurrent activation races:
       ```php
       $versions = SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $definition->hive_id)
           ->where('slug', $definition->slug)
           ->lockForUpdate()
           ->get();
       ```
     - Find the target version from the locked set: `$versions->firstWhere('version', $targetVersion)` — throw exception if not found
     - Deactivate **all** active versions for this slug+hive (not just the passed `$definition`):
       ```php
       SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $definition->hive_id)
           ->where('slug', $definition->slug)
           ->where('is_active', true)
           ->update(['is_active' => false]);
       ```
     - Activate target version: `$target->update(['is_active' => true])`
   - Log activity: action='rolled_back' with from_version and to_version

5. Implement `deactivate()`:
   - Wrap in `DB::transaction()`:
     - Lock the **hive row** (`Hive::withoutGlobalScopes()->lockForUpdate()->find($definition->hive_id)`) to serialize concurrent deactivate/update/rollback operations. Without this lock, a concurrent `update()` or `rollback()` could re-activate a version while `deactivate()` is in progress, leaving the slug in an inconsistent state. On MySQL/MariaDB there is no filtered unique-index backstop, so the hive-row lock is the sole concurrency guard.
     - Re-read the live active candidate set inside the locked transaction (do **not** trust the passed `$definition` — it may be stale if a concurrent `update()` or `rollback()` changed the active version between the caller's read and lock acquisition):
       ```php
       $activeDefinitions = SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $definition->hive_id)
           ->where('slug', $definition->slug)
           ->where('is_active', true)
           ->lockForUpdate()
           ->get();
       ```
     - If no active definitions found, return false (already deactivated)
     - Set `is_active=false` on **all** active definitions for this slug+hive (not just the passed `$definition`):
       ```php
       SubAgentDefinition::withoutGlobalScopes()
           ->where('hive_id', $definition->hive_id)
           ->where('slug', $definition->slug)
           ->where('is_active', true)
           ->update(['is_active' => false]);
       ```
   - Log activity: action='deactivated'

6. Implement `assemble()`:
   ```php
   public function assemble(SubAgentDefinition $definition): string
   {
       $order = SubAgentDefinition::DOCUMENTS;
       $sections = [];
       foreach ($order as $docName) {
           $content = $definition->getDocument($docName);
           if ($content !== null && $content !== '') {
               $sections[] = "# {$docName}\n\n{$content}";
           }
       }
       return implode("\n\n", $sections);
   }
   ```

7. Implement `list()`:
   ```php
   public function list(string $hiveId, ?bool $activeOnly = true): Collection
   {
       $query = SubAgentDefinition::where('hive_id', $hiveId);
       if ($activeOnly) {
           $query->active();
       }
       return $query->orderBy('slug')->get();
   }
   ```

8. Write comprehensive tests

## Test Plan

### Unit Tests

- [ ] `assemble()` concatenates documents in correct order with `# {NAME}` prefix
- [ ] `assemble()` skips null/empty documents
- [ ] `assemble()` handles definition with no documents (returns empty string)
- [ ] `assemble()` handles definition with only one document

### Feature Tests

- [ ] `create()` creates definition with version=1 and is_active=true (fresh slug)
- [ ] `create()` after deactivate allocates monotonic version (e.g., version=2 after deactivated version=1 — no `uq_sub_agent_slug_version` collision)
- [ ] `create()` sets superpos_id from hive
- [ ] `create()` rejects duplicate active slug in same hive
- [ ] `create()` allows same slug in different hives
- [ ] `create()` logs activity with action='created'
- [ ] `update()` creates new version with incremented version number
- [ ] `update()` deactivates previous version atomically
- [ ] `update()` preserves slug and hive_id from original
- [ ] `update()` after rollback allocates monotonic version (no collision with `uq_sub_agent_slug_version`)
- [ ] `update()` logs activity with action='version_created'
- [ ] `rollback()` activates target version and deactivates current
- [ ] `rollback()` throws exception for non-existent target version
- [ ] `rollback()` logs activity with action='rolled_back'
- [ ] `deactivate()` sets is_active=false on the live active definition (re-read inside lock)
- [ ] `deactivate()` returns false when slug is already fully deactivated
- [ ] `deactivate()` deactivates the correct version even if a concurrent update changed the active version
- [ ] `deactivate()` logs activity with action='deactivated'
- [ ] `list()` returns only active definitions by default
- [ ] `list()` returns all definitions when activeOnly=false
- [ ] `list()` scopes to correct hive
- [ ] Concurrent `create()` with same slug is serialized by hive-row lock (only one succeeds, second throws `ValidationException`)
- [ ] Version switch is atomic (if either fails, neither commits)

## Validation Checklist

- [ ] All tests pass (`php artisan test`)
- [ ] PSR-12 compliant
- [ ] Activity logging on state changes (create, update, rollback, deactivate)
- [ ] Database transactions on version switches
- [ ] Thin controller → service pattern followed
- [ ] No updated_at writes (immutable records)
