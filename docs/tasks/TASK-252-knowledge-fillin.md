# TASK-252: Knowledge fillin — scheduled per-agent knowledge gardening

**Status:** planning
**Branch:** `task/252-knowledge-fillin`
**Depends on:** TASK-222 (Knowledge Compiler persona template exists), TASK-078 (scheduled/recurring tasks dispatcher), TASK-018 (dream scheduling patterns)
**Edition:** shared
**Feature doc:** [FEATURE_KNOWLEDGE_GRAPH.md](../features/list-1/FEATURE_KNOWLEDGE_GRAPH.md)

## Objective

Implement a scheduled per-agent "knowledge fillin" task that proactively writes/updates knowledge entries for gaps the agent has observed across multiple tasks, channels, and activities. Complements the per-task `KnowledgeCompiler` (TASK-222) by being cross-cutting and pattern-seeking rather than reactive to a single task result.

## Background

Knowledge production in Superpos today is **reactive**:

- **`KnowledgeCompiler` / `KnowledgeCompilerTriggerService`** — fires per task completion, channel resolution, or batch threshold and extracts structured entries from raw data. It sees one unit of work at a time.
- **`KnowledgeCurator` (TASK-225)** — runs scheduled health/maintenance passes over existing entries (stale, orphan, broken links, contradictions). It does not *write new knowledge*, only grades and recommends.

There is no mechanism for an agent to **step back across many recent tasks / messages / entries it produced** and ask "what patterns, conventions, or decisions have I converged on that aren't yet captured?" That's a gap that a per-task compiler can never close — the signal only emerges across multiple tasks.

This task introduces a **per-agent, scheduled, proactive** pass analogous to the existing `dream` mechanism (`DreamService`): a periodic "knowledge gardening" task that inspects the agent's recent activity, looks for recurring patterns, and writes or updates knowledge entries where gaps are evident.

## Requirements

### Functional

- [ ] FR-1: New task type `knowledge_fillin` (analogous to `dream`), excluded from triggering further fillins/dreams.
- [ ] FR-2: Per-agent enable/schedule lives on the `Agent` model as new columns `knowledge_fillin_enabled` (boolean, default `false`) and `knowledge_fillin_schedule` (string, cron expression, nullable) — mirroring the existing `Agent.dream_enabled` column (`app/Models/Agent.php`). This matches the canonical per-agent reflection toggle pattern. The write scope for emitted entries is a separate configuration value with enum `"hive" | "apiary" | "agent:{agent_id}"`; for agent-scoped writes the string is interpolated with the agent's ULID (e.g. `scope: "agent:01HZX..."`) to match the shape that `KnowledgeController::validateScope()` enforces and that `KnowledgeApiTest` / `ContextAssemblyTest` exercise (`'scope' => 'agent:'.$agent->id`). The scope value is derived from `config('apiary.knowledge.fillin.default_scope')` unless overridden per-agent in `Agent.metadata` (non-authoritative hint).
- [ ] FR-3: Scheduled via the existing Superpos schedule mechanism (TASK-078); one schedule per agent when enabled. Toggling `Agent.knowledge_fillin_enabled` (and/or updating `Agent.knowledge_fillin_schedule`) creates, updates, or deletes the corresponding schedule — the `Agent` columns are the single source of truth, not `AgentPersona` settings.
- [ ] FR-4: Task payload contains a lookback window (e.g., last 7 days by default) of the agent's activity:
  - Recent completed tasks (IDs + results or summaries)
  - Recent channel messages the agent authored or was mentioned in
  - Recent knowledge entries the agent created/updated
- [ ] FR-5: Agent executes with a prompt that instructs it to:
  - Identify recurring patterns, decisions, conventions
  - Check existing knowledge for overlaps before creating new entries (`list_knowledge` / `search_knowledge`)
  - Write/update entries with title, summary, content, tags, confidence
  - Create knowledge links for related entries
- [ ] FR-6: Output recorded as knowledge entries through the normal write path — triggers auto-linking (TASK-218), FTS update (TASK-213), auto-index (TASK-219), embedding compute (TASK-226 when available).
- [ ] FR-7: Activity log entry per fillin run with count of entries created/updated and lookback window metadata.
- [ ] FR-8: Configurable in `config/apiary.php`:
  ```php
  'knowledge' => [
      'fillin' => [
          'enabled' => true,            // global kill-switch
          'default_schedule' => '0 3 * * *',
          'default_lookback_days' => 7,
      ],
  ],
  ```
- [ ] FR-9: Respects `knowledge.write` and `knowledge.write_apiary` permissions based on the configured `scope`. The fillin `scope` value is an identity tag (`"hive"`, `"apiary"`, or `"agent:{agent_id}"`) matching the existing knowledge model, not a privacy control. Access privacy is controlled separately by `KnowledgeEntry.visibility` (enum `public` | `private`, validated in `CreateKnowledgeRequest` as `in:public,private` and defaulted in `knowledge_entries` to `public`): agent-scope fillin writes should default `visibility = 'private'`; hive/apiary-scope fillin writes should default `visibility = 'public'` and require the corresponding `knowledge.write` / `knowledge.write_apiary` permission on the executing agent.

### Non-Functional

- [ ] NFR-1: Follows existing dream/compiler patterns (`DreamService`, `KnowledgeCompilerTriggerService`) for service/trigger/task shape.
- [ ] NFR-2: CE code must not import `App\Cloud`. Scope-gating, permission checks, and scheduling all live in shared code.
- [ ] NFR-3: Graceful degradation when `Agent.knowledge_fillin_enabled = false` (the default) — no schedule created, no error, no noise.
- [ ] NFR-4: Respects Pint code style; tests pass on SQLite.
- [ ] NFR-5: Cost-aware — a single LLM call per run, not per entry. The agent decides in one pass which entries to create/update and emits them as a batch of tool calls.

