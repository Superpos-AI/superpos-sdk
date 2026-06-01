# TASK-293: Issues Show page with tabs (Overview, Runs, Discussion, Dependencies)

**Status:** pending
**Branch:** `task/293-issues-show-page`
**PR:** —
**Depends on:** TASK-292 (Issues Index page — provides `IssueStatePill`, transitively includes TASK-290 & TASK-291)
**Blocks:** TASK-294 (Create page), TASK-295 (Runs tab wiring)
**Edition:** shared
**Feature doc:** [`docs/proposals/issues-concept.md`](../proposals/issues-concept.md) (§8 UI — Issue detail view)

## Objective

Ship the Issue detail page (`Pages/Issues/Show.jsx`) at
`/dashboard/issues/{issue}`. Includes the page header (title, state
pill, type, assignee, created-by) and four tabs:

- **Overview** — description, metadata, dependency graph (simple list
  V1), linked Channel, open ApprovalRequests rendered as cards.
- **Runs** — placeholder in this task; wired up in TASK-295 with the
  filtered task list.
- **Discussion** — Thread messages posted via new dashboard routes;
  a new `ThreadComposer` component handles input (the existing
  `ChatInput` is channel-specific and cannot be reused as-is). This
  task owns the **thread-message author contract** for human-authored
  messages — the current `ThreadMessage` schema is agent/task-only,
  so writable-from-dashboard requires adding a `user_id` column,
  model fillable + relation, and a serializer field (see "Thread
  message author contract" below).
- **Dependencies** — blocks / blocked-by list (read-only V1 plus
  add/remove using the existing dependencies endpoints from TASK-290).

This task adds **new dashboard controller actions** for the approval
and dependency workflows that cannot reuse the agent-only API routes
(which are gated behind `auth:sanctum-agent`). Specifically, the
agent API exposes `request-approval` at
`POST /api/v1/hives/{hive}/issues/{issue}/request-approval`,
hive-scoped approval approve/deny at
`POST /api/v1/hives/{hive}/approvals/{approval}/approve|deny`, and
dependency add/remove at
`POST /api/v1/hives/{hive}/issues/{issue}/dependencies` and
`DELETE /api/v1/hives/{hive}/issues/{issue}/dependencies/{dependency}`,
but none of these are accessible from the dashboard session. The
existing `ApprovalDashboardController` already handles org-scoped
approve/deny at `/dashboard/approvals/{approval}/approve|deny`, so
the new routes needed are:

- `POST /dashboard/issues/{issue}/request-approval` — creates an
  `ApprovalRequest` for the issue from the dashboard (mirrors the
  agent-only `IssueController@requestApproval`).
- `POST /dashboard/issues/{issue}/dependencies` — adds a dependency
  (mirrors `IssueController@storeDependency`).
- `DELETE /dashboard/issues/{issue}/dependencies/{dependency}` —
  removes a dependency (mirrors `IssueController@destroyDependency`).
- `POST /dashboard/issues/{issue}/start-discussion` — lazy-creates a
  `Thread` and links it to the issue (sets `issue.thread_id`). Returns
  the new thread. No-ops if the issue already has a thread. Mirrors
  the agent-only thread creation at `POST /api/v1/hives/{hive}/threads`.
- `POST /dashboard/issues/{issue}/messages` — posts a message to the
  issue's linked thread. Requires the issue to have a `thread_id`
  (callers must call `start-discussion` first if null). Mirrors the
  agent-only `POST /api/v1/hives/{hive}/threads/{thread}/messages`.

These routes must be registered in `routes/web.php` and implemented as
new actions on `IssueDashboardController`. The existing dashboard
approve/deny routes on `ApprovalDashboardController` are reused
as-is for the approval card buttons.

**Dashboard-scoped validation:** The `storeDependency()` and
`storeMessage()` actions must not bind directly to the agent-API
FormRequests (`CreateIssueDependencyRequest`, `AppendThreadMessageRequest`).
Those FormRequests resolve the current hive via
`$this->attributes->get('hive')?->id` or
`$this->user('sanctum-agent')->organization_id`, which are only
populated on agent-API routes carrying a `{hive}` segment or using the
`sanctum-agent` guard. The dashboard routes have neither, so
tenant-scoped validations would run with `null` values and silently
bypass cross-hive isolation. Instead, introduce dashboard-scoped
FormRequests (see Files table below) that resolve the hive/org from
the authenticated session context.

All other state-transition actions consume the dashboard endpoints
already shipped in TASK-290 (`transition`, `close`, `reopen`).

### Thread message author contract (owned by this task)

The Discussion tab is the first surface that posts thread messages
from a dashboard session — i.e. authored by a `User`, not an `Agent`
or `Task`. The shipped schema does not support this:

- `thread_messages` columns are `thread_id`, `task_id` (nullable),
  `agent_id` (nullable), `message`, `metadata`, `created_at`
  (`database/migrations/2026_03_27_100000_create_threads_table.php`).
- `App\Models\ThreadMessage::$fillable` exposes `thread_id`,
  `task_id`, `agent_id`, `message`, `metadata` only; there is no
  `user_id` or author-type field, and no `user()` relation
  (`app/Models/ThreadMessage.php`).
- `App\Models\Thread::appendMessage()` accepts `?string $agentId`
  and `?string $taskId` only (`app/Models/Thread.php`).
- `App\Http\Controllers\Api\ThreadController::formatMessage()` only
  serializes `task_id` and `agent_id` for the author identity
  (`app/Http/Controllers/Api/ThreadController.php` ~lines 263-273).
- `App\Models\Thread::toContextArray()` (`app/Models/Thread.php`
  ~lines 64-76) — a **separate** serialization path used when a
  thread is embedded into task context for agents — only emits
  `task_id` and `agent_id` per message (no `user_id`, no `author`
  shape). It is consumed by
  `App\Http\Controllers\Api\TaskController::formatTaskThread()`
  (`app/Http/Controllers/Api/TaskController.php` ~lines 1740-1762),
  which returns `$thread->toContextArray()` directly under
  `messages`. Fixing only `ThreadController::formatMessage()` would
  surface human authorship on `/threads/*` responses but still
  silently drop it whenever a thread is embedded into task context
  for an agent — which is the primary way agents see thread history.

Without owning this contract, a dashboard-posted message ends up
either unattributed or pinned to an undocumented metadata-only
convention. This task explicitly owns the schema + model + serializer
changes so the Discussion tab can post first-class human-authored
messages. The required deltas are:

1. **Migration** — add a nullable `user_id` (`string(26)`, FK to
   `users.id`, `nullOnDelete()`) to `thread_messages`. Author identity
   is implied by which `*_id` columns are set. The combination of
   `user_id` / `agent_id` / `task_id` columns encodes one of four
   supported author states:
   - `user_id` set (others null) → human-authored (dashboard).
   - `agent_id` set, `task_id` null → agent-authored (agent API, no
     task context).
   - `agent_id` AND `task_id` both set → agent acting on behalf of a
     task (agent API with task context — e.g. `ThreadController` agent
     posts with a task reference, or `TaskController` context messages
     at task creation).
   - All three null → system-authored (e.g. approval denial messages
     created by `ApprovalManager`; `metadata.system_event` identifies
     the context).

   At least one of `user_id` / `agent_id` SHOULD be set for
   non-system messages, but the all-null (system) case is explicitly
   valid and already present in existing data. Existing rows are not
   backfilled. A composite `(thread_id, created_at)` index already
   exists and is unchanged.
2. **`ThreadMessage` model** — add `user_id` to `$fillable`, add a
   `user(): BelongsTo` relation to `App\Models\User` (no global hive
   scope to drop), and keep the existing `task()` / `agent()`
   relations.
3. **`Thread::appendMessage()`** — extend the signature to accept an
   optional `?string $userId` parameter (default `null`) and persist
   it on the new `ThreadMessage`. Existing callers (`TaskWorker`,
   agent-API thread routes) continue to pass `agentId` / `taskId`
   unchanged.
4. **Dashboard `storeMessage()`** — populate `user_id` from
   `$request->user()->id` and pass it through
   `Thread::appendMessage()`. Never sets `agent_id` or `task_id`
   from a dashboard call.
5. **API serializer** — extend
   `ThreadController::formatMessage()` to include `user_id` alongside
   `agent_id` / `task_id`, and an `author` object of the shape
   `{ type: 'user'|'agent'|'task'|'system', id: string|null,
   name: string|null }` resolved from the eager-loaded relation.
   Because multiple `*_id` columns may be set simultaneously (e.g.
   `agent_id` + `task_id`), the serializer applies the following
   precedence rule to determine `author.type`:
   1. If `user_id` is non-null → `type: 'user'`.
   2. Else if `task_id` is non-null → `type: 'task'` (takes precedence
      over `agent_id` since task context is more specific).
   3. Else if `agent_id` is non-null → `type: 'agent'`.
   4. Else (all null) → `type: 'system'`.

   The `Thread::toApiArray()` / `toApiArrayWithMessages()` helpers stay
   wire-compatible: existing keys are not removed.
6. **Task-context serializer (`Thread::toContextArray()`)** — extend
   the per-message shape returned by `Thread::toContextArray()` so the
   task-embedded thread payload carries the same author identity as
   the `/threads/*` responses. Specifically:
   - Add `user_id` to the per-message array alongside the existing
     `task_id` and `agent_id` keys.
   - Add the same `author` object `{ type, id, name }` resolved with
     the precedence rule from step 5 (`user_id` → `'user'`, else
     `task_id` → `'task'`, else `agent_id` → `'agent'`, else
     `'system'`).
   - Existing keys (`id`, `task_id`, `agent_id`, `message`,
     `metadata`, `created_at`) are retained for wire compatibility
     with current agent consumers.

   `TaskController::formatTaskThread()`
   (`app/Http/Controllers/Api/TaskController.php` ~lines 1740-1762)
   returns `$thread->toContextArray()` directly under `messages` and
   needs no additional changes once `toContextArray()` emits the new
   keys; it inherits `user_id` + `author` propagation automatically.
   If the controller is refactored to project specific fields out of
   `toContextArray()` instead of passing it through, it MUST forward
   `user_id` and `author` alongside the existing keys — dropping
   either silently re-introduces the lost-authorship bug for any
   thread embedded into task context.
7. **`ThreadComposer` posting contract** — the new dashboard route
   `POST /dashboard/issues/{issue}/messages` writes a message with
   `user_id = auth()->id()` set by the controller. The
   `ThreadComposer` payload contains only `{ message: string }` —
   author identity is server-derived, never client-supplied.

This is intentionally bundled into TASK-293 (not pushed to a separate
prerequisite ticket) because the schema delta is small, scoped to
the Discussion tab's writable contract, and has no dependents
outside this task. Subsequent tickets that surface human-authored
thread messages (e.g. a future cross-thread search) inherit the
`author` shape from the serializer extended here.

## Requirements

### Functional

- [ ] FR-1: Route `GET /dashboard/issues/{issue}` renders Inertia
      component `Issues/Show` with the issue eager-loaded for type,
      thread, recent tasks, open approvals, dependencies.
- [ ] FR-2: Header shows: title, state pill, type, assignee,
      created-by, and a primary action menu (transition, request
      approval, close, reopen — gated by current state).
- [ ] FR-3: Tabs are URL-addressable via `?tab=overview|runs|discussion|dependencies`
      so deep-links preserve the active tab.
- [ ] FR-4: **Overview** tab shows description (markdown rendered),
      metadata (created/updated, linked channel, linked-task count),
      and open `ApprovalRequest` cards. The "Request Approval" action
      calls the new `POST /dashboard/issues/{issue}/request-approval`
      dashboard route added in this task. The approval cards
      themselves reuse the existing reason-capture interaction
      pattern from `resources/js/Pages/Approvals.jsx`
      (see `denyingId` / `denyReason` / `denyCancelIssue` state at
      lines ~112-165 and the inline reason input at lines ~400-417),
      and call the existing dashboard approval endpoints from
      `ApprovalDashboardController`. The required UI contract is:
      - **Three buttons per approval card**: **Approve**, **Reject**,
        and **Reject & Cancel** — matching
        `docs/proposals/issues-concept.md` §7 (lines 185-191).
      - **Approve** → `POST /dashboard/approvals/{approval}/approve`
        (no body). Calls `ApprovalDashboardController@approve`.
      - **Reject** → opens an inline reason input on the card; on
        confirm, posts to `POST /dashboard/approvals/{approval}/deny`
        with body `{ reason: <trimmed string>, cancel_issue: false }`.
        Keeps the issue in `blocked` state. Reuses the manager amend-
        and-re-approve workflow described in the proposal.
      - **Reject & Cancel** → opens the same inline reason input but
        with the "cancel" intent flagged; on confirm, posts to
        `POST /dashboard/approvals/{approval}/deny` with body
        `{ reason: <trimmed string>, cancel_issue: true }`. Drives
        the `blocked → cancelled` transition via the existing
        `ApprovalManager::deny()` cancel-issue path.
      - **Reason validation** — required, non-empty after `trim`,
        max 1000 chars (mirrors the server-side rules at
        `ApprovalDashboardController@deny` lines 171-185). The
        Confirm button MUST be disabled while `reason.trim() === ''`.
      - **No "approve / reject" shortcut** — an implementation that
        ships only Approve + a single bare Reject button (no reason
        capture, no cancel variant) does NOT satisfy FR-4 and must
        be rejected in review. The blocked-to-cancelled path is part
        of the contract, not optional.
- [ ] FR-5: **Runs** tab in this task is a stub showing "Wired in
      TASK-295" — the actual filtered task list lands there.
- [ ] FR-6: **Discussion** tab displays thread messages scoped to the
      issue's linked thread and allows posting new messages.
      If the issue has no linked thread (`thread_id` is null — e.g.
      legacy issues created via the API without one), the tab MUST
      show an empty state with a "Start Discussion" action that calls
      `POST /dashboard/issues/{issue}/start-discussion` to lazy-create
      a `Thread` and associate it with the issue.
      Once a thread exists, new messages are posted via
      `POST /dashboard/issues/{issue}/messages`.
      **UI component note:** the existing `ChatInput` component
      (`resources/js/Components/Channels/ChatInput.jsx`) is
      hardwired to `channelId` and posts to the channel message
      route. It cannot be reused as-is. This task must create a new
      `ThreadComposer` component (or refactor `ChatInput` into a
      generic `MessageComposer` that accepts either a `channelId` or
      an `issueId` prop). The message list can reuse the existing
      `MessageBubble` / `MessageList` presentational components if
      they exist, but the input + posting logic requires a new
      component targeting the dashboard issue-message route.
      This depends on TASK-294 ensuring that all dashboard-created
      issues already have a thread (see TASK-294 auto-create
      requirement), so the empty-state fallback is only expected for
      API-created or migrated issues.
- [ ] FR-7: **Dependencies** tab lists `blocks` and `blocked_by`
      entries; an add/remove form calls the new dashboard routes
      `POST /dashboard/issues/{issue}/dependencies` and
      `DELETE /dashboard/issues/{issue}/dependencies/{dependency}`
      added in this task (the corresponding agent-API endpoints from
      TASK-290 sit behind `auth:sanctum-agent` and cannot be called
      from a dashboard session).
- [ ] FR-8: State transitions and close/reopen use the dashboard
      routes from TASK-290 (`POST /dashboard/issues/{issue}/transition`,
      `close`, `reopen`) and refresh the page via Inertia partial reload.
- [ ] FR-9: Returns 404 for cross-hive access (controller validates
      `issue.hive_id` matches current hive).

### Non-Functional

- [ ] NFR-1: Permission gated by `issues.read` for view;
      `issues.manage` for mutating actions.
- [ ] NFR-2: PSR-12 + Pint clean. ESLint clean.
- [ ] NFR-3: Reuses the `IssueStatePill` component from TASK-292.

## Architecture & Design

### Files to Create / Modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docs/tasks/TASK-293-issues-show-page.md` | This file |
| Modify | `app/Http/Controllers/Dashboard/IssueDashboardController.php` | `show()`, `requestApproval()`, `storeDependency()`, `destroyDependency()`, `startDiscussion()`, `storeMessage()` actions |
| Create | `resources/js/Pages/Issues/Show.jsx` | Detail page shell + tab router |
| Create | `resources/js/Components/Issues/IssueHeader.jsx` | Header + action menu |
| Create | `resources/js/Components/Issues/Tabs/OverviewTab.jsx` | Overview tab |
| Create | `resources/js/Components/Issues/Tabs/RunsTab.jsx` | Stub tab (filled in TASK-295) |
| Create | `resources/js/Components/Issues/Tabs/DiscussionTab.jsx` | Thread messages list + compose; empty state with "Start Discussion" CTA |
| Create | `resources/js/Components/Issues/ThreadComposer.jsx` | Message input that posts to `POST /dashboard/issues/{issue}/messages` (not channel-bound) |
| Create | `resources/js/Components/Issues/Tabs/DependenciesTab.jsx` | List + add/remove |
| Create | `resources/js/Components/Issues/ApprovalCard.jsx` | Inline approval card with **Approve / Reject / Reject & Cancel** buttons and reason capture, reusing the interaction pattern from `Pages/Approvals.jsx` (see FR-4) |
| Create | `database/migrations/<timestamp>_add_user_id_to_thread_messages.php` | Adds nullable `user_id` (FK `users.id`, `nullOnDelete()`) to `thread_messages`; no backfill of existing rows |
| Modify | `app/Models/ThreadMessage.php` | Add `user_id` to `$fillable`; add `user(): BelongsTo` relation to `App\Models\User` |
| Modify | `app/Models/Thread.php` | `appendMessage()` accepts optional `?string $userId` and persists it; existing `$agentId` / `$taskId` parameters and call sites unchanged. **Also** extend `toContextArray()` (~lines 64-76) to emit `user_id` and the `author` object `{ type, id, name }` per message so task-embedded thread payloads carry human authorship; existing keys retained for wire compatibility |
| Modify | `app/Http/Controllers/Api/ThreadController.php` | `formatMessage()` adds `user_id` plus an `author` object `{ type, id, name }`; existing keys (`task_id`, `agent_id`) retained for wire compatibility |
| Modify (verify) | `app/Http/Controllers/Api/TaskController.php` | `formatTaskThread()` (~lines 1740-1762) returns `$thread->toContextArray()` directly under `messages` and inherits the new `user_id` + `author` keys automatically — no code change required as long as the call stays a pass-through. If refactored to project fields explicitly, MUST forward `user_id` and `author` alongside existing keys |
| Create | `app/Http/Requests/Dashboard/StoreDependencyRequest.php` | Dashboard-scoped FormRequest mirroring `CreateIssueDependencyRequest` rules but resolving the current hive from the authenticated session/user context (not from a `{hive}` route segment). Bound to the dashboard `storeDependency()` action. |
| Create | `app/Http/Requests/Dashboard/StoreIssueMessageRequest.php` | Dashboard-scoped FormRequest mirroring `AppendThreadMessageRequest` rules but resolving the org/hive from the authenticated session/user context (not from `sanctum-agent` guard). Bound to the dashboard `storeMessage()` action. |
| Modify | `routes/web.php` | Register `/dashboard/issues/{issue}` (show), `POST .../request-approval`, `POST .../dependencies`, `DELETE .../dependencies/{dependency}`, `POST .../start-discussion`, `POST .../messages` |

### Decisions (locked in)

1. **Tabs are URL-addressable.** Active tab is read from the `?tab=`
   query string. Default is `overview`. This lets users share
   deep-links to a specific tab.
2. **Runs tab is a stub here.** Keeps this task scoped. TASK-295
   replaces the stub with the filtered task list and any necessary
   eager-loading.
3. **Reuse existing approval components where possible.** The
   `ApprovalCard` here is a thin wrapper around the existing approval
   approve/deny controls — it does not duplicate the approval
   business logic.
4. **New dashboard routes for request-approval, dependencies, and discussion.**
   The agent API's `request-approval`, `dependencies`, and `threads`
   endpoints are gated behind `auth:sanctum-agent` and are not callable
   from the dashboard session. This task adds five new dashboard routes
   on `IssueDashboardController`, each mirroring the corresponding
   agent-API logic and gated by `issues.manage`:
   - `POST /dashboard/issues/{issue}/request-approval`
     (`requestApproval()`)
   - `POST /dashboard/issues/{issue}/dependencies`
     (`storeDependency()`)
   - `DELETE /dashboard/issues/{issue}/dependencies/{dependency}`
     (`destroyDependency()`)
   - `POST /dashboard/issues/{issue}/start-discussion`
     (`startDiscussion()`) — lazy-creates a `Thread`, sets
     `issue.thread_id`, no-ops if thread already exists.
   - `POST /dashboard/issues/{issue}/messages`
     (`storeMessage()`) — posts a message to the issue's linked
     thread. Requires `thread_id` to be set (caller must call
     `start-discussion` first for threadless issues).

   The existing dashboard approve/deny routes on
   `ApprovalDashboardController` are reused for the approval card
   buttons. No new *API* endpoints are introduced.
5. **Thread-message author contract owned by this task.** The
   shipped `thread_messages` schema and `ThreadMessage` model are
   agent/task-only. Making the Discussion tab writable without first
   establishing a `user_id` author column would force either
   unattributed messages or an undocumented metadata-only convention.
   TASK-293 therefore owns: (a) the migration adding a nullable
   `user_id` FK to `thread_messages`; (b) the `ThreadMessage` model
   delta (`$fillable` + `user()` relation); (c) the
   `Thread::appendMessage()` signature extension; (d) the dashboard
   `storeMessage()` populating `user_id` from
   `$request->user()->id`; (e) the `ThreadController::formatMessage()`
   extension exposing the resolved `author` shape on `/threads/*`
   responses; and (f) the `Thread::toContextArray()` extension
   exposing the same `user_id` + `author` shape on the task-embedded
   thread payload consumed by `TaskController::formatTaskThread()`.
   Both serialization paths must move together — extending one
   without the other surfaces human authorship on dashboard reads
   while silently dropping it whenever agents read the same thread
   via task context. The `ThreadComposer`
   client payload is `{ message }` only — author identity is
   server-derived from the authenticated session and never
   client-supplied. See "Thread message author contract" above for
   the full delta and rationale.
6. **Approval card uses the proposal's three-button contract.** The
   `ApprovalCard` component renders **Approve**, **Reject** (keeps
   issue blocked), and **Reject & Cancel** (drives `blocked →
   cancelled`), each calling the existing dashboard approval
   endpoints. Both reject variants require a non-empty trimmed
   reason; the inline reason-capture pattern from
   `Pages/Approvals.jsx` is reused rather than reinvented. An
   approve-plus-bare-reject implementation does not satisfy FR-4
   (see the proposal §7 lines 185-191 and the server-side
   validation in `ApprovalDashboardController@deny` lines 171-185).
7. **Dashboard-scoped FormRequests for `storeDependency()` and
   `storeMessage()`.** The `storeDependency()` action must not bind
   directly to `CreateIssueDependencyRequest` — that FormRequest
   resolves the current hive via `$this->attributes->get('hive')?->id`,
   which is only populated by the route-model-bound `{hive}` segment
   on the agent API. The dashboard route has no `{hive}` segment, so
   tenant-scoped `Rule::exists(..., 'hive_id', $hiveId)` checks would
   run with `hive_id = null` and silently bypass cross-hive isolation.
   Instead, introduce `App\Http\Requests\Dashboard\StoreDependencyRequest`
   that resolves the current hive from the authenticated session/user
   context. Similarly, `storeMessage()` must not bind to
   `AppendThreadMessageRequest` — that FormRequest resolves the
   organization via `$this->user('sanctum-agent')->organization_id`,
   which is null outside the `sanctum-agent` guard. Instead, introduce
   `App\Http\Requests\Dashboard\StoreIssueMessageRequest` that
   resolves the org/hive from the authenticated session context. Each
   dashboard FormRequest may extend the agent-API counterpart and
   override the hive/org resolver, or duplicate the rule shape —
   but it must own its own context resolution.

## Test Plan

### Feature tests

- `show()` returns 200 with the issue and its eager-loaded relations.
- Cross-hive isolation: 404 when accessing an issue from another
  hive.
- Tab querystring is reflected back in the Inertia `tab` prop.
- Transition action calls the API and refreshes the prop.
- Open `ApprovalRequest`s appear on the Overview tab; approve / deny
  buttons call the existing dashboard approval endpoints.
- `storeDependency()` and `destroyDependency()` add/remove a
  dependency, require `issues.manage`, enforce same-hive, reject
  self-dependencies, and reject duplicate dependency entries (same
  invariants as the current agent-API counterparts from TASK-290).
  **Note:** `activity_log` writes and transitive cycle detection are
  not yet implemented in the API and are deferred to a future
  API-hardening ticket.
- `startDiscussion()` creates a `Thread`, sets `issue.thread_id`,
  and returns the thread. No-ops (returns existing thread) if the
  issue already has one. Requires `issues.manage`.
- `storeMessage()` posts a message to the issue's linked thread.
  Returns 422 if `thread_id` is null. Requires `issues.manage`.
- `storeDependency()` via the dashboard route rejects a dependency
  target from another hive (cross-hive isolation enforced by the
  dashboard-scoped `StoreDependencyRequest`, not the agent-API
  FormRequest).
- `storeMessage()` via the dashboard route scopes thread validation
  to the current org/hive (cross-hive isolation enforced by the
  dashboard-scoped `StoreIssueMessageRequest`, not the agent-API
  FormRequest).
- `storeMessage()` persists `user_id = $request->user()->id` on the
  new `ThreadMessage` row and leaves `agent_id` / `task_id` null.
- The new `add_user_id_to_thread_messages` migration is reversible
  and a fresh `migrate:fresh` + `migrate` round-trip succeeds.
- `ThreadMessage::user()` relation eager-loads the authoring `User`
  and the API serializer returns the `author` shape `{ type, id,
  name }` using the precedence rule: `user_id` → `'user'`, else
  `task_id` → `'task'`, else `agent_id` → `'agent'`, else
  `'system'`. Verified for: dashboard-authored (`user_id` only),
  agent-only (`agent_id` only), agent+task (`agent_id` + `task_id` →
  resolves to `'task'`), and system (all null → `'system'`).
  Regression covered: existing `task_id` / `agent_id` keys still
  emitted.
- **Task-context thread payload (`Thread::toContextArray()` /
  `TaskController::formatTaskThread()`):** when an agent fetches a
  task whose thread contains a dashboard-authored message, the
  embedded `thread.messages[]` entries MUST include `user_id` and
  the resolved `author` object `{ type, id, name }` using the same
  precedence rule as the `/threads/*` serializer. Covered by a
  feature test that:
  1. seeds a thread with one human-authored message (`user_id`
     only), one agent-authored message (`agent_id` only), one
     agent+task message (`agent_id` + `task_id` → resolves to
     `'task'`), and one system message (all null → `'system'`);
  2. attaches the thread to a task;
  3. calls the task-fetch endpoint as an agent with `threads.read`
     and asserts each embedded message carries the expected
     `user_id` + `author.type`;
  4. regression-asserts that the existing per-message keys (`id`,
     `task_id`, `agent_id`, `message`, `metadata`, `created_at`)
     are still present so legacy agent consumers do not break.
- **ApprovalCard deny flow (Reject):** clicking Reject opens the
  reason input, Confirm is disabled while reason is blank/whitespace,
  and submit posts `cancel_issue=false` to
  `POST /dashboard/approvals/{approval}/deny`; the issue stays
  `blocked`.
- **ApprovalCard deny flow (Reject & Cancel):** clicking Reject &
  Cancel opens the same reason input but submit posts
  `cancel_issue=true`; the underlying `ApprovalManager::deny()` call
  drives the issue `blocked → cancelled` transition.
- Server-side: `ApprovalDashboardController@deny` rejects an empty
  or whitespace-only `reason` for both `cancel_issue=false` and
  `cancel_issue=true` paths (already covered by the existing
  controller tests; this task adds a render-level assertion that
  the Confirm button stays disabled on whitespace-only input).

### Render tests

- Header renders title, state pill, type, assignee.
- Dependencies tab renders both `blocks` and `blocked_by` sections,
  empty-state when both are empty.

## Out of Scope (deferred)

- Filtered task list in the Runs tab (TASK-295).
- Inline editing of issue fields (currently navigates to update via
  a small form / modal — full inline edit is V2).
- Dependency graph visualization (V1 is a flat list).

## Validation Checklist

- [ ] `/dashboard/issues/{issue}` renders all four tabs.
- [ ] Tab routing via `?tab=` works.
- [ ] State transitions persist and refresh.
- [ ] Dependencies tab can add and remove entries.
- [ ] Discussion tab renders Thread messages (when thread exists).
- [ ] Discussion tab shows empty state + "Start Discussion" CTA (when `thread_id` is null).
- [ ] "Start Discussion" creates a thread and transitions to the message view.
- [ ] Posting a message via `ThreadComposer` appears in the thread
      with `user_id` populated (and `agent_id` / `task_id` null) on
      the persisted `ThreadMessage` row.
- [ ] API serializer for `thread_messages` returns the `author`
      shape `{ type, id, name }` alongside the existing `task_id` /
      `agent_id` keys.
- [ ] Task-embedded thread payload (`TaskController::formatTaskThread()`
      via `Thread::toContextArray()`) also returns `user_id` and the
      `author` shape per message, so dashboard-authored messages
      retain human authorship when an agent reads them via task
      context (not just via `/threads/*`).
- [ ] ApprovalCard renders **Approve**, **Reject**, and **Reject &
      Cancel** buttons (not just approve + a bare reject).
- [ ] Both deny variants capture a required, trimmed, non-empty
      reason before submit; Confirm is disabled while reason is
      blank.
- [ ] Reject posts `cancel_issue=false`; Reject & Cancel posts
      `cancel_issue=true`. The cancel path transitions the issue
      `blocked → cancelled`.
- [ ] Cross-hive isolation verified.
- [ ] PSR-12 / Pint + ESLint clean.
- [ ] Full suite green (`php artisan test`, `npm test`).
