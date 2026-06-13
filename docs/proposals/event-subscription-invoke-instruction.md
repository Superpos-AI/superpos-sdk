# Proposal: Event Subscription Invoke Instruction

Status: Draft for review
Owner: @doxadoxa
Scope: Give `EventSubscription` an optional `invoke_instructions` prompt template so that an event firing into a subscribed agent produces a task whose prompt makes the agent's expected reaction explicit, with payload variables interpolated. Refs #732.

---

## 1. Problem

A user (issue #732) reports:

> Probably it makes sense to pass also invoke instruction to task that created by event subscription.
> **For now i don't understand how agent should react on event.**
> Consider subscriptions as a main part of this flow. How to make it better in UI?

The confusion is structural, not cosmetic. The platform currently has **two** mechanisms that connect an event to an agent — and only one of them carries any instruction:

| | `EventSubscription` (this proposal) | `EventTrigger` |
|---|---|---|
| Model | `app/Models/EventSubscription.php` | `app/Models/EventTrigger.php` |
| Wiring | Agent polls; matching events delivered as-is via `EventBus::poll()` | Cursor-driven dispatcher renders a prompt and creates a task (`EventTriggerService::processTrigger`) |
| Carries an instruction? | **No** — only `event_type`, `scope` | **Yes** — `prompt_template`, `task_payload_template`, target agent / capability, dedup, overlap, timeout, retries |
| Result of an event firing | Agent receives the raw event payload on its next poll and must decide what to do with it | A `Task` is created with a rendered prompt, ready for any agent to pick up |
| Dashboard surface | Events › Subscriptions (list + add form) | Not yet a dashboard surface; configured via API/seed |

From the manager's chair, "I subscribed agent X to event Y" implies "agent X will do something when Y happens." In reality the platform delivers the raw payload and the agent is left to introspect `event.type` and `event.payload` and infer intent. For agents wired up by hand this works; for agents installed from templates or driven by a human operator who doesn't know the agent's code, the contract is invisible.

`EventTrigger` already solves the templated-prompt half of the problem, but it lives outside the subscription UI, has no dashboard surface yet, and is not what the manager reaches for when they click **Subscriptions**. The user's framing — *"Consider subscriptions as a main part of this flow"* — is the right one: subscriptions are the noun managers use, so the instruction has to live there.

## 2. Goals / Non-goals

**Goals**
- Let an `EventSubscription` optionally carry an **invoke instruction** (a free-text prompt template) that becomes the prompt of a task created when a matching event fires.
- Make "what should the agent do?" a first-class field on the subscription form, not a tribal-knowledge concern.
- Interpolate event payload variables into the instruction at task-creation time using a documented syntax.
- Preserve every existing flow: subscriptions without an instruction keep delivering raw events via `poll()` exactly as today.
- Reduce the conceptual gap between `EventSubscription` and `EventTrigger`; lay the groundwork for unifying them in a later iteration without committing to that unification now.
- Improve discoverability — surface subscriptions as a top-level concept in the nav since the user calls them "a main part of this flow."

**Non-goals (V1)**
- Replacing or deleting `EventTrigger`. It keeps its richer surface (dedup, overlap policy, retries, payload template). See §10.
- A full template DSL — V1 picks one interpolation syntax and ships with a small built-in variable set.
- Per-event-type instruction libraries / presets. Useful, but deferred (see §8 open questions).
- Conditional filtering on subscriptions (`EventTrigger.filter` is the existing answer); not added here.
- Changing the polling contract or the `events.poll` API response shape.
- Modifying the poll query to return invoke-mode rows (they are explicitly **excluded** — see §3 delivery modes and §6.1).

## 3. Concepts

**Invoke instruction** — an optional, free-text prompt template stored on an `EventSubscription`. When an event matches the subscription:

- If the subscription has **no** invoke instruction (current behavior, unchanged): the event is delivered to the agent's poll cursor as-is. The agent picks it up via `GET /api/v1/hives/{hive}/events/poll` and decides what to do.
- If the subscription **has** an invoke instruction: one or more `Task` rows are created with `payload.invoke.instructions = render(invoke_instructions, eventContext)`, each targeting a specific agent (for direct subscriptions: the subscribed agent; for capability-pool subscriptions: one task per agent in the pool — see §6.2 for fan-out semantics). The agent claims the task via the normal task-claim flow. No new poll endpoint, no new SDK contract. Note: the rendered instruction is stored in the task's JSON `payload` column (at `payload.invoke.instructions`), not in a top-level DB column — the `tasks` table has no `prompt` column. This aligns with the existing convention used by the API/dashboard path, and `TaskSummaryService` already knows how to read `payload.invoke.instructions`. **Runtime change required:** `ManagedAgentRuntime::buildUserMessage()` must be updated to read `payload.invoke.instructions` before falling back to the JSON dump, so that managed agents receive the rendered instruction as their user message (see §6.2 for details).

**Delivery modes** — every subscription is now one of two modes, decided by whether `invoke_instructions` is null:

| Mode | Trigger | What the agent sees |
|---|---|---|
| `poll` (today) | `invoke_instructions IS NULL` | Raw event in `events.poll` response |
| `invoke` (new) | `invoke_instructions IS NOT NULL` | A new task in its task queue with a rendered prompt |

A subscription cannot be both modes simultaneously — the column's null-ness is the discriminator. Switching modes is a single PATCH on the subscription.

**Event context for rendering** — a flat, documented namespace of values available to the template. V1 ships with:

- `{{ event.id }}` — event ULID
- `{{ event.type }}` — e.g. `github.issue.opened`
- `{{ event.hive_id }}` — hive scope (null for cross-hive)
- `{{ event.is_cross_hive }}`
- `{{ event.source_agent_id }}` — emitter, if any
- `{{ event.created_at }}` — ISO-8601
- `{{ event.payload.* }}` — any path into the JSON payload (e.g. `{{ event.payload.issue.title }}`)
- `{{ subscription.agent_id }}`, `{{ subscription.event_type }}`, `{{ subscription.scope }}`

Unknown paths render to empty string (do not throw). This matches the behavior of `HandlebarsTemplateRenderer` already used by `EventTriggerService` — V1 reuses that renderer rather than introducing a second template engine. See §8 for the open question on syntax.

**Relationship to `EventTrigger`** — `EventTrigger` keeps its place as the *power-user* primitive (priority, dedup keys, overlap policy, retries, payload template, target capability resolution, paused/active state). `EventSubscription.invoke_instructions` is the *minimum viable* path: one event → one task with a prompt. The two are not merged in V1 (see §10) but the proposal is deliberately designed so a future unification is a code change, not a data migration.

## 4. Data model

Additive column on two existing tables; no new tables.

```text
event_subscriptions
  agent_id              (existing, pk part)
  event_type            (existing, pk part)
  scope                 (existing)
  created_at            (existing)
  invoke_instructions   (text, nullable, new)         -- prompt template; null = poll mode
  last_processed_seq    (bigint, nullable, new)       -- cursor for invoke-mode dispatch (§6)
  updated_at            (timestamp, nullable, new)    -- needed so PATCH can be detected

capability_event_subscriptions
  id                    (existing, pk)
  organization_id       (existing)
  hive_id               (existing, nullable)
  capability            (existing)
  event_type            (existing)
  scope                 (existing)
  created_at            (existing)
  invoke_instructions   (text, nullable, new)         -- prompt template; null = poll mode
  last_processed_seq    (bigint, nullable, new)       -- cursor for invoke-mode dispatch (§6)
  updated_at            (timestamp, nullable, new)    -- needed so PATCH can be detected
```

**Migration** — single new migration `*_add_invoke_instructions_to_event_subscriptions_tables.php` covering both tables:

```php
Schema::table('event_subscriptions', function (Blueprint $table) {
    $table->text('invoke_instructions')->nullable()->after('scope');
    $table->unsignedBigInteger('last_processed_seq')->nullable()->after('invoke_instructions');
    $table->timestamp('updated_at')->nullable()->after('created_at');
});

Schema::table('capability_event_subscriptions', function (Blueprint $table) {
    $table->text('invoke_instructions')->nullable()->after('scope');
    $table->unsignedBigInteger('last_processed_seq')->nullable()->after('invoke_instructions');
    $table->timestamp('updated_at')->nullable()->after('created_at');
});

// Bootstrap cursor so existing subscriptions don't replay history
$maxSeq = DB::table('events')->max('seq') ?? 0;
DB::table('event_subscriptions')->update(['last_processed_seq' => $maxSeq]);
DB::table('capability_event_subscriptions')->update(['last_processed_seq' => $maxSeq]);
```

Rollback: drop all three new columns (`invoke_instructions`, `last_processed_seq`, `updated_at`) from both tables. No data loss for existing rows (they all start with `invoke_instructions = NULL`, which is the current behavior).

**Model changes** — `app/Models/EventSubscription.php`:
- Add `invoke_instructions` and `updated_at` to `$fillable`.
- Set `public $timestamps = true;` (currently `false`). The existing `setKeysForSaveQuery()` override already preserves the composite-key save path; Laravel will populate `updated_at` automatically. `created_at` continues to be explicitly set by `EventBus::subscribe()`. Existing call sites that do not pass `invoke_instructions` are unaffected — the parameter defaults to `null` (see §6.3 for the required service-layer changes).
- Add helper `hasInvokeInstructions(): bool { return $this->invoke_instructions !== null; }`. Empty-string inputs are normalized to `NULL` at the API/form-input boundary (see §5), so a single `IS NOT NULL` / `!== null` predicate is sufficient everywhere — both in this helper and in the create/update/dispatcher/bulk-replace paths (§§6.2–6.4). This keeps mode detection consistent across the application.

**Model changes** — `app/Models/CapabilityEventSubscription.php`:
- Add `invoke_instructions` and `updated_at` to `$fillable`.
- Set `public $timestamps = true;` (currently `false`). The capability PATCH path in §6.4 mutates the row via `$subscription->save()`; without `$timestamps = true`, `updated_at` would never advance on a capability-row instruction edit. The existing `setKeysForSaveQuery()` override on this model preserves the ULID-key save path; Laravel will populate `updated_at` automatically. `created_at` continues to be explicitly set by `EventBus::subscribeCapability()`.
- Add same `hasInvokeInstructions()` helper (single `!== null` predicate — empty string is normalized to `NULL` at the API boundary; see §5).

**Capability-pool delivery model** — a capability-pool subscription with `invoke_instructions` creates **one assigned task per pool member at dispatch time** (per-agent fan-out). For each matching event, the dispatcher resolves the current pool membership (agents owning `subscription.capability`, scoped to the subscription's hive — or org-wide for apiary scope) and emits one task per resolved agent with `target_agent_id` set. This is required because the alternative — a single unassigned task with `target_capability` set — only works through the agent poll API (`app/Http/Controllers/Api/TaskController.php` matches `target_capability` in its claim filter), but **not** through hosted/managed agents: `ManagedAgentRuntime::claimNextTaskLocked()` (`app/Cloud/Services/ManagedAgentRuntime.php`) only claims tasks targeted directly at the agent or unrouted tasks matching the agent's `claim_type`, and never checks `target_capability`. Per-agent fan-out works uniformly across both claim paths and matches the fan-out pattern already used elsewhere in the platform. See §6.2 for the dispatch flow and the idempotency-key strategy that prevents duplicate tasks on retry.

**No changes to** `events`, `event_triggers`, `tasks`. The created task uses the existing `tasks` schema unchanged. All invoke-mode data is stored inside the task's JSON `payload` column: `payload.invoke.instructions` carries the rendered prompt (matching the convention used by the API/dashboard path — `TaskSummaryService` already reads this field), `payload.dedup_key` provides idempotency (matching the `EventTriggerService` convention), and traceability fields (`payload.event_id`, `payload.event_type`, `payload.event_subscription_id`, etc.) identify the originating event and subscription. See §6.2 for the full field list.

## 5. API

Both the dashboard form and the agent-facing API accept the new field. All changes are additive and backward-compatible.

**Agent API** — `app/Http/Requests/SubscribeEventRequest.php`:

```diff
 return [
     'event_type' => ['required', 'string', 'max:100', 'regex:/^'.EventSubscription::EVENT_TYPE_PATTERN.'$/'],
     'scope' => ['sometimes', 'string', Rule::in(EventSubscription::VALID_SCOPES)],
     'capability' => [ ... existing ... ],
+    'invoke_instructions' => ['sometimes', 'nullable', 'string', 'max:8000'],
 ];
```

**Boundary normalization (empty string → NULL).** Both the agent API form requests (`SubscribeEventRequest`, `UpdateSubscriptionRequest`, and the capability variants) and the dashboard controllers must normalize an empty-string `invoke_instructions` to `NULL` before passing the value to the service layer. The simplest path is a `prepareForValidation()` hook that rewrites `''` to `null` on the input bag, but a `mutator` on the `EventSubscription` / `CapabilityEventSubscription` models that does the same on assignment is equally acceptable so long as it runs on every write path (create, update, bulk replace). With this normalization in place, **every** downstream predicate — DB queries (`whereNull` / `whereNotNull`, `IS NOT NULL`), PHP comparisons (`!== null`), and the `hasInvokeInstructions()` helper — uses a single rule: `invoke_instructions IS NOT NULL ⇔ invoke mode`. The doc deliberately does **not** use a mixed predicate (e.g. "non-null and non-empty") anywhere — that drift was the original mode-detection inconsistency this section closes.

**Template validation on create** — when `invoke_instructions` is provided and non-null, the controller must dry-render the template before persisting, following the same pattern as `EventTriggerController::store()` (lines 92–97). This prevents permanently broken templates from being saved — §6.2 specifies that render failures cause the cursor to advance past the failed event, which means a malformed template would silently drop every matching event.

Add a `validateInvokeTemplate()` helper to `EventController` (or a shared trait) that dry-renders the template with an empty context:

```php
private function validateInvokeTemplate(?string $template): ?JsonResponse
{
    // Empty string is normalized to null at the request boundary (see "Boundary
    // normalization" above), so a single null check is sufficient. The
    // belt-and-braces `=== ''` guard is kept as defense in depth in case a new
    // call site forgets the normalization step.
    if ($template === null || $template === '') {
        return null;
    }

    try {
        $this->renderer->renderWithContext($template, ['event' => []]);
    } catch (\Throwable $e) {
        return $this->validationError([
            'invoke_instructions' => 'Template parse error: '.$e->getMessage(),
        ]);
    }

    return null;
}
```

This check must be called in `EventController::subscribe()` and `EventController::updateSubscription()` (and their capability-pool variants) before any persistence, returning a 422 on parse failure. The dashboard store/update controllers must apply the same validation.

`POST /api/v1/agents/subscriptions` accepts the new field; `GET /api/v1/agents/subscriptions` returns it in each subscription row.

**New endpoint** — `PATCH /api/v1/agents/subscriptions/{eventType}` — update `invoke_instructions` on an existing direct subscription without deleting and recreating it. Required so the dashboard can toggle a subscription from poll mode to invoke mode without losing its row.

**PATCH authorization** — the PATCH endpoint enforces the same authorization invariants as POST and DELETE:
- **Direct subscriptions** (no `capability` parameter): the authenticated agent can only update its own subscription row (`agent_id = auth agent`). No special permission required (same as direct POST/DELETE).
- **Capability-pool subscriptions** (when `capability` query parameter is provided): requires `events.manage` permission (mirrors `EventController::subscribe()` line 217 and `EventController::unsubscribe()` line 279). The PATCH route for capability-pool rows uses the subscription's `id` (ULID) as the path parameter rather than `eventType`, since capability-pool rows are identified by `id`, not by `(agent_id, event_type)`.
- **Hive-scoped capability subscriptions**: the PATCH endpoint enforces same-hive access — an agent in hive A cannot update a hive-scoped subscription owned by hive B. The subscription's `hive_id` must match the authenticated agent's `hive_id`. This mirrors the POST/DELETE contract where `hive_id` is derived from the authenticated agent. Only apiary-scoped rows are eligible for cross-hive access (with the `cross_hive` permission).
- **Apiary-scoped subscriptions**: requires `cross_hive` permission (mirrors POST line 210, DELETE line 307). The scope of an existing subscription **cannot** be changed via PATCH — only `invoke_instructions` is mutable. To change scope, delete and recreate the subscription. This prevents an unprivileged agent from escalating a hive-scoped row to apiary scope without the `cross_hive` check.

**PATCH cursor reset** — when PATCH transitions a subscription from poll mode to invoke mode (`invoke_instructions` changing from `NULL` to non-`NULL`), the handler **must** set `last_processed_seq = current MAX(seq) FROM events` in the same transaction. Without this, the dispatcher would use the stale cursor value seeded at migration time and replay every event since then. The three transition cases:
- `NULL → non-NULL` (poll → invoke): set `last_processed_seq = (SELECT MAX(seq) FROM events)` in the same transaction. Only future events produce tasks.
- `non-NULL → non-NULL` (invoke instruction edit): keep the existing `last_processed_seq`. The dispatcher continues from where it left off.
- `non-NULL → NULL` (invoke → poll): `last_processed_seq` becomes irrelevant (poll mode does not use it). Leave the value as-is for potential future re-enable, or null it out — either is safe since the poll path ignores the column.

This cursor reset rule applies identically to both `event_subscriptions` and `capability_event_subscriptions` rows.

**Dashboard form** — `EventDashboardController::storeSubscription()` and the matching capability variant: add `invoke_instructions` to the validated payload (`nullable|string|max:8000`).

**Bulk replace (`PUT /api/v1/agents/subscriptions`) — invoke-mode exclusion:** `ReplaceSubscriptionsRequest` does **not** accept `invoke_instructions` per entry. The `PUT` endpoint is a destructive full replacement used by SDKs that sync a declarative subscription list. Older SDK versions do not know about the `invoke_instructions` field and would recreate every row with `invoke_instructions = null`, silently downgrading invoke-mode subscriptions back to poll mode. To prevent this:
- `ReplaceSubscriptionsRequest` validation **rejects** any entry that includes `invoke_instructions`. If a client sends it, the endpoint returns 422 with a message directing the caller to the dedicated PATCH endpoint.
- `EventBus::replaceSubscriptions()` **preserves** existing invoke-mode subscriptions during the replace cycle. The preservation key is **`event_type` alone**, because `event_subscriptions` has its primary key on `(agent_id, event_type)` (see `database/migrations/2026_02_28_200000_create_event_subscriptions_table.php:17`) — `scope` is not part of the row's identity. Before deleting, the method identifies rows with `invoke_instructions IS NOT NULL` and keys them by `event_type`. Those rows are **kept as-is** (instruction, scope, cursor, and all) and excluded from the delete-and-recreate pass. Any incoming entry whose `event_type` matches a preserved invoke-mode row is skipped since the existing invoke-mode row already covers that event type.
- **Scope-change collision rule:** if an incoming bulk-replace entry has the same `event_type` as an existing invoke-mode row **but a different `scope`**, the endpoint **rejects the entire request with 422** and mutates no rows. The error body must name the conflicting `event_type`, report the current and requested scopes, and direct the caller to either `DELETE /api/v1/agents/subscriptions/{eventType}` followed by `POST` (to re-run the scope-change authorization flow), or `PATCH` (for instruction edits that do not change scope). This mirrors the PATCH endpoint's "scope is immutable" contract (see earlier in this section) and prevents bulk replace from silently moving an invoke-mode subscription between `hive` and `apiary` scopes — a change that would otherwise bypass the `cross_hive` permission check applied on POST. The collision check must run **before** the destructive delete so that the rejection leaves all existing rows untouched.
- If the incoming list does **not** include a matching entry for an existing invoke-mode subscription, the invoke-mode row is **still preserved** — bulk replace only removes poll-mode rows. To delete an invoke-mode subscription, the client must use the dedicated `DELETE` endpoint.
- Invoke-mode subscriptions should only be created via `POST /api/v1/agents/subscriptions` (individual subscribe) and updated via `PATCH /api/v1/agents/subscriptions/{eventType}` or `PATCH /api/v1/agents/subscriptions/capability/{subscriptionId}`.
- **Response shape on success:** `PUT /api/v1/agents/subscriptions` returns the **full post-replace subscription list** — every preserved invoke-mode row plus every newly-inserted poll-mode row — not just the rows the call inserted. This matches what the caller would see on a follow-up `GET /api/v1/agents/subscriptions` and prevents the bulk-replace response from appearing to truncate the caller's invoke-mode subscriptions. See the implementation note in §6.3 (`EventBus::replaceSubscriptions()` must return preserved-plus-created, e.g. `$invokeModeSubs->values()->concat($created)`, or equivalently re-query after the transaction).

**Response envelope** — the existing `{ data, meta, errors }` envelope is preserved. Each subscription resource gains:

```json
{
  "agent_id": "01J...",
  "event_type": "github.issue.opened",
  "scope": "hive",
  "invoke_instructions": "Triage this issue. Title: {{ event.payload.issue.title }}",
  "delivery_mode": "invoke",
  "created_at": "...",
  "updated_at": "..."
}
```

`delivery_mode` is a computed field (`invoke` or `poll`) for client convenience; it is **not** stored.

## 6. Dispatch path

### 6.1. Poll-path exclusion of invoke-mode subscriptions

Because `poll` and `invoke` are mutually exclusive delivery modes (§3), `EventBus::poll()` **must not** return events for subscriptions that have `invoke_instructions` set. Those events are delivered as tasks by the `EventSubscriptionDispatcher` (§6.2) — leaking them through the poll path would cause double-delivery.

**Required change to `EventBus::poll()`** (around line 448):

```diff
- $subscriptions = EventSubscription::where('agent_id', $agent->id)->get();
+ $subscriptions = EventSubscription::where('agent_id', $agent->id)
+     ->whereNull('invoke_instructions')
+     ->get();
```

The same filter must be applied to the capability-pool poll augmentation queries (around lines 471–485). Both the hive-scoped and apiary-scoped `CapabilityEventSubscription` queries must add `->whereNull('invoke_instructions')`:

```diff
  $hivePoolQuery = CapabilityEventSubscription::query()
      ->where('scope', CapabilityEventSubscription::SCOPE_HIVE)
      ->where('hive_id', $effectiveHiveId)
-     ->whereIn('capability', $agentCapabilities);
+     ->whereIn('capability', $agentCapabilities)
+     ->whereNull('invoke_instructions');

  // ...

  $apiaryPoolQuery = CapabilityEventSubscription::query()
      ->where('scope', CapabilityEventSubscription::SCOPE_APIARY)
      ->where('organization_id', $agent->organization_id)
-     ->whereIn('capability', $agentCapabilities);
+     ->whereIn('capability', $agentCapabilities)
+     ->whereNull('invoke_instructions');
```

Similarly, `EventBus::dispatch()` (the query-only resolution helper at line 330) must exclude invoke-mode rows so that its agent-ID resolution remains consistent with the poll path:

```diff
  $query = EventSubscription::where(function ($q) use ($event, $wildcards) {
      $q->where('event_type', $event->type);
      if (! empty($wildcards)) {
          $q->orWhereIn('event_type', $wildcards);
      }
- });
+ })->whereNull('invoke_instructions');
```

**Invariant:** any subscription with `invoke_instructions IS NOT NULL` is invisible to the poll/dispatch path. It is only processed by `EventSubscriptionDispatcher`.

### 6.2. Current execution flow and new dispatch path

#### Current execution flow (for context)

The live publish path does **not** call `EventBus::dispatch()`. The actual flow is:

1. **Publish:** `EventController::publish()` calls `EventBus::publish()`, which persists the event row and its activity log inside a single DB transaction — then returns.
2. **Poll delivery (existing):** Agents later consume events by calling `GET /api/v1/hives/{hive}/events/poll`, which calls `EventBus::poll()`. This is the pull-based path — no task is created.
3. **Trigger delivery (existing):** The `events:dispatch-triggers` Artisan command (run on a schedule by Horizon) calls `EventTriggerService::dispatchPendingEvents()`, which iterates every active `EventTrigger`, cursor-scans for new events, renders templates via `HandlebarsTemplateRenderer`, and creates tasks via `TaskCreationService`.

`EventBus::dispatch(Event $event)` is a query-only helper that resolves which agent IDs match a given event's subscriptions (used in tests and the polling resolution path). It does **not** create tasks or trigger side-effects. The proposal must not hang invoke-mode delivery off `dispatch()` because it is not in the publish hot path.

#### Where the new behavior plugs in

Invoke-mode delivery follows the same **cursor-driven, scheduled dispatcher** pattern as `EventTriggerService`. A new service — `EventSubscriptionDispatcher` — runs alongside `EventTriggerService` on the same schedule (called from a new Artisan command `events:dispatch-subscriptions` or co-located in the existing `events:dispatch-triggers` command).

The dispatcher processes subscription rows **one at a time** (row-by-row), not after agent-ID resolution:

1. Query all `event_subscriptions` rows where `invoke_instructions IS NOT NULL`.
2. For each row, cursor-scan `events` for new matching events (same type/wildcard matching logic as `EventTriggerService::fetchPendingEvents()`; cursor stored as `last_processed_seq` on the subscription row — see migration note below).
3. **Apply the recipient-scoping filter** before rendering (see "Recipient scoping" below).
4. For each matching event, render the template via `HandlebarsTemplateRenderer` and create a task via `TaskCreationService` with the rendered text stored in `payload.invoke.instructions`.
5. Advance the cursor.

**Recipient scoping (security invariant).** The dispatcher MUST mirror the `recipient_agent_ids` filter applied by `EventBus::poll()` (`app/Services/EventBus.php:599-600`) and `EventTriggerService::fetchPendingEvents()` (`app/Services/EventTriggerService.php:229-236`). For each candidate event, the dispatcher is allowed to create a task only when:

- `events.recipient_agent_ids IS NULL` (globally visible), **or**
- `subscription.agent_id ∈ events.recipient_agent_ids` (the subscribed agent is on the recipient list).

Concretely, the query-builder predicate added to the cursor scan is (using Laravel's JSON helpers for driver portability — all examples in this proposal follow this convention):

```php
// Mirror of EventBus::applyRecipientFilter() (app/Services/EventBus.php:596-601)
$query->where(function ($q) use ($subscription) {
    $q->whereNull('recipient_agent_ids')
        ->orWhereJsonContains('recipient_agent_ids', $subscription->agent_id);
});
```

Recipient-scoped events that do not name the subscribed agent are skipped (cursor still advances past them — they are "delivered to nobody" from this subscription's perspective, identical to the poll path). This invariant is non-negotiable: without it, invoke-mode delivery becomes a privilege-escalation path around recipient scoping. See test plan items 16–17.

For **capability-pool subscriptions** (`capability_event_subscriptions` with `invoke_instructions IS NOT NULL`), the dispatcher processes each subscription row individually and **fans out one assigned task per resolved pool member**:

1. Cursor-scan events matching the row's `event_type` / `scope`.
2. For each matching event, resolve the current pool membership **per subscription row** using a new **row-scoped resolver** (see below). Do **not** reuse `EventBus::resolveCapabilityPoolAgentIds()` — that method is a global resolver designed for the poll-mode path: it collects all matching capability subscriptions, deduplicates to a flat capability list, and returns one merged agent set, losing per-subscription context (subscription ID, invoke_instructions template, dedup keys). Invoke-mode dispatch requires per-subscription context, so the resolver must operate on a single `CapabilityEventSubscription` row.
3. Apply the recipient-scoping filter: if `events.recipient_agent_ids IS NOT NULL`, intersect the resolved pool with the recipient set (using `whereJsonContains` — see query-builder example below). Pool members not on the recipient list are skipped silently. If the intersection is empty, no task is created and the cursor still advances past the event.
4. For each surviving agent, create one task with `target_agent_id = <agent_id>`, `target_capability = NULL`, `payload.invoke.instructions` set to the rendered template, and a deterministic `payload.dedup_key` for idempotency (see below).
5. Because each `capability_event_subscriptions` row is processed independently, two pool subscriptions with different `invoke_instructions` for the same capability produce separate per-agent task sets with distinct prompts.

**Row-scoped resolver for invoke-mode capability-pool dispatch.** The existing `EventBus::resolveCapabilityPoolAgentIds()` (`app/Services/EventBus.php:384`) is a **global** resolver for the poll-mode path — it scans all matching `CapabilityEventSubscription` rows, collapses their capabilities into a deduplicated flat list, and returns one merged agent set. This loses per-subscription context (which subscription triggered the dispatch, what template to render, what dedup key to use), making it unsuitable for invoke-mode dispatch where each subscription row carries its own `invoke_instructions` and needs its own task set.

Instead, the `EventSubscriptionDispatcher` must use a **row-scoped** approach: given a single `CapabilityEventSubscription` row, extract its `capability` value and find agents matching that one capability within the subscription's scope. This is essentially the agent-membership query from `EventBus.php:410-424` but scoped to a single capability rather than a collected list:

```php
/**
 * Resolve agents owning a single capability, scoped to the subscription's
 * hive (or org-wide for apiary scope). This is the invoke-mode equivalent
 * of the agent-membership query in EventBus::resolveCapabilityPoolAgentIds()
 * (lines 410-424), but operates on one subscription row at a time to
 * preserve per-subscription context (template, dedup key, subscription ID).
 *
 * @return Collection<int, string>  Agent IDs
 */
private function resolvePoolForSubscription(CapabilityEventSubscription $subscription): Collection
{
    $query = Agent::query()
        ->withoutGlobalScope('hive')
        ->withoutGlobalScope('apiary')
        ->whereJsonContains('capabilities', $subscription->capability);

    if ($subscription->scope === CapabilityEventSubscription::SCOPE_APIARY) {
        $query->where('organization_id', $subscription->organization_id);
    } else {
        $query->where('hive_id', $subscription->hive_id);
    }

    return $query->pluck('id');
}
```

`EventBus::resolveCapabilityPoolAgentIds()` remains available for the poll-mode path (which does not need per-subscription context) and must not be used for invoke-mode dispatch.

**Why per-agent fan-out (not `target_capability`).** The earlier draft of this section proposed emitting one unassigned task with `target_capability = subscription.capability` and letting any pool member claim it. That model only works for agents that claim through the API poll endpoint, which explicitly matches `target_capability` (`app/Http/Controllers/Api/TaskController.php`, the `target_capability` branch of the eligibility filter). **Hosted/managed agents do not use that path**: `ManagedAgentRuntime::claimNextTaskLocked()` (`app/Cloud/Services/ManagedAgentRuntime.php`) only claims tasks targeted directly at the agent (`target_agent_id = <agent>`) or unrouted tasks whose `type` matches the agent's `claim_type`, and never checks `target_capability`. An unassigned-with-capability task would sit pending forever for managed-agent pools. Per-agent fan-out at dispatch time produces tasks that both claim paths handle uniformly (each task is directly targeted at one agent), reuses the fan-out pattern the platform already applies elsewhere, and requires no new logic in the managed-runtime **claim** path. However, `ManagedAgentRuntime::buildUserMessage()` must be updated to read `payload.invoke.instructions` before the JSON fallback, so that the rendered instruction reaches the model as the user message instead of a raw JSON dump. This is a small, scoped change to the runtime's message-building logic (not the claim path).

**Idempotency.** Per-agent fan-out turns one (subscription, event) pair into N tasks, so the dispatcher needs a per-(subscription, event, agent) idempotency key to keep retries safe. Each created task carries a deterministic `payload.dedup_key` of the form `event_capability_subscription:{subscription.id}:{event.id}:{agent.id}` plus a pre-insert existence check using Laravel's JSON arrow syntax (`->where('payload->dedup_key', $dedupKey)`) within the dispatcher transaction. This mirrors the existing `EventTriggerService` convention which uses `payload.dedup_key` for idempotency. On retry (e.g., dispatcher crash mid-fan-out), the cursor has not advanced and the loop re-runs; the dedup-key guard prevents duplicate tasks while still letting any agents that were not yet created get their task. The cursor advances only after all pool members for an event have either been emitted or skipped (recipient-scoping miss).

**Recipient scoping naturally honored.** Because tasks are now per-agent assigned, the dispatcher applies the same `recipient_agent_ids` check used for direct subscriptions (above) to each resolved pool member. Recipient-scoped events deliver only to the intersection of pool members and the recipient list, which is the desired behavior — no carveout is required.

**Cursor column** — both `event_subscriptions` and `capability_event_subscriptions` gain a `last_processed_seq` (bigint, nullable, default null) column. The cursor is initialized in three scenarios:
- **Migration time** — a data migration sets `last_processed_seq = (SELECT MAX(seq) FROM events)` on all existing rows in both tables, so existing subscriptions don't replay history if they later gain an instruction.
- **Create time** — when a new subscription is created with `invoke_instructions IS NOT NULL`, the cursor is set to the current `MAX(seq)` (see §6.3).
- **PATCH time** — when an existing poll-mode subscription is switched to invoke mode (`invoke_instructions` changing from `NULL` to non-`NULL`), the cursor is reset to the current `MAX(seq)` in the same transaction (see §6.4). Without this, the dispatcher would replay every event since the stale migration-time cursor.

Poll-mode subscriptions (`invoke_instructions IS NULL`) ignore `last_processed_seq` — agents continue to poll via `EventBus::poll()` as today.

**Transactional guarantees** — each (subscription, event) pair is processed inside a DB transaction: cursor advance + task creation are atomic. Renderer failures are logged via `ActivityLogger` as `event_invoke_render_failed` and the cursor advances past the failed event so it is not retried indefinitely.

**Key tests that prove the path:**
- `tests/Feature/EventTriggerServiceTest.php` — the existing cursor-driven dispatch loop, which the new service mirrors. Proves the pattern of cursor scan → template render → task creation → cursor advance.
- `tests/Feature/EventBusServiceTest.php::test_dispatch_*` — proves subscription matching logic (wildcard, scope, cross-hive). The new dispatcher reuses the same matching predicates.

### Task fields produced from an invoke-mode subscription

**Direct subscription** (`event_subscriptions`):

| Task field | Source |
|---|---|
| `target_agent_id` | `subscription.agent_id` |
| `target_capability` | `null` |
| `task_type` | `event_subscription` (new constant — distinguishable from `event_trigger`) |
| `priority` | hive default (V1 — see §9 open question on per-subscription priority) |
| `payload.invoke.instructions` | `render(subscription.invoke_instructions, eventContext)` — the rendered prompt, stored in the task's JSON `payload` column (not a top-level DB column). `TaskSummaryService` reads both `payload.invoke.instructions` and `payload.prompt`, with `payload.prompt` taking priority; this proposal uses the `invoke.instructions` path to align with the canonical API/dashboard convention. **Runtime contract:** `ManagedAgentRuntime::buildUserMessage()` is updated to check `payload.invoke.instructions` after `payload.prompt` and `payload.message` but before the JSON fallback, ensuring managed agents receive the rendered instruction as their user message. |
| `payload.event_id` | `event.id` — for traceability |
| `payload.event_type` | `event.type` |
| `payload.event_subscription_id` | `"{agent_id}:{event_type}"` — identifies the originating subscription |
| `payload.hive_id` | `event.hive_id` |
| `payload.is_cross_hive` | `event.is_cross_hive` |
| `payload.source_agent_id` | `event.source_agent_id` |
| `payload.dedup_key` | `"event_subscription:{agent_id}:{event_type}:{event.id}"` — deterministic idempotency key to prevent duplicate tasks on retry |

**Capability-pool subscription** (`capability_event_subscriptions`) — one row per resolved pool member per event:

| Task field | Source |
|---|---|
| `target_agent_id` | resolved pool member (one task per agent owning `subscription.capability`, post-recipient-scoping) |
| `target_capability` | `null` (fan-out at dispatch time — see §6.2) |
| `task_type` | `event_subscription` |
| `priority` | hive default |
| `payload.invoke.instructions` | `render(subscription.invoke_instructions, eventContext)` — rendered prompt in the task's JSON `payload` column |
| `payload.event_id` | `event.id` — for traceability |
| `payload.event_type` | `event.type` |
| `payload.event_subscription_id` | `subscription.id` (ULID) — identifies the originating capability-pool subscription |
| `payload.hive_id` | `event.hive_id` |
| `payload.is_cross_hive` | `event.is_cross_hive` |
| `payload.source_agent_id` | `event.source_agent_id` |
| `payload.capability` | `subscription.capability` |
| `payload.dedup_key` | `"event_capability_subscription:{subscription.id}:{event.id}:{agent.id}"` — deterministic idempotency key per (subscription, event, agent) to prevent duplicates on retry (see §6.2) |

### 6.3. Create-path changes (subscribe with invoke_instructions)

The current `EventBus::subscribe()` and `EventBus::subscribeCapability()` methods accept only the subscription identity columns (`agent_id`/`capability`, `event_type`, `scope`). They must be extended to accept and persist `invoke_instructions`, and — critically — to initialize the cursor for invoke-mode subscriptions.

**`EventBus::subscribe()` (line 111)** — add an optional `invoke_instructions` parameter:

```diff
  public function subscribe(
      string $agentId,
      string $eventType,
      string $scope = EventSubscription::SCOPE_HIVE,
+     ?string $invokeInstructions = null,
  ): EventSubscription {
```

The `create()` call must include the new field and, when `invoke_instructions` is set, bootstrap the cursor from the current max event seq (matching the pattern used by `EventTriggerController::store()` at line 119):

```diff
  return EventSubscription::create([
      'agent_id' => $agentId,
      'event_type' => $eventType,
      'scope' => $scope,
      'created_at' => now(),
+     'invoke_instructions' => $invokeInstructions,
+     'last_processed_seq' => $invokeInstructions !== null
+         ? (int) (Event::withoutGlobalScopes()->max('seq') ?? 0)
+         : null,
  ]);
```

If `invoke_instructions` is null (poll mode), `last_processed_seq` stays null — poll-mode subscriptions do not use a cursor. If `invoke_instructions` is set (invoke mode), the cursor starts at the current max seq so only future events produce tasks. Without this bootstrap, `EventSubscriptionDispatcher` would replay every historical event for new invoke-mode subscriptions.

The idempotent "already exists" branch should also update `invoke_instructions` and `last_processed_seq` on the existing row when the caller provides a non-null instruction on re-subscribe, or leave them unchanged when the caller omits the field.

**`EventBus::subscribeCapability()` (line 152)** — same pattern:

```diff
  public function subscribeCapability(
      string $organizationId,
      ?string $hiveId,
      string $capability,
      string $eventType,
      string $scope = CapabilityEventSubscription::SCOPE_HIVE,
+     ?string $invokeInstructions = null,
  ): CapabilityEventSubscription {
```

```diff
  return CapabilityEventSubscription::create([
      'id' => (string) Str::ulid(),
      'organization_id' => $organizationId,
      'hive_id' => $hiveId,
      'capability' => $capability,
      'event_type' => $eventType,
      'scope' => $scope,
      'created_at' => now(),
+     'invoke_instructions' => $invokeInstructions,
+     'last_processed_seq' => $invokeInstructions !== null
+         ? (int) (Event::withoutGlobalScopes()->max('seq') ?? 0)
+         : null,
  ]);
```

**`EventController::subscribe()` (line 199)** — validate the template (if provided) then pass the validated field through to the service:

```php
// Dry-render to catch malformed templates before persisting (see §5)
$templateError = $this->validateInvokeTemplate($validated['invoke_instructions'] ?? null);
if ($templateError !== null) {
    return $templateError;
}
```

```diff
  $subscription = $this->eventBus->subscribe(
      agentId: $agent->id,
      eventType: $validated['event_type'],
      scope: $scope,
+     invokeInstructions: $validated['invoke_instructions'] ?? null,
  );
```

And for the capability-pool branch:

```diff
  $poolSubscription = $this->eventBus->subscribeCapability(
      organizationId: $agent->organization_id,
      hiveId: $scope === CapabilityEventSubscription::SCOPE_HIVE ? $agent->hive_id : null,
      capability: $capability,
      eventType: $validated['event_type'],
      scope: $scope,
+     invokeInstructions: $validated['invoke_instructions'] ?? null,
  );
```

**`EventBus::replaceSubscriptions()` (line 293)** — the bulk-replace method must **not** accept `invoke_instructions`. Instead, it must preserve existing invoke-mode subscriptions (keyed by `event_type` alone, matching the table's `(agent_id, event_type)` primary key), reject any incoming entry that would move an invoke-mode row to a different `scope`, and only replace poll-mode rows. The entire flow runs inside the existing `DB::transaction(...)` wrapper so that the 422 path leaves all rows untouched:

```diff
  return DB::transaction(function () use ($agentId, $subscriptions) {
+     // Identify existing invoke-mode subscriptions — these are never touched by bulk replace.
+     // Key on event_type alone: the table's primary key is (agent_id, event_type) — scope
+     // is not part of the row's identity, so a per-event_type lookup is the only one that
+     // matches reality. See database/migrations/2026_02_28_200000_create_event_subscriptions_table.php:17.
+     $invokeModeSubs = EventSubscription::where('agent_id', $agentId)
+         ->whereNotNull('invoke_instructions')
+         ->get()
+         ->keyBy('event_type');
+
+     // Collision check (must run BEFORE any deletes / inserts):
+     // If an incoming entry shares an event_type with an existing invoke-mode row but
+     // has a different scope, reject the whole request. Bulk replace cannot silently
+     // move an invoke-mode subscription between hive and apiary scope — that change
+     // requires DELETE + POST (to re-run the cross_hive authorization flow) or PATCH
+     // (for instruction edits that do not change scope).
+     foreach ($subscriptions as $sub) {
+         $incomingScope = $sub['scope'] ?? EventSubscription::SCOPE_HIVE;
+         $existing = $invokeModeSubs->get($sub['event_type']);
+         if ($existing !== null && $existing->scope !== $incomingScope) {
+             throw new InvokeModeScopeChangeException(
+                 eventType: $sub['event_type'],
+                 currentScope: $existing->scope,
+                 requestedScope: $incomingScope,
+             );
+         }
+     }
+
+     // Delete only poll-mode subscriptions (invoke_instructions IS NULL).
+     EventSubscription::where('agent_id', $agentId)
+         ->whereNull('invoke_instructions')
+         ->delete();
-     EventSubscription::where('agent_id', $agentId)->delete();

      $created = collect();

      foreach ($subscriptions as $sub) {
+         // Skip if an invoke-mode subscription already covers this event_type.
+         // Scope-change attempts were rejected above, so any match here is a same-scope
+         // duplicate of a preserved invoke-mode row.
+         if ($invokeModeSubs->has($sub['event_type'])) {
+             continue;
+         }
+
          $created->push(EventSubscription::create([
              'agent_id' => $agentId,
              'event_type' => $sub['event_type'],
              'scope' => $sub['scope'] ?? EventSubscription::SCOPE_HIVE,
              'created_at' => now(),
          ]));
      }

-     return $created;
+     // Return the FULL post-replace set: the preserved invoke-mode rows
+     // (untouched by this call) plus the newly-inserted poll-mode rows.
+     // Returning only `$created` would silently truncate the response for
+     // `PUT /api/v1/agents/subscriptions` — callers would observe their
+     // invoke-mode rows "disappear" from the response body even though
+     // those rows still exist in the database.
+     return $invokeModeSubs->values()->concat($created);
  });
```

The method MUST return the full post-replace set — preserved invoke-mode rows plus newly-created poll-mode rows — so that `PUT /api/v1/agents/subscriptions` returns the complete subscription list rather than only the rows it just inserted. An equivalent alternative is to re-query `EventSubscription::where('agent_id', $agentId)->get()` at the end of the transaction; both produce the same observable contract. The `EventController::replaceSubscriptions()` (and the dashboard variant) must pass this full collection through to `formatSubscription()` so the API response reflects every row that the caller would see on a follow-up `GET /api/v1/agents/subscriptions`.

`InvokeModeScopeChangeException` is rendered by `EventController::replaceSubscriptions()` (and the capability-pool variant) as a 422 response naming the conflicting `event_type`, its current scope, the requested scope, and pointing the caller at `DELETE` + `POST` or `PATCH`. Because the exception is thrown inside `DB::transaction(...)` before any mutations, the transaction is rolled back and all existing subscription rows — both poll-mode and invoke-mode — are left untouched.

This ensures that older SDK versions calling `PUT /api/v1/agents/subscriptions` to sync their poll-mode subscription list cannot accidentally destroy invoke-mode subscriptions configured via the dashboard or PATCH endpoint, and cannot silently move an invoke-mode row across scopes. See the restriction documented in §5 (API).

**Dashboard controllers** — `EventDashboardController::storeSubscription()` and the capability variant must pass the validated `invoke_instructions` through in the same way.

**Cursor bootstrap invariant:** every code path that creates an invoke-mode subscription (`invoke_instructions IS NOT NULL`) must set `last_processed_seq` to the current `MAX(seq)` from the `events` table. This prevents historical event replay and matches the established pattern in `EventTriggerController::store()` (line 119: `'last_processed_seq' => $this->currentMaxSeq()`).

### 6.4. Update-path changes (PATCH invoke_instructions)

The PATCH endpoint allows toggling an existing subscription between poll and invoke modes. This section specifies the full implementation, including cursor management and authorization.

**Route** — two PATCH routes, mirroring the POST/DELETE split:

```
PATCH /api/v1/agents/subscriptions/{eventType}                     — direct subscription
PATCH /api/v1/agents/subscriptions/capability/{subscriptionId}     — capability-pool subscription
```

Direct subscriptions are identified by `(auth_agent_id, eventType)` (matching the existing DELETE pattern). Capability-pool subscriptions are identified by ULID `id` because they are not agent-scoped.

**Request validation** — new `UpdateSubscriptionRequest`:

```php
return [
    'invoke_instructions' => ['sometimes', 'nullable', 'string', 'max:8000'],
];
```

Only `invoke_instructions` is mutable via PATCH. Scope changes require delete + recreate to re-run the authorization flow. The same `validateInvokeTemplate()` dry-render check described in §5 applies here — the PATCH handler must reject malformed templates with a 422 before persisting.

**Omitted vs. cleared (PATCH semantics).** `sometimes|nullable` lets the client distinguish three cases, and the handler MUST honor them:

| Wire | Meaning | Persisted action |
|---|---|---|
| key absent (e.g. `{}`) | "leave it alone" | no-op on `invoke_instructions` |
| `"invoke_instructions": null` | "clear it (back to poll mode)" | set to `NULL` |
| `"invoke_instructions": "..."` | "set/replace" | set to the new string |

Using `$validated['invoke_instructions'] ?? null` conflates "absent" and "explicit null" and silently demotes invoke-mode subscriptions to poll mode on any unrelated PATCH. The handler MUST gate the assignment on `$request->has('invoke_instructions')` (true for both `null` and non-null values; false only when the key is absent). See test plan item 18.

**`EventController::updateSubscription()` — direct path:**

```php
public function updateSubscription(UpdateSubscriptionRequest $request, string $eventType): JsonResponse
{
    $agent = $request->user('sanctum-agent');
    $validated = $request->validated();

    $subscription = EventSubscription::where('agent_id', $agent->id)
        ->where('event_type', $eventType)
        ->first();

    if (! $subscription) {
        return $this->notFound('Subscription not found.');
    }

    // Authorization: apiary-scoped rows require cross_hive permission
    // (mirrors POST line 210, DELETE line 307)
    if ($subscription->scope === EventSubscription::SCOPE_APIARY
        && ! $this->crossHiveService->hasAnyCrossHivePermission($agent)
    ) {
        return $this->forbidden('Apiary-scoped subscriptions require cross_hive permission.');
    }

    // PATCH semantics: only touch invoke_instructions if the key was present
    // in the request body. Using $validated[...] ?? null would conflate
    // "absent" with "explicit null" and silently demote invoke → poll.
    if (! $request->has('invoke_instructions')) {
        return $this->success($this->formatSubscription($subscription));
    }

    $newInstructions = $validated['invoke_instructions']; // may be null (clear) or string (set)

    // Dry-render to catch malformed templates before persisting (see §5)
    $templateError = $this->validateInvokeTemplate($newInstructions);
    if ($templateError !== null) {
        return $templateError;
    }

    $oldInstructions = $subscription->invoke_instructions;

    DB::transaction(function () use ($subscription, $newInstructions, $oldInstructions) {
        $subscription->invoke_instructions = $newInstructions;

        // Cursor reset: poll → invoke transition must start from current max seq
        if ($oldInstructions === null && $newInstructions !== null) {
            $subscription->last_processed_seq = (int) (Event::withoutGlobalScopes()->max('seq') ?? 0);
        }

        $subscription->save();
    });

    return $this->success($this->formatSubscription($subscription));
}
```

**`EventController::updateCapabilitySubscription()` — capability-pool path:**

```php
public function updateCapabilitySubscription(UpdateSubscriptionRequest $request, string $subscriptionId): JsonResponse
{
    $agent = $request->user('sanctum-agent');

    // Authorization: capability-pool updates require events.manage
    if (! $agent->hasPermission('events.manage')) {
        return $this->forbidden('Capability pool subscriptions require events.manage permission.');
    }

    $subscription = CapabilityEventSubscription::where('id', $subscriptionId)
        ->where('organization_id', $agent->organization_id)
        ->first();

    if (! $subscription) {
        return $this->notFound('Capability subscription not found.');
    }

    // Authorization: hive-scoped rows enforce same-hive — an agent in hive A
    // cannot patch a hive-scoped subscription owned by hive B.
    // This mirrors the POST/DELETE contract where hive_id is derived from the
    // authenticated agent (EventController::subscribe() and unsubscribe()).
    if ($subscription->scope === CapabilityEventSubscription::SCOPE_HIVE
        && $subscription->hive_id !== $agent->hive_id
    ) {
        return $this->forbidden('Cannot update a hive-scoped subscription belonging to another hive.');
    }

    // Authorization: apiary-scoped rows require cross_hive permission
    if ($subscription->scope === CapabilityEventSubscription::SCOPE_APIARY
        && ! $this->crossHiveService->hasAnyCrossHivePermission($agent)
    ) {
        return $this->forbidden('Apiary-scoped subscriptions require cross_hive permission.');
    }

    $validated = $request->validated();

    // PATCH semantics: only touch invoke_instructions if the key was present
    // in the request body (see §6.4 omitted-vs-cleared table).
    if (! $request->has('invoke_instructions')) {
        return $this->success($this->formatCapabilitySubscription($subscription));
    }

    $newInstructions = $validated['invoke_instructions']; // may be null (clear) or string (set)

    // Dry-render to catch malformed templates before persisting (see §5)
    $templateError = $this->validateInvokeTemplate($newInstructions);
    if ($templateError !== null) {
        return $templateError;
    }

    $oldInstructions = $subscription->invoke_instructions;

    DB::transaction(function () use ($subscription, $newInstructions, $oldInstructions) {
        $subscription->invoke_instructions = $newInstructions;

        // Cursor reset: poll → invoke transition must start from current max seq
        if ($oldInstructions === null && $newInstructions !== null) {
            $subscription->last_processed_seq = (int) (Event::withoutGlobalScopes()->max('seq') ?? 0);
        }

        $subscription->save();
    });

    return $this->success($this->formatCapabilitySubscription($subscription));
}
```

**`EventBus::updateSubscriptionInstructions()`** — service-layer method encapsulating the cursor-reset logic:

```php
public function updateSubscriptionInstructions(
    EventSubscription|CapabilityEventSubscription $subscription,
    ?string $invokeInstructions,
): void {
    $oldInstructions = $subscription->invoke_instructions;

    DB::transaction(function () use ($subscription, $invokeInstructions, $oldInstructions) {
        $subscription->invoke_instructions = $invokeInstructions;

        // Poll → invoke: reset cursor to current max so only future events fire
        if ($oldInstructions === null && $invokeInstructions !== null) {
            $subscription->last_processed_seq = (int) (Event::withoutGlobalScopes()->max('seq') ?? 0);
        }

        $subscription->save();
    });
}
```

**Cursor reset invariant:** every code path that transitions `invoke_instructions` from `NULL` to non-`NULL` — whether via PATCH, the idempotent re-subscribe branch in `EventBus::subscribe()`, or the dashboard update form — must set `last_processed_seq = current MAX(seq)` in the same transaction. This is the same invariant as the create-path bootstrap (§6.3) but applied to existing rows.

**Dashboard controllers** — `EventDashboardController::updateSubscription()` and the capability variant call `EventBus::updateSubscriptionInstructions()` to apply the same cursor-reset logic.

## 7. UI

This is the half of the issue the user explicitly asks about: *"How to make it better in UI?"*

**Subscription form (Events › Subscriptions)** — `resources/js/Pages/Events/Subscriptions.jsx` gains a new field below the existing Agent / Event type / Scope row:

- **Label:** *Invoke instruction (optional)*
- **Control:** multiline textarea, ~6 rows, monospace, autosize.
- **Helper text below the textarea:**
  > Leave blank for poll mode (the agent receives the raw event). Fill in to create a task whose prompt is this text with payload variables interpolated.
- **Variable hint chip row** — small, clickable chips that insert the variable at the cursor:
  `event.id` · `event.type` · `event.payload.*` · `event.source_agent_id` · `event.created_at`
- **Preview pane** — collapsible "Preview" section that lets the operator paste a sample JSON payload (or pick from the last 5 observed events of this `event_type` for this hive — already queryable via the existing `observedEventTypes()` helper in `EventDashboardController`) and renders the template against it. Read-only output box. No network round-trip is required if rendering happens client-side; if the server-side renderer is the source of truth, debounce to a `POST /api/v1/agents/subscriptions/preview` endpoint that takes `{ template, sample_payload }` and returns `{ rendered }`. V1 picks the server-side route to guarantee parity with dispatch-time rendering.

**Subscription list** — the existing table grows a **Mode** column with a small badge: `Invoke` (filled) or `Poll` (outline). Clicking the badge opens the row in edit mode so the operator can toggle. The `invoke_instructions` text is truncated to one line with a tooltip on hover.

**Empty state** — when a hive has zero subscriptions, the empty state today is a plain "No subscriptions" message. Replace it with a short decision-tree card:

> **What should happen when an event fires?**
> - **Just notify the agent** — pick poll mode. The agent decides what to do.
> - **Run a specific instruction** — pick invoke mode and write the prompt. We'll create a task with that prompt every time the event fires.

This directly addresses the user's confusion ("i don't understand how agent should react on event") at the point of subscription creation, not buried in docs.

**Discoverability — the "main part of this flow" point** — the user states that subscriptions are a main part of the flow. Today **Subscriptions** is a sub-tab of **Events**; the **Events** entry sits inside a larger nav. V1 elevates the sub-tab without restructuring the sidebar wholesale: rename the existing nav entry from **Events** to **Events & Subscriptions**, and on the Events landing page surface a prominent *Subscriptions* card (count, last-created, "Manage" button) above the event log. A larger nav restructure (e.g. promoting Subscriptions to its own top-level entry, or merging Subscriptions + Triggers under a "Reactions" group) is left as an open question (§8) because it touches sibling proposals — see e.g. issues-concept §8 "Automations" group.

**Per-subscription "test fire"** — small power-user affordance: a "Test" button on each row publishes a synthetic event with a sample payload and shows the resulting task (or the raw event, for poll mode) inline. Cheap to ship and lets operators verify their instruction does what they meant. Optional V1 — flag as nice-to-have.

## 8. Migration

**Capability-pool subscriptions are in V1.** Both `event_subscriptions` and `capability_event_subscriptions` receive the new `invoke_instructions` column in the same migration (see §4 for the full schema diff). The cursor column (`last_processed_seq`) is also added to both tables. V1 ships support for both direct and capability-pool invoke-mode subscriptions.

- **Existing subscriptions** — every existing row in both tables has `invoke_instructions = NULL` by default. Behavior for those subscriptions is **byte-identical** to today: the agent polls and receives the raw event. No operator action required, no SDK change required.
- **Existing SDK clients** — `superpos_sdk` continues to call `POST /agents/subscriptions` without the new field; the server treats it as null. Adding `invoke_instructions` to the SDK is additive and lands in the same release as the API change.
- **`EventTrigger` users** — unchanged. The proposal does not auto-migrate triggers into subscriptions. A doc note in the trigger section of `docs/PRODUCT.md` calls out the new subscription mode and points to it as the simpler path for new use cases.
- **Capability pool subscriptions** — same `invoke_instructions` column on `capability_event_subscriptions`, same null-default. When an operator sets an instruction on a capability-pool subscription, the `EventSubscriptionDispatcher` (§6) resolves the current pool membership and fans out one assigned task per pool member per matching event (see §6.2 for why fan-out is preferred over an unassigned-with-`target_capability` task — the short version: it works uniformly for both API-polling and hosted/managed agents, the latter of which never matches on `target_capability`). This only fires when an operator opts in by setting the instruction. Updates to capability-pool subscriptions use `PATCH /api/v1/agents/subscriptions/capability/{subscriptionId}` and require the same `events.manage` permission (plus `cross_hive` for apiary-scoped rows) that POST and DELETE enforce — see §6.4 for the full update-path specification.
- **Cursor bootstrap** — the data migration sets `last_processed_seq = (SELECT MAX(seq) FROM events)` on all existing rows in both tables. This ensures that when an operator adds `invoke_instructions` to an existing subscription, only future events trigger tasks — no replay of historical events.
- **Cloud feature gating** — V1 does not gate the new field behind any plan. If a future plan tier needs it as a paid feature, the gate goes on `EventSubscriptionDispatcher` next to the existing `custom_webhooks` check in `WebhookRouteEvaluator`.

Rollback safety: drop the `invoke_instructions`, `updated_at`, and `last_processed_seq` columns from both tables. Any in-flight invoke-mode subscriptions revert to poll mode silently. No tasks are lost retroactively (already-created tasks live in the `tasks` table independent of the subscription).

## 9. Open questions

Items the proposal author should not decide alone:

1. **Template syntax.** `EventTriggerService` already uses a `HandlebarsTemplateRenderer`. V1 proposes reusing it (`{{ event.payload.issue.title }}`). Alternatives: Mustache (already a Handlebars subset), Twig (richer, but adds a dependency surface), Laravel Blade (familiar to Laravel devs but designed for HTML rendering and overpowered for this). **Recommend: Handlebars, for consistency with `EventTrigger`.** Confirm before implementation.
2. **Per-event-type instruction overrides.** Should a single subscription be able to attach different instructions per sub-type (e.g. one instruction for `github.issue.opened`, another for `github.issue.labeled`) while still using a wildcard `github.issue.*` subscription? V1 says no — one subscription, one instruction; create N subscriptions for N variants. Worth a second look if the wildcard subscription pattern turns out to be the common case in real hives.
3. **Preset instruction library.** Should the dashboard ship with a small library of recommended prompts per common event type (`github.issue.opened` → "Triage this issue. Decide priority and label."; `pagerduty.incident.triggered` → "Acknowledge if low-severity, escalate otherwise.")? Useful for onboarding but creates a content-maintenance surface. Defer to V2 unless the answer to #2 makes it cheap.
4. **~~Capability-pool fan-out semantics.~~** Resolved: V1 uses **per-agent fan-out** at dispatch time — one assigned task per pool member per event, with a deterministic idempotency key on `(subscription, event, agent)`. An earlier draft picked the single-unassigned-task model (`target_capability` set, `target_agent_id` null) to mirror `EventTrigger.task_target_capability`, but that model only works through the API poll endpoint and silently leaves tasks pending for hosted/managed agents — `ManagedAgentRuntime::claimNextTaskLocked()` (`app/Cloud/Services/ManagedAgentRuntime.php`) only claims tasks targeted directly at the agent or unrouted tasks matching `claim_type`, never `target_capability`. Per-agent fan-out works uniformly across both claim paths and requires no new claim-path logic. See §4 and §6.2.
5. **Nav restructure.** Promote Subscriptions to a top-level nav entry? Merge Subscriptions + EventTriggers + WebhookRoutes under a new "Reactions" or "Automations" group? Coordinate with the structure proposed in `issues-concept.md` §8 (Work / Discuss / Automations).
6. **Eventual unification with `EventTrigger`.** The medium-term direction is to have one primitive ("a subscription that may include execution options") rather than two. V1 keeps them separate to ship the immediate fix. Worth a follow-up proposal once both surfaces are in production for a couple of cycles.
7. **Per-subscription task priority / timeout.** §6 sets task priority to the hive default. Should subscriptions carry their own `task_priority` / `task_timeout_seconds` (parity with `EventTrigger`)? Argues for: parity. Argues against: pushes subscriptions back toward trigger complexity and undermines goal #5. Recommendation: no in V1; surface only `invoke_instructions`. Reopen if real hives ask for it.

## 10. Out of scope

- Deleting or merging `EventTrigger`. V1 lives alongside it (see open question 6).
- Conditional filters on `EventSubscription` (the existing answer is `EventTrigger.filter`).
- Dedup keys, overlap policy, retry policy on subscriptions (these stay on `EventTrigger` for the power-user case).
- A library of preset instructions per event type (see open question 3).
- A visual / no-code workflow builder on top of subscriptions.
- Cross-hive instruction inheritance or per-org instruction defaults.
- Renaming or restructuring the existing nav beyond the focused tweak in §7.

## 11. Test plan

Key test scenarios that must pass before the feature ships. Items 1–2 cover the existing cursor-driven patterns; items 3–6 cover the new invoke-mode behavior; items 7–8 prove the poll-exclusion and create-path cursor invariants; items 9–12 prove the update-path cursor reset and authorization invariants; items 13–14 prove template validation on create/update; item 15 proves the bulk-replace invoke-mode scope-change collision rule; items 16–17 prove the recipient-scoping invariants on the dispatcher (§6.2); item 18 proves PATCH omitted-vs-cleared semantics (§6.4).

1. **Existing poll behavior unchanged** — a subscription with `invoke_instructions = NULL` continues to deliver events via `EventBus::poll()` exactly as before.
2. **Existing trigger behavior unchanged** — `EventTriggerService::dispatchPendingEvents()` is not affected by the new subscription columns.
3. **Invoke-mode dispatch** — creating a subscription with `invoke_instructions` set, then publishing a matching event, causes `EventSubscriptionDispatcher` to create a task with the rendered prompt.
4. **Template rendering** — `{{ event.payload.* }}` variables interpolate correctly; unknown paths render to empty string.
5. **Capability-pool invoke dispatch** — a `capability_event_subscriptions` row with `invoke_instructions`, given a pool of N agents owning the capability, produces N assigned tasks (one per pool member) per matching event, each with `target_agent_id` set and `target_capability = NULL`. Re-running the dispatcher (with the cursor not advanced — e.g., simulated mid-fan-out crash) does not create duplicates: the deterministic `payload.dedup_key = "event_capability_subscription:{subscription.id}:{event.id}:{agent.id}"` idempotency key guards inserts. This proves both fan-out and the §6.2 idempotency contract; no new managed-runtime claim-path test is required because the emitted tasks are directly targeted at agents (claimable via both the API poll endpoint and `ManagedAgentRuntime::claimNextTaskLocked()`).
6. **Cursor advance** — after dispatch, `last_processed_seq` advances past the processed event; re-running the dispatcher does not create duplicate tasks.
7. **Invoke-mode rows excluded from poll** — `event_subscriptions` is uniquely keyed on `(agent_id, event_type)` (see migration `2026_02_28_200000_create_event_subscriptions_table.php:11-17`), so the same agent cannot hold two direct subscriptions on the same event type. Exercise the poll-exclusion path with a legal setup instead: create one direct invoke-mode subscription for agent A on event type `T1` (`invoke_instructions = 'Do X'`) **and** one direct poll-mode subscription for the same agent A on a different event type `T2` (`invoke_instructions = NULL`). Publish one event of each type. Call `EventBus::poll()` for agent A. Assert only the `T2` event appears in the poll result — the `T1` invoke-mode row must not contribute. Then, for the cross-mode case on the same event type, create a poll-mode direct subscription for agent A on `T3` **and** an invoke-mode capability-pool subscription on `T3` for a capability that agent A owns. Publish a `T3` event. Assert (a) the poll result for agent A contains the event exactly once (from the direct row), and (b) the capability subscription does not augment agent A's poll types — the invoke-mode capability row only produces an assigned task (targeting agent A by fan-out) via the dispatcher.
8. **New invoke-mode subscription starts from current cursor** — record the current `MAX(seq)` from `events`. Publish 3 events. Create a new invoke-mode subscription via `POST /api/v1/agents/subscriptions` with `invoke_instructions` set. Assert `last_processed_seq` on the created row equals the max seq recorded **after** the 3 events (i.e., the current max at creation time, not null or zero). Publish 1 more event. Run `EventSubscriptionDispatcher`. Assert exactly 1 task is created (for the post-subscription event), not 4. This proves new invoke-mode subscriptions do not replay historical events.
9. **PATCH poll→invoke resets cursor to current max** — create a poll-mode subscription (`invoke_instructions = NULL`). Publish 5 events. Record the current `MAX(seq)`. PATCH the subscription to set `invoke_instructions = 'Handle: {{ event.type }}'`. Assert `last_processed_seq` on the updated row equals the max seq recorded after the 5 events. Publish 1 more event. Run `EventSubscriptionDispatcher`. Assert exactly 1 task is created (for the post-PATCH event), not 6. This proves the cursor-reset invariant prevents historical event replay on mode transitions.
10. **PATCH invoke→invoke preserves cursor** — create an invoke-mode subscription. Publish 3 events and run the dispatcher (creates 3 tasks, cursor advances). PATCH `invoke_instructions` to a different template. Assert `last_processed_seq` is unchanged (still at the value after the 3rd event). Publish 1 more event and run the dispatcher. Assert exactly 1 new task is created with the **new** template text.
11. **PATCH capability-pool subscription requires events.manage** — create a capability-pool subscription. Attempt to PATCH it as an agent **without** `events.manage` permission. Assert 403 Forbidden. Retry with an agent that has `events.manage`. Assert 200 and the subscription is updated. Additionally, for an apiary-scoped capability-pool subscription, assert that an agent with `events.manage` but **without** `cross_hive` permission receives 403.
12. **PATCH capability-pool poll→invoke resets cursor** — same as test 9 but for a `capability_event_subscriptions` row. Create a poll-mode capability-pool subscription. Publish events. PATCH to invoke mode. Assert `last_processed_seq` is reset to current max. Run the dispatcher. Assert only post-PATCH events produce tasks.
13. **Malformed template rejected on create** — `POST /api/v1/agents/subscriptions` with `invoke_instructions = '{{ event.payload.unclosed'` (malformed Handlebars). Assert 422 with a `invoke_instructions` validation error mentioning "Template parse error". Assert no subscription row was created. This mirrors the existing dry-render validation in `EventTriggerController::store()` (lines 92–97).
14. **Malformed template rejected on PATCH** — create a poll-mode subscription. PATCH with `invoke_instructions = '{{#if}}'` (invalid block helper). Assert 422 with a template parse error. Assert the subscription's `invoke_instructions` remains `NULL` (the update was not persisted). Repeat for capability-pool subscriptions. This prevents permanently broken templates from silently dropping events (§6.2 specifies that render failures advance the cursor past the failed event).
15. **Bulk-replace scope-change collision is rejected and leaves all rows untouched** — seed an existing invoke-mode subscription for `event_type = 'task.created'`, `scope = 'hive'`, `invoke_instructions = 'Handle: {{ event.type }}'`, with `last_processed_seq` at the current max. Also seed two poll-mode subscriptions (`agent.online` hive, `agent.offline` hive). Call `PUT /api/v1/agents/subscriptions` with a payload that includes `{event_type: 'task.created', scope: 'apiary'}` plus a different poll-mode entry. Assert 422 with an error body naming `task.created`, the current scope (`hive`), the requested scope (`apiary`), and a pointer to `DELETE` + `POST` or `PATCH`. Assert that **no** rows were mutated: the original invoke-mode row is unchanged (same `scope`, same `invoke_instructions`, same `last_processed_seq`); both original poll-mode rows still exist; and the new poll-mode entry from the payload was **not** inserted (because the whole transaction rolled back). Then repeat the call with the same `event_type` and the **same** scope (`hive`): assert 200, the invoke-mode row is preserved as-is (including its cursor), and any other entries in the payload replaced the poll-mode rows as expected. This proves the preservation key is `event_type` (matching the `(agent_id, event_type)` primary key) and that scope-change attempts via bulk replace are atomic-fail rather than silent moves.
16. **Dispatcher honors `recipient_agent_ids` on direct subscriptions** — create two invoke-mode direct subscriptions on the same event type for agents A and B (`invoke_instructions = 'Handle: {{ event.type }}'`). Publish event E1 with `recipient_agent_ids = [A]` and event E2 with `recipient_agent_ids = NULL`. Run `EventSubscriptionDispatcher`. Assert: (a) one task created targeting agent A for E1; (b) **no** task targeting agent B for E1 (B is not on the recipient list); (c) one task each for A and B for E2 (global event reaches both). Assert both subscriptions' `last_processed_seq` advanced past both events (the E1-for-B skip still moves the cursor). This proves the dispatcher mirrors the recipient-scoping filter from `EventBus::poll()` (`app/Services/EventBus.php:599-600`) and `EventTriggerService::fetchPendingEvents()` (`app/Services/EventTriggerService.php:229-236`); without it, invoke-mode would be a privilege-escalation path around recipient scoping.
17. **Recipient-scoping filters capability-pool fan-out** — create an invoke-mode capability-pool subscription on event type `T` for capability `triager`, with agents A and B both owning `triager`. Publish event E1 with `recipient_agent_ids = [A]` and event E2 with `recipient_agent_ids = NULL`. Run `EventSubscriptionDispatcher`. Assert: (a) exactly one task is created for E1, targeting agent A (the intersection of the pool `{A, B}` and the recipient set `[A]`); (b) **no** task targeting B for E1 (B is not on the recipient list); (c) two tasks for E2, one targeting A and one targeting B (global event reaches every pool member); (d) the subscription's `last_processed_seq` advances past both events. This proves per-agent fan-out honors recipient scoping by construction — recipient-list filtering applies to the resolved fan-out set, with no separate carveout needed.
18. **PATCH omitted-field semantics** — create an invoke-mode direct subscription (`invoke_instructions = 'Handle X'`). PATCH the subscription with body `{}` (empty JSON — `invoke_instructions` key absent). Assert 200 and the row's `invoke_instructions` is **still `'Handle X'`** (omission is "leave it alone", not "clear"). Now PATCH with `{"invoke_instructions": null}` (key present, value null). Assert 200 and the row's `invoke_instructions` is `NULL` (explicit clear → demoted to poll mode; cursor reset rules in §6.4 apply on the next poll→invoke transition). Now PATCH with `{"invoke_instructions": "Handle Y"}`. Assert 200 and `invoke_instructions = 'Handle Y'`, `last_processed_seq` reset to current max (poll→invoke transition). Repeat all three cases for the capability-pool PATCH endpoint. This proves `$request->has('invoke_instructions')` correctly distinguishes the three wire states from §6.4.