## Out of scope (deferred)

- Auto-detection of which agents should have fillin enabled (heuristic/opt-in; future task).
- Dashboard UI for reviewing fillin output (future gap; can piggyback on the Knowledge Explorer / activity log in the interim).
- Cross-agent knowledge aggregation (patterns visible only across multiple agents; future task).

## Implementation steps

### Migration

Add a new migration `database/migrations/YYYY_MM_DD_XXXXXX_add_knowledge_fillin_to_agents_table.php` that introduces two columns on `agents`, mirroring the `dream_enabled` precedent (`database/migrations/2026_03_24_100000_add_dream_enabled_to_agents_table.php`):

```php
Schema::table('agents', function (Blueprint $table) {
    $table->boolean('knowledge_fillin_enabled')->default(false)->after('dream_enabled');
    $table->string('knowledge_fillin_schedule')->nullable()->after('knowledge_fillin_enabled');
});
```

- `knowledge_fillin_enabled` defaults to `false` — fillin is opt-in per agent; no backfill is required (existing rows pick up the column default).
- `knowledge_fillin_schedule` is nullable; when `null` and the feature is enabled, the scheduler falls back to `config('apiary.knowledge.fillin.default_schedule')` (FR-8).
- `down()` drops both columns.
- Add `knowledge_fillin_enabled` and `knowledge_fillin_schedule` to `$fillable` and cast `knowledge_fillin_enabled` to `boolean` in `app/Models/Agent.php`.

### Schedule reconciliation

- Observing changes to `Agent.knowledge_fillin_enabled` / `Agent.knowledge_fillin_schedule` (model observer or service method invoked from the dashboard/API that flips the toggle) creates, updates, or deletes the corresponding TASK-078 schedule entry. The `Agent` columns remain the source of truth; the schedule row is a derived artefact.
- No reading from, or writing to, `AgentPersona` settings for fillin enable/schedule state. (If future work wants to expose the toggle in the persona UI, it should still write through to these `Agent` columns.)

### Service / task wiring

- New `KnowledgeFillinService` analogous to `DreamService` — guards on `Agent.knowledge_fillin_enabled`, builds the lookback payload (FR-4), dispatches a `knowledge_fillin` task targeted at the agent (FR-1).
- Task handler writes entries via the standard knowledge write path so auto-linking / FTS / indexing / embeddings all fire (FR-6) and `KnowledgeController::validateScope()` enforces the `agent:{id}` / `hive` / `apiary` shape for every emitted entry (FR-2, FR-9).

## Design notes

- **Auditability flag.** Consider flagging fillin output as `auto_generated: true` in entry metadata so the Curator (TASK-225) and humans can audit / filter / decay confidence appropriately. Curator's existing "stale / orphan / contradiction" passes should treat auto-generated entries the same as any other, but the flag is useful for dashboards.
- **Duplication prevention.** The prompt must emphasise "don't duplicate existing knowledge" — the agent is required to call `list_knowledge` / `search_knowledge` before writing. The context assembly pipeline (TASK-223) should supply a summary of existing entries in the scope up front.
- **Transcript.** Consider adding a "fillin transcript" field on the task result (or a dedicated activity log entry) to store the agent's reasoning about *why* each entry was created/updated. This helps post-hoc review and tuning of the prompt.
- **Scope alignment.** The configured `scope` determines both which activity is included in the payload and where entries are written. Valid values match the existing knowledge scope model (`KnowledgeController::validateScope()`): `"hive"`, `"apiary"`, or `"agent:{agent_id}"` (where `{agent_id}` is the executing agent's ULID). An agent-scope fillin only sees/writes that agent's own `agent:{id}`-scoped knowledge; hive-scope sees hive activity; apiary-scope (if permitted) aggregates cross-hive signal. Scope is identity-only — privacy/visibility of each emitted entry is set independently via `KnowledgeEntry.visibility` (`public` or `private`).
- **Schedule hygiene.** Default `0 3 * * *` (daily at 03:00) is deliberately off-peak and paired with Curator's 02:00 slot (TASK-225). Fillin runs *after* Curator so it sees fresh health signals and can react to "thin topics" recommendations.
- **Overlap policy.** Use schedule `overlap: skip` by default — if the previous fillin is still running (unusual but possible for large lookbacks), skip the next run rather than stacking.
- **Default scope flipped to `hive` (post-merge).** The initial implementation defaulted `knowledge.fillin.default_scope` to `agent`, which wrote every fillin entry to the executing agent's private `agent:{id}` scope. That defeats the point of fillin — shared-brain is the point, not private pockets of insight no other agent can see. Default is now `hive`, with graceful fallback to `agent:{id}` via `coerceHiveScope()` when the executing agent lacks `knowledge.write` (mirrors the existing `coerceApiaryScope()` fallback). The coercion emits a `knowledge.fillin.scope_coerced` activity log entry (`from=hive, to=agent:<id>, reason=missing_knowledge.write`) so operators can spot permission gaps. Motivation: agent-scope was a permission-safety default, not a correctness default — flipping the default makes the common case (cross-cutting patterns / decisions / invariants) visible to the hive and the dashboard, while the fallback preserves the permission-safety property.

## Open questions

- Should fillin dispatch via the hive-level TaskRouter or be targeted directly at the agent like `dream`? Initial instinct: targeted, same as dream.
- Should the lookback window be configurable per-agent (e.g., as an additional `Agent.knowledge_fillin_lookback_days` column or a key in `Agent.metadata`) or only globally? Per-agent feels right; defaults fall back to the global config.
- What happens when an agent's fillin produces zero entries? Log activity as "no gaps identified" and move on — this is a valid, frequent outcome.
